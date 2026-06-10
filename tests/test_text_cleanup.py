"""Tests for PDF text sanitization."""

from pathlib import Path

import pytest

from novelflow.text_cleanup import collapse_pdf_spacing, sanitize_pdf_text


@pytest.mark.parametrize(
    ("broken", "expected"),
    [
        ("Someone has given me aqua to\x00ana and has", "Someone has given me aqua tofana and has"),
        ("Someone has given me aqua to\u0283ana and has", "Someone has given me aqua tofana and has"),
        ("the collective toxic e\u0283ects of", "the collective toxic effects of"),
        ("death that Mozart su\u0283ered.", "death that Mozart suffered."),
        ("what he would \x00nd when he slipped away", "what he would find when he slipped away"),
        ("Up a winding \x00ight of stone steps", "Up a winding flight of stone steps"),
        ("turned it o\x00 and slipped it in", "turned it off and slipped it in"),
        ("resume in \x00fteen minutes", "resume in fifteen minutes"),
        ("with champagne \x00utes. As", "with champagne flutes. As"),
        ("a tall marble \x00replace, he could", "a tall marble fireplace, he could"),
        ("congratulate you on a \x00ne recital", "congratulate you on a fine recital"),
        ("The Debussy was magni\x00cent. I eagerly", "The Debussy was magnificent. I eagerly"),
        ("A \x00ash of lightning", "A flash of lightning"),
        ("laden conifers \x00ashed by", "laden conifers flashed by"),
        ("on his desk \x00ickered as he", "on his desk flickered as he"),
        ("REPLY, his \x00ngers jittery on", "REPLY, his fingers jittery on"),
        ("the video-clip \x00le", "the video-clip file"),
        ("Then she'd de\x00nitely receive", "Then she'd definitely receive"),
        ("He was \x00fty yards from", "He was fifty yards from"),
        ("\x00loor of the hall", "floor of the hall"),  # fallback: NUL -> f
    ],
)
def test_sanitize_pdf_text_phrases(broken: str, expected: str) -> None:
    assert sanitize_pdf_text(broken) == expected


def test_sanitize_noop_without_nulls() -> None:
    text = "Normal prose with find, flight, and off."
    assert sanitize_pdf_text(text) is text


def test_sanitize_empty_string() -> None:
    assert sanitize_pdf_text("") == ""


def test_collapse_pdf_spacing() -> None:
    assert collapse_pdf_spacing("scene  he  had  just") == "scene he had just"


@pytest.mark.parametrize(
    ("broken", "expected"),
    [
        ("what he would \u0279nd when he slipped", "what he would find when he slipped"),
        ("Up a winding \u027bight of stone steps", "Up a winding flight of stone steps"),
        ("with champagne \u027butes. As", "with champagne flutes. As"),
        ("turned it o\u0283 and slipped", "turned it off and slipped"),
        ("the Met O\u027dce weather", "the Met Office weather"),
    ],
)
def test_sanitize_pymupdf_ligature_glyphs(broken: str, expected: str) -> None:
    assert sanitize_pdf_text(broken) == expected


def test_mozart_pdf_sanitization_if_present() -> None:
    import re

    pdf_path = Path(__file__).resolve().parents[1] / "The Mozart Conspiracy.pdf"
    if not pdf_path.is_file():
        pytest.skip("Mozart PDF not present")

    pymupdf = pytest.importorskip("pymupdf")
    doc = pymupdf.open(str(pdf_path))
    raw = "\n".join(page.get_text("text") for page in doc)
    doc.close()

    cleaned = sanitize_pdf_text(raw)
    assert not re.search(r"[\u0279\u027b\u0283\u027d\u0280\x00\ufffd]", cleaned)
    assert "aqua tofana" in cleaned
    assert "muffler" in cleaned
    assert "Office" in cleaned or "office" in cleaned
