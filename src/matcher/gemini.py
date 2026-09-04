"""
Gemini Semantic Matcher for Job Hunter v1.

Evaluates job-candidate fit using Gemini 2.5 Flash.
Receives PRE-EXTRACTED deterministic facts alongside the job description.

Spec Reference: Technical_Specification.md §5

Invariants:
  - Gemini NEVER mutates application state directly.
  - Database transactions are forbidden during LLM network requests.
  - Output must be strictly structured JSON.
"""

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import google.generativeai as genai

from src.config import GeminiConfig
from src.evaluators.extraction import ExtractionResult

logger = logging.getLogger(__name__)

# ============================================================
# Prompt Template
# ============================================================

_MATCH_PROMPT = """You are a job-matching assistant. Compare this job posting against the candidate profile and the pre-extracted facts.

## Job Posting
- **Title**: {title}
- **Company**: {company}
- **Location**: {location}
- **Description**: {description}

## Pre-Extracted Facts (Deterministic — trust these)
- **Contact Email**: {contact_email}
- **Min Experience Required**: {min_experience} years
- **German Requirement**: {german_requirement}

## Candidate Profile
{profile_json}

## Instructions
1. Score the match from 0 to 100 based on skills, experience, location, and language fit.
2. List technologies that match between the job and candidate.
3. List gaps where the candidate falls short.
4. Select 2-4 specific entries from the candidate's profile (by their "key" field) that should be highlighted in a tailored CV.
5. Write a 2-3 sentence cover letter pitch customized to this job.

## Output Format
Respond with ONLY a valid JSON object — no markdown, no explanation:
{{
  "score": <integer 0-100>,
  "method": "gemini-2.5-flash",
  "tech_matches": ["tech1", "tech2"],
  "gaps": ["gap1", "gap2"],
  "tailored_cv_bullets": ["profile.experience[key1]", "profile.projects[key2]"],
  "cover_letter_pitch": "<2-3 sentence pitch>"
}}"""


# ============================================================
# Profile Loader
# ============================================================

def load_profile(profile_dir: str = "profile") -> Dict[str, Any]:
    """
    Load the candidate profile from JSON files.

    Loads profile.json, projects.json, and experience.json
    and merges them into a single dict.

    Args:
        profile_dir: Path to the profile directory.

    Returns:
        Merged profile dictionary.
    """
    base = Path(profile_dir)
    profile: Dict[str, Any] = {}

    for filename in ["profile.json", "projects.json", "experience.json"]:
        filepath = base / filename
        if filepath.exists():
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
                key = filename.replace(".json", "")
                profile[key] = data
        else:
            logger.warning("Profile file not found: %s", filepath)

    return profile


# ============================================================
# Matcher
# ============================================================

@dataclass
class MatchResult:
    """Structured result from Gemini matching."""
    score: int
    method: str
    tech_matches: List[str]
    gaps: List[str]
    tailored_cv_bullets: List[str]
    cover_letter_pitch: str


class GeminiMatcher:
    """
    Semantic job matcher using Google Gemini.

    Usage:
        matcher = GeminiMatcher(config)
        result = matcher.match(job_data, extraction_result)
    """

    def __init__(self, config: GeminiConfig, profile_dir: str = "profile"):
        genai.configure(api_key=config.api_key)
        self._model = genai.GenerativeModel(config.model)
        self._threshold = config.match_threshold
        self._profile = load_profile(profile_dir)
        logger.info(
            "GeminiMatcher initialized (model=%s, threshold=%d)",
            config.model,
            config.match_threshold,
        )

    @property
    def threshold(self) -> int:
        """Match score threshold for MATCHED state."""
        return self._threshold

    def match(
        self,
        job: Dict[str, Any],
        extraction: ExtractionResult,
    ) -> MatchResult:
        """
        Evaluate job-candidate fit using Gemini.

        IMPORTANT: This method makes a network call to the Gemini API.
        Do NOT call this inside an open database transaction.

        Args:
            job: Job record dict with title, company, description, etc.
            extraction: Pre-extracted deterministic facts.

        Returns:
            MatchResult with score, matches, gaps, and CV suggestions.

        Raises:
            ValueError: If Gemini returns unparseable output.
            Exception: On API errors.
        """
        # Build prompt
        prompt = _MATCH_PROMPT.format(
            title=job.get("title", "Unknown"),
            company=job.get("company", "Unknown"),
            location=job.get("location", "Not specified"),
            description=job.get("description", "No description"),
            contact_email=extraction.contact_email or "Not found",
            min_experience=extraction.min_experience or "Not specified",
            german_requirement=extraction.german_requirement.value,
            profile_json=json.dumps(self._profile, indent=2),
        )

        # Call Gemini API (NO database transaction should be open here)
        logger.info("Calling Gemini for job: %s", job.get("title", "Unknown"))
        try:
            response = self._model.generate_content(prompt)
            raw_text = response.text.strip()
        except Exception as e:
            logger.error("Gemini API call failed: %s", e)
            raise

        # Parse JSON response
        try:
            # Strip markdown code fences if present
            if raw_text.startswith("```"):
                lines = raw_text.split("\n")
                raw_text = "\n".join(
                    line for line in lines
                    if not line.strip().startswith("```")
                )

            data = json.loads(raw_text)
        except json.JSONDecodeError as e:
            logger.error("Failed to parse Gemini output: %s\nRaw: %s", e, raw_text[:500])
            raise ValueError(f"Gemini returned unparseable output: {e}")

        # Validate and construct result
        result = MatchResult(
            score=int(data.get("score", 0)),
            method=data.get("method", "gemini-2.5-flash"),
            tech_matches=data.get("tech_matches", []),
            gaps=data.get("gaps", []),
            tailored_cv_bullets=data.get("tailored_cv_bullets", []),
            cover_letter_pitch=data.get("cover_letter_pitch", ""),
        )

        # Clamp score to valid range
        result.score = max(0, min(100, result.score))

        logger.info(
            "Match result for '%s': score=%d, matches=%d, gaps=%d",
            job.get("title", "Unknown"),
            result.score,
            len(result.tech_matches),
            len(result.gaps),
        )

        return result

    def is_match(self, result: MatchResult) -> bool:
        """Check if the match score meets the threshold."""
        return result.score >= self._threshold
