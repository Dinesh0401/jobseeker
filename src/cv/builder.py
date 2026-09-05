"""
LaTeX CV Builder for Job Hunter v1.

Compiles tailored CVs by selecting profile entries referenced
in Gemini's tailored_cv_bullets output.

Spec Reference: Technical_Specification.md §8

Invariants:
  - ONLY entries present in profile/projects.json and profile/experience.json may appear.
  - Zero synthesized experience. Fabricating employers, tools, or responsibilities is FORBIDDEN.
  - LaTeX compilation uses xu-cheng/latex-action in CI; subprocess pdflatex locally.
"""

import json
import logging
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.matcher.gemini import load_profile

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
    """
    Resolve Gemini's tailored_cv_bullets to actual profile entries.

    Bullets are in format: "profile.experience[key]" or "profile.projects[key]"
    Only entries with keys that EXIST in the profile are included.

    Returns:
        Dict with 'experience_keys' and 'project_keys' lists.
    """
    experience_keys: List[str] = []
    project_keys: List[str] = []

    exp_pattern = re.compile(r"profile\.experience\[(\w+)\]")
    proj_pattern = re.compile(r"profile\.projects\[(\w+)\]")

    # Build lookup sets from actual profile data
    valid_exp_keys = {
        entry.get("key") for entry in profile.get("experience", [])
        if entry.get("key")
    }
    valid_proj_keys = {
        entry.get("key") for entry in profile.get("projects", [])
        if entry.get("key")
    }

    for bullet in bullets:
        key = bullet.strip()
        
        # Check experience references
        exp_match = exp_pattern.search(key)
        if exp_match:
            key = exp_match.group(1)
            
        proj_match = proj_pattern.search(key)
        if proj_match:
            key = proj_match.group(1)

        if key in valid_exp_keys:
            experience_keys.append(key)
        elif key in valid_proj_keys:
            project_keys.append(key)
        else:
            logger.warning("CV integrity: Unrecognized or invalid key: '%s' — SKIPPED", bullet)

    return {
        "experience_keys": experience_keys,
        "project_keys": project_keys,
    }


# ============================================================
# LaTeX Content Builders
# ============================================================

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
) -> str:
    """Build LaTeX experience entries, prioritizing highlighted keys."""
    entries = profile.get("experience", [])
    lines: List[str] = []

    # Sort: highlighted first, then by date
    highlighted = [e for e in entries if e.get("key") in highlighted_keys]
    others = [e for e in entries if e.get("key") not in highlighted_keys]
    ordered = highlighted + others

    for entry in ordered:
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
        if techs:
            tech_str = ", ".join(_escape_latex(t) for t in techs)
            lines.append(f"  \\item \\textit{{Technologies: {tech_str}}}")
        lines.append("\\end{itemize}")
        lines.append("\\vspace{4pt}")

    return "\n".join(lines)


def _build_project_section(
    profile: Dict[str, Any],
    highlighted_keys: List[str],
) -> str:
    """Build LaTeX project entries, prioritizing highlighted keys."""
    entries = profile.get("projects", [])
    lines: List[str] = []

    highlighted = [p for p in entries if p.get("key") in highlighted_keys]
    others = [p for p in entries if p.get("key") not in highlighted_keys]
    ordered = highlighted + others

    for entry in ordered:
        name = _escape_latex(entry.get("name", ""))
        description = _escape_latex(entry.get("description", ""))
        techs = entry.get("technologies", [])
        highlights = entry.get("highlights", [])
        year = entry.get("year", "")

        lines.append(f"\\textbf{{{name}}} \\hfill {year}")
        lines.append(f"\\\\{description}")
        if highlights:
            lines.append("\\begin{itemize}")
            for h in highlights:
                lines.append(f"  \\item {_escape_latex(h)}")
            lines.append("\\end{itemize}")
        if techs:
            tech_str = ", ".join(_escape_latex(t) for t in techs)
            lines.append(f"\\textit{{Stack: {tech_str}}}")
        lines.append("\\vspace{4pt}")

    return "\n".join(lines)


