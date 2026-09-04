"""
Job Listing Collector for Job Hunter v1.

Collects job postings from configured sources (RSS feeds, APIs, email).
Deduplicates on URL and inserts new listings as INGESTED.

Spec Reference: Technical_Specification.md §1 (Component 1)
"""

import hashlib
import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode

import requests

from src.config import Config
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
    """
    Normalize a URL for deduplication.

    - Strips tracking parameters (utm_*, fbclid, etc.)
    - Removes trailing slashes
    - Lowercases scheme and host
    - Removes fragments

    Args:
        url: Raw URL string.

    Returns:
        Normalized URL string.
    """
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
# RSS Feed Collector
# ============================================================

@dataclass
class RSSFeedConfig:
    """Configuration for an RSS feed source."""
    name: str
    url: str
    source_label: str  # e.g., "stackoverflow", "remoteok"


@dataclass
class CollectedJob:
    """A raw collected job before database insertion."""
    source: str
    title: str
    company: str
    url: str
    description: str


def collect_from_rss(feed_config: RSSFeedConfig) -> List[CollectedJob]:
    """
    Collect job listings from an RSS feed.

    Args:
        feed_config: RSS feed configuration.

    Returns:
        List of CollectedJob objects.
    """
    jobs: List[CollectedJob] = []

    try:
        response = requests.get(feed_config.url, timeout=30)
        response.raise_for_status()

        root = ET.fromstring(response.text)

        # Handle both RSS 2.0 and Atom feeds
        items = root.findall(".//item") or root.findall(
            ".//{http://www.w3.org/2005/Atom}entry"
        )

        for item in items:
            # RSS 2.0 fields
            title_el = item.find("title")
            link_el = item.find("link")
            desc_el = item.find("description") or item.find("content:encoded")

            # Atom fallbacks
            if link_el is None:
                link_el = item.find("{http://www.w3.org/2005/Atom}link")
            if title_el is None:
                title_el = item.find("{http://www.w3.org/2005/Atom}title")
            if desc_el is None:
                desc_el = item.find("{http://www.w3.org/2005/Atom}content")

            title = title_el.text.strip() if title_el is not None and title_el.text else ""
            link = (
                link_el.get("href", "") if link_el is not None and link_el.get("href")
                else (link_el.text.strip() if link_el is not None and link_el.text else "")
            )
            description = desc_el.text.strip() if desc_el is not None and desc_el.text else ""

            if not title or not link:
                continue

            # Extract company from title if pattern matches "Title at Company"
            company = _extract_company_from_title(title)
            normalized_url = normalize_url(link)

            # Strip HTML tags from description
            clean_description = re.sub(r"<[^>]+>", " ", description)
            clean_description = re.sub(r"\s+", " ", clean_description).strip()

            jobs.append(
                CollectedJob(
                    source=feed_config.source_label,
                    title=title,
                    company=company,
                    url=normalized_url,
                    description=clean_description,
                )
            )

        logger.info(
            "Collected %d jobs from RSS feed: %s", len(jobs), feed_config.name
        )

    except requests.RequestException as e:
        logger.error("Failed to fetch RSS feed %s: %s", feed_config.name, e)
    except ET.ParseError as e:
        logger.error("Failed to parse RSS feed %s: %s", feed_config.name, e)

    return jobs


def _extract_company_from_title(title: str) -> str:
    """
    Extract company name from job title patterns.

    Patterns: "Title at Company", "Title - Company", "Title | Company"
    Falls back to "Unknown" if no pattern matches.
    """
    patterns = [
        re.compile(r"^.+?\s+at\s+(.+)$", re.IGNORECASE),
        re.compile(r"^.+?\s*[-–—]\s*(.+)$"),
        re.compile(r"^.+?\s*\|\s*(.+)$"),
    ]
    for pattern in patterns:
        match = pattern.match(title)
        if match:
            return match.group(1).strip()
    return "Unknown"


# ============================================================
# Ingestion Pipeline
# ============================================================

# Default RSS feeds — extend this list with your sources
DEFAULT_FEEDS: List[RSSFeedConfig] = [
    RSSFeedConfig(
        name="Stack Overflow - Python",
        url="https://stackoverflow.com/jobs/feed?q=python",
        source_label="stackoverflow",
    ),
    RSSFeedConfig(
        name="RemoteOK - Developer",
        url="https://remoteok.com/remote-dev-jobs.rss",
        source_label="remoteok",
    ),
]


def run_collection(db: DatabaseClient, feeds: Optional[List[RSSFeedConfig]] = None) -> int:
    """
    Run the full collection pipeline.

    Collects from all configured RSS feeds, normalizes URLs,
    and inserts new jobs into the database as INGESTED.

    Args:
        db: DatabaseClient instance.
        feeds: Optional list of feed configs. Uses DEFAULT_FEEDS if None.

    Returns:
        Number of new jobs inserted.
    """
    if feeds is None:
        feeds = DEFAULT_FEEDS

    total_inserted = 0

    for feed in feeds:
        logger.info("Collecting from: %s", feed.name)
        collected = collect_from_rss(feed)

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
