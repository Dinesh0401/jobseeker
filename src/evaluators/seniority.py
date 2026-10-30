"""
Seniority and Experience Level Classifier for Job Hunter v2.

Prioritizes 0-1 years / Fresher / Junior / Intern / Working Student positions.
Identifies senior, staff, lead, and management roles for hard-gate rejection.
"""

import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class SeniorityTier(str, Enum):
    ENTRY_OR_JUNIOR = "ENTRY_OR_JUNIOR"      # 0-1 years, Fresher, Junior, Intern, Working Student
    MID_LEVEL = "MID_LEVEL"                  # 2-4 years
    SENIOR_PLUS = "SENIOR_PLUS"              # 5+ years, Lead, Staff, Principal, Architect, Manager
    UNKNOWN = "UNKNOWN"


@dataclass
class SeniorityAssessment:
    tier: SeniorityTier
    min_years: Optional[int]
    is_early_career_match: bool
    rejection_reason: Optional[str] = None


_ENTRY_KEYWORDS = re.compile(
    r"\b(junior|entry[\s-]level|graduate|fresher|intern|internship|trainee|working\s+student|werkstudent|associate)\b",
    re.IGNORECASE,
)

_SENIOR_KEYWORDS = re.compile(
    r"\b(senior|sr\.?|lead|staff|principal|head\s+of|director|manager|architect|team\s+lead)\b",
    re.IGNORECASE,
)


def classify_seniority(title: str, min_years: Optional[int], description: str = "") -> SeniorityAssessment:
    """
    Classify the seniority tier of the posting based on title and extracted years of experience.
    """
    # 1. Check title keywords
    is_senior_title = bool(_SENIOR_KEYWORDS.search(title))
    is_entry_title = bool(_ENTRY_KEYWORDS.search(title))

    # 2. Check explicitly stated fresh graduate acceptance in description
    accepts_freshers = bool(re.search(
        r"\b(open\s+to\s+fresh\s+graduates|recent\s+graduates?\s+welcome|no\s+experience\s+required|0[\s-]1\s+years?)\b",
        description,
        re.IGNORECASE,
    ))

    # Decision logic:
    if is_senior_title:
        return SeniorityAssessment(
            tier=SeniorityTier.SENIOR_PLUS,
            min_years=min_years or 5,
            is_early_career_match=False,
            rejection_reason=f"Title indicates senior/lead level: '{title}'",
        )

    if min_years is not None:
        if min_years <= 1 or accepts_freshers:
            return SeniorityAssessment(
                tier=SeniorityTier.ENTRY_OR_JUNIOR,
                min_years=min_years,
                is_early_career_match=True,
            )
        elif 2 <= min_years <= 4:
            # Low priority exception if entry title or accepts freshers
            if is_entry_title or accepts_freshers:
                return SeniorityAssessment(
                    tier=SeniorityTier.ENTRY_OR_JUNIOR,
                    min_years=min_years,
                    is_early_career_match=True,
                )
            return SeniorityAssessment(
                tier=SeniorityTier.MID_LEVEL,
                min_years=min_years,
                is_early_career_match=False,
                rejection_reason=f"Requires {min_years} years of experience (Target: 0-1 years)",
            )
        else: # min_years >= 5
            return SeniorityAssessment(
                tier=SeniorityTier.SENIOR_PLUS,
                min_years=min_years,
                is_early_career_match=False,
                rejection_reason=f"Requires {min_years}+ years of experience (Target: 0-1 years)",
            )

    # If min_years is None, infer from title
    if is_entry_title or accepts_freshers:
        return SeniorityAssessment(
            tier=SeniorityTier.ENTRY_OR_JUNIOR,
            min_years=0,
            is_early_career_match=True,
        )

    # General software engineer without senior or junior qualifier
    return SeniorityAssessment(
        tier=SeniorityTier.UNKNOWN,
        min_years=None,
        is_early_career_match=True,  # Kept open for LLM evaluation
    )