# ============================================================
# CV Builder
# ============================================================

class CVBuilder:
    """
    LaTeX CV compiler.

    Generates tailored CVs by selecting and ordering profile entries
    based on Gemini's recommendations, while enforcing source integrity.
    """

    def __init__(self, profile_dir: str = "profile", output_dir: str = "output"):
        self._profile = load_profile(profile_dir)
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
        Generate a tailored CV PDF.

        Args:
            job_id: Job identifier for output filename.
            tailored_cv_bullets: Gemini's profile entry references.
            job_title: Optional job title for logging.

        Returns:
            Path to the generated PDF file.

        Raises:
            RuntimeError: If LaTeX compilation fails.
        """
        # Resolve bullet references against actual profile
        resolved = _resolve_bullet_references(tailored_cv_bullets, self._profile)

        # Build LaTeX content
        profile_data = self._profile.get("profile", {})
        latex = _LATEX_TEMPLATE
        latex = latex.replace("<<NAME>>", _escape_latex(profile_data.get("name", "Candidate")))
        latex = latex.replace("<<TITLE>>", _escape_latex(profile_data.get("title", "")))
        latex = latex.replace("<<EMAIL>>", _escape_latex(profile_data.get("email", "")))
        latex = latex.replace("<<LOCATION>>", _escape_latex(profile_data.get("location", "")))
        latex = latex.replace("<<SUMMARY>>", _escape_latex(profile_data.get("summary", "")))

        # Skills
        skills = profile_data.get("skills", [])
        skills_str = ", ".join(_escape_latex(s) for s in skills) if skills else "N/A"
        latex = latex.replace("<<SKILLS>>", skills_str)

        # Experience (highlighted entries first)
        exp_section = _build_experience_section(
            self._profile, resolved["experience_keys"]
        )
        latex = latex.replace("<<EXPERIENCE_ENTRIES>>", exp_section)

        # Projects (highlighted entries first)
        proj_section = _build_project_section(
            self._profile, resolved["project_keys"]
        )
        latex = latex.replace("<<PROJECT_ENTRIES>>", proj_section)

        # Education
        education = profile_data.get("education", [])
        edu_lines = []
        for edu in education:
            degree = _escape_latex(edu.get("degree", ""))
            institution = _escape_latex(edu.get("institution", ""))
            year = edu.get("year", "")
            edu_lines.append(f"\\textbf{{{degree}}} — {institution} \\hfill {year}")
        latex = latex.replace("<<EDUCATION>>", "\n\n".join(edu_lines) if edu_lines else "N/A")

        # Languages
        languages = profile_data.get("languages", [])
        lang_parts = [
            f"{_escape_latex(l.get('language', ''))}: {_escape_latex(l.get('level', ''))}"
            for l in languages
        ]
        latex = latex.replace("<<LANGUAGES>>", " \\quad | \\quad ".join(lang_parts) if lang_parts else "N/A")

        # Write .tex file
        tex_path = self._output_dir / f"{job_id[:16]}_cv.tex"
        pdf_path = self._output_dir / f"{job_id[:16]}_cv.pdf"

        with open(tex_path, "w", encoding="utf-8") as f:
            f.write(latex)

        logger.info("Generated LaTeX: %s (for job: %s)", tex_path, job_title or job_id[:12])

        # Compile to PDF (local only — CI uses xu-cheng/latex-action)
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
                    "pdflatex not found locally. .tex file saved at %s. "
                    "Use xu-cheng/latex-action in CI to compile.",
                    tex_path,
                )
                return str(tex_path)

            logger.info("Compiled PDF: %s", pdf_path)
            return str(pdf_path)
        else:
            logger.info("compile_pdf=False: Skipping local compilation. Returning .tex path.")
            return str(tex_path)
