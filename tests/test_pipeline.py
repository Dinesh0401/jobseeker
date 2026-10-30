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
            class MockClientTableSelectEq:
                def __init__(self, parent, table, column, value):
                    self.parent = parent
                    self.table = table
                    self.value = value
                def execute(self):
                    class MockRes:
                        def __init__(self, data): self.data = data
                    if self.table == "action_queue":
                        found = [a for a in self.parent.actions if a['job_id'] == self.value]
                        return MockRes([{"id": found[0]['id']}] if found else [])
                    return MockRes([])

            class MockClientTableSelect:
                def __init__(self, parent, table, cols):
                    self.parent = parent
                    self.table = table
                def eq(self, column, value):
                    return MockClientTableSelectEq(self.parent, self.table, column, value)
            
            class MockClientTable:
                def __init__(self, parent, table):
                    self.parent = parent
                    self.table = table
                def select(self, cols):
                    return MockClientTableSelect(self.parent, self.table, cols)

            class MockClient:
                def __init__(self, parent):
                    self.parent = parent
                def table(self, name):
                    return MockClientTable(self.parent, name)

            self.client = MockClient(self)

        def insert_job(self, source, title, company, url, description):
            job_id = DatabaseClient.generate_job_id(source, title, company, url)
            if job_id in self.jobs:
                return None
            self.jobs[job_id] = {
                "id": job_id,
                "source": source,
                "title": title,
                "company": company,
                "url": url,
                "description": description,
                "state": "INGESTED",
            }
            return {"id": job_id}

        def upsert_assets(self, job_id, pdf_path, cover_letter):
            self.assets[job_id] = {"pdf": pdf_path, "cover": cover_letter}

        def enqueue_action(self, job_id, recipient=None):
            new_id = "test-queue-id"
            self.actions.append({"id": new_id, "job_id": job_id, "status": "QUEUED"})
            self.inserted_actions.append(job_id)
            return {"id": new_id}

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

def test_missing_required_documents_blocks_assets_ready(mock_db, monkeypatch, tmp_path):
    job_id = "job-missing-degree"
    # Job description requires degree certificate at application time
    desc = "Please submit your degree certificate and transcripts along with your application."
    mock_db.jobs[job_id] = {
        "id": job_id,
        "title": "Test",
        "company": "TestCorp",
        "state": "MATCHED",
        "description": desc
    }
    mock_db.upsert_evaluation(job_id, {"cover_letter_pitch": "Hello", "score": 85})
    
    # Create fake PDF
    pdf_path = tmp_path / f"{job_id[:16]}_cv.pdf"
    pdf_path.touch()
    
    phase_finalize_assets(mock_db, output_dir=str(tmp_path))
    
    # Assert job remains in MATCHED because required document (Degree Certificate) is missing
    assert mock_db.jobs[job_id]['state'] == "MATCHED"
    assert (job_id, "ASSETS_READY") not in mock_db.transitions


def test_pipeline_e2e_generate_tex_and_finalize(mock_db, monkeypatch, tmp_path):
    from src.collectors.aggregator import CollectionReport
    from src.matching.models import GeminiEvaluationResponse
    from src.observability.metrics import RunSummary

    # 1. Mock Collector Aggregator to return 2 jobs: 1 target junior role, 1 senior role
    def mock_aggregator_run(self, db, limit_per_source=30):
        db.insert_job(
            source="arbeitnow",
            title="Junior AI Engineer",
            company="RemoteAI Labs",
            url="https://example.com/junior-ai",
            description="We are seeking an entry-level Junior AI Engineer. Requirements: Python, LLMs, and RAG. Fully remote worldwide. English only. 0-1 years of experience.",
        )
        db.insert_job(
            source="jobicy",
            title="Senior Director of Machine Learning",
            company="Enterprise AI",
            url="https://example.com/senior-director",
            description="Leading AI teams. Requirements: 10+ years experience, staff management.",
        )
        report = CollectionReport(
            sources_attempted=2,
            sources_successful=2,
            jobs_fetched=2,
            jobs_relevant=2,
            jobs_inserted=2,
        )
        return report

    monkeypatch.setattr("src.pipeline.JobCollectorAggregator.run", mock_aggregator_run)

    # 2. Mock Gemini call in SemanticMatcher
    def mock_call_gemini(self, prompt):
        return {
            "technical_score": 92,
            "matched_skills": ["Python", "LLMs"],
            "missing_skills": [],
            "matched_experience_keys": ["internship_applied_ai"],
            "matched_project_keys": ["job_hunter_v2"],
            "experience_fit_score": 95,
            "recommendation": "APPLY",
            "risks_and_reasons": [],
            "cover_letter_pitch": "I am passionate about building agentic workflows with Python.",
        }

    monkeypatch.setattr("src.matching.evaluator.SemanticMatcher._call_gemini_with_retry", mock_call_gemini)

    # Phase 1: generate_tex
    summary = RunSummary()
    phase_generate_tex(
        db=mock_db,
        profile_dir="profile",
        match_threshold=60,
        output_dir=str(tmp_path),
        summary=summary,
    )

    # Verify that junior job matched and senior job was rejected
    junior_jobs = [j for j in mock_db.jobs.values() if "Junior" in j["title"]]
    senior_jobs = [j for j in mock_db.jobs.values() if "Senior" in j["title"]]
    assert len(junior_jobs) == 1
    assert len(senior_jobs) == 1

    junior_id = junior_jobs[0]["id"]
    senior_id = senior_jobs[0]["id"]

    assert junior_jobs[0]["state"] == "MATCHED"
    assert senior_jobs[0]["state"] == "REJECTED"

    # Verify .tex and provenance JSON generated for junior job
    tex_file = tmp_path / f"{junior_id[:16]}_cv.tex"
    provenance_file = tmp_path / f"{junior_id[:16]}_provenance.json"
    assert tex_file.exists(), "LaTeX CV file should have been generated for matched job"
    assert provenance_file.exists(), "Provenance JSON should have been generated for matched job"

    # Verify no .tex generated for senior job
    senior_tex = tmp_path / f"{senior_id[:16]}_cv.tex"
    assert not senior_tex.exists(), "No CV should be generated for rejected job"

    # Phase 2: finalize_assets
    # Create fake valid compiled PDF (>2KB) for the matched job
    pdf_path = tmp_path / f"{junior_id[:16]}_cv.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n" + b"A" * 2500)

    telegram_sent = []
    def mock_send_card(*args, **kwargs):
        telegram_sent.append(kwargs)

    monkeypatch.setattr("src.pipeline.send_approval_card", mock_send_card)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "mock-token")
    monkeypatch.setenv("MY_TELEGRAM_CHAT_ID", "mock-chat-id")

    phase_finalize_assets(mock_db, output_dir=str(tmp_path), summary=summary)

    # Verify job moved to PENDING_APPROVAL and action_queue was created
    assert junior_jobs[0]["state"] == "PENDING_APPROVAL"
    assert len(mock_db.actions) == 1
    assert mock_db.actions[0]["job_id"] == junior_id
    assert len(telegram_sent) == 1
    assert summary.jobs_sent_to_telegram == 1


