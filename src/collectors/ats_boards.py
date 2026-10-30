"""
Public ATS Job Board Adapter (Greenhouse and Lever).

Collects open opportunities from public career APIs of international,
remote-friendly technology companies without requiring authentication or scraping.
"""

import logging
import re
from typing import List, Optional
import requests

from src.collectors.base import JobSourceAdapter, RawJobPosting

logger = logging.getLogger(__name__)

# Curated list of international, remote-friendly tech organizations with public ATS feeds
DEFAULT_GREENHOUSE_BOARDS = [
    "canonical",
    "automattic",
    "gitlab",
]

DEFAULT_LEVER_BOARDS = []


class GreenhousePublicAdapter(JobSourceAdapter):
    """Adapter for public Greenhouse job boards (https://boards-api.greenhouse.io/v1/boards/{board}/jobs)."""

    def __init__(self, board_tokens: Optional[List[str]] = None):
        self._board_tokens = board_tokens or DEFAULT_GREENHOUSE_BOARDS

    @property
    def source_name(self) -> str:
        return "greenhouse_public"

    def fetch_jobs(self, limit: int = 50) -> List[RawJobPosting]:
        jobs: List[RawJobPosting] = []
        headers = {
            "User-Agent": "JobHunterBot/2.0 (Career Discovery Engine; contact: dinesh@example.com)",
            "Accept": "application/json",
        }

        for token in self._board_tokens:
            if len(jobs) >= limit:
                break

            url = f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"
            try:
                resp = requests.get(url, headers=headers, timeout=20)
                if resp.status_code == 404:
                    logger.warning("Greenhouse board not found: %s", token)
                    continue
                resp.raise_for_status()
                data = resp.json()

                for item in data.get("jobs", []):
                    title = (item.get("title") or "").strip()
                    job_url = (item.get("absolute_url") or "").strip()
                    raw_content = item.get("content") or ""
                    location = item.get("location", {}).get("name", "Remote")

                    if not title or not job_url:
                        continue

                    # Clean HTML tags
                    clean_desc = re.sub(r"<[^>]+>", " ", raw_content)
                    clean_desc = re.sub(r"&nbsp;|&amp;|&lt;|&gt;", " ", clean_desc)
                    clean_desc = re.sub(r"\s+", " ", clean_desc).strip()

                    is_remote = "remote" in location.lower() or "anywhere" in location.lower()

                    jobs.append(
                        RawJobPosting(
                            source=f"greenhouse:{token}",
                            source_job_id=str(item.get("id")),
                            title=title,
                            company=token.capitalize(),
                            url=job_url,
                            description=clean_desc,
                            location=location,
                            is_remote=is_remote,
                            published_at=item.get("updated_at"),
                            raw_payload={"board": token},
                        )
                    )

                    if len(jobs) >= limit:
                        break

            except Exception as e:
                logger.warning("Error fetching Greenhouse board %s: %s", token, e)

        logger.info("GreenhousePublicAdapter fetched %d jobs", len(jobs))
        return jobs

