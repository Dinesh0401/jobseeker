import pytest

from src.db.client import DatabaseClient


class _Result:
    def __init__(self, data):
        self.data = data


class _JobEvaluationsTable:
    def __init__(self, error_messages=None):
        self.error_messages = list(error_messages or [])
        self.calls = 0
        self.upsert_payloads = []

    def upsert(self, data, on_conflict):
        self.upsert_payloads.append(dict(data))
        return self

    def execute(self):
        self.calls += 1
        if self.error_messages:
            raise Exception(self.error_messages.pop(0))
        return _Result([{"job_id": "job-1", "score": 77}])


class _Client:
    def __init__(self, table):
        self._table = table

    def table(self, name):
        assert name == "job_evaluations"
        return self._table


def _build_db(table):
    db = DatabaseClient.__new__(DatabaseClient)
    db._client = _Client(table)
    return db


def test_upsert_evaluation_retries_when_schema_missing_column():
    table = _JobEvaluationsTable(
        error_messages=[
            "Could not find the 'email_type' column of 'job_evaluations' in the schema cache",
            "Could not find the 'required_documents' column of 'job_evaluations' in the schema cache",
        ],
    )
    db = _build_db(table)

    result = db.upsert_evaluation(
        "job-1",
        {"score": 77, "email_type": "HR", "required_documents": "{}", "method": "test"},
    )

    assert result["score"] == 77
    assert table.calls == 3
    assert "email_type" in table.upsert_payloads[0]
    assert "email_type" not in table.upsert_payloads[1]
    assert "required_documents" not in table.upsert_payloads[2]
    assert table.upsert_payloads[2]["method"] == "test"


def test_upsert_evaluation_raises_for_non_schema_error():
    table = _JobEvaluationsTable(error_messages=["network timeout"])
    db = _build_db(table)

    with pytest.raises(Exception, match="network timeout"):
        db.upsert_evaluation("job-1", {"score": 70})
