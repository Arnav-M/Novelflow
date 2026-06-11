"""Turn raw PDF text into readable fiction markdown."""

import re

from novelflow.text_cleanup import collapse_pdf_spacing, sanitize_pdf_text

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
    r"^.{0,40}\d{1,2}(?:[.:]\d{2})?\s*(?:a\.m\.|p\.m\.|am|pm)(?:\s+.{0,25})?$",
    re.I,
)

SCENE_HEADER_MAX_LEN = 72
SCENE_HEADER_SLOTS = 5
SCENE_HEADER_ITALIC_MAX_LEN = 45
SCENE_HEADER_ITALIC_MAX_WORDS = 6

_LOCATION_CONNECTORS = frozenset({
    "of", "over", "in", "near", "on", "the", "and", "de", "la", "le", "du", "des",
})
_PROSE_VERB = re.compile(
    r"\b(?:"
    r"gazed|walked|huddled|spent|locked|skidded|checked|waited|paced|drove|parked|"
    r"sat|watched|wedged|strode|switched|took|could|would|had|have|was|were|"
    r"is|are|been|being|felt|said|thought|knew|made|got|went|came|turned|looked|"
    r"heard|saw|found|began|started|tried|wanted|needed|seemed|appeared"
    r")\b",
    re.I,
)
_RELATIVE_TIME = re.compile(
    r"^(?:"
    r"(?:A few|Several|Many) (?:hours|days|weeks|months|years) (?:later|earlier)"
    r"|(?:\d+|One|Two|Three|Four|Five|Six|Seven|Eight|Nine|Ten|Eleven|Twelve|"
    r"Thirteen|Fourteen|Fifteen|Twenty|Thirty|Forty|Fifty) "
    r"(?:hours?|days?|weeks?|months?|years?) (?:later|earlier|ago)"
    r"|The (?:present day|same day|next day|following day|morning|afternoon|evening|night)"
    r"|That (?:morning|afternoon|evening|night|same day|day)"
    r"|(?:Earlier|Later) that (?:day|evening|morning|night|afternoon)"
    r"|Towards (?:dawn|dusk|noon|midnight)"
    r"|(?:Same|The same) (?:morning|afternoon|evening|night|day)"
    r")\s*$",
    re.I,
)
_INTERNAL_SENTENCE = re.compile(r'[.!?]["\')\]]*\s+\S')

MOJIBAKE_RE = re.compile(r"(?<=[a-z])A([\"'^(~])")
MOJIBAKE_MAP = {'"': "ë", "'": "é", "^": "ê", "(": "è", "~": "ñ"}

BACK_MATTER = frozenset({
    "Author's Note", "Acknowledgements", "Preview", "About the Author",
    "Copyright", "About the Publisher", "By The Same Author:",
})

MONTHS = (
    "January", "February", "March", "April", "May", "June", "July",
    "August", "September", "October", "November", "December",
)
MONTH_YEAR = re.compile(
    rf"^.+, .+, (?:{'|'.join(MONTHS)}) \d{{4}}$"
)
SHORT_MONTH_YEAR = re.compile(
    rf"^.+, (?:{'|'.join(MONTHS)}) \d{{4}}$"
)
_DATE_HEADER = re.compile(
    rf"^(?:\d{{1,2}}\s+)?(?:{'|'.join(MONTHS)})(?:\s+\d{{4}})?\s*$",
    re.I,
)

SCENE_HEADER_EXACT = tuple(
    re.compile(pattern, re.I)
    for pattern in (
        r"^The (?:first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth) day$",
        r"^That (?:morning|afternoon|evening|night|same day|day)$",
        r"^Near .+$",
        r"^Two minutes later\b.*$",
        r"^\d{1,2}\.\d{2}\s*(?:a\.m\.|p\.m\.).*$",
        r"^[^.!?]{2,50}, [^.!?]{0,45}\d{4}$",
    )
)

MERGED_HEADER_SPLIT = re.compile(
    r"(?<=\d{4})(?=The (?:first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth) day\b)",
    re.I,
)
MERGED_TIME_SPLIT = re.compile(
    r"(?<=[a-z])(?=\d{1,2}[.:]\d{2}\s*(?:a\.m\.|p\.m\.|am|pm)\b)",
    re.I,
)

PIPE_SEPARATOR_ROW = re.compile(r"\|\s*[-:]+\s*(\|\s*[-:]+\s*)+")
_MULTI_SPACE = re.compile(r" {2,}")


def normalize_line_key(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip())


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
    total = len(lines)
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or not CHAPTER_RE.match(stripped):
            continue
        following: list[str] = []
        for j in range(i + 1, min(i + 6, total)):
            next_line = lines[j].strip()
            if next_line:
                following.append(next_line)
        if not following:
            continue
        if any(CHAPTER_RE.match(item) for item in following):
            continue
        if following[0] in BACK_MATTER or GENERIC_HEADING_RE.match(following[0]):
            continue
        return i
    return 0


