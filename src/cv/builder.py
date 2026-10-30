"""
LaTeX CV Builder for Job Hunter v2.

Compiles tailored CVs by selecting profile entries referenced
in Gemini's tailored_cv_bullets output and recording strict provenance mapping.
"""

import json
import logging
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.profiles.loader import load_candidate_profile, load_profile_as_dict
from src.cv.provenance import CVProvenanceAudit, validate_tex_content
from src.cv.pdf_validator import validate_compiled_pdf, PDFValidationError

logger = logging.getLogger(__name__)

# ============================================================
# LaTeX Template
# ============================================================

_LATEX_TEMPLATE = r"""
\documentclass[11pt,a4paper]{article}
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage{lmodern}
\usepackage[margin=1.5cm]{geometry}
\usepackage{enumitem}
\usepackage{hyperref}
\usepackage{xcolor}
\usepackage{titlesec}

\definecolor{primary}{RGB}{37,99,235}
\definecolor{gray600}{RGB}{75,85,99}

\titleformat{\section}{\large\bfseries\color{primary}}{}{0em}{}[\titlerule]
\titlespacing*{\section}{0pt}{12pt}{6pt}

\pagestyle{empty}
\setlength{\parindent}{0pt}
\setlist[itemize]{leftmargin=1.5em, itemsep=2pt, parsep=0pt}

\begin{document}

% Header
{\LARGE\bfseries <<NAME>>} \\[4pt]
{\color{gray600} <<TITLE>>} \\[2pt]
{\small <<EMAIL>> \quad | \quad <<LOCATION>>}

\vspace{8pt}

% Summary
\section{Summary}
<<SUMMARY>>

% Skills
\section{Technical Skills}
<<SKILLS>>

% Experience
\section{Experience}
<<EXPERIENCE_ENTRIES>>

% Projects
\section{Projects}
<<PROJECT_ENTRIES>>

% Education
\section{Education}
<<EDUCATION>>

% Languages
\section{Languages}
<<LANGUAGES>>

\end{document}
"""


# ============================================================
# Profile Entry Resolution
# ============================================================

def _resolve_bullet_references(
    bullets: List[str],
    profile: Dict[str, Any],
) -> Dict[str, List[str]]:
    experience_keys: List[str] = []
    project_keys: List[str] = []

    valid_exp_keys = {
        entry.get("key") for entry in profile.get("experience", [])
        if entry.get("key")
    }
    valid_proj_keys = {
        entry.get("key") for entry in profile.get("projects", [])
        if entry.get("key")
    }

    for key in bullets:
        key = key.strip()
        if key in valid_exp_keys:
            experience_keys.append(key)
        elif key in valid_proj_keys:
            project_keys.append(key)
        else:
            logger.warning("CV integrity: Unrecognized or invalid key: '%s' — SKIPPED", key)

    return {
        "experience_keys": experience_keys,
        "project_keys": project_keys,
    }


