"""Tests for audiobook section parsing."""

from novelflow.book_structure import SectionKind, parse_book_sections


SAMPLE = """\
# The Example Novel

*JANE AUTHOR*

## Dedication

For my family.

## Chapter One

It was a dark and stormy night. The wind howled.

## Chapter Two

Morning came softly over the hills.

## Acknowledgements

Thanks to everyone who helped.
"""


def test_parse_sections_order():
    manifest = parse_book_sections(SAMPLE)
    titles = [s.title for s in manifest.sections]
    assert titles[0] == "The Example Novel"
    assert "Dedication" in titles
    assert "Chapter One" in titles
    assert "Acknowledgements" in titles
    assert titles.index("Dedication") < titles.index("Chapter One")
    assert titles.index("Chapter Two") < titles.index("Acknowledgements")


def test_section_kinds():
    manifest = parse_book_sections(SAMPLE)
    by_title = {s.title: s for s in manifest.sections}
    assert by_title["The Example Novel"].kind == SectionKind.TITLE
    assert by_title["Dedication"].kind == SectionKind.FRONT_MATTER
    assert by_title["Chapter One"].kind == SectionKind.CHAPTER
    assert by_title["Acknowledgements"].kind == SectionKind.BACK_MATTER


def test_strip_markdown_for_tts():
    manifest = parse_book_sections(SAMPLE)
    ch1 = next(s for s in manifest.sections if s.title == "Chapter One")
    assert "##" not in ch1.text
    assert "dark and stormy" in ch1.text


def test_default_audiobook_filter():
    from novelflow.book_structure import (
        SectionKind,
        apply_default_audiobook_filter,
        default_audiobook_disabled_ids,
        parse_book_sections,
    )

    manifest = parse_book_sections(SAMPLE)
    disabled = default_audiobook_disabled_ids(manifest)
    assert any(s.title == "Dedication" for s in manifest.sections if s.id in disabled)
    filtered = apply_default_audiobook_filter(manifest)
    enabled_kinds = {s.kind for s in filtered.enabled_sections()}
    assert SectionKind.CHAPTER in enabled_kinds
    assert SectionKind.FRONT_MATTER not in enabled_kinds
    assert SectionKind.BACK_MATTER not in enabled_kinds


def test_navigation_skipped():
    md = """\
# Book

## Navigation

- [Chapter One](#chapter-one)

## Chapter One

Story here.
"""
    manifest = parse_book_sections(md)
    titles = [s.title for s in manifest.sections]
    assert "Navigation" not in titles
    assert "Chapter One" in titles


def test_duplicate_titles_collapsed():
    md = """\
# The Doomsday Prophecy

The Doomsday Prophecy

# The Doomsday Prophecy

The Doomsday Prophecy

# The Doomsday Prophecy

SCOTT MARIANI

## Chapter One

It begins.
"""
    manifest = parse_book_sections(md)
    title_sections = [s for s in manifest.sections if s.kind == SectionKind.TITLE]
    assert len(title_sections) == 1
    # The single title still carries the book title text.
    assert "Doomsday Prophecy" in title_sections[0].text
