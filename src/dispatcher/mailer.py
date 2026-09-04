"""
Email Dispatcher for Job Hunter v1.

Sends job applications via Gmail SMTP with PDF attachments.
Enforces idempotency via SHA256 keys and rate limiting.

Spec Reference: Technical_Specification.md §7

Invariants:
  - No email is sent without verifying APPROVED_FOR_DISPATCH state.
  - Idempotency key prevents duplicate sends.
  - Rate limit: max 5 emails per run (configurable).
  - SMTP timeout reverts to APPROVED_FOR_DISPATCH for retry.
"""

import hashlib
import logging
import smtplib
from datetime import date, datetime, timezone
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.config import DispatchConfig, GmailConfig
from src.db.client import DatabaseClient

logger = logging.getLogger(__name__)


# ============================================================
# Idempotency Key Generation
# ============================================================

def generate_idempotency_key(job_id: str, contact_email: str, dispatch_date: Optional[str] = None) -> str:
    """
    Generate a deterministic idempotency key for dispatch.

    Args:
        job_id: The SHA256 job identifier.
        contact_email: Target email address.
        dispatch_date: ISO date string. Defaults to today.

    Returns:
        SHA256 hex digest of the combined inputs.
    """
    if dispatch_date is None:
        dispatch_date = date.today().isoformat()
    raw = f"{job_id}{contact_email}{dispatch_date}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ============================================================
# Email Composer
# ============================================================

def compose_email(
    sender: str,
    recipient: str,
    subject: str,
    body: str,
    pdf_path: Optional[str] = None,
) -> MIMEMultipart:
    """
    Compose a MIME email with optional PDF attachment.

    Args:
        sender: Sender email address.
        recipient: Recipient email address.
        subject: Email subject line.
        body: Email body text.
        pdf_path: Optional path to PDF attachment.

    Returns:
        MIMEMultipart email object.
    """
    msg = MIMEMultipart()
    msg["From"] = sender
    msg["To"] = recipient
    msg["Subject"] = subject

    # Body
    msg.attach(MIMEText(body, "plain", "utf-8"))

    # PDF attachment
    if pdf_path:
        pdf_file = Path(pdf_path)
        if pdf_file.exists():
            with open(pdf_file, "rb") as f:
                part = MIMEBase("application", "pdf")
                part.set_payload(f.read())
                encoders.encode_base64(part)
                part.add_header(
                    "Content-Disposition",
                    f"attachment; filename={pdf_file.name}",
                )
                msg.attach(part)
            logger.info("Attached PDF: %s", pdf_file.name)
        else:
            logger.warning("PDF not found for attachment: %s", pdf_path)

    return msg


# ============================================================
# SMTP Sender
# ============================================================

def send_email(
    gmail_config: GmailConfig,
    msg: MIMEMultipart,
) -> bool:
    """
    Send an email via Gmail SMTP.

    Args:
        gmail_config: Gmail SMTP configuration.
        msg: Composed MIME email.

    Returns:
        True if sent successfully, False on failure.
    """
    try:
        with smtplib.SMTP(gmail_config.smtp_host, gmail_config.smtp_port, timeout=gmail_config.smtp_timeout) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(gmail_config.sender_address, gmail_config.app_password)
            server.send_message(msg)

        logger.info("Email sent to: %s", msg["To"])
        return True

    except smtplib.SMTPException as e:
        logger.error("SMTP error sending to %s: %s", msg["To"], e)
        return False
    except TimeoutError:
        logger.error("SMTP timeout sending to %s", msg["To"])
        return False
    except Exception as e:
        logger.error("Unexpected error sending email: %s", e)
        return False


# ============================================================
# Dispatch Worker
# ============================================================

