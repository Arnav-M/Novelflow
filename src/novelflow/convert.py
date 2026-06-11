"""PDF extraction via PyMuPDF + readability refinement."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from novelflow.pdf_extract import extract_pdf_text
from novelflow.pdf_italics import extract_italic_lines
from novelflow.refine import refine_markdown
from novelflow.text_cleanup import sanitize_pdf_text


class ConversionCancelled(Exception):
    """Raised when a caller-supplied ``cancel_check`` requests a stop."""


def _check_cancel(cancel_check: Callable[[], bool] | None) -> None:
    if cancel_check is not None and cancel_check():
        raise ConversionCancelled("Conversion cancelled.")


def convert_pdf(
    pdf_path: str | Path,
    output_path: str | Path | None = None,
    *,
    keep_raw: bool = False,
    progress: Callable[[str], None] | None = None,
    on_progress: Callable[[float], None] | None = None,
    audiobook: bool = False,
    tts_engine: str = "auto",
    tts_voice: str | None = None,
    audio_format: str = "m4b",
    disabled_section_ids: set[str] | None = None,
    chapters_and_title_only: bool = True,
    cancel_check: Callable[[], bool] | None = None,
) -> Path:
    """
    Convert a PDF to readable markdown.

    Runs PyMuPDF text extraction, then applies paragraph/chapter/scene-header cleanup.

    Args:
        pdf_path: Input PDF file.
        output_path: Output .md path. Defaults to ``<name>.readable.md`` beside the PDF.
        keep_raw: If True, also write ``<name>.raw.md`` (extracted text before cleanup).
        progress: Optional callback for status messages (defaults to ``print``).
        on_progress: Optional callback for a 0–100 completion percentage.
        cancel_check: Optional predicate; when it returns True the run aborts
            with :class:`ConversionCancelled` at the next safe checkpoint.

    Returns:
        Path to the readable markdown file.
    """
    log = progress or print

    # The markdown phase is quick; when an audiobook follows (the slow part)
    # it only owns the first 8% of the bar so the rest tracks narration time.
    md_span = 8.0 if audiobook else 100.0

    def report(raw_pct: float, msg: str) -> None:
        log(msg)
        if on_progress:
            on_progress(min(raw_pct, 100.0) * md_span / 100.0)

    pdf = Path(pdf_path).resolve()
    if not pdf.is_file():
        raise FileNotFoundError(f"PDF not found: {pdf}")

    if output_path is None:
        out = pdf.with_suffix(".readable.md")
    else:
        out = Path(output_path).resolve()

    _check_cancel(cancel_check)
    report(4, f"Extracting text from {pdf.name}...")

    def on_page(done: int, total: int) -> None:
        _check_cancel(cancel_check)
        if on_progress and total:
            # Extraction spans 4–42% of the markdown phase, weighted by page.
            on_progress((4 + 38 * (done / total)) * md_span / 100.0)

    raw_md = extract_pdf_text(pdf, on_page=on_page)
    null_count = raw_md.count("\x00")
    raw_md = sanitize_pdf_text(raw_md)
    report(45, "Extraction complete.")
    if null_count:
        report(47, f"  Repaired {null_count:,} missing-glyph placeholder(s) from PDF fonts.")

    if keep_raw:
        raw_path = pdf.with_suffix(".raw.md")
        raw_path.write_text(raw_md, encoding="utf-8")
        report(52, f"  Raw extraction output: {raw_path}")

    _check_cancel(cancel_check)
    report(50, "Scanning PDF for italic scene headers...")
    italic_hints = extract_italic_lines(pdf)
    if italic_hints:
        report(54, f"  Found {len(italic_hints):,} italic line(s) in PDF fonts.")

    _check_cancel(cancel_check)
    report(58, "Refining paragraphs, chapters, and scene headers...")
    readable = refine_markdown(raw_md, italic_hints=italic_hints or None)
    report(88, "Refinement complete.")

    out.write_text(readable, encoding="utf-8")
    report(100, f"Done: {out} ({out.stat().st_size:,} bytes)")

    if audiobook:
        from novelflow.audiobook import create_audiobook

        log("Building audiobook sections…")

        def audio_progress(pct: float) -> None:
            # Audiobook reports 0–100; it owns the bar from md_span to 100.
            if on_progress:
                on_progress(md_span + pct * (100.0 - md_span) / 100.0)

        create_audiobook(
            out,
            engine=tts_engine,
            voice=tts_voice,
            audio_format=audio_format,
            disabled_section_ids=disabled_section_ids,
            chapters_and_title_only=chapters_and_title_only,
            progress=log,
            on_progress=audio_progress,
            cancel_check=cancel_check,
        )

    return out
