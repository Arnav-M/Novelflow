# Novelflow

**PDF → readable markdown → chapter-marked audiobook.**

Novelflow extracts text with [PyMuPDF](https://pymupdf.readthedocs.io/) and post-processes it so fiction PDFs become actually readable: proper paragraphs, foldable chapter headings, scene headers, navigation links, and common glyph fixes.

Optionally builds a **local audiobook** (M4B/MP3) with navigable section markers — title, dedication, chapters, acknowledgements, and more.

No manual pipeline. No upload. No page limits.

## Install (end users)

Download **`Novelflow-Setup.exe`** from [GitHub Releases](https://github.com/Arnav-M/Novelflow/releases) and run the wizard. No Python required.

For audiobooks, install [ffmpeg](https://ffmpeg.org/) and add it to your PATH.

## Install (developers)

```bash
git clone https://github.com/Arnav-M/Novelflow.git
cd Novelflow
pip install -e ".[audiobook,dev]"
```

Requires Python 3.10+.

## Usage (CLI)

```bash
# Markdown only
novelflow "book.pdf"

# Markdown + audiobook (auto engine — Kokoro on GPU, else parallel Edge)
novelflow "book.pdf" --audiobook

# Include dedication, acknowledgements, etc.
novelflow "book.pdf" --audiobook --all-sections

# Audiobook from existing markdown
novelflow book.readable.md --from-markdown --audiobook

# List voices
novelflow --list-voices --tts-engine edge
novelflow --list-voices --tts-engine kokoro
```

Output:
- `book.readable.md` — cleaned markdown
- `book.audiobook.m4b` — audiobook with chapter markers
- `book.audiobook.manifest.json` — section timestamps for in-app skip (future UI)

## Audiobook sections

By default only **title + chapters** are synthesized (skips Contents, Dedication, Acknowledgements, etc.).

Use the **Audiobook settings** tab in the GUI to enable extra sections, or:

```bash
novelflow book.pdf --audiobook --all-sections
```

Section markers are saved in `.manifest.json` with `start_ms` / `end_ms` for in-app skip.

## TTS engines

| Engine | When used | Speed |
|--------|-----------|--------|
| **auto** (default) | Kokoro if GPU/DirectML detected, else Edge | Best for your PC |
| **edge** | Online, 6 parallel chunks × 4 parallel sections | ~2–4× faster than before |
| **kokoro** | Offline; WAV batched, one MP3 encode per section | Fastest with NVIDIA/DirectML GPU |

## GUI

Run `novelflow-gui` — check **Also create chapter-marked audiobook** on the Convert tab, then open **Audiobook settings** for engine, voice, and section pickers.

## Test sample PDFs

Local fiction PDFs live in `tests/fixtures/pdfs/`:

- `the-mozart-conspiracy.pdf` — long thriller (~70 chapters)
- `doomsday-prophecy.pdf` — long thriller with dedication, contents, acknowledgements

Run tests (regenerates `.readable.md` outputs):

```bash
python -m pytest tests/test_integration_pdfs.py -v
```

Optional Gutenberg downloads (if you want more samples):

```bash
python scripts/download_sample_pdfs.py
```

## Pipeline

```
PDF  →  PyMuPDF  →  novelflow refine  →  .readable.md  →  TTS  →  .audiobook.m4b
                                              ↓
                                    .manifest.json (section markers)
```

## License

MIT
