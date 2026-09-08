"""
Job Listing Collector for Job Hunter v1.

Collects job postings from Arbeitnow API.
Deduplicates on URL and inserts new listings as INGESTED.

Spec Reference: Technical_Specification.md §1 (Component 1)
"""

import logging
import re
from dataclasses import dataclass
from typing import List, Optional
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode

import requests

from src.db.client import DatabaseClient

logger = logging.getLogger(__name__)


# ============================================================
# URL Normalization
# ============================================================

# Tracking parameters to strip from URLs
_TRACKING_PARAMS = frozenset({
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "fbclid", "gclid", "ref", "source", "tracking_id",
    "mc_cid", "mc_eid", "trk", "trkInfo",
})


def normalize_url(url: str) -> str:
    """Normalize a URL for deduplication."""
    try:
        parsed = urlparse(url)

        # Lowercase scheme and netloc
        scheme = parsed.scheme.lower()
        netloc = parsed.netloc.lower()

        # Strip tracking query params
        if parsed.query:
            params = parse_qs(parsed.query, keep_blank_values=True)
            filtered = {
                k: v for k, v in params.items()
                if k.lower() not in _TRACKING_PARAMS
            }
            query = urlencode(filtered, doseq=True)
        else:
            query = ""

        # Remove fragment, normalize path
        path = parsed.path.rstrip("/") or "/"

        return urlunparse((scheme, netloc, path, parsed.params, query, ""))
    except Exception:
        return url


# ============================================================
# API Collectors
# ============================================================

@dataclass
class CollectedJob:
    """A raw collected job before database insertion."""
    source: str
    title: str
    company: str
    url: str
    description: str


def _is_relevant_job(title: str, location: str, remote: bool, description: str) -> bool:
    """
    Filter jobs based on target roles and location (Germany / Remote).
    Target roles: Python, Backend, Software Engineer, AI, ML, Data.
    """
    # 1. Check Target Roles (Expanded for freelance & interns)
    target_roles = re.compile(
        r"\b(python|backend|software|developer|engineer|data|machine learning|ai|ml|freelance|freelancer|intern|internship|werkstudent|contract)\b", 
        re.IGNORECASE
    )
    if not target_roles.search(title):
        return False
        
    # 2. Check Location (Germany or Remote)
    # Arbeitnow is mostly Germany, but we can explicitly check if location implies another country.
    # Usually locations are cities like "Berlin", "Munich", or "Remote".
    location_lower = location.lower()
    is_germany = any(city in location_lower for city in ["berlin", "munich", "münchen", "hamburg", "frankfurt", "cologne", "köln", "stuttgart", "germany"])
    
    if not (is_germany or remote):
        # We also accept if the description mentions Germany
        if "germany" not in description.lower():
            return False

    return True


def collect_from_arbeitnow_api() -> List[CollectedJob]:
    """
    Collect job listings from Arbeitnow API (Germany Job Board).
    """
    jobs: List[CollectedJob] = []
    url = "https://www.arbeitnow.com/api/job-board-api"

    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        data = response.json()

        for item in data.get("data", []):
            title = item.get("title", "")
            company = item.get("company_name", "")
            job_url = item.get("url", "")
            description = item.get("description", "")
            location = item.get("location", "")
            remote = item.get("remote", False)

            if not title or not job_url:
                continue
                
            if not _is_relevant_job(title, location, remote, description):
                continue

            # Strip HTML tags from description
            clean_description = re.sub(r"<[^>]+>", " ", description)
            clean_description = re.sub(r"\s+", " ", clean_description).strip()

            jobs.append(
                CollectedJob(
                    source="arbeitnow",
                    title=title,
                    company=company,
                    url=normalize_url(job_url),
                    description=clean_description,
                )
            )

        logger.info("Collected %d jobs from Arbeitnow API", len(jobs))

    except requests.RequestException as e:
        logger.error("Failed to fetch Arbeitnow API: %s", e)
    except Exception as e:
        logger.error("Failed to parse Arbeitnow API: %s", e)

    return jobs


# ============================================================
# Ingestion Pipeline
# ============================================================

def run_collection(db: DatabaseClient) -> int:
    """
    Run the full collection pipeline.

    Collects from Arbeitnow API, normalizes URLs,
    and inserts new jobs into the database as INGESTED.

    Args:
        db: DatabaseClient instance.

    Returns:
        Number of new jobs inserted.
    """
    total_inserted = 0
    logger.info("Collecting from: Arbeitnow API")
    collected = collect_from_arbeitnow_api()

    for job in collected:
        result = db.insert_job(
            source=job.source,
            title=job.title,
            company=job.company,
            url=job.url,
            description=job.description,
        )
        if result is not None:
            total_inserted += 1

    logger.info("Collection complete. %d new jobs inserted.", total_inserted)
    return total_inserted
