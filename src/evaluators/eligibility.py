"""
International Remote & Location Eligibility Engine for Job Hunter v2.

Determines whether a candidate residing in India can genuinely apply for
an international role (Remote from India, or Relocation/Visa pathway).
"""

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class EligibilityCategory(str, Enum):
    WORLDWIDE_REMOTE = "WORLDWIDE_REMOTE"
    INDIA_ELIGIBLE_REMOTE = "INDIA_ELIGIBLE_REMOTE"
    GERMANY_REMOTE = "GERMANY_REMOTE"
    EUROPE_REMOTE = "EUROPE_REMOTE"
    COUNTRY_SPECIFIC_REMOTE = "COUNTRY_SPECIFIC_REMOTE"
    RELOCATION_SUPPORTED = "RELOCATION_SUPPORTED"
    ONSITE_INTERNATIONAL = "ONSITE_INTERNATIONAL"
    COUNTRY_RESTRICTED = "COUNTRY_RESTRICTED"
    ELIGIBILITY_UNKNOWN = "ELIGIBILITY_UNKNOWN"


@dataclass
class EligibilityAssessment:
    category: EligibilityCategory
    can_apply_from_india: bool
    is_relocation_pathway: bool
    evidence: List[str] = field(default_factory=list)
    eligible_countries: List[str] = field(default_factory=list)
    excluded_countries: List[str] = field(default_factory=list)
    visa_sponsorship: Optional[bool] = None
    relocation_available: Optional[bool] = None


# --- REGEX RULES FOR ELIGIBILITY ---

_WORLDWIDE_PATTERNS = [
    re.compile(r"\b(?:anywhere\s+in\s+the\s+world|work\s+from\s+anywhere|worldwide\s+remote|remote\s+worldwide|hiring\s+globally|global\s+remote|fully\s+distributed\s+worldwide)\b", re.IGNORECASE),
    re.compile(r"\b(?:any\s+timezone|work\s+from\s+any\s+location|remote\s*-\s*anywhere)\b", re.IGNORECASE),
]

_INDIA_PATTERNS = [
    re.compile(r"\b(?:remote\s+in\s+india|india\s+remote|remote\s*[-–]\s*india|based\s+in\s+india|india\s+or\s+remote|open\s+to\s+candidates\s+in\s+india)\b", re.IGNORECASE),
    re.compile(r"\b(?:apac\s+region|apac\s+remote|asia\s+remote)\b", re.IGNORECASE),
]

_RELOCATION_PATTERNS = [
    re.compile(r"\b(?:relocation\s+assistance|relocation\s+package|relocation\s+support|visa\s+sponsorship(?:\s+available|\s+provided)?|we\s+sponsor\s+visas?|blue\s+card\s+sponsorship)\b", re.IGNORECASE),
    re.compile(r"\b(?:support\s+your\s+relocation|help\s+with\s+relocation|relocate\s+to\s+(?:germany|berlin|munich|europe))\b", re.IGNORECASE),
]

_RESTRICTION_PATTERNS = [
    re.compile(r"\b(?:us\s+citizenship\s+required|must\s+be\s+a\s+us\s+citizen|security\s+clearance\s+required|active\s+secret\s+clearance)\b", re.IGNORECASE),
    re.compile(r"\b(?:must\s+be\s+located\s+in\s+the\s+(?:us|usa|united\s+states)|us\s+only|us\s+residents?\s+only|united\s+states\s+only)\b", re.IGNORECASE),
    re.compile(r"\b(?:must\s+reside\s+in\s+(?:canada|uk|united\s+kingdom|australia)|uk\s+only|canada\s+only)\b", re.IGNORECASE),
    re.compile(r"\b(?:no\s+visa\s+sponsorship|cannot\s+sponsor\s+visas?|unable\s+to\s+sponsor|we\s+do\s+not\s+offer\s+visa\s+sponsorship)\b", re.IGNORECASE),
    re.compile(r"\b(?:must\s+have\s+existing\s+work\s+authorization|right\s+to\s+work\s+in\s+(?:the\s+)?(?:eu|uk|us)\s+required)\b", re.IGNORECASE),
]

_GERMANY_ONLY_PATTERNS = [
    re.compile(r"\b(?:deutschlandweit\s+remote|remote\s+in\s+germany|remote\s+within\s+germany|resident\s+in\s+germany|wohnsitz\s+in\s+deutschland)\b", re.IGNORECASE),
]

_EUROPE_ONLY_PATTERNS = [
    re.compile(r"\b(?:remote\s+(?:in|across)\s+europe|european\s+timezones?|eu\s+remote|must\s+be\s+based\s+in\s+(?:the\s+)?(?:eu|europe|uk)|timezones?\s+(?:cet|cest|utc\+?[0-3]))\b", re.IGNORECASE),
]


