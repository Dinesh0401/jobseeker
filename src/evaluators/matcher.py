"""
Gemini Semantic Matcher for Job Hunter v1.

Evaluates job-candidate fit using Gemini 2.5 Flash via direct REST API.
Receives PRE-EXTRACTED deterministic facts alongside the job description.

Spec Reference: Technical_Specification.md §5

Invariants:
  - Gemini NEVER mutates application state directly.
  - Database transactions are forbidden during LLM network requests.
  - Contact email comes ONLY from deterministic extraction — LLM cannot override.
  - Output must be strictly structured JSON.
"""

import os
import json
import logging
import urllib.request
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")


def evaluate_job(
    title: str,
    company: str,
    description: str,
    profile: dict,
    deterministic_facts: dict,
) -> dict:
    """
    Evaluate a job posting against the candidate profile using Gemini 2.5 Flash.

    Uses the raw REST API (urllib.request) to avoid SDK dependencies.
    Description is truncated to 3500 chars to stay within token limits.

    Args:
        title: Job title.
        company: Company name.
        description: Full job description text.
        profile: Candidate profile dict (from profile.json).
        deterministic_facts: Pre-extracted facts dict with keys:
            - contact_email: str | None
            - min_experience: int | None
            - german_requirement: str

    Returns:
        Structured dict with keys:
            - score (0-100)
            - verdict: "APPLY" | "REVIEW" | "SKIP"
            - method: "EMAIL" | "ATS" | "LINKEDIN_EASY_APPLY" | "EXTERNAL"
            - contact_email: from deterministic facts only
            - tech_matches: list of matched technologies
            - gaps: list of gaps
            - tailored_cv_bullets: list mapped to profile.json entries
            - cover_letter_pitch: concise pitch string
    """
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
    )

    prompt = f"""
    Evaluate this job for the Candidate Profile.
    
    Candidate Profile: {json.dumps(profile)}
    Deterministic Facts (DO NOT OVERRIDE): {json.dumps(deterministic_facts)}
    
    Job Title: {title}
    Company: {company}
    Description: {description[:3500]}
    
    Instructions:
    1. Score the match from 0 to 100 based on skills, experience, location, and language fit.
    2. List technologies that match between the job and candidate.
    3. List gaps where the candidate falls short.
    4. Provide exactly 1-3 EXACT keys from the Candidate Profile's experience.json that best match this job. DO NOT invent prose. Only output the string value of the "key" field from the JSON.
    5. Provide exactly 1-2 EXACT keys from the Candidate Profile's projects.json that best match this job. DO NOT invent prose. Only output the string value of the "key" field from the JSON.
    6. Write a 2-3 sentence cover letter pitch customized to this job.
    
    Output strictly valid JSON:
    {{
      "score": <0-100>,
      "verdict": "APPLY" | "REVIEW" | "SKIP",
      "method": "EMAIL" | "ATS" | "LINKEDIN_EASY_APPLY" | "EXTERNAL",
      "contact_email": "<Use email from Deterministic Facts ONLY, or null>",
      "tech_matches": ["list"],
      "gaps": ["list"],
      "matched_experience_keys": ["<EXACT_EXPERIENCE_KEY_1>"],
      "matched_project_keys": ["<EXACT_PROJECT_KEY_1>"],
      "cover_letter_pitch": "<Concise 100-word pitch>"
    }}
    """

    payload = json.dumps(
        {"contents": [{"parts": [{"text": prompt}]}]}
    ).encode()

    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
    )

    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode())
            raw_text = (
                data["candidates"][0]["content"]["parts"][0]["text"]
                .replace("```json", "")
                .replace("```", "")
                .strip()
            )
            result = json.loads(raw_text)
            
            # Combine keys into tailored_cv_bullets for DB storage
            exp_keys = result.get("matched_experience_keys", [])
            proj_keys = result.get("matched_project_keys", [])
            
            if isinstance(exp_keys, list) and isinstance(proj_keys, list):
                result["tailored_cv_bullets"] = exp_keys + proj_keys
            else:
                result["tailored_cv_bullets"] = []
                
            logger.info(
                "Gemini evaluation: %s at %s -> score=%d, verdict=%s",
                title, company, result.get("score", 0), result.get("verdict", "UNKNOWN"),
            )
            return result
    except Exception as e:
        logger.error("Gemini API call failed for '%s' at '%s': %s", title, company, e)
        return {"score": 0, "verdict": "SKIP", "method": "UNKNOWN"}
