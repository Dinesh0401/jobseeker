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
            
            # For transaction mocking
            class MockCursor:
                def __init__(self, parent):
                    self.parent = parent
                    self._last_row = None
                def __enter__(self): return self
                def __exit__(self, *args): pass
                def execute(self, query, params=None):
                    if "INSERT INTO application_assets" in query:
                        self.parent.assets[params[0]] = {"pdf": params[1], "cover": params[2]}
                    elif "SELECT id FROM action_queue WHERE job_id" in query:
                        found = [a for a in self.parent.actions if a['job_id'] == params[0]]
                        self._last_row = {"id": found[0]['id']} if found else None
                    elif "INSERT INTO action_queue" in query:
                        new_id = "test-queue-id"
                        self.parent.actions.append({"id": new_id, "job_id": params[0], "status": "QUEUED"})
                        self.parent.inserted_actions.append(params[0])
                        self._last_row = {"id": new_id}
                def fetchone(self):
                    return self._last_row
                
            class MockConn:
                def __init__(self, parent): self.parent = parent
                def cursor(self): return MockCursor(self.parent)
                def commit(self): pass
                
            self._conn = MockConn(self)

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
            
    return MockDB()

def test_missing_pdf_blocks_assets_ready(mock_db, monkeypatch, tmp_path):
    # Setup MATCHED job
    job_id = "job-missing-pdf"
    mock_db.jobs[job_id] = {"id": job_id, "title": "Test", "company": "TestCorp", "state": "MATCHED"}
    mock_db.upsert_evaluation(job_id, {"cover_letter_pitch": "Hello"})
    
    # Run finalize
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
