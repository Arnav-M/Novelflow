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


def extract_first_page_cover_image(
    pdf_path: str | Path,
    output_path: str | Path,
    *,
    min_pixels: int = 2500,
) -> Path | None:
    """Save the largest raster image from page 1 as a PNG, when present."""
    pdf = Path(pdf_path)
    out = Path(output_path)
    if not pdf.is_file():
        return None

    doc = pymupdf.open(str(pdf))
    try:
        if doc.page_count == 0:
            return None
        page = doc[0]
        best_xref = 0
        best_area = 0
        for img in page.get_images(full=True):
            xref = img[0]
            width = img[2] if len(img) > 2 else 0
            height = img[3] if len(img) > 3 else 0
            area = width * height
            if area > best_area:
                best_area = area
                best_xref = xref
        if best_xref == 0 or best_area < min_pixels:
            return None

        pix = pymupdf.Pixmap(doc, best_xref)
        if pix.n - pix.alpha >= 4:
            pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
        out.parent.mkdir(parents=True, exist_ok=True)
        pix.save(str(out))
        return out
    finally:
        doc.close()
