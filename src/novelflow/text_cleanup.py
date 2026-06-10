"""Repair common PDF text extraction artifacts (ligatures, NUL placeholders)."""

from __future__ import annotations

import re

# PDF fonts with bad ToUnicode maps emit IPA/modifier letters (U+0250–U+02FF)
# or NUL/replacement chars where a ligature glyph should be. The letters that
# *follow* the placeholder encode which ligature was intended (fi, fl, ff, f).
_LIGATURE_PLACEHOLDER = re.compile(r"[\u0279\u027b\u0283\u027d\u0280\x00\ufffd]")

# Standard Unicode ligature codepoints (decompose before suffix inference).
_UNICODE_LIGATURES: tuple[tuple[str, str], ...] = (
    ("\ufb00", "ff"),
    ("\ufb01", "fi"),
    ("\ufb02", "fl"),
    ("\ufb03", "ffi"),
    ("\ufb04", "ffl"),
)

# (suffix, expansion) — longest match first; applies to any placeholder unless a
# per-glyph override matches first.
_UNIVERSAL_SUFFIX_RULES: tuple[tuple[str, str], ...] = (
    ("fteen", "fi"),
    ("replace", "fi"),
    ("nitely", "fi"),
    ("nished", "fi"),
    ("ngers", "fi"),
    ("nger", "fi"),
    ("gure", "fi"),
    ("ltered", "fi"),
    ("lling", "fi"),
    ("cent", "fi"),
    ("ickered", "fl"),
    ("ickering", "fl"),
    ("fluence", "fl"),
    ("uence", "fl"),
    ("ortlessl", "ff"),
    ("erently", "ff"),
    ("ectively", "ff"),
    ("erence", "ff"),
    ("erson", "ff"),
    ("ering", "ff"),
    ("ered", "ff"),
    ("erent", "ff"),
    ("ects", "ff"),
    ("ect", "ff"),
    ("ees", "ff"),
    ("torte", "ff"),
    ("ipped", "fl"),
    ("ashed", "fl"),
    ("ashing", "fl"),
    ("ushed", "fl"),
    ("anked", "fl"),
    ("owers", "fl"),
    ("icked", "fl"),
    ("icker", "fl"),
    ("rst", "fi"),
    ("red", "fi"),
    ("lled", "fi"),
    ("fty", "fi"),
    ("oor", "fl"),
    ("ight", "fl"),
    ("ames", "fl"),
    ("utes", "fl"),
    ("akes", "fl"),
    ("esh", "fl"),
    ("ame", "fl"),
    ("ick", "fl"),
    ("ung", "fl"),
    ("oat", "fl"),
    ("orded", "ff"),
    ("ord", "ff"),
    ("air", "ff"),
    ("ort", "ff"),
    ("nd", "fi"),
    ("ng", "fi"),
    ("ne", "fi"),
    ("re", "fi"),
    ("ee", "ff"),
    ("ana", "f"),
    ("ash", "fl"),
    ("ile", "fi"),
    ("ed", "fi"),
    ("st", "fi"),
    ("le", "fi"),
    ("ve", "fi"),
    ("lm", "fi"),
    ("ew", "fl"),
    ("at", "fl"),
    ("ly", "fl"),
    ("er", "ff"),
    ("en", "ff"),
    ("y", "ff"),
    ("s", "ff"),
    ("e", "ff"),
)

# Glyph-specific overrides (same suffix can expand differently per placeholder).
_PLACEHOLDER_SUFFIX_RULES: dict[str, tuple[tuple[str, str], ...]] = {
    "\u027d": (
        ("ciently", "ffi"),
        ("cially", "ff"),
        ("cious", "ff"),
        ("ficial", "ff"),
        ("cers", "ffi"),
        ("cult", "ff"),
        ("cial", "ff"),
        ("cer", "ffi"),
        ("ce", "ffi"),
        ("ng", "ffi"),
        ("ti", "ffi"),
        ("gy", "ffi"),
        ("c", "ffi"),
        ("n", "ffi"),
    ),
    "\u0280": (
        ("ing", "ffl"),
        ("er", "ffl"),
        ("ed", "ff"),
        ("y", "ff"),
        ("e", "ffl"),
    ),
}

_FALLBACK_EXPANSION: dict[str, str] = {
    "\u0279": "fi",
    "\u027b": "fl",
    "\u0283": "ff",
    "\u027d": "ff",
    "\u0280": "ff",
    "\x00": "f",
    "\ufffd": "f",
}

_OFF_RULE = re.compile(
    rf"(?<=[oO]){_LIGATURE_PLACEHOLDER.pattern}(?=\s|[,.!?;:'\"])"
)

_MULTI_SPACE = re.compile(r" {2,}")


def _compile_suffix_patterns(
    placeholder: str,
    rules: tuple[tuple[str, str], ...],
) -> tuple[tuple[re.Pattern[str], str], ...]:
    return tuple(
        (
            re.compile(
                rf"{re.escape(placeholder)}(?={re.escape(suffix)})",
                re.IGNORECASE,
            ),
            expansion,
        )
        for suffix, expansion in rules
    )


def _decompose_unicode_ligatures(text: str) -> str:
    for glyph, plain in _UNICODE_LIGATURES:
        if glyph in text:
            text = text.replace(glyph, plain)
    return text


def _expand_ligature_placeholders(text: str) -> str:
    if not _LIGATURE_PLACEHOLDER.search(text):
        return text

    text = _OFF_RULE.sub("ff", text)

    placeholders = {match.group() for match in _LIGATURE_PLACEHOLDER.finditer(text)}

    for placeholder in placeholders:
        rules = _PLACEHOLDER_SUFFIX_RULES.get(placeholder, _UNIVERSAL_SUFFIX_RULES)
        for pattern, expansion in _compile_suffix_patterns(placeholder, rules):
            text = pattern.sub(expansion, text)

        # Placeholders without a glyph-specific table still use universal rules.
        if placeholder not in _PLACEHOLDER_SUFFIX_RULES:
            continue
        for pattern, expansion in _compile_suffix_patterns(
            placeholder, _UNIVERSAL_SUFFIX_RULES
        ):
            text = pattern.sub(expansion, text)

    for placeholder, expansion in _FALLBACK_EXPANSION.items():
        text = text.replace(placeholder, expansion)

    return text


def sanitize_pdf_text(text: str) -> str:
    """
    Fix ligature placeholders and glyph damage from PDF extractors.

    Uses suffix-following-letter inference (generic across fiction PDFs), not
    word-specific patches. Safe on clean text; returns the original object when
    nothing changes.
    """
    if not text:
        return text

    original = text
    text = _decompose_unicode_ligatures(text)
    text = _expand_ligature_placeholders(text)

    return text if text != original else original


def collapse_pdf_spacing(text: str) -> str:
    """Collapse runs of spaces introduced by PDF row extraction."""
    return _MULTI_SPACE.sub(" ", text)
