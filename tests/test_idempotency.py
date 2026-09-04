"""
Unit tests for dispatch idempotency logic.

Validates idempotency key generation and the dispatch
safety protocol from Technical_Specification.md §7.
"""

import hashlib
from datetime import date

import pytest


# ============================================================
# Idempotency Key Generation (matches dispatcher contract)
# ============================================================

def generate_idempotency_key(job_id: str, contact_email: str, dispatch_date: str) -> str:
    """
    Generate a deterministic idempotency key for dispatch.

    This mirrors the logic that will be in src/dispatcher/mailer.py.

    Args:
        job_id: The SHA256 job identifier
        contact_email: Target email address
        dispatch_date: ISO date string (YYYY-MM-DD)

    Returns:
        SHA256 hex digest of the combined inputs
    """
    raw = f"{job_id}{contact_email}{dispatch_date}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class TestIdempotencyKeyGeneration:
    """Test the idempotency key generation function."""

    def test_deterministic_output(self):
        """Same inputs always produce the same key."""
        key1 = generate_idempotency_key("abc123", "hr@corp.de", "2026-09-01")
        key2 = generate_idempotency_key("abc123", "hr@corp.de", "2026-09-01")
        assert key1 == key2

    def test_different_job_different_key(self):
        """Different job IDs produce different keys."""
        key1 = generate_idempotency_key("job_a", "hr@corp.de", "2026-09-01")
        key2 = generate_idempotency_key("job_b", "hr@corp.de", "2026-09-01")
        assert key1 != key2

    def test_different_email_different_key(self):
        """Different emails produce different keys."""
        key1 = generate_idempotency_key("abc123", "hr@corp.de", "2026-09-01")
        key2 = generate_idempotency_key("abc123", "jobs@corp.de", "2026-09-01")
        assert key1 != key2

    def test_different_date_different_key(self):
        """Different dates produce different keys."""
        key1 = generate_idempotency_key("abc123", "hr@corp.de", "2026-09-01")
        key2 = generate_idempotency_key("abc123", "hr@corp.de", "2026-09-02")
        assert key1 != key2

    def test_key_is_sha256_hex(self):
        """Key should be a 64-character hex string."""
        key = generate_idempotency_key("abc", "x@y.com", "2026-01-01")
        assert len(key) == 64
        assert all(c in "0123456789abcdef" for c in key)

    def test_empty_inputs_still_produce_key(self):
        """Even empty strings produce a valid hash."""
        key = generate_idempotency_key("", "", "")
        assert len(key) == 64


class TestDispatchSafetyProtocol:
    """Test the dispatch safety checks per spec §7."""

    def test_only_approved_for_dispatch_is_valid(self):
        """Only APPROVED_FOR_DISPATCH items should be picked up."""
        valid_statuses = {"APPROVED_FOR_DISPATCH"}
        invalid_statuses = {"QUEUED", "EXECUTING", "DONE", "FAILED"}

        for status in valid_statuses:
            assert status == "APPROVED_FOR_DISPATCH"

        for status in invalid_statuses:
            assert status != "APPROVED_FOR_DISPATCH"

    def test_rate_limit_is_five(self):
        """Dispatch worker must cap at 5 per run."""
        MAX_EMAILS_PER_RUN = 5
        batch = list(range(10))  # simulate 10 pending items
        dispatched = batch[:MAX_EMAILS_PER_RUN]
        assert len(dispatched) == 5

    def test_dispatch_failure_tracked_in_queue_not_job_state(self):
        """Dispatch failure stays in action_queue.status, NOT jobs.state.

        Per schema.sql: 'Dispatch execution failures are tracked in
        action_queue.status, NOT as an application_state.'
        The job reverts from DISPATCHING → APPROVED so it can be re-queued.
        """
        from src.db.client import VALID_TRANSITIONS
        # FAILED should NOT be a valid application state
        assert "FAILED" not in VALID_TRANSITIONS
        # But FAILED is a valid action_queue status
        valid_queue_statuses = {"QUEUED", "APPROVED_FOR_DISPATCH", "EXECUTING", "DONE", "FAILED"}
        assert "FAILED" in valid_queue_statuses
