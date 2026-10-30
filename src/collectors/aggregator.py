"""
Job Collector Aggregator for Job Hunter v2.

Coordinates multi-source job ingestion, URL normalization, cross-source deduplication,
and produces comprehensive collection metrics.
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from src.collectors.base import JobSourceAdapter, RawJobPosting
from src.collectors.arbeitnow import ArbeitnowAdapter
from src.collectors.jobicy import JobicyAdapter
from src.collectors.ats_boards import GreenhousePublicAdapter
from src.db.client import DatabaseClient
from src.normalizers.url import normalize_url

logger = logging.getLogger(__name__)

# Target technical role keywords (Primary: AI, GenAI, LLM, Agent; Secondary: Python, Data, Backend)
_ROLE_KEYWORD_REGEX = re.compile(
    r"\b(ai|artificial\s+intelligence|genai|generative\s+ai|llm|agent|machine\s+learning|ml|"
    r"python|backend|software|developer|engineer|data\s+engineer|research\s+engineer)\b",
    re.IGNORECASE,
)

# Unrelated roles to actively filter out
_EXCLUDED_ROLE_REGEX = re.compile(
    r"\b(sales|account\s+executive|recruiter|hr|human\s+resources|customer\s+support|"
    r"marketing|copywriter|content\s+creator|finance|accountant|legal)\b",
    re.IGNORECASE,
)


@dataclass
class CollectionReport:
    """Detailed metrics from a collection cycle."""
    sources_attempted: int = 0
    sources_successful: int = 0
    jobs_fetched: int = 0
    jobs_relevant: int = 0
    duplicates_skipped: int = 0
    jobs_inserted: int = 0
    errors_by_source: Dict[str, str] = field(default_factory=dict)


def is_target_role(title: str, description: str = "") -> bool:
    """Filter for relevant technical roles while dropping non-technical noise."""
    if _EXCLUDED_ROLE_REGEX.search(title):
        return False
    return bool(_ROLE_KEYWORD_REGEX.search(title))


class JobCollectorAggregator:
    """Aggregates and orchestrates all configured job source adapters."""

    def __init__(self, adapters: Optional[List[JobSourceAdapter]] = None):
        if adapters is not None:
            self._adapters = adapters
        else:
            self._adapters = [
                ArbeitnowAdapter(),
                JobicyAdapter(),
                GreenhousePublicAdapter(),
            ]

    def run(self, db: DatabaseClient, limit_per_source: int = 50) -> CollectionReport:
        report = CollectionReport()
        report.sources_attempted = len(self._adapters)

        all_collected: List[RawJobPosting] = []

        for adapter in self._adapters:
            name = adapter.source_name
            try:
                logger.info("Executing source adapter: %s", name)
                batch = adapter.fetch_jobs(limit=limit_per_source)
                all_collected.extend(batch)
                report.sources_successful += 1
                logger.info("Source '%s' successfully fetched %d jobs", name, len(batch))
            except Exception as e:
                logger.error("Source adapter '%s' failed: %s", name, e)
                report.errors_by_source[name] = str(e)

        report.jobs_fetched = len(all_collected)

        # Ingest into database with deduplication and relevance filtering
        for raw_job in all_collected:
            if not is_target_role(raw_job.title, raw_job.description):
                continue
            report.jobs_relevant += 1

            canonical_url = normalize_url(raw_job.url)
            try:
                result = db.insert_job(
                    source=raw_job.source,
                    title=raw_job.title,
                    company=raw_job.company,
                    url=canonical_url,
                    description=raw_job.description,
                )
                if result is not None:
                    report.jobs_inserted += 1
                else:
                    report.duplicates_skipped += 1
            except Exception as e:
                logger.error("Failed to insert job %s: %s", canonical_url, e)

        logger.info(
            "Collection Summary: Sources=%d/%d, Fetched=%d, Relevant=%d, Inserted=%d, Duplicates=%d",
            report.sources_successful,
            report.sources_attempted,
            report.jobs_fetched,
            report.jobs_relevant,
            report.jobs_inserted,
            report.duplicates_skipped,
        )
        return report
