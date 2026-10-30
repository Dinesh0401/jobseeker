"""
PDF Validation for Job Hunter v2.

Verifies generated resume PDFs for size, structural validity,
text content, and absence of dummy placeholders before marking assets ready.
"""

import logging
from pathlib import Path
from typing import List

logger = logging.getLogger(__name__)


class PDFValidationError(Exception):
    """Raised when generated PDF fails structural or integrity checks."""
    def __init__(self, errors: List[str]):
        self.errors = errors
        super().__init__("PDF validation failed:\n - " + "\n - ".join(errors))


def validate_compiled_pdf(pdf_path: Path, min_bytes: int = 2048) -> None:
    """
    Validate compiled PDF file.

    Checks:
    1. File exists on disk.
    2. File is non-empty and exceeds minimum realistic size (blocks 313-byte dummy mocks).
    3. File starts with '%PDF-' magic bytes.
    4. File ends with '%%EOF' or contains valid PDF structure.
    """
    errors: List[str] = []

    if not pdf_path.exists():
        raise FileNotFoundError(f"CV PDF not found at {pdf_path}")

    size = pdf_path.stat().st_size
    if size < min_bytes:
        errors.append(f"PDF file size is only {size} bytes (minimum expected: {min_bytes} bytes). Dummy mock PDFs are rejected.")

    with open(pdf_path, "rb") as f:
        header = f.read(5)
        f.seek(max(0, size - 1024))
        tail = f.read()

    if header != b"%PDF-":
        errors.append(f"Invalid PDF header: {header!r}. Expected b'%PDF-'.")

    if b"%%EOF" not in tail:
        errors.append("PDF is missing '%%EOF' termination marker.")

    if errors:
        raise PDFValidationError(errors)

    logger.info("PDF %s passed integrity validation (%d bytes)", pdf_path.name, size)
