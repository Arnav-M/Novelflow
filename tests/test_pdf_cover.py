"""Tests for first-page cover extraction."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from novelflow.pdf_extract import extract_first_page_cover_image


def test_extract_first_page_cover_image_saves_png(tmp_path: Path):
    pdf = tmp_path / "book.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    out = tmp_path / "book.readable.cover.png"

    mock_pix = MagicMock()
    mock_pix.n = 3
    mock_pix.alpha = 0

    mock_page = MagicMock()
    mock_page.get_images.return_value = [(42, 0, 200, 300, 8, "DeviceRGB", "", "img", "")]

    mock_doc = MagicMock()
    mock_doc.page_count = 1
    mock_doc.__getitem__.return_value = mock_page

    with (
        patch("novelflow.pdf_extract.pymupdf.open", return_value=mock_doc),
        patch("novelflow.pdf_extract.pymupdf.Pixmap", return_value=mock_pix),
    ):
        result = extract_first_page_cover_image(pdf, out)

    assert result == out
    mock_pix.save.assert_called_once_with(str(out))
