"""
Unit tests for modular job source adapters and collectors aggregator.
"""

from unittest.mock import MagicMock
from src.normalizers.url import normalize_url
from src.collectors.base import JobSourceAdapter, RawJobPosting
from src.collectors.aggregator import JobCollectorAggregator, is_target_role


def test_url_normalization():
    raw_url = "https://Company.com/careers/job-123/?utm_source=linkedin&utm_medium=feed&ref=123#apply"
    expected = "https://company.com/careers/job-123"
    assert normalize_url(raw_url) == expected


def test_url_normalization_preserves_legitimate_query():
    raw_url = "https://company.com/jobs?id=456&utm_campaign=winter"
    expected = "https://company.com/jobs?id=456"
    assert normalize_url(raw_url) == expected


def test_is_target_role():
    assert is_target_role("Junior AI Engineer")
    assert is_target_role("Generative AI Developer")
    assert is_target_role("LLM Application Engineer")
    assert is_target_role("Python Backend Engineer")
    assert is_target_role("AI Agent Researcher")
    assert not is_target_role("Sales Account Executive")
    assert not is_target_role("HR Specialist")
    assert not is_target_role("Financial Controller")


class MockSuccessAdapter(JobSourceAdapter):
    @property
    def source_name(self) -> str:
        return "mock_success"

    def fetch_jobs(self, limit: int = 50):
        return [
            RawJobPosting(
                source="mock_success",
                source_job_id="1",
                title="AI Engineer",
                company="TechCorp",
                url="https://techcorp.com/jobs/1?utm_source=twitter",
                description="Python and PyTorch required.",
                location="Remote",
                is_remote=True,
            ),
            # Duplicate URL with different tracking query
            RawJobPosting(
                source="mock_success",
                source_job_id="2",
                title="AI Engineer",
                company="TechCorp",
                url="https://techcorp.com/jobs/1?utm_source=newsletter",
                description="Python and PyTorch required.",
                location="Remote",
                is_remote=True,
            ),
        ]


class MockFailingAdapter(JobSourceAdapter):
    @property
    def source_name(self) -> str:
        return "mock_fail"

    def fetch_jobs(self, limit: int = 50):
        raise ConnectionError("Upstream service unavailable")


def test_collector_aggregator_resilience_and_deduplication():
    db_mock = MagicMock()
    # First insert succeeds, second returns None (duplicate)
    db_mock.insert_job.side_effect = [{"id": "job-1"}, None]

    aggregator = JobCollectorAggregator(adapters=[MockSuccessAdapter(), MockFailingAdapter()])
    report = aggregator.run(db_mock)

    assert report.sources_attempted == 2
    assert report.sources_successful == 1
    assert "mock_fail" in report.errors_by_source
    assert report.jobs_fetched == 2
    assert report.jobs_inserted == 1
    assert report.duplicates_skipped == 1
