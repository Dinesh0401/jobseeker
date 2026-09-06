import os
import pytest
from pathlib import Path

from src.db.client import DatabaseClient
from src.pipeline import phase_generate_tex, phase_finalize_assets
from src.config import Config

@pytest.fixture
def mock_db():
    # We would ideally mock the db or use a test container, 
    # but for unit testing the pipeline logic, we can mock the DatabaseClient.
    class MockDB:
        def __init__(self):
            self.jobs = {}
            self.evaluations = {}
            self.actions = []
            self.assets = {}
            self.transitions = []
            self.inserted_actions = []

            class MockActionQueueQuery:
                def __init__(self, parent):
                    self.parent = parent
                    self._job_id = None

                def select(self, *_args, **_kwargs):
                    return self

                def eq(self, column, value):
                    if column == "job_id":
                        self._job_id = value
                    return self

                def limit(self, _n):
                    return self

                def execute(self):
                    found = [a for a in self.parent.actions if a['job_id'] == self._job_id]
                    data = [{"id": found[0]['id']}] if found else []
                    return type("Result", (), {"data": data})()

            class MockSupabaseClient:
                def __init__(self, parent):
                    self.parent = parent

                def table(self, name):
                    assert name == "action_queue"
                    return MockActionQueueQuery(self.parent)

            self.client = MockSupabaseClient(self)

        def get_jobs_by_state(self, state):
            return [j for j in self.jobs.values() if j['state'] == state]

        def upsert_evaluation(self, job_id, data):
            if job_id not in self.evaluations:
                self.evaluations[job_id] = {}
            self.evaluations[job_id].update(data)

        def get_evaluation(self, job_id):
            return self.evaluations.get(job_id, {})

        def transition_state(self, job_id, new_state):
            self.jobs[job_id]['state'] = new_state
            self.transitions.append((job_id, new_state))

        def upsert_assets(self, job_id, cv_pdf_path, cover_letter_body):
            self.assets[job_id] = {"pdf": cv_pdf_path, "cover": cover_letter_body}

        def enqueue_action(self, job_id, chat_id):
            new_id = "test-queue-id"
            self.actions.append({"id": new_id, "job_id": job_id, "telegram_chat_id": chat_id, "status": "QUEUED"})
            self.inserted_actions.append(job_id)
            return {"id": new_id}
            
    return MockDB()

def test_missing_pdf_blocks_assets_ready(mock_db, monkeypatch, tmp_path):
    # Setup MATCHED job
    job_id = "job-missing-pdf"
    mock_db.jobs[job_id] = {"id": job_id, "title": "Test", "company": "TestCorp", "state": "MATCHED"}
    mock_db.upsert_evaluation(job_id, {"cover_letter_pitch": "Hello"})
    
    # Run finalize
    with pytest.raises(FileNotFoundError):
        phase_finalize_assets(mock_db, output_dir=str(tmp_path))
    
    # Assert
    assert mock_db.jobs[job_id]['state'] == "MATCHED", "Job should remain MATCHED if PDF is missing"
    assert ("job-missing-pdf", "ASSETS_READY") not in mock_db.transitions

def test_pdf_exists_progresses_to_pending_approval(mock_db, monkeypatch, tmp_path):
    job_id = "job-has-pdf"
    mock_db.jobs[job_id] = {"id": job_id, "title": "Test", "company": "TestCorp", "state": "MATCHED"}
    mock_db.upsert_evaluation(job_id, {"cover_letter_pitch": "Hello", "score": 90, "contact_email": "test@test.com"})
    
    # Create fake PDF
    pdf_path = tmp_path / f"{job_id[:16]}_cv.pdf"
    pdf_path.touch()
    
    # Mock telegram
    telegram_called = False
    def mock_send(*args, **kwargs):
        nonlocal telegram_called
        telegram_called = True
    
    monkeypatch.setattr("src.pipeline.send_approval_card", mock_send)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "fake")
    monkeypatch.setenv("MY_TELEGRAM_CHAT_ID", "fake")
    
    phase_finalize_assets(mock_db, output_dir=str(tmp_path))
    
    # Assert
    assert mock_db.jobs[job_id]['state'] == "PENDING_APPROVAL"
    assert ("job-has-pdf", "ASSETS_READY") in mock_db.transitions
    assert telegram_called
    assert job_id in mock_db.assets
    assert job_id in mock_db.inserted_actions

def test_duplicate_telegram_card_prevention(mock_db, monkeypatch, tmp_path):
    job_id = "job-duplicate-test"
    # Put job in ASSETS_READY
    mock_db.jobs[job_id] = {"id": job_id, "title": "Test", "company": "TestCorp", "state": "ASSETS_READY"}
    mock_db.upsert_evaluation(job_id, {"score": 90})
    
    # Simulate action_queue already has an entry
    mock_db.actions.append({"id": "existing-queue", "job_id": job_id, "status": "QUEUED"})
    
    telegram_called = False
    def mock_send(*args, **kwargs):
        nonlocal telegram_called
        telegram_called = True
        
    monkeypatch.setattr("src.pipeline.send_approval_card", mock_send)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "fake")
    monkeypatch.setenv("MY_TELEGRAM_CHAT_ID", "fake")
    
    phase_finalize_assets(mock_db, output_dir=str(tmp_path))
    
    # Assert telegram was sent (idempotently picks up existing queue id)
    assert telegram_called
    # Assert no new action_queue was inserted
    assert len(mock_db.inserted_actions) == 0
    assert mock_db.jobs[job_id]['state'] == "PENDING_APPROVAL"
