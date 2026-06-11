"""Optional: download extra public-domain PDFs from Project Gutenberg.

Primary test PDFs are the local files in tests/fixtures/pdfs/
(the-mozart-conspiracy.pdf, doomsday-prophecy.pdf).
"""

from __future__ import annotations

import urllib.request
from pathlib import Path

OPTIONAL_SAMPLES = {
    "alice.pdf": "http://www.gutenberg.org/cache/epub/11/pg11-images.pdf",
    "frankenstein.pdf": "http://www.gutenberg.org/cache/epub/84/pg84-images.pdf",
}

ROOT = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "pdfs"


def _download(url: str, dest: Path) -> None:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Novelflow/0.2 (+https://github.com/Arnav-M/Novelflow)"},
    )
    with urllib.request.urlopen(request, timeout=300) as response:
        dest.write_bytes(response.read())


def main() -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    print(f"Optional downloads go to: {ROOT}")
    print("Local test PDFs (the-mozart-conspiracy.pdf, doomsday-prophecy.pdf) are already used by pytest.\n")
    for name, url in OPTIONAL_SAMPLES.items():
        dest = ROOT / name
        if dest.is_file() and dest.stat().st_size > 10_000:
            print(f"skip {name} (exists)")
            continue
        print(f"downloading {name} ...")
        try:
            _download(url, dest)
            print(f"  saved ({dest.stat().st_size:,} bytes)")
        except Exception as exc:
            print(f"  failed: {exc}")


if __name__ == "__main__":
    main()
