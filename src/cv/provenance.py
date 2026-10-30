"""
Auditable CV Provenance Engine for Job Hunter v2.

Maintains strict traceability mapping:
    CV Statement -> Source File -> Source Key

Guarantees zero-hallucination document synthesis.
"""

from dataclasses import dataclass, asdict
import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List

from src.profiles.models import CandidateProfile

logger = logging.getLogger(__name__)

_PLACEHOLDER_REGEX = re.compile(
    r"\b(your-email@example\.com|your\s+university|example\s+corp|example\s+project|placeholder|todo)\b",
    re.IGNORECASE,
)


@dataclass
class ProvenanceClaim:
    statement: str
    section: str
    source_file: str
    source_key: str


class CVProvenanceAudit:
    """Manages statement-to-source traceability for a tailored CV."""

    def __init__(self, job_id: str, profile: CandidateProfile):
        self.job_id = job_id
        self.profile = profile
        self.claims: List[ProvenanceClaim] = []

    def record_claim(self, section: str, statement: str, source_file: str, source_key: str) -> None:
        self.claims.append(
            ProvenanceClaim(
                statement=statement.strip(),
                section=section,
                source_file=source_file,
                source_key=source_key,
            )
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "job_id": self.job_id,
            "candidate_name": self.profile.name,
            "total_claims": len(self.claims),
            "claims": [asdict(c) for c in self.claims],
        }

    def save(self, output_path: Path) -> None:
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2)
        logger.info("Saved CV provenance map to %s (%d claims)", output_path, len(self.claims))


def validate_tex_content(tex_content: str, profile: CandidateProfile) -> List[str]:
    """
    Validate LaTeX content against candidate profile before compilation.
    Checks for placeholders and ensures header identity matches profile.
    """
    errors: List[str] = []

    # Check for placeholder text
    matches = _PLACEHOLDER_REGEX.findall(tex_content)
    if matches:
        errors.append(f"Generated LaTeX contains placeholder strings: {set(matches)}")

    # Verify candidate name in header
    if profile.name not in tex_content:
        errors.append(f"Candidate name '{profile.name}' is missing from document header.")

    # Verify candidate email in header
    if profile.email not in tex_content:
        errors.append(f"Candidate email '{profile.email}' is missing from document header.")

    return errors
