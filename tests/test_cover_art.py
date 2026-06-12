"""Tests for cover art discovery and loading."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from novelflow.cover_art import find_cover_for_audiobook, find_cover_in_markdown, load_cover_photo


def test_find_cover_in_markdown_jpg(tmp_path: Path):
    cover = tmp_path / "front.jpg"
    cover.write_bytes(b"\xff\xd8\xff" + b"\x00" * 32)
    md = tmp_path / "book.readable.md"
    md.write_text("# Book\n\n![Cover](front.jpg)\n\n## Chapter One\n\nHi.\n", encoding="utf-8")
    assert find_cover_in_markdown(md) == cover.resolve()


def test_find_cover_for_audiobook_colocated_jpg(tmp_path: Path):
    audio = tmp_path / "novel.audiobook.m4b"
    audio.write_bytes(b"audio")
    cover = tmp_path / "novel.cover.jpg"
    cover.write_bytes(b"\xff\xd8\xff" + b"\x00" * 32)
    assert find_cover_for_audiobook(audio) == cover.resolve()


def test_load_cover_photo_png(tmp_path: Path):
    import tkinter as tk

    cover = tmp_path / "cover.png"
    # Minimal valid 1x1 PNG
    cover.write_bytes(
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
        b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
        b"\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4"
        b"\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    root = tk.Tk()
    root.withdraw()
    try:
        photo = load_cover_photo(cover, max_size=48, master=root)
        assert photo is not None
        assert photo.width() >= 1
    finally:
        root.destroy()


def test_load_cover_photo_jpg_via_pymupdf(tmp_path: Path):
    import tkinter as tk

    cover = tmp_path / "cover.jpg"
    cover.write_bytes(b"\xff\xd8\xff" + b"\x00" * 32)
    mock_pix = MagicMock()
    mock_pix.alpha = 0
    mock_pix.tobytes.return_value = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
        b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
        b"\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4"
        b"\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    mock_doc = MagicMock()
    mock_doc.__getitem__.return_value.get_pixmap.return_value = mock_pix
    root = tk.Tk()
    root.withdraw()
    try:
        with patch("novelflow.cover_art.pymupdf.open", return_value=mock_doc):
            photo = load_cover_photo(cover, max_size=48, master=root)
        assert photo is not None
    finally:
        root.destroy()
