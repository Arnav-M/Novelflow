"""Extract plain text from fiction PDFs via PyMuPDF."""

from __future__ import annotations

from pathlib import Path

import pymupdf


def extract_pdf_text(pdf_path: str | Path) -> str:
    """Return page text joined with newlines (one block per page)."""
    path = Path(pdf_path)
    if not path.is_file():
        raise FileNotFoundError(f"PDF not found: {path}")

    doc = pymupdf.open(str(path))
    try:
        return "\n".join(page.get_text("text") for page in doc)
    finally:
        doc.close()
