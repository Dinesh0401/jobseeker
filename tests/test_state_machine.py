"""
Unit tests for the state machine transition logic.

Tests the Python-side validation in DatabaseClient.validate_transition()
without requiring a live database connection.

Spec Reference: Technical_Specification.md §3
"""

import pytest

from src.db.client import (
    DatabaseClient,
    InvalidStateTransition,
    VALID_TRANSITIONS,
)


# ============================================================
# Transition Matrix Completeness
# ============================================================

class TestTransitionMatrix:
    """Verify the transition matrix covers all states."""

    ALL_STATES = [
        "INGESTED", "EVALUATED", "MATCHED", "ASSETS_READY",
        "PENDING_APPROVAL", "APPROVED", "DISPATCHING",
        "SENT", "SUBMITTED", "FOLLOW_UP", "INTERVIEW",
        "REJECTED", "CLOSED",
    ]

    def test_all_states_in_matrix(self):
        """Every state must appear as a key in VALID_TRANSITIONS."""
        for state in self.ALL_STATES:
            assert state in VALID_TRANSITIONS, f"Missing state: {state}"

    def test_no_unknown_states_in_targets(self):
        """Transition targets must all be valid states."""
        for source, targets in VALID_TRANSITIONS.items():
            for target in targets:
                assert target in self.ALL_STATES, (
                    f"Unknown target state: {source} -> {target}"
                )


# ============================================================
# Valid Transitions
# ============================================================

class TestValidTransitions:
    """Test that all valid transitions are accepted."""

    @pytest.mark.parametrize(
        "current, target",
        [
            ("INGESTED", "EVALUATED"),
            ("EVALUATED", "MATCHED"),
            ("EVALUATED", "REJECTED"),
            ("MATCHED", "ASSETS_READY"),
            ("MATCHED", "REJECTED"),
            ("ASSETS_READY", "PENDING_APPROVAL"),
            ("PENDING_APPROVAL", "APPROVED"),
            ("PENDING_APPROVAL", "REJECTED"),
            ("APPROVED", "DISPATCHING"),
            ("DISPATCHING", "SENT"),
            ("DISPATCHING", "SUBMITTED"),
            ("SENT", "FOLLOW_UP"),
            ("SENT", "INTERVIEW"),
            ("SENT", "REJECTED"),
            ("SENT", "CLOSED"),
            ("SUBMITTED", "FOLLOW_UP"),
            ("SUBMITTED", "INTERVIEW"),
            ("SUBMITTED", "REJECTED"),
            ("SUBMITTED", "CLOSED"),
        ],
    )
    def test_valid_transition(self, current, target):
        assert DatabaseClient.validate_transition(None, current, target) is True


# ============================================================
# Invalid Transitions — Hard Rejects
# ============================================================

class TestInvalidTransitions:
    """Test that illegal state transitions are rejected."""

    @pytest.mark.parametrize(
        "current, target, reason",
        [
            # Skip enrichment
            ("INGESTED", "MATCHED", "Cannot skip EVALUATED"),
            ("INGESTED", "SENT", "Cannot skip entire pipeline"),
            ("INGESTED", "APPROVED", "Cannot skip to approval"),
            # Skip approval
            ("EVALUATED", "SENT", "Cannot skip to SENT"),
            ("EVALUATED", "DISPATCHING", "Cannot skip to DISPATCHING"),
            ("MATCHED", "DISPATCHING", "Must go through PENDING_APPROVAL"),
            ("MATCHED", "SENT", "Cannot skip to SENT"),
            # Backward transitions
            ("SENT", "INGESTED", "Cannot go backward"),
            ("APPROVED", "EVALUATED", "Cannot go backward"),
            ("DISPATCHING", "APPROVED", "Cannot go backward"),
            # Terminal states
            ("REJECTED", "EVALUATED", "REJECTED is terminal"),
            ("REJECTED", "MATCHED", "REJECTED is terminal"),
            ("REJECTED", "APPROVED", "REJECTED is terminal"),
            ("CLOSED", "INGESTED", "CLOSED is terminal"),
            ("CLOSED", "FOLLOW_UP", "CLOSED is terminal"),
            # Self-transitions
            ("INGESTED", "INGESTED", "Cannot self-transition"),
            ("SENT", "SENT", "Cannot self-transition"),
            # FOLLOW_UP and INTERVIEW are terminal
            ("FOLLOW_UP", "SENT", "FOLLOW_UP is terminal"),
            ("INTERVIEW", "SENT", "INTERVIEW is terminal"),
        ],
    )
    def test_invalid_transition(self, current, target, reason):
        assert DatabaseClient.validate_transition(None, current, target) is False, reason


# ============================================================
# InvalidStateTransition Exception
# ============================================================

class TestInvalidStateTransitionException:
    """Test the exception class."""

    def test_exception_message(self):
        exc = InvalidStateTransition("INGESTED", "SENT")
        assert exc.current == "INGESTED"
        assert exc.target == "SENT"
        assert "INGESTED" in str(exc)
        assert "SENT" in str(exc)


# ============================================================
# Job ID Generation
# ============================================================

class TestJobIdGeneration:
    """Test deterministic SHA256 job ID generation."""

    def test_deterministic(self):
        """Same inputs produce same ID."""
        id1 = DatabaseClient.generate_job_id("linkedin", "Dev", "Corp", "https://example.com/1")
        id2 = DatabaseClient.generate_job_id("linkedin", "Dev", "Corp", "https://example.com/1")
        assert id1 == id2

    def test_different_inputs_produce_different_ids(self):
        """Different inputs produce different IDs."""
        id1 = DatabaseClient.generate_job_id("linkedin", "Dev", "Corp", "https://example.com/1")
        id2 = DatabaseClient.generate_job_id("indeed", "Dev", "Corp", "https://example.com/2")
        assert id1 != id2

    def test_id_is_sha256_hex(self):
        """ID should be a 64-character hex string."""
        job_id = DatabaseClient.generate_job_id("src", "title", "co", "url")
        assert len(job_id) == 64
        assert all(c in "0123456789abcdef" for c in job_id)
