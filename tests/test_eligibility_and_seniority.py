"""
Unit tests for international eligibility, seniority, and language requirements.
"""

from src.evaluators.eligibility import (
    EligibilityCategory,
    classify_eligibility,
)
from src.evaluators.seniority import (
    SeniorityTier,
    classify_seniority,
)
from src.evaluators.languages import (
    LanguageCategory,
    classify_languages,
)


# --- ELIGIBILITY TESTS ---

def test_worldwide_remote_eligibility():
    desc = "We are a fully distributed global team. You can work from anywhere in the world."
    res = classify_eligibility("Junior AI Engineer", "Anywhere", desc, is_remote=True)
    assert res.category == EligibilityCategory.WORLDWIDE_REMOTE
    assert res.can_apply_from_india is True


def test_india_eligible_remote():
    desc = "We are expanding our engineering hub. This role is open to candidates based in India."
    res = classify_eligibility("Python Developer", "India", desc, is_remote=True)
    assert res.category == EligibilityCategory.INDIA_ELIGIBLE_REMOTE
    assert res.can_apply_from_india is True


def test_us_restricted_remote():
    desc = "You must be a US citizen with an active security clearance. US residents only."
    res = classify_eligibility("Software Engineer", "US Remote", desc, is_remote=True)
    assert res.category == EligibilityCategory.COUNTRY_RESTRICTED
    assert res.can_apply_from_india is False


def test_germany_remote_only():
    desc = "Deutschlandweit remote. Wohnsitz in Deutschland ist zwingend erforderlich."
    res = classify_eligibility("Python Backend Engineer", "Germany Remote", desc, is_remote=True)
    assert res.category == EligibilityCategory.GERMANY_REMOTE
    assert res.can_apply_from_india is False


def test_relocation_supported():
    desc = "Join our Berlin office! We provide full visa sponsorship and a comprehensive relocation package."
    res = classify_eligibility("AI Engineer", "Berlin, Germany", desc, is_remote=False)
    assert res.category == EligibilityCategory.RELOCATION_SUPPORTED
    assert res.can_apply_from_india is False  # Requires relocation, not remote from India
    assert res.is_relocation_pathway is True
    assert res.visa_sponsorship is True


def test_eligibility_unknown_when_unclear():
    desc = "Looking for a skilled Python developer to join our growing company."
    res = classify_eligibility("Python Developer", "Berlin", desc, is_remote=False)
    assert res.category == EligibilityCategory.ELIGIBILITY_UNKNOWN
    assert res.can_apply_from_india is False


# --- SENIORITY TESTS ---

def test_seniority_entry_level_keywords():
    res = classify_seniority("Junior GenAI Engineer", None)
    assert res.tier == SeniorityTier.ENTRY_OR_JUNIOR
    assert res.is_early_career_match is True


def test_seniority_working_student():
    res = classify_seniority("Working Student - AI & ML", None)
    assert res.tier == SeniorityTier.ENTRY_OR_JUNIOR
    assert res.is_early_career_match is True


def test_seniority_low_experience():
    res = classify_seniority("Software Engineer", 1)
    assert res.tier == SeniorityTier.ENTRY_OR_JUNIOR
    assert res.is_early_career_match is True


def test_seniority_senior_title_rejected():
    res = classify_seniority("Senior AI Researcher", 1)
    assert res.tier == SeniorityTier.SENIOR_PLUS
    assert res.is_early_career_match is False
    assert "Title indicates senior" in res.rejection_reason


def test_seniority_high_experience_rejected():
    res = classify_seniority("Python Developer", 6)
    assert res.tier == SeniorityTier.SENIOR_PLUS
    assert res.is_early_career_match is False


# --- LANGUAGE TESTS ---

def test_language_c1_german_blocked():
    desc = "Verhandlungssichere Deutschkenntnisse (C1) zwingend erforderlich."
    res = classify_languages(desc)
    assert res.category == LanguageCategory.GERMAN_REQUIRED_C1_PLUS
    assert res.is_immediately_eligible is False
    assert res.requires_future_learning is True


def test_language_preferred_german_allowed():
    desc = "English is our working language. German language is an advantage."
    res = classify_languages(desc)
    assert res.category == LanguageCategory.ENGLISH_REQUIRED_GERMAN_PREFERRED
    assert res.is_immediately_eligible is True


def test_language_english_only_allowed():
    desc = "Our team is 100% international. English fluency is required."
    res = classify_languages(desc)
    assert res.category == LanguageCategory.ENGLISH_ONLY
    assert res.is_immediately_eligible is True

