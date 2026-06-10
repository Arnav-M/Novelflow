"""PDF extraction via PyMuPDF + readability refinement."""

from collections.abc import Callable
from pathlib import Path

from novelflow.pdf_extract import extract_pdf_text
from novelflow.pdf_italics import extract_italic_lines
from novelflow.refine import refine_markdown
from novelflow.text_cleanup import sanitize_pdf_text


def convert_pdf(
    pdf_path: str | Path,
    output_path: str | Path | None = None,
    *,
    keep_raw: bool = False,
    progress: Callable[[str], None] | None = None,
    on_progress: Callable[[float], None] | None = None,
) -> Path:
    """
    Convert a PDF to readable markdown.

    Runs PyMuPDF text extraction, then applies paragraph/chapter/scene-header cleanup.

    Args:
        pdf_path: Input PDF file.
        output_path: Output .md path. Defaults to ``<name>.readable.md`` beside the PDF.
        keep_raw: If True, also write ``<name>.raw.md`` (extracted text before cleanup).
        progress: Optional callback for status messages (defaults to ``print``).

    Returns:
        Path to the readable markdown file.
    """
    log = progress or print

    def report(pct: float, msg: str) -> None:
        log(msg)
        if on_progress:
            on_progress(pct)

    pdf = Path(pdf_path).resolve()
    if not pdf.is_file():
        raise FileNotFoundError(f"PDF not found: {pdf}")

    if output_path is None:
        out = pdf.with_suffix(".readable.md")
    else:
        out = Path(output_path).resolve()

    report(8, f"Extracting text from {pdf.name}...")
    raw_md = extract_pdf_text(pdf)
    null_count = raw_md.count("\x00")
    raw_md = sanitize_pdf_text(raw_md)
    report(45, "Extraction complete.")
    if null_count:
        report(47, f"  Repaired {null_count:,} missing-glyph placeholder(s) from PDF fonts.")

    if keep_raw:
        raw_path = pdf.with_suffix(".raw.md")
        raw_path.write_text(raw_md, encoding="utf-8")
        report(52, f"  Raw extraction output: {raw_path}")

    report(50, "Scanning PDF for italic scene headers...")
    italic_hints = extract_italic_lines(pdf)
    if italic_hints:
        report(54, f"  Found {len(italic_hints):,} italic line(s) in PDF fonts.")

    report(58, "Refining paragraphs, chapters, and scene headers...")
    readable = refine_markdown(raw_md, italic_hints=italic_hints or None)
    report(88, "Refinement complete.")

    out.write_text(readable, encoding="utf-8")
    report(100, f"Done: {out} ({out.stat().st_size:,} bytes)")
    return out
