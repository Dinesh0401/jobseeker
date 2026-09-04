"""
Unit tests for the deterministic extraction pipeline.

Tests: email extraction, YoE extraction, German proficiency detection,
and the unified run_extraction() function.

Spec Reference: Technical_Specification.md §4
"""

import pytest

from src.evaluators.extraction import (
    ExtractionResult,
    GermanRequirement,
    detect_german_requirement,
    extract_email,
    extract_years_experience,
    run_extraction,
)


# ============================================================
# Email Extraction Tests
# ============================================================

class TestExtractEmail:
    """Tests for extract_email()."""

    def test_simple_email(self):
        assert extract_email("Contact us at hr@techcorp.de") == "hr@techcorp.de"

    def test_email_in_long_text(self):
        text = """
        We are looking for a Senior Developer.
        Please send your CV to jobs@company.com.
        Visit our website at https://company.com.
        """
        assert extract_email(text) == "jobs@company.com"

    def test_multiple_emails_returns_first_valid(self):
        text = "noreply@company.com and recruiting@company.com"
        assert extract_email(text) == "recruiting@company.com"

    def test_excludes_noreply(self):
        assert extract_email("Contact noreply@company.com") is None

    def test_excludes_no_reply_dash(self):
        assert extract_email("Email: no-reply@service.com") is None

    def test_excludes_donotreply(self):
        assert extract_email("From donotreply@company.com") is None

    def test_excludes_example_domain(self):
        assert extract_email("user@example.com is not real") is None

    def test_excludes_test_domain(self):
        assert extract_email("admin@test.com") is None

    def test_excludes_github_domain(self):
        assert extract_email("bot@github.com") is None

    def test_returns_lowercase(self):
        assert extract_email("Email HR@TechCorp.DE") == "hr@techcorp.de"

    def test_no_email_found(self):
        assert extract_email("No contact information provided.") is None

    def test_email_with_plus(self):
        assert extract_email("send to hiring+dev@corp.io") == "hiring+dev@corp.io"

    def test_email_with_dots(self):
        assert extract_email("john.doe.hr@company.co.uk") == "john.doe.hr@company.co.uk"

    def test_empty_string(self):
        assert extract_email("") is None


# ============================================================
# Years of Experience Extraction Tests
# ============================================================

class TestExtractYearsExperience:
    """Tests for extract_years_experience()."""

    def test_simple_years(self):
        assert extract_years_experience("5 years of experience required") == 5

    def test_years_with_plus(self):
        assert extract_years_experience("3+ years experience") == 3

    def test_minimum_years(self):
        assert extract_years_experience("Minimum 4 years of experience") == 4

    def test_at_least(self):
        assert extract_years_experience("At least 2 years of relevant experience") == 2

    def test_range_returns_lower_bound(self):
        assert extract_years_experience("3-5 years of experience") == 3

    def test_range_with_en_dash(self):
        assert extract_years_experience("3–5 years experience") == 3

    def test_yrs_abbreviation(self):
        assert extract_years_experience("5+ yrs exp") == 5

    def test_german_jahre(self):
        assert extract_years_experience("5 Jahre Berufserfahrung") == 5

    def test_german_mindestens(self):
        assert extract_years_experience("mindestens 3 Jahre Erfahrung") == 3

    def test_no_experience_mentioned(self):
        assert extract_years_experience("We need a skilled developer") is None

    def test_unreasonable_value_rejected(self):
        assert extract_years_experience("50 years of experience") is None

    def test_zero_years_rejected(self):
        assert extract_years_experience("0 years experience") is None

    def test_empty_string(self):
        assert extract_years_experience("") is None


# ============================================================
# German Requirement Detection Tests
# ============================================================

