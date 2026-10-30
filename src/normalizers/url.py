"""
URL normalization and deduplication utilities for Job Hunter v2.
"""

from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

_TRACKING_PARAMS = frozenset({
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "fbclid", "gclid", "ref", "source", "tracking_id",
    "mc_cid", "mc_eid", "trk", "trkinfo", "gh_src", "lever-source",
    "sr_source", "origin", "s",
})


def normalize_url(url: str) -> str:
    """
    Normalize a job URL for strict canonical deduplication.

    - Strips marketing tracking query parameters.
    - Normalizes scheme and domain to lowercase.
    - Strips URL fragments (#hash).
    - Removes trailing slashes on paths.
    """
    if not url:
        return ""

    try:
        parsed = urlparse(url.strip())

        scheme = parsed.scheme.lower()
        netloc = parsed.netloc.lower()

        # Filter query params
        if parsed.query:
            params = parse_qs(parsed.query, keep_blank_values=True)
            filtered = {
                k: v for k, v in params.items()
                if k.lower() not in _TRACKING_PARAMS
            }
            query = urlencode(filtered, doseq=True)
        else:
            query = ""

        # Normalize path
        path = parsed.path.rstrip("/")
        if not path and netloc:
            path = "/"

        return urlunparse((scheme, netloc, path, parsed.params, query, ""))
    except Exception:
        return url.strip()

