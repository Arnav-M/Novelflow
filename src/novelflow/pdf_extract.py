"""Extract plain text from fiction PDFs via PyMuPDF."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pymupdf


def extract_pdf_text(
    pdf_path: str | Path,
    *,
    on_page: Callable[[int, int], None] | None = None,
) -> str:
    """Return page text joined with newlines (one block per page).

    ``on_page`` (when given) is called as ``on_page(done, total)`` after each
    page so callers can show real extraction progress on large books.
    """
    path = Path(pdf_path)
    if not path.is_file():
        raise FileNotFoundError(f"PDF not found: {path}")

    doc = pymupdf.open(str(path))
    try:
        total = doc.page_count
        parts: list[str] = []
        for index, page in enumerate(doc, start=1):
            parts.append(page.get_text("text"))
            if on_page:
                on_page(index, total)
        return "\n".join(parts)
    finally:
        doc.close()
