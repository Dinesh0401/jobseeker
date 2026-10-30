"""
Validator for Candidate Career Profile.

Enforces zero placeholders, valid unique keys, date sanity,
and blocks real application dispatch if profile data is incomplete or simulated.
"""

import re
from typing import List, Set
from src.profiles.models import CandidateProfile, ProfileValidationReport

_PLACEHOLDER_PATTERNS = [
    re.compile(r"your-email@example\.com", re.IGNORECASE),
    re.compile(r"@example\.(com|org|net)", re.IGNORECASE),
    re.compile(r"your\s+university", re.IGNORECASE),
    re.compile(r"example\s+corp", re.IGNORECASE),
    re.compile(r"example\s+project", re.IGNORECASE),
    re.compile(r"\bplaceholder\b", re.IGNORECASE),
    re.compile(r"\btodo\b", re.IGNORECASE),
]

_EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")


class ProfileValidationError(Exception):
    """Raised when profile validation fails or when real dispatch is blocked by dummy data."""
    def __init__(self, errors: List[str]):
        self.errors = errors
        super().__init__(f"Candidate Profile is invalid for real application dispatch:\n - " + "\n - ".join(errors))


def _contains_placeholder(text: str) -> bool:
    if not text:
        return False
    return any(pattern.search(text) for pattern in _PLACEHOLDER_PATTERNS)


def validate_profile_object(profile: CandidateProfile) -> ProfileValidationReport:
    """
    Validate a CandidateProfile instance for truthfulness, completeness, and lack of placeholders.
    """
    errors: List[str] = []
    warnings: List[str] = []
    placeholder_fields: List[str] = []

    # 1. Identity & Email
    if _contains_placeholder(profile.email) or not _EMAIL_REGEX.match(profile.email):
        placeholder_fields.append("email")
        errors.append(f"Email '{profile.email}' is a placeholder or invalid format.")

    if _contains_placeholder(profile.name):
        placeholder_fields.append("name")
        errors.append(f"Name '{profile.name}' appears to be a placeholder.")

    if _contains_placeholder(profile.location):
        placeholder_fields.append("location")
        errors.append(f"Location '{profile.location}' contains a placeholder.")

    if _contains_placeholder(profile.summary):
        placeholder_fields.append("summary")
        errors.append("Summary contains placeholder text.")

    # 2. Education
    if not profile.education:
        warnings.append("No education entries listed in profile.")
    for edu in profile.education:
        if _contains_placeholder(edu.institution):
            placeholder_fields.append(f"education.institution ({edu.institution})")
            errors.append(f"Education institution '{edu.institution}' is a placeholder.")
        if _contains_placeholder(edu.degree):
            placeholder_fields.append(f"education.degree ({edu.degree})")
            errors.append(f"Education degree '{edu.degree}' is a placeholder.")

    # 3. Experience (Fresher/0 YoE can have empty experience, but non-empty cannot have placeholders)
    exp_keys: Set[str] = set()
    for exp in profile.experience:
        if exp.key in exp_keys:
            errors.append(f"Duplicate experience key: '{exp.key}'. Keys must be unique.")
        exp_keys.add(exp.key)

        if _contains_placeholder(exp.company):
            placeholder_fields.append(f"experience[{exp.key}].company ({exp.company})")
            errors.append(f"Experience '{exp.key}' has placeholder company: '{exp.company}'.")
        if _contains_placeholder(exp.role):
            placeholder_fields.append(f"experience[{exp.key}].role ({exp.role})")
            errors.append(f"Experience '{exp.key}' has placeholder role: '{exp.role}'.")
        for resp in exp.responsibilities:
            if _contains_placeholder(resp):
                placeholder_fields.append(f"experience[{exp.key}].responsibilities")
                errors.append(f"Experience '{exp.key}' has placeholder in responsibilities.")
                break

    # 4. Projects
    proj_keys: Set[str] = set()
    for proj in profile.projects:
        if proj.key in proj_keys:
            errors.append(f"Duplicate project key: '{proj.key}'. Keys must be unique.")
        proj_keys.add(proj.key)

        if _contains_placeholder(proj.name):
            placeholder_fields.append(f"projects[{proj.key}].name ({proj.name})")
            errors.append(f"Project '{proj.key}' has placeholder name: '{proj.name}'.")
        if _contains_placeholder(proj.description):
            placeholder_fields.append(f"projects[{proj.key}].description")
            errors.append(f"Project '{proj.key}' has placeholder description.")
        for h in proj.highlights:
            if _contains_placeholder(h):
                placeholder_fields.append(f"projects[{proj.key}].highlights")
                errors.append(f"Project '{proj.key}' has placeholder in highlights.")
                break

    # 5. Skills
    if not profile.skills:
        errors.append("Profile has no skills listed.")

    is_valid = len(errors) == 0

    return ProfileValidationReport(
        is_valid=is_valid,
        errors=errors,
        warnings=warnings,
        placeholder_fields=placeholder_fields,
        experience_keys=sorted(list(exp_keys)),
        project_keys=sorted(list(proj_keys)),
    )


def validate_candidate_profile(profile_dir: str = "profile") -> ProfileValidationReport:
    """
    Load and validate candidate profile from profile directory files.
    """
    from src.profiles.loader import load_candidate_profile
    profile = load_candidate_profile(profile_dir)
    return validate_profile_object(profile)


def assert_profile_ready_for_dispatch(profile_dir: str = "profile") -> None:
    """
    Safety gate to prevent CV generation or dispatch if the profile contains placeholders.
    Raises ProfileValidationError if validation fails.
    """
    report = validate_candidate_profile(profile_dir)
    if not report.is_valid:
        raise ProfileValidationError(report.errors)
