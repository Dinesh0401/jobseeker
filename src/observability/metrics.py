"""
Observability and Run Reporting for Job Hunter v2.

Captures, formats, and logs end-to-end operational metrics for every pipeline execution.
"""

from dataclasses import dataclass, field, asdict
import json
import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class RunSummary:
    """Comprehensive metrics container for pipeline execution."""
    sources_attempted: int = 0
    sources_successful: int = 0
    jobs_fetched: int = 0
    jobs_normalized: int = 0
    duplicates_removed: int = 0
    jobs_inserted: int = 0
    jobs_evaluated: int = 0
    jobs_rejected: int = 0
    jobs_held_for_verification: int = 0
    evaluation_failures: int = 0

    # International Classification Metrics
    india_eligible_jobs: int = 0
    worldwide_remote_jobs: int = 0
    germany_remote_jobs: int = 0
    europe_remote_jobs: int = 0
    relocation_opportunities: int = 0
    eligibility_unknown_jobs: int = 0

    # Seniority Metrics
    early_career_0_1_yr_matches: int = 0

    # Presentation & Dispatch Metrics
    jobs_sent_to_telegram: int = 0
    cvs_generated: int = 0
    applications_approved: int = 0
    applications_dispatched: int = 0
    failed_or_uncertain_dispatches: int = 0

    errors_by_stage: Dict[str, List[str]] = field(default_factory=dict)

    def record_error(self, stage: str, message: str) -> None:
        if stage not in self.errors_by_stage:
            self.errors_by_stage[stage] = []
        self.errors_by_stage[stage].append(message)

    def to_markdown(self) -> str:
        """Render a clean Markdown summary of the run."""
        return f"""
### 📊 Job Hunter v2 Run Summary

| Metric | Count |
| :--- | :--- |
| **Sources Attempted / Successful** | {self.sources_attempted} / {self.sources_successful} |
| **Total Jobs Fetched** | {self.jobs_fetched} |
| **Duplicates Skipped** | {self.duplicates_removed} |
| **New Jobs Ingested** | {self.jobs_inserted} |
| **Jobs Evaluated** | {self.jobs_evaluated} |
| **Hard Gated / Rejected** | {self.jobs_rejected} |
| **Held for Location Verification** | {self.jobs_held_for_verification} |
| **Evaluation Failures** | {self.evaluation_failures} |
| **India-Eligible Remote** | {self.india_eligible_jobs} |
| **Worldwide Remote** | {self.worldwide_remote_jobs} |
| **Relocation / Visa Pathway** | {self.relocation_opportunities} |
| **Eligibility Unknown** | {self.eligibility_unknown_jobs} |
| **Early Career (0–1 Years) Matches** | {self.early_career_0_1_yr_matches} |
| **Cards Sent to Telegram** | {self.jobs_sent_to_telegram} |
| **CVs Compiled & Verified** | {self.cvs_generated} |
| **Applications Dispatched** | {self.applications_dispatched} |
"""

    def print_report(self) -> None:
        logger.info(self.to_markdown())

