"""
Multi-Dimensional Semantic Matcher for Job Hunter v2.

Evaluates job listings against full candidate profile, enforces hard gates,
and computes distinct scores across technical, experience, location, and language dimensions.
"""

import json
import logging
import os
import time
from typing import Any, Dict, Optional
import urllib.request
import urllib.error

from src.profiles.loader import load_candidate_profile, load_profile_as_dict
from src.evaluators.extraction import run_extraction
from src.evaluators.eligibility import classify_eligibility, EligibilityCategory
from src.evaluators.seniority import classify_seniority, SeniorityTier
from src.evaluators.languages import classify_languages, LanguageCategory
from src.matching.models import GeminiEvaluationResponse, MultiDimensionalEvaluationResult

logger = logging.getLogger(__name__)


def compute_location_score(category: EligibilityCategory, is_relocation: bool) -> int:
    """Compute 0-100 score for location eligibility from India."""
    if category in [EligibilityCategory.WORLDWIDE_REMOTE, EligibilityCategory.INDIA_ELIGIBLE_REMOTE]:
        return 100
    if category == EligibilityCategory.RELOCATION_SUPPORTED or is_relocation:
        return 85
    if category == EligibilityCategory.ELIGIBILITY_UNKNOWN:
        return 40
    # Germany/Europe remote only or country restricted = 0
    return 0


def compute_language_score(category: LanguageCategory) -> int:
    """Compute 0-100 score for language compatibility (Candidate: English Fluent, German Basic A1)."""
    if category == LanguageCategory.ENGLISH_ONLY:
        return 100
    if category == LanguageCategory.ENGLISH_AND_BASIC_GERMAN_ACCEPTED:
        return 95
    if category == LanguageCategory.ENGLISH_REQUIRED_GERMAN_PREFERRED:
        return 85
    if category == LanguageCategory.GERMAN_REQUIRED_A1_A2:
        return 80
    if category == LanguageCategory.LANGUAGE_UNKNOWN:
        return 70
    if category == LanguageCategory.GERMAN_REQUIRED_B1_B2:
        return 30
    # C1+ German or another foreign language required = 0
    return 0


def compute_experience_score(tier: SeniorityTier) -> int:
    """Compute 0-100 score for seniority fit (Candidate: 0-1 years / Junior)."""
    if tier == SeniorityTier.ENTRY_OR_JUNIOR:
        return 100
    if tier == SeniorityTier.UNKNOWN:
        return 70
    if tier == SeniorityTier.MID_LEVEL:
        return 40
    # Senior / Lead / Manager = 0
    return 0


