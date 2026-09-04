"""
Deterministic Extraction Pipeline for Job Hunter v1.

All structured data is extracted via regex BEFORE any LLM invocation.
The Gemini API receives pre-enriched context, never raw unprocessed text.

Spec Reference: Technical_Specification.md §4

Invariants:
  - LLM is forbidden from independently searching for or inventing contact details.
  - Extraction results are integers, strings, or enum tiers — never free-form LLM output.
"""

import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional


# ============================================================
# German Proficiency Tiers
# ============================================================

class GermanRequirement(str, Enum):
    """German language proficiency classification tiers."""
    MANDATORY_C1_PLUS = "MANDATORY_C1_PLUS"
    PREFERRED_B1_B2 = "PREFERRED_B1_B2"
    OPTIONAL_A1_A2 = "OPTIONAL_A1_A2"
    UNKNOWN = "UNKNOWN"


# ============================================================
# Extraction Result Container
# ============================================================

@dataclass
class ExtractionResult:
    """Container for all deterministically extracted fields."""
    contact_email: Optional[str] = None
    min_experience: Optional[int] = None
    german_requirement: GermanRequirement = GermanRequirement.UNKNOWN


# ============================================================
# Email Extraction
# ============================================================

# Standard email pattern
_EMAIL_PATTERN = re.compile(
    r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}",
)

# Emails to exclude — dummy/noreply addresses
_EMAIL_EXCLUSIONS = re.compile(
    r"^(noreply|no-reply|no\.reply|donotreply|do-not-reply|"
    r"example|test|info@example|user@example|"
    r"admin@localhost|mailer-daemon)"
    r"@",
    re.IGNORECASE,
)

# Common non-contact domains to skip
_EXCLUDED_DOMAINS = frozenset({
    "example.com",
    "example.org",
    "test.com",
    "localhost",
    "sentry.io",
    "github.com",
    "githubusercontent.com",
})


def extract_email(text: str) -> Optional[str]:
    """
    Extract the first valid contact email from text.

    Filters out noreply addresses, example domains, and common
    non-contact patterns. Returns lowercase email or None.

    Args:
        text: Raw job description or posting text.

    Returns:
        Lowercase email string, or None if no valid email found.
    """
    for match in _EMAIL_PATTERN.finditer(text):
        email = match.group(0).lower()

        # Skip excluded prefixes
        if _EMAIL_EXCLUSIONS.match(email):
            continue

        # Skip excluded domains
        domain = email.split("@", 1)[1]
        if domain in _EXCLUDED_DOMAINS:
            continue

        return email

    return None


# ============================================================
# Years of Experience Extraction
# ============================================================

_YOE_PATTERNS = [
    # "5+ years of experience", "3 years experience"
    re.compile(
        r"(\d{1,2})\+?\s*(?:years?|yrs?)\s*(?:of\s+)?(?:experience|exp(?:erience)?|berufserfahrung)",
        re.IGNORECASE,
    ),
    # "minimum 3 years", "at least 5 years"
    re.compile(
        r"(?:minimum|min\.?|at\s+least|mindestens)\s*(\d{1,2})\s*(?:years?|yrs?|jahre)",
        re.IGNORECASE,
    ),
    # "3-5 years", "2 to 4 years" — extract lower bound
    re.compile(
        r"(\d{1,2})\s*[-–—]\s*\d{1,2}\s*(?:years?|yrs?|jahre)",
        re.IGNORECASE,
    ),
    # German: "5 Jahre Erfahrung"
    re.compile(
        r"(\d{1,2})\+?\s*jahre\s*(?:erfahrung|berufserfahrung)?",
        re.IGNORECASE,
    ),
]


def extract_years_experience(text: str) -> Optional[int]:
    """
    Extract minimum years of experience required.

    Scans multiple patterns and returns the first match (lowest bound
    for range patterns). Returns None if no experience requirement found.

    Args:
        text: Raw job description or posting text.

    Returns:
        Integer years, or None if not found.
    """
    for pattern in _YOE_PATTERNS:
        match = pattern.search(text)
        if match:
            years = int(match.group(1))
            # Sanity check: ignore unreasonable values
            if 0 < years <= 30:
                return years
    return None


# ============================================================
# German Language Requirement Detection
# ============================================================

# Tier 1: Mandatory C1+ / native / fluent
_GERMAN_MANDATORY = [
    re.compile(
        r"\b(?:german|deutsch)\b.*\b(?:required|mandatory|must|"
        r"essential|erforderlich|zwingend|fluent|flie[ßs]end|"
        r"native|muttersprach|c[12])\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:required|mandatory|must|essential|erforderlich|"
        r"fluent|flie[ßs]end|native|muttersprach|c[12])\b"
        r".*\b(?:german|deutsch)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:deutschkenntnisse|muttersprachlich|"
        r"verhandlungssicher(?:es?)?\s+deutsch)\b",
        re.IGNORECASE,
    ),
]

# Tier 2: Preferred B1/B2
_GERMAN_PREFERRED = [
    re.compile(
        r"\b(?:german|deutsch)\b.*\b(?:preferred|advantage|plus|"
        r"beneficial|wünschenswert|von\s+vorteil|b[12]|intermediate)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:preferred|advantage|wünschenswert|von\s+vorteil|"
        r"b[12])\b.*\b(?:german|deutsch)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bgute\s+deutschkenntnisse\b",
        re.IGNORECASE,
    ),
]

# Tier 3: Optional A1/A2 / basic / beginner
_GERMAN_OPTIONAL = [
    re.compile(
        r"\b(?:german|deutsch)\b.*\b(?:basic|beginner|"
        r"a[12]|grundkenntnisse|nice\s+to\s+have)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:basic|beginner|a[12]|grundkenntnisse)\b"
        r".*\b(?:german|deutsch)\b",
        re.IGNORECASE,
    ),
]


def detect_german_requirement(text: str) -> GermanRequirement:
    """
    Classify German language proficiency requirement into tiers.

    Priority order (highest wins):
      1. MANDATORY_C1_PLUS — fluent/native/C1/C2 required
      2. PREFERRED_B1_B2   — intermediate preferred
      3. OPTIONAL_A1_A2    — basic/beginner mentioned
      4. UNKNOWN           — no German signals detected

    Args:
        text: Raw job description or posting text.

    Returns:
        GermanRequirement enum value.
    """
    # Check highest tier first
    if any(p.search(text) for p in _GERMAN_MANDATORY):
        return GermanRequirement.MANDATORY_C1_PLUS

    if any(p.search(text) for p in _GERMAN_PREFERRED):
        return GermanRequirement.PREFERRED_B1_B2

    if any(p.search(text) for p in _GERMAN_OPTIONAL):
        return GermanRequirement.OPTIONAL_A1_A2

    return GermanRequirement.UNKNOWN


# ============================================================
# Unified Extraction Pipeline
# ============================================================

def run_extraction(text: str) -> ExtractionResult:
    """
    Run the full deterministic extraction pipeline on a job description.

    This MUST be called before any LLM invocation. The result
    is passed alongside the raw text to the Gemini matcher.

    Args:
        text: Raw job description or posting text.

    Returns:
        ExtractionResult with all extracted fields.
    """
    return ExtractionResult(
        contact_email=extract_email(text),
        min_experience=extract_years_experience(text),
        german_requirement=detect_german_requirement(text),
    )
