"""
Deterministic Extraction Pipeline for Job Hunter v1.

All structured data is extracted via regex BEFORE any LLM invocation.
The Gemini API receives pre-enriched context, never raw unprocessed text.

Spec Reference: Technical_Specification.md §4

Invariants:
  - LLM is forbidden from independently searching for or inventing contact details.
  - Extraction results are integers, strings, or enum tiers — never free-form LLM output.
"""

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Tuple, Dict, List


# ============================================================
# Enums
# ============================================================

class GermanRequirement(str, Enum):
    """German language proficiency classification tiers."""
    MANDATORY_C1_PLUS = "MANDATORY_C1_PLUS"
    PREFERRED_B1_B2 = "PREFERRED_B1_B2"
    OPTIONAL_A1_A2 = "OPTIONAL_A1_A2"
    UNKNOWN = "UNKNOWN"

class EmailType(str, Enum):
    APPLICATION = "APPLICATION"
    RECRUITER = "RECRUITER"
    HR = "HR"
    CAREERS = "CAREERS"
    UNKNOWN = "UNKNOWN"

class DocumentRequirement(str, Enum):
    REQUIRED_AT_APPLICATION = "REQUIRED_AT_APPLICATION"
    OPTIONAL = "OPTIONAL"
    AFTER_INTERVIEW = "AFTER_INTERVIEW"
    ONBOARDING = "ONBOARDING"
    UNKNOWN = "UNKNOWN"


# ============================================================
# Extraction Result Container
# ============================================================

@dataclass
class ExtractionResult:
    """Container for all deterministically extracted fields."""
    contact_email: Optional[str] = None
    email_type: EmailType = EmailType.UNKNOWN
    min_experience: Optional[int] = None
    german_requirement: GermanRequirement = GermanRequirement.UNKNOWN
    required_documents: Dict[str, DocumentRequirement] = field(default_factory=dict)


# ============================================================
# Email Extraction
# ============================================================

_EMAIL_PATTERN = re.compile(
    r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}",
)

_EMAIL_EXCLUSIONS = re.compile(
    r"^(noreply|no-reply|no\.reply|donotreply|do-not-reply|"
    r"example|test|info@example|user@example|"
    r"admin@localhost|mailer-daemon)"
    r"@",
    re.IGNORECASE,
)

_EXCLUDED_DOMAINS = frozenset({
    "example.com",
    "example.org",
    "test.com",
    "localhost",
    "sentry.io",
    "github.com",
    "githubusercontent.com",
})


def extract_email(text: str) -> Optional[str]:
    """
    Extract the best contact email from text, excluding no-reply and test domains.
    Returns the email string or None.
    """
    emails = []
    for match in _EMAIL_PATTERN.finditer(text):
        email = match.group(0).lower()
        if _EMAIL_EXCLUSIONS.match(email):
            continue
        domain = email.split("@", 1)[1]
        if domain in _EXCLUDED_DOMAINS:
            continue
        emails.append(email)

    if not emails:
        return None

    classified = []
    for e in emails:
        local_part = e.split("@")[0]
        if any(kw in local_part for kw in ["apply", "application", "bewerbung"]):
            classified.append((e, 1))
        elif "recruit" in local_part:
            classified.append((e, 2))
        elif local_part == "hr" or "humanresources" in local_part:
            classified.append((e, 2))
        elif any(kw in local_part for kw in ["career", "job", "karriere"]):
            classified.append((e, 3))
        else:
            classified.append((e, 4))

    # Sort by priority (1 is highest)
    classified.sort(key=lambda x: x[1])
    return classified[0][0]


def classify_email_type(email: Optional[str]) -> EmailType:
    """Classify the type of the extracted email."""
    if not email:
        return EmailType.UNKNOWN

    local_part = email.split("@")[0].lower()
    if any(kw in local_part for kw in ["apply", "application", "bewerbung"]):
        return EmailType.APPLICATION
    elif "recruit" in local_part:
        return EmailType.RECRUITER
    elif local_part in ["hr", "humanresources"] or "hr@" in email or "humanresources" in local_part:
        return EmailType.HR
    elif any(kw in local_part for kw in ["career", "job", "karriere"]):
        return EmailType.CAREERS
    else:
        return EmailType.UNKNOWN


# ============================================================
# Required Documents Extraction
# ============================================================

