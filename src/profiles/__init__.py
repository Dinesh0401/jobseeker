"""
Candidate Profile module for Job Hunter v2.

Source-of-truth career data models, loaders, and validators.
"""

from src.profiles.models import (
    CandidateProfile,
    EducationEntry,
    ExperienceEntry,
    LanguageEntry,
    ProjectEntry,
    ProfileValidationReport,
)
from src.profiles.loader import load_candidate_profile
from src.profiles.validator import (
    ProfileValidationError,
    validate_candidate_profile,
    assert_profile_ready_for_dispatch,
)

__all__ = [
    "CandidateProfile",
    "EducationEntry",
    "ExperienceEntry",
    "LanguageEntry",
    "ProjectEntry",
    "ProfileValidationReport",
    "load_candidate_profile",
    "validate_candidate_profile",
    "assert_profile_ready_for_dispatch",
    "ProfileValidationError",
]
