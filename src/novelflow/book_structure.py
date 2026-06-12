"""Parse readable markdown into titled audiobook sections with chapter markers."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path

from novelflow.cover_art import find_cover_in_markdown as find_cover_image_path
from novelflow.refine import BACK_MATTER, CHAPTER_RE, GENERIC_HEADING_RE, chapter_slug

SKIP_SECTIONS = frozenset({"navigation"})
NAVIGATION_RE = re.compile(r"^navigation$", re.I)


class SectionKind(str, Enum):
    TITLE = "title"
    FRONT_MATTER = "front_matter"
    CHAPTER = "chapter"
    BACK_MATTER = "back_matter"
    OTHER = "other"


FRONT_MATTER_TITLES = frozenset({
    "contents", "title page", "dedication", "epigraph", "book jacket",
    "summary:", "rating:", "copyright", "also by", "by the same author:",
})


@dataclass
class BookSection:
    """One navigable block in the audiobook (title, chapter, acknowledgements, …)."""

    id: str
    title: str
    kind: SectionKind
    text: str
    enabled: bool = True
    order: int = 0

    def to_dict(self) -> dict:
        data = asdict(self)
        data["kind"] = self.kind.value
        return data

    @classmethod
    def from_dict(cls, data: dict) -> BookSection:
        return cls(
            id=data["id"],
            title=data["title"],
            kind=SectionKind(data["kind"]),
            text=data["text"],
            enabled=data.get("enabled", True),
            order=data.get("order", 0),
        )


@dataclass
class BookManifest:
    """Audiobook navigation manifest — supports in-app skip and future section pruning."""

    book_title: str
    author: str | None
    source_markdown: str
    sections: list[BookSection] = field(default_factory=list)
    version: int = 1

    def enabled_sections(self) -> list[BookSection]:
        return [s for s in self.sections if s.enabled and s.text.strip()]

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "book_title": self.book_title,
            "author": self.author,
            "source_markdown": self.source_markdown,
            "sections": [s.to_dict() for s in self.sections],
        }

    @classmethod
    def from_dict(cls, data: dict) -> BookManifest:
        return cls(
            version=data.get("version", 1),
            book_title=data["book_title"],
            author=data.get("author"),
            source_markdown=data.get("source_markdown", ""),
            sections=[BookSection.from_dict(s) for s in data["sections"]],
        )

    def save(self, path: Path) -> None:
        path.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> BookManifest:
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))


def _strip_markdown_for_tts(text: str) -> str:
    """Flatten markdown to plain speech-friendly text."""
    lines: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            lines.append("")
            continue
        if line.startswith("- [") and "](#" in line:
            continue
        line = re.sub(r"^#{1,6}\s+", "", line)
        line = re.sub(r"\*\*(.+?)\*\*", r"\1", line)
        line = re.sub(r"\*(.+?)\*", r"\1", line)
        line = re.sub(r"\[(.+?)\]\(.+?\)", r"\1", line)
        lines.append(line)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _classify_section(title: str) -> SectionKind:
    normalized = title.strip()
    lower = normalized.lower()
    if NAVIGATION_RE.match(lower) or lower in SKIP_SECTIONS:
        return SectionKind.OTHER
    if CHAPTER_RE.match(normalized) or re.match(r"^chapter\s+", lower):
        return SectionKind.CHAPTER
    if lower in FRONT_MATTER_TITLES or (
        GENERIC_HEADING_RE.match(normalized)
        and normalized not in BACK_MATTER
    ):
        return SectionKind.FRONT_MATTER
    if normalized in BACK_MATTER or lower in {b.lower() for b in BACK_MATTER}:
        return SectionKind.BACK_MATTER
    if lower in {"title", "title page"} or normalized.startswith("#"):
        return SectionKind.TITLE
    return SectionKind.OTHER


def _norm_title_text(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _collapse_title_sections(
    title_sections: list[BookSection], book_title: str,
) -> tuple[list[BookSection], list[BookSection]]:
    """Collapse repeated/near-duplicate title blocks into a single spoken title.

    Scanned PDFs routinely repeat the title page two or three times (cover,
    half-title, title page), which made the narrator read the title several
    times. Returns ``(kept_titles, demoted)`` where ``demoted`` are over-long
    title-like blocks pushed to front matter (off by default) rather than read
    as the title.
    """
    if len(title_sections) <= 1:
        return title_sections, []

    seen: set[str] = set()
    unique: list[BookSection] = []
    for section in title_sections:
        key = _norm_title_text(section.text)
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(section)
    if not unique:
        return title_sections[:1], []

    short = [s for s in unique if len(s.text.strip()) <= 200]
    demoted: list[BookSection] = []
    for section in unique:
        if section not in short:
            section.kind = SectionKind.FRONT_MATTER
            demoted.append(section)
    if not short:
        keep = unique[0]
        keep.kind = SectionKind.TITLE
        return [keep], unique[1:]

    book_norm = _norm_title_text(book_title)
    short.sort(
        key=lambda s: 0
        if book_norm and (book_norm in _norm_title_text(s.text) or _norm_title_text(s.text) in book_norm)
        else 1
    )
    keep = short[0]
    keep.title = "Title"
    keep.text = ". ".join(s.text.strip().rstrip(".") for s in short if s.text.strip())
    return [keep], demoted


def _unique_id(title: str, existing: set[str]) -> str:
    base = chapter_slug(title) or "section"
    candidate = base
    n = 2
    while candidate in existing:
        candidate = f"{base}-{n}"
        n += 1
    existing.add(candidate)
    return candidate


def _split_markdown_blocks(markdown: str) -> list[tuple[str, str]]:
    """Return (heading, body) pairs. Heading may be empty for preamble."""
    blocks: list[tuple[str, str]] = []
    current_title = ""
    current_lines: list[str] = []

    for line in markdown.splitlines():
        if line.startswith("# "):
            if current_title or current_lines:
                blocks.append((current_title, "\n".join(current_lines).strip()))
            current_title = line[2:].strip()
            current_lines = []
            continue
        if line.startswith("## "):
            if current_title or current_lines:
                blocks.append((current_title, "\n".join(current_lines).strip()))
            current_title = line[3:].strip()
            current_lines = []
            continue
        current_lines.append(line)

    if current_title or current_lines:
        blocks.append((current_title, "\n".join(current_lines).strip()))
    return blocks


def _detect_title_author(markdown: str) -> tuple[str, str | None]:
    title = "Untitled"
    author: str | None = None
    for line in markdown.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("# "):
            return stripped[2:].strip(), author
        if title == "Untitled":
            title = stripped.lstrip("#").strip()
            continue
        if (
            author is None
            and stripped == stripped.upper()
            and 2 <= len(stripped.split()) <= 4
            and len(stripped) <= 40
        ):
            author = stripped
            break
        break
    return title, author


def parse_book_sections(markdown: str) -> BookManifest:
    """
    Parse novelflow readable markdown into ordered audiobook sections.

    Order: title → front matter (dedication, …) → chapters → back matter.
    Inserts a spoken title section when the book title is known.
    """
    book_title, author = _detect_title_author(markdown)
    blocks = _split_markdown_blocks(markdown)
    raw_sections: list[BookSection] = []
    seen_ids: set[str] = set()
    order = 0

    for heading, body in blocks:
        title = heading.strip() or book_title
        if NAVIGATION_RE.match(title) or title.lower() == "navigation":
            continue
        if not heading and not body.strip():
            continue

        kind = _classify_section(title if heading else book_title)
        if heading and (heading == book_title or title == book_title):
            kind = SectionKind.TITLE
        if not heading and kind == SectionKind.OTHER and body:
            kind = SectionKind.TITLE

        speech = _strip_markdown_for_tts(body)
        if not speech and heading:
            speech = title

        section_title = title if heading else book_title
        section_id = _unique_id(section_title, seen_ids)
        raw_sections.append(
            BookSection(
                id=section_id,
                title=section_title,
                kind=kind,
                text=speech,
                enabled=True,
                order=order,
            )
        )
        order += 1

    if not raw_sections:
        raw_sections.append(
            BookSection(
                id="full-text",
                title=book_title,
                kind=SectionKind.OTHER,
                text=_strip_markdown_for_tts(markdown),
                enabled=True,
                order=0,
            )
        )

    has_title = any(
        s.kind == SectionKind.TITLE or s.title == book_title for s in raw_sections
    )
    sections: list[BookSection] = []

    if not has_title:
        intro = book_title
        if author:
            intro = f"{book_title}, by {author}"
        sections.append(
            BookSection(
                id=_unique_id("title-page", seen_ids),
                title="Title",
                kind=SectionKind.TITLE,
                text=intro,
                enabled=True,
                order=0,
            )
        )

    front: list[BookSection] = []
    chapters: list[BookSection] = []
    back: list[BookSection] = []
    other: list[BookSection] = []

    for section in raw_sections:
        if section.kind == SectionKind.TITLE:
            sections.append(section)
        elif section.kind == SectionKind.FRONT_MATTER:
            front.append(section)
        elif section.kind == SectionKind.CHAPTER:
            chapters.append(section)
        elif section.kind == SectionKind.BACK_MATTER:
            back.append(section)
        else:
            other.append(section)

    sections, demoted_titles = _collapse_title_sections(sections, book_title)
    front = demoted_titles + front

    ordered = sections + front + other + chapters + back
    for idx, section in enumerate(ordered):
        section.order = idx
    return BookManifest(
        book_title=book_title,
        author=author,
        source_markdown=markdown,
        sections=ordered,
    )


def apply_section_filter(manifest: BookManifest, disabled_ids: set[str]) -> BookManifest:
    """Return a copy with selected sections disabled (for in-app pruning)."""
    sections = [
        BookSection(
            id=s.id,
            title=s.title,
            kind=s.kind,
            text=s.text,
            enabled=s.id not in disabled_ids,
            order=s.order,
        )
        for s in manifest.sections
    ]
    return BookManifest(
        book_title=manifest.book_title,
        author=manifest.author,
        source_markdown=manifest.source_markdown,
        sections=sections,
        version=manifest.version,
    )


def default_audiobook_disabled_ids(manifest: BookManifest) -> set[str]:
    """Section ids skipped by default — only title + chapters are included."""
    return {
        s.id
        for s in manifest.sections
        if s.kind not in (SectionKind.TITLE, SectionKind.CHAPTER)
    }


def apply_default_audiobook_filter(
    manifest: BookManifest,
    *,
    chapters_and_title_only: bool = True,
) -> BookManifest:
    if not chapters_and_title_only:
        return manifest
    return apply_section_filter(manifest, default_audiobook_disabled_ids(manifest))