class SemanticMatcher:
    """Orchestrates deterministic eligibility checks and semantic Gemini evaluation."""

    def __init__(self, api_key: Optional[str] = None, profile_dir: str = "profile"):
        self._api_key = api_key or os.getenv("GEMINI_API_KEY")
        self._profile_dir = profile_dir
        self._profile_obj = load_candidate_profile(profile_dir)
        self._valid_exp_keys = {e.key for e in self._profile_obj.experience}
        self._valid_proj_keys = {p.key for e in [self._profile_obj.projects] for p in e}

    def _call_gemini_with_retry(self, prompt: str) -> Dict[str, Any]:
        """Call Gemini REST API with bounded retries and exponential backoff."""
        if not self._api_key:
            raise ValueError("GEMINI_API_KEY is not set.")

        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={self._api_key}"
        payload = json.dumps({"contents": [{"parts": [{"text": prompt}]}]}).encode("utf-8")
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})

        last_error = None
        for attempt in range(1, 4):
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    raw_text = (
                        data["candidates"][0]["content"]["parts"][0]["text"]
                        .replace("```json", "")
                        .replace("```", "")
                        .strip()
                    )
                    return json.loads(raw_text)
            except urllib.error.HTTPError as e:
                last_error = e
                logger.warning("Gemini API HTTP %d (attempt %d/3): %s", e.code, attempt, e.reason)
                if e.code in [429, 500, 503]:
                    time.sleep(2 ** attempt)
                else:
                    break
            except Exception as e:
                last_error = e
                logger.warning("Gemini network error (attempt %d/3): %s", attempt, e)
                time.sleep(2 ** attempt)

        raise RuntimeError(f"Gemini API invocation failed after retries: {last_error}")

    def evaluate(
        self,
        title: str,
        company: str,
        location: str,
        description: str,
        is_remote: bool = False,
    ) -> MultiDimensionalEvaluationResult:
        """
        Evaluate a job posting against candidate profile.
        Combines deterministic fact gates and semantic LLM analysis.
        """
        # 1. Deterministic Extraction
        extraction = run_extraction(description)

        # 2. Seniority Assessment
        seniority = classify_seniority(title, extraction.min_experience, description)

        # 3. Location & India Eligibility Assessment
        eligibility = classify_eligibility(title, location, description, is_remote)

        # 4. Language Requirements Assessment
        languages = classify_languages(description)

        # 5. Check Hard Gates
        hard_gate_failures = []
        if not seniority.is_early_career_match:
            hard_gate_failures.append(seniority.rejection_reason or "Seniority exceeds early-career profile")

        if not eligibility.can_apply_from_india and not eligibility.is_relocation_pathway and eligibility.category != EligibilityCategory.ELIGIBILITY_UNKNOWN:
            hard_gate_failures.append(f"Ineligible location: {eligibility.category.value} (Cannot apply from India)")

        if not languages.is_immediately_eligible and languages.category == LanguageCategory.GERMAN_REQUIRED_C1_PLUS:
            hard_gate_failures.append("Mandatory German C1+ requirement exceeds current basic proficiency")
        elif not languages.is_immediately_eligible and languages.category == LanguageCategory.OTHER_LANGUAGE_REQUIRED:
            hard_gate_failures.append(languages.rejection_reason or "Unmet mandatory foreign language")

        # Compute baseline sub-scores
        exp_score = compute_experience_score(seniority.tier)
        loc_score = compute_location_score(eligibility.category, eligibility.is_relocation_pathway)
        lang_score = compute_language_score(languages.category)

        # If hard gates failed, we can fast-fail without burning Gemini tokens
        if hard_gate_failures:
            return MultiDimensionalEvaluationResult(
                technical_match_score=0,
                experience_level_score=exp_score,
                location_eligibility_score=loc_score,
                language_compatibility_score=lang_score,
                overall_match_score=0,
                verdict="REJECT",
                hard_gate_passed=False,
                hard_gate_failures=hard_gate_failures,
                eligibility_category=eligibility.category,
                language_category=languages.category,
                seniority_tier=seniority.tier,
                can_apply_from_india=eligibility.can_apply_from_india,
                is_relocation_pathway=eligibility.is_relocation_pathway,
                cover_letter_pitch="",
                contact_email=extraction.contact_email,
                email_type=extraction.email_type.value if extraction.email_type else None,
            )

        # 6. Full Profile Semantic Evaluation via Gemini
        full_profile = load_profile_as_dict(self._profile_dir)

        prompt = f"""You are an objective technical recruiter evaluating a candidate for this job.

Candidate Complete Profile (Source of Truth):
{json.dumps(full_profile, indent=2)}

Job Details:
- Title: {title}
- Company: {company}
- Location: {location}
- Description: {description[:3500]}

Deterministic Facts:
- Min Experience Extracted: {extraction.min_experience} years
- Seniority Tier: {seniority.tier.value}
- Location Classification: {eligibility.category.value}
- Language Classification: {languages.category.value}

CRITICAL INSTRUCTIONS:
1. Score technical_score from 0 to 100 based on overlap between candidate verified skills/projects and job requirements.
2. Select 1-3 EXACT keys from Candidate Profile "experience" array that are most relevant. DO NOT invent keys. Output only valid string keys.
3. Select 1-2 EXACT keys from Candidate Profile "projects" array that are most relevant. DO NOT invent keys. Output only valid string keys.
4. List matched skills and missing skills.
5. Provide a 2-3 sentence tailored cover_letter_pitch focusing on candidate's real projects and skills.
6. Provide a recommendation: "APPLY", "REVIEW", or "REJECT".

Output ONLY valid JSON matching this schema:
{{
  "technical_score": <int 0-100>,
  "matched_skills": ["skill1", "skill2"],
  "missing_skills": ["gap1", "gap2"],
  "matched_experience_keys": ["key1"],
  "matched_project_keys": ["key2"],
  "experience_fit_score": <int 0-100>,
  "recommendation": "APPLY" | "REVIEW" | "REJECT",
  "risks_and_reasons": ["reason1"],
  "cover_letter_pitch": "<2-3 sentence pitch>"
}}"""

        try:
            llm_raw = self._call_gemini_with_retry(prompt)
            llm_res = GeminiEvaluationResponse(**llm_raw)

            # Sanitize keys against genuine profile
            sanitized_exp_keys = [k for k in llm_res.matched_experience_keys if k in self._valid_exp_keys]
            sanitized_proj_keys = [k for k in llm_res.matched_project_keys if k in self._valid_proj_keys]

            tech_score = llm_res.technical_score
            overall = int(round(
                0.40 * tech_score +
                0.25 * exp_score +
                0.20 * loc_score +
                0.15 * lang_score
            ))

            verdict = "APPLY" if overall >= 65 and llm_res.recommendation != "REJECT" else "REVIEW"
            if overall < 50 or llm_res.recommendation == "REJECT":
                verdict = "REJECT"

            return MultiDimensionalEvaluationResult(
                technical_match_score=tech_score,
                experience_level_score=exp_score,
                location_eligibility_score=loc_score,
                language_compatibility_score=lang_score,
                overall_match_score=overall,
                verdict=verdict,
                hard_gate_passed=True,
                hard_gate_failures=[],
                eligibility_category=eligibility.category,
                language_category=languages.category,
                seniority_tier=seniority.tier,
                can_apply_from_india=eligibility.can_apply_from_india,
                is_relocation_pathway=eligibility.is_relocation_pathway,
                matched_experience_keys=sanitized_exp_keys,
                matched_project_keys=sanitized_proj_keys,
                tech_matches=llm_res.matched_skills,
                gaps=llm_res.missing_skills,
                cover_letter_pitch=llm_res.cover_letter_pitch,
                contact_email=extraction.contact_email,
                email_type=extraction.email_type.value if extraction.email_type else None,
            )

        except Exception as e:
            logger.error("Semantic evaluation failed for '%s' at '%s': %s", title, company, e)
            return MultiDimensionalEvaluationResult(
                technical_match_score=0,
                experience_level_score=exp_score,
                location_eligibility_score=loc_score,
                language_compatibility_score=lang_score,
                overall_match_score=0,
                verdict="REJECT",
                hard_gate_passed=False,
                hard_gate_failures=[f"LLM evaluation failed: {e}"],
                eligibility_category=eligibility.category,
                language_category=languages.category,
                seniority_tier=seniority.tier,
                can_apply_from_india=eligibility.can_apply_from_india,
                is_relocation_pathway=eligibility.is_relocation_pathway,
                cover_letter_pitch="",
                contact_email=extraction.contact_email,
                email_type=extraction.email_type.value if extraction.email_type else None,
            )
