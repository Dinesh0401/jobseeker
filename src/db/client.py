"""
Database client for Job Hunter v1.

Wraps the Supabase Python SDK and enforces the 13-state lifecycle
via the `transition_job_state` PostgreSQL function.

Also provides `get_connection()` for raw psycopg2 access needed
by the dispatcher's FOR UPDATE SKIP LOCKED queries.

Spec Reference: Technical_Specification.md §2, §3
"""

import hashlib
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import psycopg2
import psycopg2.extras
from supabase import create_client, Client

from src.config import SupabaseConfig

logger = logging.getLogger(__name__)

# Auto-load .env for local execution
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from pathlib import Path
_env_file = Path(__file__).resolve().parents[2] / ".env"
if _env_file.exists():
    with open(_env_file, "r", encoding="utf-8") as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))


# ============================================================
# Raw PostgreSQL Connection (for dispatcher raw SQL)
# ============================================================

def get_connection():
    """
    Get a raw psycopg2 connection using DATABASE_URL.

    Used by the dispatch worker for FOR UPDATE SKIP LOCKED
    queries that the Supabase SDK cannot express.

    Returns:
        psycopg2 connection with RealDictCursor factory.
    """
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise EnvironmentError(
            "DATABASE_URL environment variable is required for raw SQL access."
        )
    conn = psycopg2.connect(
        database_url,
        cursor_factory=psycopg2.extras.RealDictCursor,
    )
    conn.autocommit = False
    return conn

# ============================================================
# Valid state transition matrix (mirrors schema.sql)
#
# Note: Dispatch failures are tracked in action_queue.status,
# NOT as an application_state. There is no FAILED state.
# ============================================================
VALID_TRANSITIONS: Dict[str, List[str]] = {
    "INGESTED": ["EVALUATED"],
    "EVALUATED": ["MATCHED", "REJECTED"],
    "MATCHED": ["ASSETS_READY", "REJECTED"],
    "ASSETS_READY": ["PENDING_APPROVAL"],
    "PENDING_APPROVAL": ["APPROVED", "REJECTED"],
    "APPROVED": ["DISPATCHING"],
    "DISPATCHING": ["SENT", "SUBMITTED"],
    "SENT": ["FOLLOW_UP", "INTERVIEW", "REJECTED", "CLOSED"],
    "SUBMITTED": ["FOLLOW_UP", "INTERVIEW", "REJECTED", "CLOSED"],
    # Terminal states with no outgoing transitions
    "FOLLOW_UP": [],
    "INTERVIEW": [],
    "REJECTED": [],
    "CLOSED": [],
}


class InvalidStateTransition(Exception):
    """Raised when an invalid state transition is attempted."""

    def __init__(self, current: str, target: str):
        self.current = current
        self.target = target
        super().__init__(f"Invalid state transition: {current} -> {target}")


