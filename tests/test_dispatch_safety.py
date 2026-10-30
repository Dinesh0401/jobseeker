"""
Unit tests for dispatch safety gating and orphan task recovery.
"""

from unittest.mock import MagicMock
from src.dispatchers.gmail import _recover_stale_executing, dispatch_approved_applications


def test_recover_stale_executing():
    """Verify that _recover_stale_executing resets status and job state."""
    cur = MagicMock()
    cur.fetchall.return_value = [{"id": "queue-1", "job_id": "job-1"}]

    recovered = _recover_stale_executing(cur)

    assert recovered == 1
    assert cur.execute.call_count == 2
    # Second execute should reset job state
    assert "UPDATE jobs SET state = 'APPROVED'" in cur.execute.call_args_list[1][0][0]


def test_dispatch_aborts_when_profile_has_placeholders(monkeypatch):
    """Verify that dispatch halts without opening DB connection if profile is invalid."""
    get_conn_mock = MagicMock()
    monkeypatch.setattr("src.dispatchers.gmail.get_connection", get_conn_mock)

    # Calling dispatch on current repository with placeholders
    dispatch_approved_applications()

    # get_connection should NEVER be called because safety gate blocks early
    assert get_conn_mock.call_count == 0
