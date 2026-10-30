"""
Unit tests for Multi-Dimensional Semantic Matcher.
"""

from unittest.mock import MagicMock
from src.evaluators.eligibility import EligibilityCategory
from src.evaluators.languages import LanguageCategory
from src.evaluators.seniority import SeniorityTier
from src.matching.evaluator import (
    SemanticMatcher,
    compute_location_score,
    compute_language_score,
    compute_experience_score,
)


def test_subscore_computations():
    assert compute_location_score(EligibilityCategory.WORLDWIDE_REMOTE, False) == 100
    assert compute_location_score(EligibilityCategory.GERMANY_REMOTE, False) == 0
    assert compute_location_score(EligibilityCategory.RELOCATION_SUPPORTED, True) == 85

    assert compute_language_score(LanguageCategory.ENGLISH_ONLY) == 100
    assert compute_language_score(LanguageCategory.GERMAN_REQUIRED_C1_PLUS) == 0
    assert compute_language_score(LanguageCategory.ENGLISH_REQUIRED_GERMAN_PREFERRED) == 85

    assert compute_experience_score(SeniorityTier.ENTRY_OR_JUNIOR) == 100
    assert compute_experience_score(SeniorityTier.SENIOR_PLUS) == 0


def test_hard_gate_rejects_senior_without_llm():
    matcher = SemanticMatcher(api_key="mock_key")
    # Mock LLM call should NOT be made
    matcher._call_gemini_with_retry = MagicMock()

    result = matcher.evaluate(
        title="Senior Principal AI Architect",
        company="BigTech",
        location="Worldwide",
        description="We need 8+ years experience in deep learning.",
        is_remote=True,
    )

    assert not result.hard_gate_passed
    assert result.verdict == "REJECT"
    assert result.overall_match_score == 0
    assert matcher._call_gemini_with_retry.call_count == 0


def test_hard_gate_rejects_us_only_location_without_llm():
    matcher = SemanticMatcher(api_key="mock_key")
    matcher._call_gemini_with_retry = MagicMock()

    result = matcher.evaluate(
        title="Junior AI Engineer",
        company="DefenseTech",
        location="US Remote",
        description="US Citizenship required. US residents only. 1 year experience.",
        is_remote=True,
    )

    assert not result.hard_gate_passed
    assert result.verdict == "REJECT"
    assert "Ineligible location" in result.hard_gate_failures[0]
    assert matcher._call_gemini_with_retry.call_count == 0


def test_hard_gate_rejects_german_c1_without_llm():
    matcher = SemanticMatcher(api_key="mock_key")
    matcher._call_gemini_with_retry = MagicMock()

    result = matcher.evaluate(
        title="Junior Python Engineer",
        company="BerlinSoft",
        location="Berlin",
        description="Fließend Deutsch (C1/C2) erforderlich. 0-1 Jahre Erfahrung.",
        is_remote=False,
    )

    assert not result.hard_gate_passed
    assert result.verdict == "REJECT"
    assert "German" in result.hard_gate_failures[0] and "C1" in result.hard_gate_failures[0]
    assert matcher._call_gemini_with_retry.call_count == 0


def test_successful_evaluation_with_key_sanitization():
    matcher = SemanticMatcher(api_key="mock_key")
    matcher._call_gemini_with_retry = MagicMock(return_value={
        "technical_score": 85,
        "matched_skills": ["Python", "FastAPI"],
        "missing_skills": ["Kubernetes"],
        "matched_experience_keys": ["exp_example", "hallucinated_exp_key"],
        "matched_project_keys": ["project_example", "hallucinated_proj_key"],
        "experience_fit_score": 90,
        "recommendation": "APPLY",
        "risks_and_reasons": ["Minor gap in K8s"],
        "cover_letter_pitch": "Experienced with Python and REST APIs.",
    })

    result = matcher.evaluate(
        title="Junior AI Engineer",
        company="GlobalAI",
        location="Anywhere in the world",
        description="Work from anywhere. Python, FastAPI, and machine learning models.",
        is_remote=True,
    )

    assert result.hard_gate_passed
    assert result.verdict == "APPLY"
    assert result.overall_match_score >= 80
    # Hallucinated keys must be removed
    assert "hallucinated_exp_key" not in result.matched_experience_keys
    assert "hallucinated_proj_key" not in result.matched_project_keys
    assert "exp_example" in result.matched_experience_keys
    assert "project_example" in result.matched_project_keys

