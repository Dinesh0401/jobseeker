"""
Profile loader for Candidate Career Data.

Loads and merges profile.json, experience.json, and projects.json
into typed CandidateProfile instances.
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict

from src.profiles.models import (
    CandidateProfile,
    EducationEntry,
    ExperienceEntry,
    LanguageEntry,
    ProjectEntry,
)

logger = logging.getLogger(__name__)


def load_candidate_profile(profile_dir: str = "profile") -> CandidateProfile:
    """
    Load the candidate profile from the 3 JSON files in profile_dir.

    Raises:
        FileNotFoundError: If any required profile file is missing.
        ValueError: If JSON parsing or Pydantic validation fails.
    """
    base = Path(profile_dir)

    profile_file = base / "profile.json"
    experience_file = base / "experience.json"
    projects_file = base / "projects.json"

    for path in [profile_file, experience_file, projects_file]:
        if not path.exists():
            raise FileNotFoundError(f"Required profile file missing: {path}")

    with open(profile_file, "r", encoding="utf-8") as f:
        profile_data = json.load(f)

    with open(experience_file, "r", encoding="utf-8") as f:
        exp_data = json.load(f)

    with open(projects_file, "r", encoding="utf-8") as f:
        proj_data = json.load(f)

    languages = [LanguageEntry(**item) for item in profile_data.get("languages", [])]
    education = [EducationEntry(**item) for item in profile_data.get("education", [])]
    experience = [ExperienceEntry(**item) for item in exp_data]
    projects = [ProjectEntry(**item) for item in proj_data]

    return CandidateProfile(
        name=profile_data.get("name", ""),
        title=profile_data.get("title", ""),
        email=profile_data.get("email", ""),
        location=profile_data.get("location", ""),
        summary=profile_data.get("summary", ""),
        skills=profile_data.get("skills", []),
        languages=languages,
        education=education,
        experience=experience,
        projects=projects,
    )


def load_profile_as_dict(profile_dir: str = "profile") -> Dict[str, Any]:
    """
    Load candidate profile as a merged dictionary for prompts and backwards compatibility.
    """
    profile = load_candidate_profile(profile_dir)
    return profile.model_dump()