def extract_required_documents(text: str) -> Dict[str, DocumentRequirement]:
    """
    Extract required application documents and classify their requirement stage.
    """
    docs = {
        "CV": DocumentRequirement.UNKNOWN,
        "Cover Letter": DocumentRequirement.UNKNOWN,
        "Degree Certificate": DocumentRequirement.UNKNOWN,
        "Work Authorization": DocumentRequirement.UNKNOWN,
    }
    
    text_lower = text.lower()
    
    # CV
    if re.search(r"\b(cv|resume|lebenslauf)\b", text_lower):
        docs["CV"] = DocumentRequirement.REQUIRED_AT_APPLICATION
        
    # Cover Letter
    if re.search(r"\b(cover letter|anschreiben|motivation letter)\b", text_lower):
        if re.search(r"\b(optional|if you want|freiwillig)\b.*(cover letter|anschreiben)", text_lower) or \
           re.search(r"(cover letter|anschreiben).*\b(optional|if you want|freiwillig)\b", text_lower):
            docs["Cover Letter"] = DocumentRequirement.OPTIONAL
        else:
            docs["Cover Letter"] = DocumentRequirement.REQUIRED_AT_APPLICATION
            
    # Degree Certificate
    if re.search(r"\b(degree certificate|zeugnis|diploma|transcript)\b", text_lower):
        if re.search(r"\b(onboarding|later|request|background check|hiring process)\b", text_lower):
            docs["Degree Certificate"] = DocumentRequirement.ONBOARDING
        else:
            docs["Degree Certificate"] = DocumentRequirement.REQUIRED_AT_APPLICATION
            
    return {k: v for k, v in docs.items() if v != DocumentRequirement.UNKNOWN}


# ============================================================
# Years of Experience Extraction
# ============================================================

_YOE_PATTERNS = [
    # Range patterns first so lower bound is matched: "3-5 years" -> 3
    re.compile(
        r"(\d{1,2})\s*[-–—]\s*\d{1,2}\s*(?:years?|yrs?|jahre)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:minimum|min\.?|at\s+least|mindestens)\s*(\d{1,2})\s*(?:years?|yrs?|jahre)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(\d{1,2})\+?\s*(?:years?|yrs?)\s*(?:of\s+)?(?:experience|exp(?:erience)?|berufserfahrung)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(\d{1,2})\+?\s*jahre\s*(?:erfahrung|berufserfahrung)?",
        re.IGNORECASE,
    ),
]


def extract_years_experience(text: str) -> Optional[int]:
    for pattern in _YOE_PATTERNS:
        match = pattern.search(text)
        if match:
            years = int(match.group(1))
            if 0 < years <= 30:
                return years
    return None


# ============================================================
# German Language Requirement Detection
# ============================================================

_GERMAN_MANDATORY = [
    re.compile(r"\b(?:german|deutsch)\b.*\b(?:required|mandatory|must|essential|erforderlich|zwingend|fluent|flie[ßs]end|native|muttersprach|c[12])\b", re.IGNORECASE),
    re.compile(r"\b(?:required|mandatory|must|essential|erforderlich|fluent|flie[ßs]end|native|muttersprach|c[12])\b.*\b(?:german|deutsch)\b", re.IGNORECASE),
    re.compile(r"\b(?:sehr\s+gute\s+deutschkenntnisse|muttersprachlich|verhandlungssicher(?:es?)?\s+deutsch)\b", re.IGNORECASE),
]

_GERMAN_PREFERRED = [
    re.compile(r"\b(?:german|deutsch)\b.*\b(?:preferred|advantage|plus|beneficial|wünschenswert|von\s+vorteil|b[12]|intermediate)\b", re.IGNORECASE),
    re.compile(r"\b(?:preferred|advantage|wünschenswert|von\s+vorteil|b[12])\b.*\b(?:german|deutsch)\b", re.IGNORECASE),
    re.compile(r"\bgute\s+deutschkenntnisse\b", re.IGNORECASE),
]

_GERMAN_OPTIONAL = [
    re.compile(r"\b(?:basic|beginner|a[12]|grundkenntnisse|nice\s+to\s+have)\b.*\b(?:german|deutsch)\b", re.IGNORECASE),
    re.compile(r"\b(?:german|deutsch)\b.*\b(?:basic|beginner|a[12]|grundkenntnisse|nice\s+to\s+have)\b", re.IGNORECASE),
]

def detect_german_requirement(text: str) -> GermanRequirement:
    if not text or not text.strip():
        return GermanRequirement.UNKNOWN

    has_preferred_not_required = bool(re.search(r"preferred\s+but\s+not\s+required", text, re.IGNORECASE))
    
    is_mandatory = False
    for p in _GERMAN_MANDATORY:
        if p.search(text):
            # If matched because of 'required' but it was 'preferred but not required', check if another mandatory signal exists
            if has_preferred_not_required and not re.search(r"\b(fluent|flie[ßs]end|c[12]|muttersprach|verhandlungssicher)\b", text, re.IGNORECASE):
                continue
            is_mandatory = True
            break

    if is_mandatory:
        return GermanRequirement.MANDATORY_C1_PLUS

    if any(p.search(text) for p in _GERMAN_PREFERRED) or has_preferred_not_required:
        return GermanRequirement.PREFERRED_B1_B2

    if any(p.search(text) for p in _GERMAN_OPTIONAL):
        return GermanRequirement.OPTIONAL_A1_A2

    return GermanRequirement.UNKNOWN


# ============================================================
# Unified Extraction Pipeline
# ============================================================

def run_extraction(text: str) -> ExtractionResult:
    """
    Run the full deterministic extraction pipeline on a job description.
    """
    email = extract_email(text)
    email_type = classify_email_type(email)
    
    return ExtractionResult(
        contact_email=email,
        email_type=email_type,
        min_experience=extract_years_experience(text),
        german_requirement=detect_german_requirement(text),
        required_documents=extract_required_documents(text)
    )