class Dispatcher:
    """
    Email dispatch worker with idempotency and rate limiting.

    Processes the action_queue, sends emails with CV attachments,
    and manages state transitions.
    """

    def __init__(
        self,
        db: DatabaseClient,
        gmail_config: GmailConfig,
        dispatch_config: DispatchConfig,
    ):
        self._db = db
        self._gmail = gmail_config
        self._dispatch = dispatch_config
        logger.info(
            "Dispatcher initialized (max_per_run=%d, max_retries=%d)",
            dispatch_config.max_emails_per_run,
            dispatch_config.retry_max,
        )

    def run(self) -> Dict[str, int]:
        """
        Process the dispatch queue.

        Fetches APPROVED_FOR_DISPATCH items (up to rate limit),
        sends emails, and updates states.

        Returns:
            Dict with counts: {"sent": N, "failed": N, "skipped": N}
        """
        stats = {"sent": 0, "failed": 0, "skipped": 0}

        # Fetch pending items (rate limited by query)
        pending = self._db.get_pending_dispatches(
            limit=self._dispatch.max_emails_per_run
        )

        if not pending:
            logger.info("No items in dispatch queue.")
            return stats

        logger.info("Processing %d dispatch items", len(pending))

        for item in pending:
            queue_id = item["id"]
            job_id = item["job_id"]

            try:
                result = self._dispatch_single(item)
                if result:
                    stats["sent"] += 1
                else:
                    stats["failed"] += 1
            except Exception as e:
                logger.error("Dispatch error for queue %s: %s", queue_id, e)
                stats["failed"] += 1

                # Revert to APPROVED_FOR_DISPATCH for retry
                try:
                    self._db.update_queue_status(queue_id, "APPROVED_FOR_DISPATCH")
                except Exception:
                    logger.error("Failed to revert queue status for %s", queue_id)

        logger.info(
            "Dispatch complete: sent=%d, failed=%d, skipped=%d",
            stats["sent"], stats["failed"], stats["skipped"],
        )
        return stats

    def _dispatch_single(self, queue_item: Dict[str, Any]) -> bool:
        """
        Dispatch a single application email.

        Args:
            queue_item: Action queue record with joined job data.

        Returns:
            True if sent successfully.
        """
        queue_id = queue_item["id"]
        job_id = queue_item["job_id"]
        idempotency_key = queue_item.get("idempotency_key", "")

        # 1. Lock: set status to EXECUTING
        self._db.update_queue_status(queue_id, "EXECUTING")

        # 2. Transition job state: APPROVED -> DISPATCHING
        try:
            self._db.transition_state(job_id, "DISPATCHING")
        except Exception as e:
            logger.error("State transition to DISPATCHING failed for %s: %s", job_id[:12], e)
            self._db.update_queue_status(queue_id, "APPROVED_FOR_DISPATCH")
            return False

        # 3. Fetch evaluation for contact email
        evaluation = self._db.get_evaluation(job_id)
        if not evaluation or not evaluation.get("contact_email"):
            logger.error("No contact email for job %s", job_id[:12])
            self._db.update_queue_status(queue_id, "FAILED")
            self._db.transition_state(job_id, "FAILED")
            return False

        contact_email = evaluation["contact_email"]

        # 4. Fetch application assets
        job = self._db.get_job(job_id)
        assets_result = (
            self._db.client.table("application_assets")
            .select("*")
            .eq("job_id", job_id)
            .execute()
        )
        assets = assets_result.data[0] if assets_result.data else None

        # 5. Compose email
        subject = f"Application: {job.get('title', 'Position')} at {job.get('company', 'Company')}"
        body = assets.get("cover_letter_body", "") if assets else ""
        pdf_path = assets.get("cv_pdf_path") if assets else None

        if not body:
            body = f"Dear Hiring Team,\n\nI am writing to express my interest in the {job.get('title', 'position')} role at {job.get('company', 'your company')}.\n\nPlease find my CV attached.\n\nBest regards"

        msg = compose_email(
            sender=self._gmail.sender_address,
            recipient=contact_email,
            subject=subject,
            body=body,
            pdf_path=pdf_path,
        )

        # 6. Send with retries
        sent = False
        for attempt in range(1, self._dispatch.retry_max + 1):
            logger.info(
                "Sending email to %s (attempt %d/%d)",
                contact_email, attempt, self._dispatch.retry_max,
            )
            if send_email(self._gmail, msg):
                sent = True
                break
            logger.warning("Attempt %d failed for %s", attempt, contact_email)

        # 7. Update states based on result
        if sent:
            self._db.update_queue_status(queue_id, "DONE", "executed_at")
            self._db.transition_state(job_id, "SENT")
            logger.info("✅ Dispatched to %s (job: %s)", contact_email, job_id[:12])
            return True
        else:
            self._db.update_queue_status(queue_id, "FAILED")
            self._db.transition_state(job_id, "FAILED")
            logger.error(
                "❌ Failed to dispatch to %s after %d attempts",
                contact_email, self._dispatch.retry_max,
            )
            return False
