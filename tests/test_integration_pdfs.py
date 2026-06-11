"""Integration tests using local sample PDFs in tests/fixtures/pdfs/."""

from pathlib import Path

import pytest

from novelflow.book_structure import SectionKind, parse_book_sections
from novelflow.convert import convert_pdf

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "pdfs"

MOZART = FIXTURES / "the-mozart-conspiracy.pdf"
DOOMSDAY = FIXTURES / "doomsday-prophecy.pdf"


@pytest.mark.skipif(not MOZART.is_file(), reason="Add the-mozart-conspiracy.pdf to tests/fixtures/pdfs/")
def test_convert_mozart_conspiracy():
    out = convert_pdf(MOZART)
    assert out.is_file()
    text = out.read_text(encoding="utf-8")
    assert len(text) > 400_000
    manifest = parse_book_sections(text)
    chapters = [s for s in manifest.sections if s.kind == SectionKind.CHAPTER]
    assert len(chapters) >= 50


@pytest.mark.skipif(not DOOMSDAY.is_file(), reason="Add doomsday-prophecy.pdf to tests/fixtures/pdfs/")
def test_convert_doomsday_prophecy():
    out = convert_pdf(DOOMSDAY)
    text = out.read_text(encoding="utf-8")
    assert len(text) > 400_000
    manifest = parse_book_sections(text)
    assert "Doomsday" in manifest.book_title
    chapters = [s for s in manifest.sections if s.kind == SectionKind.CHAPTER]
    assert len(chapters) >= 50


@pytest.mark.skipif(not DOOMSDAY.is_file(), reason="Add doomsday-prophecy.pdf to tests/fixtures/pdfs/")
def test_doomsday_front_and_back_matter():
    out = convert_pdf(DOOMSDAY)
    manifest = parse_book_sections(out.read_text(encoding="utf-8"))
    titles = {s.title for s in manifest.sections}
    assert "Dedication" in titles or "Contents" in titles
    kinds = {s.kind for s in manifest.sections}
    assert SectionKind.FRONT_MATTER in kinds
    assert SectionKind.CHAPTER in kinds
