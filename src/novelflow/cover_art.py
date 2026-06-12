"""Discover and load audiobook cover images (PNG, JPG, …)."""

from __future__ import annotations

import re
import tkinter as tk
from pathlib import Path

import pymupdf

COVER_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp", ".gif")
_MD_IMAGE_RE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")
_COVER_PHOTO_CACHE: dict[tuple[str, int], tk.PhotoImage] = {}


def clear_cover_photo_cache() -> None:
    """Drop cached cover images (e.g. after switching books)."""
    _COVER_PHOTO_CACHE.clear()


def is_cover_image(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in COVER_EXTENSIONS


def _cover_search_region(markdown: str, *, max_lines: int = 120) -> str:
    from novelflow.refine import CHAPTER_RE

    region: list[str] = []
    for i, line in enumerate(markdown.splitlines()):
        if i >= max_lines:
            break
        stripped = line.strip()
        if stripped.startswith("## "):
            heading = stripped[3:].strip()
            if CHAPTER_RE.match(heading) or re.match(r"^chapter\s+", heading, re.I):
                break
        region.append(line)
    return "\n".join(region)


def _resolve_markdown_image_path(markdown_dir: Path, ref: str) -> Path | None:
    ref = ref.strip().strip("\"'")
    if Path(ref).suffix.lower() not in COVER_EXTENSIONS:
        return None
    candidate = (markdown_dir / ref).resolve()
    return candidate if is_cover_image(candidate) else None


def _audiobook_stems(audiobook_path: Path) -> list[str]:
    stem = audiobook_path.stem
    stems = [stem]
    if ".audiobook" in stem:
        stems.append(stem.split(".audiobook", 1)[0])
    for suffix in (".readable",):
        if stem.endswith(suffix):
            stems.append(stem[: -len(suffix)])
    seen: set[str] = set()
    ordered: list[str] = []
    for item in stems:
        if item and item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered


def _co_located_cover_names(stems: list[str]) -> list[str]:
    names: list[str] = []
    for stem in stems:
        for ext in COVER_EXTENSIONS:
            names.append(f"{stem}.cover{ext}")
        for ext in COVER_EXTENSIONS:
            names.append(f"{stem}{ext}")
        names.append(f"{stem}.cover.png")
    for ext in COVER_EXTENSIONS:
        names.append(f"cover{ext}")
    return names


def find_cover_in_markdown(markdown_path: Path) -> Path | None:
    """PNG/JPG referenced on the title page, or a co-located ``*.cover.*`` export."""
    path = Path(markdown_path).resolve()
    if not path.is_file():
        return None

    markdown = path.read_text(encoding="utf-8")
    for match in _MD_IMAGE_RE.finditer(_cover_search_region(markdown)):
        resolved = _resolve_markdown_image_path(path.parent, match.group(1))
        if resolved is not None:
            return resolved

    stems = _audiobook_stems(path)
    for name in _co_located_cover_names(stems):
        candidate = path.parent / name
        if is_cover_image(candidate):
            return candidate.resolve()
    return None


def find_cover_for_audiobook(
    audiobook_path: Path,
    *,
    markdown_path: Path | None = None,
) -> Path | None:
    """Best cover for an audiobook file — markdown ref, co-located art, or folder scan."""
    audio = Path(audiobook_path).resolve()
    if not audio.is_file():
        return None

    if markdown_path is not None:
        found = find_cover_in_markdown(markdown_path)
        if found is not None:
            return found

    folder = audio.parent
    for name in _co_located_cover_names(_audiobook_stems(audio)):
        candidate = folder / name
        if is_cover_image(candidate):
            return candidate.resolve()

    if markdown_path is not None and markdown_path.parent != folder:
        for name in _co_located_cover_names(_audiobook_stems(markdown_path)):
            candidate = markdown_path.parent / name
            if is_cover_image(candidate):
                return candidate.resolve()

    return None


def load_cover_photo(path: Path, *, max_size: int, master: tk.Misc | None = None) -> tk.PhotoImage | None:
    """Load a cover as ``PhotoImage``, subsampling to fit ``max_size`` (supports JPG via PyMuPDF).

    Results are cached by ``(path, max_size)`` so focus/resize events do not reload from disk.
    """
    src = Path(path).resolve()
    if not is_cover_image(src):
        return None

    cache_key = (str(src), max_size)
    cached = _COVER_PHOTO_CACHE.get(cache_key)
    if cached is not None:
        return cached

    photo: tk.PhotoImage | None = None
    if src.suffix.lower() in (".png", ".gif"):
        try:
            photo = tk.PhotoImage(file=str(src), master=master)
        except tk.TclError:
            photo = None

    if photo is None:
        try:
            doc = pymupdf.open(str(src))
            try:
                pix = doc[0].get_pixmap()
                if pix.alpha:
                    pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
                png_bytes = pix.tobytes("png")
            finally:
                doc.close()
            photo = tk.PhotoImage(data=png_bytes, master=master)
        except (OSError, RuntimeError, tk.TclError, ValueError):
            return None

    width, height = photo.width(), photo.height()
    if width > max_size or height > max_size:
        factor = max((width + max_size - 1) // max_size, (height + max_size - 1) // max_size, 1)
        photo = photo.subsample(factor)
    _COVER_PHOTO_CACHE[cache_key] = photo
    return photo