@dataclass
class Job:
    """Job record from the database."""
    id: str
    source: str
    title: str
    company: str
    url: str
    description: Optional[str]
    state: str
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class DatabaseClient:
    """
    Supabase database client with state machine enforcement.

    All state transitions go through `transition_state()` which
    validates against VALID_TRANSITIONS before calling the
    PostgreSQL `transition_job_state()` function.
    """

    def __init__(self, config: SupabaseConfig):
        self._client: Client = create_client(config.url, config.service_key)
        logger.info("Database client initialized for %s", config.url)

    @property
    def client(self) -> Client:
        """Access the raw Supabase client for advanced queries."""
        return self._client

    # ============================================================
    # Job ID Generation
    # ============================================================

    @staticmethod
    def generate_job_id(source: str, title: str, company: str, url: str) -> str:
        """
        Generate a deterministic job ID from its unique attributes.

        Returns: SHA256 hex digest of source+title+company+url
        """
        raw = f"{source}{title}{company}{url}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    # ============================================================
    # Job CRUD
    # ============================================================

    def insert_job(
        self,
        source: str,
        title: str,
        company: str,
        url: str,
        description: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Insert a new job with state='INGESTED'. Deduplicates on URL.

        Returns the inserted record, or None if the URL already exists.
        """
        job_id = self.generate_job_id(source, title, company, url)
        data = {
            "id": job_id,
            "source": source,
            "title": title,
            "company": company,
            "url": url,
            "description": description,
            "state": "INGESTED",
        }

        try:
            result = (
                self._client.table("jobs")
                .upsert(data, on_conflict="url", ignore_duplicates=True)
                .execute()
            )
            if result.data:
                logger.info("Inserted job %s: %s at %s", job_id[:12], title, company)
                return result.data[0]
            else:
                logger.debug("Duplicate URL skipped: %s", url)
                return None
        except Exception as e:
            logger.error("Failed to insert job: %s", e)
            raise

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Fetch a single job by ID."""
        result = (
            self._client.table("jobs")
            .select("*")
            .eq("id", job_id)
            .execute()
        )
        return result.data[0] if result.data else None

    def get_jobs_by_state(self, state: str, limit: int = 100) -> List[Dict[str, Any]]:
        """Fetch jobs filtered by state, ordered by creation time."""
        result = (
            self._client.table("jobs")
            .select("*")
            .eq("state", state)
            .order("created_at", desc=False)
            .limit(limit)
            .execute()
        )
        return result.data or []

    # ============================================================
    # State Machine
    # ============================================================

    def validate_transition(self, current_state: str, new_state: str) -> bool:
        """
        Validate a state transition against the transition matrix.
        Returns True if valid, False otherwise.
        """
        valid_targets = VALID_TRANSITIONS.get(current_state, [])
        return new_state in valid_targets

    def transition_state(self, job_id: str, new_state: str) -> Dict[str, Any]:
        """
        Transition a job to a new state.

        Validates the transition in Python first (fast-fail),
        then calls the PostgreSQL function for atomic enforcement.

        Args:
            job_id: The job ID to transition
            new_state: Target state

        Returns:
            Updated job record

        Raises:
            InvalidStateTransition: If the transition is not valid
            ValueError: If the job is not found
        """
        # Fetch current state
        job = self.get_job(job_id)
        if not job:
            raise ValueError(f"Job not found: {job_id}")

        current_state = job["state"]

        # Python-side validation (fast-fail before hitting DB)
        if not self.validate_transition(current_state, new_state):
            raise InvalidStateTransition(current_state, new_state)

        # Call PostgreSQL function for atomic transition
        try:
            self._client.rpc(
                "transition_job_state",
                {"p_job_id": job_id, "p_new_state": new_state},
            ).execute()
        except Exception as e:
            logger.error(
                "DB transition failed for %s: %s -> %s: %s",
                job_id[:12], current_state, new_state, e,
            )
            raise

        logger.info(
            "State transition: %s %s -> %s",
            job_id[:12], current_state, new_state,
        )

        # Return the updated record
        return self.get_job(job_id)

    # ============================================================
    # Evaluations
    # ============================================================

    def upsert_evaluation(self, job_id: str, evaluation: Dict[str, Any]) -> Dict[str, Any]:
        """
        Insert or update an evaluation for a job.

        Args:
            job_id: The job being evaluated
            evaluation: Dict with score, method, contact_email, etc.
        """
        data = {"job_id": job_id, **evaluation}
        result = (
            self._client.table("job_evaluations")
            .upsert(data, on_conflict="job_id")
            .execute()
        )
        logger.info("Upserted evaluation for job %s (score=%s)", job_id[:12], evaluation.get("score"))
        return result.data[0] if result.data else data

    def get_evaluation(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Fetch evaluation for a job."""
        result = (
            self._client.table("job_evaluations")
            .select("*")
            .eq("job_id", job_id)
            .execute()
        )
        return result.data[0] if result.data else None

    # ============================================================
    # Application Assets
    # ============================================================

    def upsert_assets(self, job_id: str, cv_pdf_path: str, cover_letter_body: str) -> Dict[str, Any]:
        """Insert or update application assets for a job."""
        data = {
            "job_id": job_id,
            "cv_pdf_path": cv_pdf_path,
            "cover_letter_body": cover_letter_body,
        }
        result = (
            self._client.table("application_assets")
            .upsert(data, on_conflict="job_id")
            .execute()
        )
        logger.info("Upserted assets for job %s", job_id[:12])
        return result.data[0] if result.data else data

    # ============================================================
    # Action Queue
    # ============================================================

    def enqueue_action(self, job_id: str, telegram_chat_id: str) -> Dict[str, Any]:
        """
        Enqueue a job for Telegram approval.
        The idempotency_key is auto-generated by PostgreSQL.
        """
        data = {
            "job_id": job_id,
            "telegram_chat_id": telegram_chat_id,
            "status": "QUEUED",
        }
        result = (
            self._client.table("action_queue")
            .insert(data)
            .execute()
        )
        logger.info("Enqueued action for job %s", job_id[:12])
        return result.data[0] if result.data else data

    def get_pending_dispatches(self, limit: int = 5) -> List[Dict[str, Any]]:
        """
        Fetch action queue items ready for dispatch.
        Default limit of 5 enforces the rate limit per spec §7.
        """
        result = (
            self._client.table("action_queue")
            .select("*, jobs(*)")
            .eq("status", "APPROVED_FOR_DISPATCH")
            .limit(limit)
            .execute()
        )
        return result.data or []

    def update_queue_status(
        self,
        queue_id: str,
        status: str,
        timestamp_field: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Update the status of an action queue item.

        Args:
            queue_id: UUID of the queue item
            status: New status ('EXECUTING', 'DONE', 'FAILED', etc.)
            timestamp_field: Optional field to set to NOW() ('approved_at', 'executed_at')
        """
        data: Dict[str, Any] = {"status": status}
        if timestamp_field:
            data[timestamp_field] = datetime.now(timezone.utc).isoformat()

        result = (
            self._client.table("action_queue")
            .update(data)
            .eq("id", queue_id)
            .execute()
        )
        logger.info("Queue %s -> %s", queue_id[:12], status)
        return result.data[0] if result.data else data