class TestDetectGermanRequirement:
    """Tests for detect_german_requirement()."""

    # MANDATORY_C1_PLUS
    def test_german_required(self):
        assert detect_german_requirement("German language is required") == GermanRequirement.MANDATORY_C1_PLUS

    def test_fluent_german(self):
        assert detect_german_requirement("Fluent German required") == GermanRequirement.MANDATORY_C1_PLUS

    def test_deutsch_fliessend(self):
        assert detect_german_requirement("Fließend Deutsch erforderlich") == GermanRequirement.MANDATORY_C1_PLUS

    def test_german_c1(self):
        assert detect_german_requirement("German C1 level required") == GermanRequirement.MANDATORY_C1_PLUS

    def test_muttersprachlich(self):
        assert detect_german_requirement("Deutsch muttersprachlich") == GermanRequirement.MANDATORY_C1_PLUS

    def test_verhandlungssicher_deutsch(self):
        assert detect_german_requirement("Verhandlungssicheres Deutsch") == GermanRequirement.MANDATORY_C1_PLUS

    def test_deutschkenntnisse(self):
        assert detect_german_requirement("Sehr gute Deutschkenntnisse erforderlich") == GermanRequirement.MANDATORY_C1_PLUS

    # PREFERRED_B1_B2
    def test_german_preferred(self):
        assert detect_german_requirement("German is preferred but not required") == GermanRequirement.PREFERRED_B1_B2

    def test_german_advantage(self):
        assert detect_german_requirement("German language is an advantage") == GermanRequirement.PREFERRED_B1_B2

    def test_german_b2(self):
        assert detect_german_requirement("German B2 level preferred") == GermanRequirement.PREFERRED_B1_B2

    def test_german_von_vorteil(self):
        assert detect_german_requirement("Deutsch von Vorteil") == GermanRequirement.PREFERRED_B1_B2

    def test_gute_deutschkenntnisse(self):
        assert detect_german_requirement("Gute Deutschkenntnisse") == GermanRequirement.PREFERRED_B1_B2

    # OPTIONAL_A1_A2
    def test_german_basic(self):
        assert detect_german_requirement("Basic German is nice to have") == GermanRequirement.OPTIONAL_A1_A2

    def test_german_a1(self):
        assert detect_german_requirement("German A1 level is helpful") == GermanRequirement.OPTIONAL_A1_A2

    def test_grundkenntnisse(self):
        assert detect_german_requirement("Grundkenntnisse Deutsch") == GermanRequirement.OPTIONAL_A1_A2

    # UNKNOWN
    def test_no_german_mentioned(self):
        assert detect_german_requirement("Python developer needed") == GermanRequirement.UNKNOWN

    def test_english_only(self):
        assert detect_german_requirement("English fluency required") == GermanRequirement.UNKNOWN

    def test_empty_string(self):
        assert detect_german_requirement("") == GermanRequirement.UNKNOWN

    # Priority: MANDATORY wins over PREFERRED
    def test_mandatory_wins_over_preferred(self):
        text = "German is preferred. Actually, fluent German is required."
        assert detect_german_requirement(text) == GermanRequirement.MANDATORY_C1_PLUS


# ============================================================
# Unified Pipeline Tests
# ============================================================

class TestRunExtraction:
    """Tests for the unified run_extraction() pipeline."""

    def test_full_extraction(self):
        text = """
        Senior Python Developer at TechCorp GmbH.
        We require 5+ years of experience in Python.
        Fluent German is required (C1 level).
        Send your CV to careers@techcorp.de.
        """
        result = run_extraction(text)
        assert isinstance(result, ExtractionResult)
        assert result.contact_email == "careers@techcorp.de"
        assert result.min_experience == 5
        assert result.german_requirement == GermanRequirement.MANDATORY_C1_PLUS

    def test_partial_extraction(self):
        text = "Looking for a developer. Apply at jobs@startup.io"
        result = run_extraction(text)
        assert result.contact_email == "jobs@startup.io"
        assert result.min_experience is None
        assert result.german_requirement == GermanRequirement.UNKNOWN

    def test_empty_extraction(self):
        result = run_extraction("No useful info here")
        assert result.contact_email is None
        assert result.min_experience is None
        assert result.german_requirement == GermanRequirement.UNKNOWN

    def test_german_extraction_with_experience(self):
        text = """
        3-5 Jahre Berufserfahrung.
        Gute Deutschkenntnisse sind wünschenswert.
        Bewerbung an hr@firma.de
        """
        result = run_extraction(text)
        assert result.contact_email == "hr@firma.de"
        assert result.min_experience == 3
        assert result.german_requirement == GermanRequirement.PREFERRED_B1_B2
