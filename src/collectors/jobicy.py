"""
Jobicy Remote Jobs API source adapter.

Provides worldwide and international remote engineering positions.
Official public API endpoint: https://jobicy.com/api/v2/remote-jobs
"""

import logging
import re
import time
from typing import List
import requests

from src.collectors.base import JobSourceAdapter, RawJobPosting

logger = logging.getLogger(__name__)


class JobicyAdapter(JobSourceAdapter):
    """Adapter for Jobicy Remote Jobs public API."""

    def __init__(self, base_url: str = "https://jobicy.com/api/v2/remote-jobs", count: int = 50, tag: str = "dev"):
        self._base_url = base_url
        self._count = count
        self._tag = tag

    @property
    def source_name(self) -> str:
        return "jobicy"

    def fetch_jobs(self, limit: int = 50) -> List[RawJobPosting]:
        jobs: List[RawJobPosting] = []
        params = {
            "count": min(limit, self._count),
            "tag": self._tag,
        }
        headers = {
            "User-Agent": "JobHunterBot/2.0 (Career Discovery Engine; contact: dinesh@example.com)",
            "Accept": "application/json",
        }

        response_data = None
        for attempt in range(1, 4):
            try:
                resp = requests.get(self._base_url, params=params, headers=headers, timeout=25)
                resp.raise_for_status()
                response_data = resp.json()
                break
            except requests.RequestException as e:
                logger.warning("Jobicy API request failed (attempt %d/3): %s", attempt, e)
                if attempt < 3:
                    time.sleep(2 ** attempt)
                else:
                    logger.error("Jobicy API aborted after 3 failed attempts.")
                    return jobs

        if not response_data or "jobs" not in response_data:
            return jobs

        for item in response_data.get("jobs", []):
            job_id = str(item.get("id") or "")
            title = (item.get("jobTitle") or "").strip()
            company = (item.get("companyName") or "").strip()
            job_url = (item.get("url") or "").strip()
            raw_desc = item.get("jobDescription") or ""

            if not title or not job_url:
                continue

            # Strip HTML tags
            clean_desc = re.sub(r"<[^>]+>", " ", raw_desc)
            clean_desc = re.sub(r"\s+", " ", clean_desc).strip()

            geo_location = item.get("jobGeo") or "Anywhere"

            jobs.append(
                RawJobPosting(
                    source=self.source_name,
                    source_job_id=job_id,
                    title=title,
                    company=company,
                    url=job_url,
                    description=clean_desc,
                    location=geo_location,
                    is_remote=True,
                    published_at=str(item.get("pubDate") or ""),
                    raw_payload={
                        "jobType": item.get("jobType", []),
                        "jobLevel": item.get("jobLevel", ""),
                        "jobIndustry": item.get("jobIndustry", []),
                    },
                )
            )

            if len(jobs) >= limit:
                break

        logger.info("JobicyAdapter fetched %d international remote jobs", len(jobs))
        return jobs
