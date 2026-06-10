"""Detect italic text lines in fiction PDFs (scene headers, etc.)."""

from __future__ import annotations

import re
from pathlib import Path

import pymupdf

_ITALIC_FONT = re.compile(r"italic|oblique|(?<=-)it(?:$|[^a-z])", re.I)
_ITALIC_FLAG = 2  # pymupdf span flag bit for italic/oblique
_WS = re.compile(r"\s+")


def _span_is_italic(span: dict) -> bool:
    if span.get("flags", 0) & _ITALIC_FLAG:
        return True
    font = span.get("font", "") or ""
    return bool(_ITALIC_FONT.search(font))


def normalize_italic_key(text: str) -> str:
    return _WS.sub(" ", text.strip())


def extract_italic_lines(pdf_path: str | Path) -> set[str]:
    """
    Return normalized strings for each predominantly-italic PDF text line.

    Used to recover scene headers that plain text extraction drops.
    """
    hints: set[str] = set()
    path = Path(pdf_path)
    if not path.is_file():
        return hints

    doc = pymupdf.open(str(path))
    try:
        for page in doc:
            for block in page.get_text("dict").get("blocks", []):
                if block.get("type") != 0:
                    continue
                for line in block.get("lines", []):
                    spans = line.get("spans", [])
                    if not spans:
                        continue
                    chars = sum(len(span.get("text", "")) for span in spans)
                    if not chars:
                        continue
                    italic = sum(
                        len(span.get("text", ""))
                        for span in spans
                        if _span_is_italic(span)
                    )
                    if italic / chars < 0.55:
                        continue
                    text = "".join(span.get("text", "") for span in spans).strip()
                    if not text:
                        continue
                    key = normalize_italic_key(text)
                    if key:
                        hints.add(key)
    finally:
        doc.close()

    return hints
