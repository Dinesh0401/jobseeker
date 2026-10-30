"""
Unit tests for CV Provenance and PDF validation.
"""

import pytest
from pathlib import Path
from src.profiles.models import (
    CandidateProfile,
    EducationEntry,
    ExperienceEntry,
    LanguageEntry,
    ProjectEntry,
)
from src.cv.provenance import CVProvenanceAudit, validate_tex_content
from src.cv.pdf_validator import validate_compiled_pdf, PDFValidationError


def test_cv_provenance_audit_records_claims():
    profile = CandidateProfile(
        name="Dinesh S J",
        title="Junior AI Engineer",
        email="dinesh@gmail.com",
        location="India",
        summary="AI engineer specializing in LLM systems and tools.",
        skills=["Python"],
        languages=[LanguageEntry(language="English", level="Fluent")],
        education=[EducationEntry(degree="B.Tech", institution="College", year=2024)],
        experience=[
            ExperienceEntry(
                key="exp_rag_dev",
                company="AI Labs",
                role="Engineer",
                start_date="2024",
                responsibilities=["Engineered RAG pipelines with pgvector"],
                technologies=["Python"],
            )
        ],
        projects=[
            ProjectEntry(
                key="proj_agent",
                name="Agent Project",
                description="Built autonomous agent system with tools.",
                technologies=["Python"],
                year=2024,
                highlights=["Reduced latency by 40%"],
            )
        ],
    )

    audit = CVProvenanceAudit("test_job_123", profile)
    audit.record_claim("experience", "Engineered RAG pipelines with pgvector", "profile/experience.json", "exp_rag_dev")
    audit.record_claim("project", "Reduced latency by 40%", "profile/projects.json", "proj_agent")

    d = audit.to_dict()
    assert d["job_id"] == "test_job_123"
    assert d["total_claims"] == 2
    assert d["claims"][0]["source_key"] == "exp_rag_dev"
    assert d["claims"][1]["source_key"] == "proj_agent"


def test_validate_tex_content_flags_placeholders():
    profile = CandidateProfile(
        name="Dinesh S J",
        title="Junior AI Engineer",
        email="dinesh@gmail.com",
        location="India",
        summary="Experienced AI engineer building autonomous agents.",
        skills=["Python"],
        languages=[],
        education=[],
        experience=[],
        projects=[],
    )

    bad_tex = r"""
    \documentclass{article}
    \begin{document}
    Dinesh S J \\
    your-email@example.com \\
    Worked at Example Corp.
    \end{document}
    """

    errors = validate_tex_content(bad_tex, profile)
    assert len(errors) > 0
    assert any("placeholder" in e.lower() for e in errors)


def test_pdf_validator_rejects_dummy_mock_pdf(tmp_path):
    # Create the minimal 313-byte mock PDF
    tiny_pdf = tmp_path / "tiny.pdf"
    tiny_pdf.write_bytes(b"%PDF-1.4 mock dummy content %%EOF")

    with pytest.raises(PDFValidationError) as exc:
        validate_compiled_pdf(tiny_pdf, min_bytes=1000)
    assert "Dummy mock PDFs are rejected" in str(exc.value)


def test_pdf_validator_accepts_valid_pdf(tmp_path):
    valid_pdf = tmp_path / "valid.pdf"
    # Create a 2.5KB file with proper magic bytes and EOF
    content = b"%PDF-1.4\n" + b"A" * 2500 + b"\n%%EOF"
    valid_pdf.write_bytes(content)

    # Should not raise
    validate_compiled_pdf(valid_pdf, min_bytes=1000)
