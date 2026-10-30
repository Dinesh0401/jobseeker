"""
Arbeitnow API source adapter.

Germany-centric and EU remote jobs board with official public REST API.
Supports pagination, timeout handling, and exponential backoff retries.
"""

import logging
import re
import time
from typing import List
import requests

from src.collectors.base import JobSourceAdapter, RawJobPosting

logger = logging.getLogger(__name__)


class ArbeitnowAdapter(JobSourceAdapter):
    """Adapter for Arbeitnow Job Board API."""

    def __init__(self, base_url: str = "https://www.arbeitnow.com/api/job-board-api", max_pages: int = 2):
        self._base_url = base_url
        self._max_pages = max_pages

    @property
    def source_name(self) -> str:
        return "arbeitnow"

    def fetch_jobs(self, limit: int = 50) -> List[RawJobPosting]:
        jobs: List[RawJobPosting] = []
        headers = {
            "User-Agent": "JobHunterBot/2.0 (Career Discovery Engine; contact: dinesh@example.com)",
            "Accept": "application/json",
        }

        current_url = self._base_url
        pages_fetched = 0

        while current_url and pages_fetched < self._max_pages and len(jobs) < limit:
            pages_fetched += 1
            logger.info("Fetching Arbeitnow page %d from %s", pages_fetched, current_url)

            # Retry with exponential backoff
            response_data = None
            for attempt in range(1, 4):
                try:
                    resp = requests.get(current_url, headers=headers, timeout=20)
                    resp.raise_for_status()
                    response_data = resp.json()
                    break
                except requests.RequestException as e:
                    logger.warning("Arbeitnow request failed (attempt %d/3): %s", attempt, e)
                    if attempt < 3:
                        time.sleep(2 ** attempt)
                    else:
                        logger.error("Arbeitnow API aborted after 3 failed attempts.")
                        return jobs

            if not response_data or "data" not in response_data:
                break

            for item in response_data.get("data", []):
                slug = item.get("slug") or item.get("url", "")
                title = (item.get("title") or "").strip()
                company = (item.get("company_name") or "").strip()
                job_url = (item.get("url") or "").strip()
                raw_desc = item.get("description") or ""

                if not title or not job_url:
                    continue

                # Strip HTML tags
                clean_desc = re.sub(r"<[^>]+>", " ", raw_desc)
                clean_desc = re.sub(r"\s+", " ", clean_desc).strip()

                jobs.append(
                    RawJobPosting(
                        source=self.source_name,
                        source_job_id=slug,
                        title=title,
                        company=company,
                        url=job_url,
                        description=clean_desc,
                        location=item.get("location") or "Germany",
                        is_remote=bool(item.get("remote", False)),
                        published_at=str(item.get("created_at") or ""),
                        raw_payload={
                            "tags": item.get("tags", []),
                            "job_types": item.get("job_types", []),
                        },
                    )
                )

                if len(jobs) >= limit:
                    break

            # Handle next page link if provided
            links = response_data.get("links", {})
            current_url = links.get("next")

        logger.info("ArbeitnowAdapter fetched %d jobs across %d pages", len(jobs), pages_fetched)
        return jobs