def _escape_latex(text: str) -> str:
    """Escape special LaTeX characters."""
    chars = {
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    for char, replacement in chars.items():
        text = text.replace(char, replacement)
    return text


def _build_experience_section(
    profile: Dict[str, Any],
    highlighted_keys: List[str],
    provenance: Optional[CVProvenanceAudit] = None,
) -> str:
    entries = profile.get("experience", [])
    lines: List[str] = []

    highlighted = [e for e in entries if e.get("key") in highlighted_keys]
    others = [e for e in entries if e.get("key") not in highlighted_keys]
    ordered = highlighted + others

    for entry in ordered:
        key = entry.get("key", "exp_unknown")
        company = _escape_latex(entry.get("company", ""))
        role = _escape_latex(entry.get("role", ""))
        start = entry.get("start_date", "")
        end = entry.get("end_date", "Present")
        responsibilities = entry.get("responsibilities", [])
        techs = entry.get("technologies", [])

        lines.append(f"\\textbf{{{role}}} \\hfill {start} -- {end}")
        lines.append(f"\\\\\\textit{{{company}}}")
        lines.append("\\begin{itemize}")
        for resp in responsibilities:
            lines.append(f"  \\item {_escape_latex(resp)}")
            if provenance:
                provenance.record_claim("experience", resp, "profile/experience.json", key)

        if techs:
            tech_str = ", ".join(_escape_latex(t) for t in techs)
            lines.append(f"  \\item \\textit{{Technologies: {tech_str}}}")
            if provenance:
                provenance.record_claim("experience_techs", tech_str, "profile/experience.json", key)

        lines.append("\\end{itemize}")
        lines.append("\\vspace{4pt}")

    return "\n".join(lines)


def _build_project_section(
    profile: Dict[str, Any],
    highlighted_keys: List[str],
    provenance: Optional[CVProvenanceAudit] = None,
) -> str:
    entries = profile.get("projects", [])
    lines: List[str] = []

    highlighted = [p for p in entries if p.get("key") in highlighted_keys]
    others = [p for p in entries if p.get("key") not in highlighted_keys]
    ordered = highlighted + others

    for entry in ordered:
        key = entry.get("key", "proj_unknown")
        name = _escape_latex(entry.get("name", ""))
        description = _escape_latex(entry.get("description", ""))
        techs = entry.get("technologies", [])
        highlights = entry.get("highlights", [])
        year = entry.get("year", "")

        lines.append(f"\\textbf{{{name}}} \\hfill {year}")
        lines.append(f"\\\\{description}")
        if provenance:
            provenance.record_claim("project_summary", description, "profile/projects.json", key)

        if highlights:
            lines.append("\\begin{itemize}")
            for h in highlights:
                lines.append(f"  \\item {_escape_latex(h)}")
                if provenance:
                    provenance.record_claim("project_highlight", h, "profile/projects.json", key)
            lines.append("\\end{itemize}")

        if techs:
            tech_str = ", ".join(_escape_latex(t) for t in techs)
            lines.append(f"\\textit{{Stack: {tech_str}}}")

        lines.append("\\vspace{4pt}")

    return "\n".join(lines)


class CVBuilder:
    """LaTeX CV compiler with auditable provenance."""

    def __init__(self, profile_dir: str = "profile", output_dir: str = "output"):
        self._profile_dir = profile_dir
        self._candidate_profile = load_candidate_profile(profile_dir)
        self._profile_dict = load_profile_as_dict(profile_dir)
        self._output_dir = Path(output_dir)
        self._output_dir.mkdir(parents=True, exist_ok=True)
        logger.info("CVBuilder initialized (output=%s)", output_dir)

    def build(
        self,
        job_id: str,
        tailored_cv_bullets: List[str],
        job_title: Optional[str] = None,
        compile_pdf: bool = True,
    ) -> str:
        """
        Generate a tailored CV LaTeX document and optional PDF.
        Records provenance mapping for every claim.
        """
        provenance = CVProvenanceAudit(job_id, self._candidate_profile)
        resolved = _resolve_bullet_references(tailored_cv_bullets, self._profile_dict)

        latex = _LATEX_TEMPLATE
        latex = latex.replace("<<NAME>>", _escape_latex(self._candidate_profile.name))
        latex = latex.replace("<<TITLE>>", _escape_latex(self._candidate_profile.title))
        latex = latex.replace("<<EMAIL>>", _escape_latex(self._candidate_profile.email))
        latex = latex.replace("<<LOCATION>>", _escape_latex(self._candidate_profile.location))
        latex = latex.replace("<<SUMMARY>>", _escape_latex(self._candidate_profile.summary))
        provenance.record_claim("summary", self._candidate_profile.summary, "profile/profile.json", "profile_summary")

        skills = self._candidate_profile.skills
        skills_str = ", ".join(_escape_latex(s) for s in skills) if skills else "N/A"
        latex = latex.replace("<<SKILLS>>", skills_str)
        provenance.record_claim("skills", skills_str, "profile/profile.json", "profile_skills")

        exp_section = _build_experience_section(self._profile_dict, resolved["experience_keys"], provenance)
        latex = latex.replace("<<EXPERIENCE_ENTRIES>>", exp_section)

        proj_section = _build_project_section(self._profile_dict, resolved["project_keys"], provenance)
        latex = latex.replace("<<PROJECT_ENTRIES>>", proj_section)

        edu_lines = []
        for edu in self._candidate_profile.education:
            degree = _escape_latex(edu.degree)
            institution = _escape_latex(edu.institution)
            year = edu.year
            edu_lines.append(f"\\textbf{{{degree}}} — {institution} \\hfill {year}")
            provenance.record_claim("education", f"{degree} from {institution}", "profile/profile.json", "profile_education")
        latex = latex.replace("<<EDUCATION>>", "\n\n".join(edu_lines) if edu_lines else "N/A")

        lang_parts = [
            f"{_escape_latex(l.language)}: {_escape_latex(l.level)}"
            for l in self._candidate_profile.languages
        ]
        latex = latex.replace("<<LANGUAGES>>", " \\quad | \\quad ".join(lang_parts) if lang_parts else "N/A")

        # Save provenance audit artifact
        prov_path = self._output_dir / f"{job_id[:16]}_provenance.json"
        provenance.save(prov_path)

        # Write .tex file
        tex_path = self._output_dir / f"{job_id[:16]}_cv.tex"
        pdf_path = self._output_dir / f"{job_id[:16]}_cv.pdf"

        with open(tex_path, "w", encoding="utf-8") as f:
            f.write(latex)

        logger.info("Generated LaTeX: %s (for job: %s)", tex_path, job_title or job_id[:12])

        if compile_pdf:
            try:
                result = subprocess.run(
                    ["pdflatex", "-interaction=nonstopmode", "-output-directory", str(self._output_dir), str(tex_path)],
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                if result.returncode != 0:
                    logger.error("pdflatex failed:\n%s", result.stderr[-1000:])
                    raise RuntimeError(f"LaTeX compilation failed: {result.stderr[-500:]}")
            except FileNotFoundError:
                logger.warning(
                    "pdflatex not found locally. .tex file saved at %s. Use xu-cheng/latex-action in CI.",
                    tex_path,
                )
                return str(tex_path)

            validate_compiled_pdf(pdf_path)
            logger.info("Compiled and validated PDF: %s", pdf_path)
            return str(pdf_path)
        else:
            return str(tex_path)
