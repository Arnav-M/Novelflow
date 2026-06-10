"""PDF extraction via markitdown + readability refinement."""

from pathlib import Path

from markitdown import MarkItDown

from novelflow.refine import refine_markdown


def convert_pdf(
    pdf_path: str | Path,
    output_path: str | Path | None = None,
    *,
    keep_raw: bool = False,
) -> Path:
    """
    Convert a PDF to readable markdown.

    Runs markitdown extraction, then applies paragraph/chapter/scene-header cleanup.

    Args:
        pdf_path: Input PDF file.
        output_path: Output .md path. Defaults to ``<name>.readable.md`` beside the PDF.
        keep_raw: If True, also write ``<name>.raw.md`` (markitdown output before cleanup).

    Returns:
        Path to the readable markdown file.
    """
    pdf = Path(pdf_path).resolve()
    if not pdf.is_file():
        raise FileNotFoundError(f"PDF not found: {pdf}")

    if output_path is None:
        out = pdf.with_suffix(".readable.md")
    else:
        out = Path(output_path).resolve()

    print(f"Extracting text from {pdf.name}...")
    converter = MarkItDown()
    result = converter.convert(str(pdf))
    raw_md = result.text_content

    if keep_raw:
        raw_path = pdf.with_suffix(".raw.md")
        raw_path.write_text(raw_md, encoding="utf-8")
        print(f"  Raw markitdown output: {raw_path}")

    print("Refining paragraphs, chapters, and scene headers...")
    readable = refine_markdown(raw_md)

    out.write_text(readable, encoding="utf-8")
    print(f"Done: {out} ({out.stat().st_size:,} bytes)")
    return out
