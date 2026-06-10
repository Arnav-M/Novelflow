# Novelflow

**PDF → readable markdown in one command.**

Novelflow extracts text with [PyMuPDF](https://pymupdf.readthedocs.io/) and post-processes it so fiction PDFs become actually readable: proper paragraphs, foldable chapter headings, scene headers, navigation links, and common glyph fixes.

No manual two-step pipeline. No GPU. No API keys.

## Install

```bash
git clone https://github.com/Arnav-M/Novelflow.git
cd novelflow
pip install -e .
```

Re-run `pip install -e .` whenever you **move** this folder — otherwise `novelflow-gui` will break.

Requires Python 3.10+.

## Install (end users)

Download **`Novelflow-Setup.exe`** from [GitHub Releases](https://github.com/Arnav-M/Novelflow/releases) and run the wizard. No Python or PowerShell required.

Creates a Start menu shortcut and optional desktop icon. Uninstall via Windows Settings → Apps.

## Build the installer (maintainers)

Double-click **`build_installer.bat`** (or run from cmd). One-time prerequisites:

1. [Python 3.10+](https://python.org)
2. [Inno Setup 6](https://jrsoftware.org/isdl.php) (free) — only needed to create the setup wizard

Output: `installer\output\Novelflow-Setup.exe` — upload that to GitHub Releases.

## GUI (developers)

After `pip install -e .`: run `novelflow-gui` or `python -m novelflow.gui`.

Dark-themed desktop UI with gradient header, progress bar, and success pulse. Pick a PDF, optional output path, click **Convert**. Shortcuts: `Ctrl+Enter` = convert, `Ctrl+L` = clear log.

## Usage (CLI)

```bash
novelflow "path/to/book.pdf"
```

Output: `book.readable.md` in the same folder.

```bash
novelflow book.pdf -o book.md
novelflow book.pdf --keep-raw   # also saves book.raw.md (extracted text before cleanup)
```

Or as a module:

```bash
python -m novelflow book.pdf
```

## Python API

```python
from novelflow import convert_pdf

convert_pdf("book.pdf")
convert_pdf("book.pdf", output_path="book.md", keep_raw=True)
```

## What it fixes

| Problem (raw PDF text) | After novelflow |
|--------------------------|-----------------|
| One line per PDF row | Full paragraphs with `\n\n` spacing |
| Page breaks mid-sentence | Merged across breaks |
| `crystal-\nclear` | `crystal-clear` |
| Plain `Chapter One` | `## Chapter One` (foldable in VS Code/Obsidian) |
| Location/time lines merged into prose | Italic scene headers |
| Italic PDF fonts lost in plain extract | PyMuPDF font scan + italic hints |
| Pipe-table garbage (`\| word \| word \|`) | Flattened back to prose |
| Merged headers (`June 2008The first day`) | Split into separate lines |
| TOC vs story chapters confused | Auto-detected |
| `ZoA"` encoding glitches | Generic accent repair |
| Missing `f` ligatures (`toʃana`, NUL bytes) | Normalized to `tofana` |

## Pipeline

```
PDF  →  PyMuPDF (extract)  →  novelflow refine  →  .readable.md
```

## Why PyMuPDF?

Novelflow targets **fiction novels**, not scanned academic papers. On a real HarperCollins thriller (~600k chars):

| Extractor | Time | NUL bytes | Dropped letters | Italic hints |
|-----------|------|-----------|-----------------|--------------|
| **PyMuPDF** | **0.4s** | **0** | **No** | **217 lines** |
| pypdfium2 | 1.1s | 0 | Yes (`toana`) | — |
| pymupdf4llm | 65s | 0 | Partial | Markdown headers |
| markitdown | 80s | 1,541 | NUL placeholders | 0 (pdfminer) |

Heavier tools ([Marker](https://github.com/VikParuchuri/marker), [MinerU](https://github.com/opendatalab/MinerU), [Docling](https://github.com/docling-project/docling)) excel on complex layouts and tables but need PyTorch/GPU and are overkill for prose fiction.

## License

MIT