def test_pipeline_unknown_eligibility_with_perfect_tech_score_does_not_generate_cv(mock_db, monkeypatch, tmp_path):
    from src.collectors.aggregator import CollectionReport
    from src.observability.metrics import RunSummary

    # Collector returns a job with unknown location eligibility
    def mock_aggregator_run(self, db, limit_per_source=30):
        db.insert_job(
            source="custom",
            title="Junior AI Engineer",
            company="Stealth AI Labs",
            url="https://example.com/stealth-ai",
            description="We are seeking an entry-level Junior AI Engineer with Python and LLMs. 0-1 years exp.",
        )
        return CollectionReport(sources_attempted=1, sources_successful=1, jobs_fetched=1, jobs_relevant=1, jobs_inserted=1)

    monkeypatch.setattr("src.pipeline.JobCollectorAggregator.run", mock_aggregator_run)

    # Gemini returns perfect 100 technical score
    def mock_call_gemini(self, prompt):
        return {
            "technical_score": 100,
            "matched_skills": ["Python", "LLMs"],
            "missing_skills": [],
            "matched_experience_keys": ["exp_example"],
            "matched_project_keys": ["project_example"],
            "experience_fit_score": 100,
            "recommendation": "APPLY",
            "risks_and_reasons": [],
            "cover_letter_pitch": "Perfect fit.",
        }

    monkeypatch.setattr("src.matching.evaluator.SemanticMatcher._call_gemini_with_retry", mock_call_gemini)

    summary = RunSummary()
    phase_generate_tex(
        db=mock_db,
        profile_dir="profile",
        match_threshold=60,
        output_dir=str(tmp_path),
        summary=summary,
    )

    jobs = list(mock_db.jobs.values())
    assert len(jobs) == 1
    job = jobs[0]

    # Verify job is held in EVALUATED state and NOT promoted to MATCHED
    assert job["state"] == "EVALUATED", "Unknown location eligibility must remain EVALUATED on hold"
    assert summary.jobs_held_for_verification == 1

    # Verify NO .tex file is created for held job
    tex_file = tmp_path / f"{job['id'][:16]}_cv.tex"
    assert not tex_file.exists(), "Unknown eligibility must NEVER generate a CV"


def test_pipeline_india_exclusion_with_worldwide_wording_is_rejected(mock_db, monkeypatch, tmp_path):
    from src.collectors.aggregator import CollectionReport
    from src.observability.metrics import RunSummary

    def mock_aggregator_run(self, db, limit_per_source=30):
        db.insert_job(
            source="custom",
            title="Junior AI Engineer",
            company="Global Corp",
            url="https://example.com/global-corp",
            description="Worldwide remote, but we cannot hire candidates from India. English only. 0-1 years exp.",
        )
        return CollectionReport(sources_attempted=1, sources_successful=1, jobs_fetched=1, jobs_relevant=1, jobs_inserted=1)

    monkeypatch.setattr("src.pipeline.JobCollectorAggregator.run", mock_aggregator_run)

    summary = RunSummary()
    phase_generate_tex(
        db=mock_db,
        profile_dir="profile",
        match_threshold=60,
        output_dir=str(tmp_path),
        summary=summary,
    )

    jobs = list(mock_db.jobs.values())
    assert len(jobs) == 1
    job = jobs[0]

    # Must be REJECTED, not MATCHED or EVALUATED
    assert job["state"] == "REJECTED", "Explicit India exclusion must be REJECTED"
    assert summary.jobs_rejected == 1

    # Verify NO .tex file is created
    tex_file = tmp_path / f"{job['id'][:16]}_cv.tex"
    assert not tex_file.exists(), "Excluded country job must NEVER generate a CV"


