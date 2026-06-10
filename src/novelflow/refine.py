"""Turn raw markitdown output into readable fiction markdown."""

import re

CHAPTER_RE = re.compile(
    r"^(?:Chapter|Part)\s+[\w-]+$|^(?:Prologue|Epilogue|Interlude)$"
    r"|^Book\s+(?:One|Two|Three|Four|Five|Six|Seven|Eight|Nine|Ten|"
    r"Eleven|Twelve|Thirteen|Fourteen|Fifteen|Sixteen|Seventeen|Eighteen|"
    r"Nineteen|Twenty|Thirty|Forty|Fifty|Sixty|Seventy|Eighty|Ninety|"
    r"Hundred|\d+|[IVXLC]+)$",
    re.I,
)
GENERIC_HEADING_RE = re.compile(
    r"^(Contents|Title Page|Dedication|Epigraph|Book Jacket|SUMMARY:|Rating:|"
    r"Author's Note|Acknowledgements|Preview|About the Author|Also by .+|"
    r"By The Same Author:?|Copyright|About the Publisher)$",
    re.I,
)
SENTENCE_END = re.compile(r'[.!?]["\')\]]*$')
TIME_LINE = re.compile(
    r"^.{0,40}\b\d{1,2}([.:]\d{2})?\s*(a\.m\.|p\.m\.|am|pm)\b.{0,25}$", re.I
)

SCENE_HEADER_MAX_LEN = 55
SCENE_HEADER_SLOTS = 5

MOJIBAKE_RE = re.compile(r"(?<=[a-z])A([\"'^(~])")
MOJIBAKE_MAP = {'"': "ë", "'": "é", "^": "ê", "(": "è", "~": "ñ"}

LIGATURE_FIXES = [
    ("\ufb00", "ff"),
    ("\ufb01", "fi"),
    ("\ufb02", "fl"),
    ("\ufb03", "ffi"),
    ("\ufb04", "ffl"),
]


def detect_book_identity(lines: list[str]) -> tuple[str | None, str | None]:
    title = None
    author = None
    for line in lines[:60]:
        stripped = line.strip()
        if not stripped:
            continue
        if title is None:
            title = stripped
            continue
        if (
            author is None
            and stripped == stripped.upper()
            and 2 <= len(stripped.split()) <= 4
            and len(stripped) <= 40
            and stripped.replace(" ", "").replace(".", "").isalpha()
        ):
            author = stripped
    return title, author


def find_body_start(lines: list[str]) -> int:
    back_matter = {
        "Author's Note", "Acknowledgements", "Preview", "About the Author",
        "Copyright", "About the Publisher", "By The Same Author:",
    }
    for i, line in enumerate(lines):
        if not CHAPTER_RE.match(line.strip()):
            continue
        following = [l.strip() for l in lines[i + 1 : i + 6] if l.strip()]
        if not following:
            continue
        if any(CHAPTER_RE.match(f) for f in following):
            continue
        if following[0] in back_matter or GENERIC_HEADING_RE.match(following[0]):
            continue
        return i
    return 0


def ends_sentence(line: str) -> bool:
    return bool(SENTENCE_END.search(line))


def starts_new_paragraph(line: str) -> bool:
    if not line:
        return False
    return line[0].isupper() or line[0] in "\"'‘"


def is_scene_header(line: str) -> bool:
    if not line or len(line) > SCENE_HEADER_MAX_LEN:
        return False
    if line[0].islower():
        return False
    if TIME_LINE.match(line):
        return True
    return not ends_sentence(line)


def fix_ocr(text: str) -> str:
    for old, new in LIGATURE_FIXES:
        text = text.replace(old, new)
    return MOJIBAKE_RE.sub(lambda m: MOJIBAKE_MAP[m.group(1)], text)


def merge_block(lines: list[str]) -> str:
    if not lines:
        return ""
    merged = lines[0]
    for nxt in lines[1:]:
        if merged.endswith("-") and not merged.endswith(" -"):
            merged = merged + nxt
        else:
            merged = f"{merged} {nxt}"
    return merged


def chapter_slug(title: str) -> str:
    slug = title.lower()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"\s+", "-", slug.strip())
    return slug


def build_navigation_toc(chapters: list[str]) -> str:
    lines = [
        "## Navigation",
        "",
        "Jump to any chapter below, or use **Ctrl+Shift+O** / the **Outline** panel. "
        "Fold chapters with the gutter arrow next to each `##` heading.",
        "",
    ]
    for ch in chapters:
        lines.append(f"- [{ch}](#{chapter_slug(ch)})")
    return "\n".join(lines)


def refine_markdown(text: str) -> str:
    """Post-process raw markitdown text into readable fiction markdown."""
    lines = text.splitlines()
    title, author = detect_book_identity(lines)
    body_start = find_body_start(lines)

    def is_heading(line: str, in_front_matter: bool) -> bool:
        if GENERIC_HEADING_RE.match(line):
            return True
        if title and line == title:
            return True
        if author and line == author:
            return True
        if in_front_matter and re.match(r"^For [A-Z][\w' ]+$", line) and len(line) <= 50:
            return True
        return False

    paragraphs: list[str] = []
    block: list[str] = []
    scene_slots = 0
    story_chapters: list[str] = []
    story_start_idx: int | None = None

    def flush() -> None:
        if block:
            paragraphs.append(merge_block(block))
            block.clear()

    for idx, raw in enumerate(lines):
        stripped = raw.strip()
        in_front_matter = idx < body_start

        if not stripped:
            if block and ends_sentence(block[-1]):
                flush()
            continue

        if CHAPTER_RE.match(stripped):
            flush()
            if in_front_matter:
                paragraphs.append(f"**{stripped}**")
                scene_slots = 0
            else:
                if story_start_idx is None:
                    story_start_idx = len(paragraphs)
                story_chapters.append(stripped)
                paragraphs.append(f"## {stripped}")
                scene_slots = SCENE_HEADER_SLOTS
            continue

        if is_heading(stripped, in_front_matter):
            flush()
            paragraphs.append(stripped)
            scene_slots = 0
            continue

        if scene_slots > 0 and is_scene_header(stripped):
            flush()
            paragraphs.append(f"*{stripped}*")
            scene_slots -= 1
            continue

        scene_slots = 0

        if block and ends_sentence(block[-1]) and starts_new_paragraph(stripped):
            flush()

        block.append(stripped)

    flush()

    if story_chapters and story_start_idx is not None:
        paragraphs.insert(story_start_idx, build_navigation_toc(story_chapters))

    return fix_ocr("\n\n".join(paragraphs) + "\n")
