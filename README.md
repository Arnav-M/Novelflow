# Novelflow

**PDF → readable markdown in one command.**

Novelflow wraps [Microsoft markitdown](https://github.com/microsoft/markitdown) and post-processes the output so book PDFs become actually readable: proper paragraphs, foldable chapter headings, scene headers, navigation links, and common OCR fixes.

No manual two-step pipeline. No GPU. No API keys.

## Install

```bash
cd novelflow
pip install -e .
```

Requires Python 3.10+.

## Usage

```bash
novelflow "path/to/book.pdf"
```

Output: `book.readable.md` in the same folder.

```bash
novelflow book.pdf -o book.md
novelflow book.pdf --keep-raw   # also saves book.raw.md (markitdown before cleanup)
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

| Problem (raw markitdown) | After novelflow |
|--------------------------|-----------------|
| One line per PDF row | Full paragraphs with `\n\n` spacing |
| Page breaks mid-sentence | Merged across breaks |
| `crystal-\nclear` | `crystal-clear` |
| Plain `Chapter One` | `## Chapter One` (foldable in VS Code/Obsidian) |
| Location/time lines merged into prose | Italic scene headers |
| TOC vs story chapters confused | Auto-detected |
| `ZoA"` encoding glitches | Generic accent repair |

## Pipeline

```
PDF  →  markitdown (extract)  →  novelflow refine  →  .readable.md
```

## License

MIT