def ends_sentence(line: str) -> bool:
    return bool(SENTENCE_END.search(line))


def starts_new_paragraph(line: str) -> bool:
    if not line:
        return False
    return line[0].isupper() or line[0] in "\"'‘"


def deflatten_pipe_prose(line: str) -> str:
    """Repair pipe-table garbage from multi-column / italic PDF layouts."""
    if "|" not in line:
        return line
    if line.count("|") < 2:
        return line

    cleaned = PIPE_SEPARATOR_ROW.sub(" ", line)
    segments = cleaned.split("|")
    parts: list[str] = []
    for segment in segments:
        chunk = segment.strip()
        if not chunk or re.fullmatch(r"[-:\s]+", chunk):
            continue
        parts.append(chunk)

    if not parts:
        return line
    return _MULTI_SPACE.sub(" ", " ".join(parts)).strip()


def split_compound_line(line: str) -> list[str]:
    """Split merged scene-header lines (common when italics lose line breaks)."""
    pieces = [line]
    for pattern in (MERGED_HEADER_SPLIT, MERGED_TIME_SPLIT):
        expanded: list[str] = []
        for piece in pieces:
            expanded.extend(part for part in pattern.split(piece) if part.strip())
        pieces = expanded
    return pieces or [line]


def looks_like_prose_fragment(line: str) -> bool:
    """Reject mid-paragraph PDF row splits masquerading as scene headers."""
    if len(line) > 55 or len(line.split()) > 9:
        return True
    if _PROSE_VERB.search(line):
        return True
    if _INTERNAL_SENTENCE.search(line):
        return True
    return False


def looks_like_location(line: str) -> bool:
    words = line.rstrip(".,;:").split()
    if not words or len(words) > 8 or len(line) > 52:
        return False
    for word in words:
        clean = word.strip(".,;:'\"")
        if not clean:
            return False
        if clean.lower() in _LOCATION_CONNECTORS:
            continue
        if clean.isdigit():
            continue
        if not clean[0].isupper():
            return False
    return True


def is_scene_header(line: str, italic_hints: set[str] | None = None) -> bool:
    if not line or len(line) > SCENE_HEADER_MAX_LEN:
        return False
    if line[0].islower():
        return False

    key = normalize_line_key(line)

    if TIME_LINE.match(line):
        return True
    if looks_like_prose_fragment(line):
        return False
    if any(pattern.match(line) for pattern in SCENE_HEADER_EXACT):
        return True
    if MONTH_YEAR.match(line) or SHORT_MONTH_YEAR.match(line):
        return True
    if _DATE_HEADER.match(line):
        return True
    if _RELATIVE_TIME.match(line):
        return True
    if line.count(",") >= 1 and not ends_sentence(line) and len(line.split()) <= 10:
        return True
    if looks_like_location(line):
        return True

    # PDF italic font metadata: only trust short, header-like lines.
    if italic_hints and key in italic_hints:
        return (
            len(line) <= SCENE_HEADER_ITALIC_MAX_LEN
            and len(line.split()) <= SCENE_HEADER_ITALIC_MAX_WORDS
            and not ends_sentence(line)
            and not GENERIC_HEADING_RE.match(line)
        )

    return False


def fix_ocr(text: str) -> str:
    if "A" in text:
        text = MOJIBAKE_RE.sub(lambda m: MOJIBAKE_MAP[m.group(1)], text)
    return text


def preprocess_raw_line(line: str) -> list[str]:
    stripped = line.strip()
    if not stripped:
        return [""]
    stripped = sanitize_pdf_text(fix_ocr(deflatten_pipe_prose(stripped)))
    stripped = collapse_pdf_spacing(stripped)
    return split_compound_line(stripped) if stripped else [""]


def merge_block(lines: list[str]) -> str:
    if not lines:
        return ""
    chunks: list[str] = [lines[0]]
    for nxt in lines[1:]:
        current = chunks[-1]
        if current.endswith("-") and not current.endswith(" -"):
            chunks[-1] = current + nxt
        else:
            chunks.append(nxt)
    return " ".join(chunks)


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


def refine_markdown(text: str, *, italic_hints: set[str] | None = None) -> str:
    """Post-process raw PDF text into readable fiction markdown."""
    text = sanitize_pdf_text(text)
    preprocessed: list[str] = []
    for raw in text.splitlines():
        preprocessed.extend(preprocess_raw_line(raw))

    lines = preprocessed
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
            paragraphs.append(f"## {stripped}")
            scene_slots = 0
            continue

        if scene_slots > 0 and is_scene_header(stripped, italic_hints):
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

    output = paragraphs
    if title:
        header = [f"# {title}"]
        if author:
            header.append(f"*{author}*")
        output = header + output

    return "\n\n".join(output) + "\n"
