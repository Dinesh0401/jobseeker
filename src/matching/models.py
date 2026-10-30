"""
Pydantic schemas and result models for Multi-Dimensional Matching Engine.
"""

from typing import List, Optional
from pydantic import BaseModel, Field

from src.evaluators.eligibility import EligibilityCategory
from src.evaluators.languages import LanguageCategory
from src.evaluators.seniority import SeniorityTier


class GeminiEvaluationResponse(BaseModel):
    """Structured output expected from Gemini 2.5 Flash."""
    technical_score: int = Field(..., ge=0, le=100)
    matched_skills: List[str] = Field(default_factory=list)
    missing_skills: List[str] = Field(default_factory=list)
    matched_experience_keys: List[str] = Field(default_factory=list, description="Exact keys from candidate experience.json")
    matched_project_keys: List[str] = Field(default_factory=list, description="Exact keys from candidate projects.json")
    experience_fit_score: int = Field(..., ge=0, le=100)
    recommendation: str = Field(..., description="APPLY, REVIEW, or REJECT")
    risks_and_reasons: List[str] = Field(default_factory=list)
    cover_letter_pitch: str = Field(..., max_length=1000)


class MultiDimensionalEvaluationResult(BaseModel):
    """Comprehensive evaluation record combining deterministic facts and semantic scoring."""
    technical_match_score: int = Field(..., ge=0, le=100)
    experience_level_score: int = Field(..., ge=0, le=100)
    location_eligibility_score: int = Field(..., ge=0, le=100)
    language_compatibility_score: int = Field(..., ge=0, le=100)
    overall_match_score: int = Field(..., ge=0, le=100)
    
    verdict: str  # APPLY, REVIEW, or REJECT
    hard_gate_passed: bool
    hard_gate_failures: List[str] = Field(default_factory=list)
    
    eligibility_category: EligibilityCategory
    language_category: LanguageCategory
    seniority_tier: SeniorityTier
    
    can_apply_from_india: bool
    is_relocation_pathway: bool
    
    matched_experience_keys: List[str] = Field(default_factory=list)
    matched_project_keys: List[str] = Field(default_factory=list)
    tech_matches: List[str] = Field(default_factory=list)
    gaps: List[str] = Field(default_factory=list)
    
    cover_letter_pitch: str
    contact_email: Optional[str] = None
    email_type: Optional[str] = None
    evaluator_version: str = "v2.0-multi-dimensional"