def classify_eligibility(
    title: str,
    location_str: str,
    description: str,
    is_remote: bool = False
) -> EligibilityAssessment:
    """
    Classify whether a job is accessible from India or via relocation.
    """
    full_text = f"{title}\n{location_str}\n{description}"
    evidence: List[str] = []

    # 1. Check for Relocation / Visa Support
    visa_sponsorship = None
    relocation_available = None
    for p in _RELOCATION_PATTERNS:
        match = p.search(full_text)
        if match:
            evidence.append(f"Relocation evidence: '{match.group(0)}'")
            visa_sponsorship = True
            relocation_available = True

    # 2. Check for explicit negative country restrictions
    for p in _RESTRICTION_PATTERNS:
        match = p.search(full_text)
        if match:
            evidence.append(f"Restriction detected: '{match.group(0)}'")
            if "no visa sponsorship" in match.group(0).lower() or "unable to sponsor" in match.group(0).lower():
                visa_sponsorship = False

    # 3. Check for India specific eligibility
    is_india_eligible = False
    for p in _INDIA_PATTERNS:
        match = p.search(full_text)
        if match:
            evidence.append(f"India eligibility evidence: '{match.group(0)}'")
            is_india_eligible = True

    # 4. Check for Worldwide Remote
    is_worldwide = False
    for p in _WORLDWIDE_PATTERNS:
        match = p.search(full_text)
        if match:
            evidence.append(f"Worldwide signal: '{match.group(0)}'")
            is_worldwide = True

    # Also check location_str
    loc_lower = (location_str or "").lower()
    if "anywhere" in loc_lower or "worldwide" in loc_lower or "global" in loc_lower:
        is_worldwide = True
        evidence.append(f"Location string worldwide: '{location_str}'")

    if "india" in loc_lower:
        is_india_eligible = True
        evidence.append(f"Location string mentions India: '{location_str}'")

    # Determine classification:
    has_hard_restriction = any("Restriction detected" in e for e in evidence)

    # Decision tree:
    if has_hard_restriction and not is_worldwide and not is_india_eligible:
        # Restricted away from India
        return EligibilityAssessment(
            category=EligibilityCategory.COUNTRY_RESTRICTED,
            can_apply_from_india=False,
            is_relocation_pathway=False,
            evidence=evidence,
            visa_sponsorship=visa_sponsorship,
            relocation_available=relocation_available,
        )

    if is_india_eligible:
        return EligibilityAssessment(
            category=EligibilityCategory.INDIA_ELIGIBLE_REMOTE,
            can_apply_from_india=True,
            is_relocation_pathway=bool(relocation_available),
            evidence=evidence,
            visa_sponsorship=visa_sponsorship,
            relocation_available=relocation_available,
        )

    if is_worldwide and not has_hard_restriction:
        return EligibilityAssessment(
            category=EligibilityCategory.WORLDWIDE_REMOTE,
            can_apply_from_india=True,
            is_relocation_pathway=bool(relocation_available),
            evidence=evidence,
            visa_sponsorship=visa_sponsorship,
            relocation_available=relocation_available,
        )

    if relocation_available or visa_sponsorship:
        return EligibilityAssessment(
            category=EligibilityCategory.RELOCATION_SUPPORTED,
            can_apply_from_india=False,
            is_relocation_pathway=True,
            evidence=evidence,
            visa_sponsorship=True,
            relocation_available=True,
        )

    # Check Germany or Europe remote
    for p in _GERMANY_ONLY_PATTERNS:
        match = p.search(full_text)
        if match:
            evidence.append(f"Germany remote restriction: '{match.group(0)}'")
            return EligibilityAssessment(
                category=EligibilityCategory.GERMANY_REMOTE,
                can_apply_from_india=False,
                is_relocation_pathway=False,
                evidence=evidence,
                visa_sponsorship=False,
                relocation_available=False,
            )

    for p in _EUROPE_ONLY_PATTERNS:
        match = p.search(full_text)
        if match:
            evidence.append(f"Europe remote restriction: '{match.group(0)}'")
            return EligibilityAssessment(
                category=EligibilityCategory.EUROPE_REMOTE,
                can_apply_from_india=False,
                is_relocation_pathway=False,
                evidence=evidence,
                visa_sponsorship=False,
                relocation_available=False,
            )

    # Check country specific remote (e.g. US, UK)
    if "united states" in loc_lower or "us remote" in loc_lower or "usa" in loc_lower:
        evidence.append("US location without international indicator")
        return EligibilityAssessment(
            category=EligibilityCategory.COUNTRY_SPECIFIC_REMOTE,
            can_apply_from_india=False,
            is_relocation_pathway=False,
            evidence=evidence,
            visa_sponsorship=visa_sponsorship,
            relocation_available=relocation_available,
        )

    # If completely unclear, mark ELIGIBILITY_UNKNOWN
    evidence.append("No explicit worldwide, India, or relocation evidence found.")
    return EligibilityAssessment(
        category=EligibilityCategory.ELIGIBILITY_UNKNOWN,
        can_apply_from_india=False,
        is_relocation_pathway=False,
        evidence=evidence,
        visa_sponsorship=visa_sponsorship,
        relocation_available=relocation_available,
    )

