"""
Unit tests for Candidate Profile validation and safety gating.
"""

import pytest
from src.profiles.models import (
    CandidateProfile,
    EducationEntry,
    ExperienceEntry,
    LanguageEntry,
    ProjectEntry,
)
from src.profiles.validator import (
    ProfileValidationError,
    validate_candidate_profile,
    validate_profile_object,
    assert_profile_ready_for_dispatch,
)


def test_current_repo_profile_fails_validation_due_to_placeholders():
    """Verify that current profile files are detected as having placeholders."""
    report = validate_candidate_profile("profile")
    assert not report.is_valid
    assert len(report.errors) > 0
    assert any("your-email@example.com" in e or "placeholder" in e.lower() for e in report.errors)
    assert "email" in report.placeholder_fields


def test_assert_profile_ready_blocks_dispatch():
    """Verify that assert_profile_ready_for_dispatch raises error for current profile."""
    with pytest.raises(ProfileValidationError) as exc_info:
        assert_profile_ready_for_dispatch("profile")
    assert "Candidate Profile is invalid" in str(exc_info.value)


def test_clean_profile_passes_validation():
    """Verify that a fully filled, placeholder-free profile passes validation."""
    clean_profile = CandidateProfile(
        name="Dinesh S J",
        title="Junior AI Engineer",
        email="dinesh.real@gmail.com",
        location="Bengaluru, India",
        summary="AI Engineer specializing in LLMs, RAG architectures, and AI agent frameworks.",
        skills=["Python", "FastAPI", "PostgreSQL", "LangChain", "Docker", "PyTorch"],
        languages=[
            LanguageEntry(language="English", level="Fluent"),
            LanguageEntry(language="German", level="A1"),
        ],
        education=[
            EducationEntry(
                degree="B.Tech Computer Science",
                institution="Anna University",
                year=2024,
            )
        ],
        experience=[
            ExperienceEntry(
                key="exp_ai_intern_2024",
                company="Tech Corp India",
                role="AI Engineering Intern",
                start_date="2024-01",
                end_date="2024-06",
                responsibilities=["Developed RAG pipeline using LangChain and pgvector"],
                technologies=["Python", "PostgreSQL", "FastAPI"],
            )
        ],
        projects=[
            ProjectEntry(
                key="proj_multimodal_agent",
                name="Multimodal Agent Assistant",
                description="Built autonomous agent system evaluating multimodal queries using Gemini API.",
                technologies=["Python", "Gemini API", "FastAPI"],
                year=2024,
                highlights=["Reduced latency by 40% with streaming responses"],
            )
        ],
    )

    report = validate_profile_object(clean_profile)
    assert report.is_valid
    assert len(report.errors) == 0
    assert "exp_ai_intern_2024" in report.experience_keys
    assert "proj_multimodal_agent" in report.project_keys


def test_duplicate_keys_rejected():
    """Verify that duplicate experience or project keys are caught."""
    profile = CandidateProfile(
        name="Dinesh S J",
        title="Junior AI Engineer",
        email="dinesh@gmail.com",
        location="India",
        summary="A passionate AI engineer focused on building intelligent systems.",
        skills=["Python"],
        languages=[LanguageEntry(language="English", level="Fluent")],
        education=[EducationEntry(degree="B.Tech", institution="College", year=2024)],
        experience=[
            ExperienceEntry(
                key="exp_duplicate",
                company="Company A",
                role="Dev",
                start_date="2024",
                responsibilities=["Coding"],
                technologies=["Python"],
            ),
            ExperienceEntry(
                key="exp_duplicate",
                company="Company B",
                role="Dev",
                start_date="2024",
                responsibilities=["Testing"],
                technologies=["Python"],
            ),
        ],
        projects=[],
    )

    report = validate_profile_object(profile)
    assert not report.is_valid
    assert any("Duplicate experience key" in err for err in report.errors)
