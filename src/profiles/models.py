"""
Pydantic models for Candidate Career Profile.
"""

from typing import List, Optional
from pydantic import BaseModel, Field


class LanguageEntry(BaseModel):
    language: str = Field(..., min_length=2)
    level: str = Field(..., min_length=2)


class EducationEntry(BaseModel):
    degree: str = Field(..., min_length=2)
    institution: str = Field(..., min_length=2)
    year: int = Field(..., ge=1970, le=2035)


class ExperienceEntry(BaseModel):
    key: str = Field(..., min_length=2, description="Unique stable key, e.g. exp_company_role")
    company: str = Field(..., min_length=2)
    role: str = Field(..., min_length=2)
    start_date: str = Field(..., min_length=4)
    end_date: Optional[str] = "Present"
    responsibilities: List[str] = Field(default_factory=list)
    technologies: List[str] = Field(default_factory=list)


class ProjectEntry(BaseModel):
    key: str = Field(..., min_length=2, description="Unique stable key, e.g. proj_rag_agent")
    name: str = Field(..., min_length=2)
    description: str = Field(..., min_length=10)
    technologies: List[str] = Field(default_factory=list)
    year: int = Field(..., ge=1970, le=2035)
    highlights: List[str] = Field(default_factory=list)


class CandidateProfile(BaseModel):
    name: str = Field(..., min_length=2)
    title: str = Field(..., min_length=2)
    email: str = Field(..., min_length=5)
    location: str = Field(..., min_length=2)
    summary: str = Field(..., min_length=10)
    skills: List[str] = Field(default_factory=list)
    languages: List[LanguageEntry] = Field(default_factory=list)
    education: List[EducationEntry] = Field(default_factory=list)
    experience: List[ExperienceEntry] = Field(default_factory=list)
    projects: List[ProjectEntry] = Field(default_factory=list)


class ProfileValidationReport(BaseModel):
    is_valid: bool
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    placeholder_fields: List[str] = Field(default_factory=list)
    experience_keys: List[str] = Field(default_factory=list)
    project_keys: List[str] = Field(default_factory=list)
