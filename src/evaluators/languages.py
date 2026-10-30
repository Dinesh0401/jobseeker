"""
Language Requirement Classifier for Job Hunter v2.

Distinguishes English-speaking workplaces, optional German, preferred German,
and mandatory German or other foreign language requirements.
"""

import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from src.evaluators.extraction import GermanRequirement, detect_german_requirement


class LanguageCategory(str, Enum):
    ENGLISH_ONLY = "ENGLISH_ONLY"
    ENGLISH_REQUIRED_GERMAN_PREFERRED = "ENGLISH_REQUIRED_GERMAN_PREFERRED"
    ENGLISH_AND_BASIC_GERMAN_ACCEPTED = "ENGLISH_AND_BASIC_GERMAN_ACCEPTED"
    GERMAN_REQUIRED_A1_A2 = "GERMAN_REQUIRED_A1_A2"
    GERMAN_REQUIRED_B1_B2 = "GERMAN_REQUIRED_B1_B2"
    GERMAN_REQUIRED_C1_PLUS = "GERMAN_REQUIRED_C1_PLUS"
    OTHER_LANGUAGE_REQUIRED = "OTHER_LANGUAGE_REQUIRED"
    LANGUAGE_UNKNOWN = "LANGUAGE_UNKNOWN"


@dataclass
class LanguageAssessment:
    category: LanguageCategory
    is_immediately_eligible: bool
    requires_future_learning: bool
    rejection_reason: Optional[str] = None


_OTHER_LANGUAGES = re.compile(
    r"\b(?:fluent|native|proficient)\s+(?:in\s+)?(french|spanish|dutch|italian|japanese|mandarin|chinese|swedish|norwegian|danish|polish)\s+is\s+required\b",
    re.IGNORECASE,
)


def classify_languages(text: str) -> LanguageAssessment:
    """
    Classify language requirements and evaluate against candidate profile (English: Fluent, German: A1/Basic).
    """
    if not text:
        return LanguageAssessment(
            category=LanguageCategory.LANGUAGE_UNKNOWN,
            is_immediately_eligible=True,
            requires_future_learning=False,
        )

    # 1. Check for other mandatory languages
    other_match = _OTHER_LANGUAGES.search(text)
    if other_match:
        lang = other_match.group(1).capitalize()
        return LanguageAssessment(
            category=LanguageCategory.OTHER_LANGUAGE_REQUIRED,
            is_immediately_eligible=False,
            requires_future_learning=True,
            rejection_reason=f"Mandatory language requirement not met: {lang}",
        )

    # 2. Check German tier
    german_tier = detect_german_requirement(text)

    if german_tier == GermanRequirement.MANDATORY_C1_PLUS:
        return LanguageAssessment(
            category=LanguageCategory.GERMAN_REQUIRED_C1_PLUS,
            is_immediately_eligible=False,
            requires_future_learning=True,
            rejection_reason="Mandatory fluent German (C1/C2) required; candidate current proficiency is basic (A1).",
        )
    elif german_tier == GermanRequirement.PREFERRED_B1_B2:
        return LanguageAssessment(
            category=LanguageCategory.ENGLISH_REQUIRED_GERMAN_PREFERRED,
            is_immediately_eligible=True,
            requires_future_learning=True,
        )
    elif german_tier == GermanRequirement.OPTIONAL_A1_A2:
        return LanguageAssessment(
            category=LanguageCategory.ENGLISH_AND_BASIC_GERMAN_ACCEPTED,
            is_immediately_eligible=True,
            requires_future_learning=False,
        )
    else:
        # Check if English only
        if re.search(r"\b(english|working\s+language\s+is\s+english|english[\s-]speaking)\b", text, re.IGNORECASE):
            return LanguageAssessment(
                category=LanguageCategory.ENGLISH_ONLY,
                is_immediately_eligible=True,
                requires_future_learning=False,
            )
        return LanguageAssessment(
            category=LanguageCategory.LANGUAGE_UNKNOWN,
            is_immediately_eligible=True,
            requires_future_learning=False,
        )

