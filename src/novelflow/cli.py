"""Command-line interface for novelflow."""

import argparse
import sys
from pathlib import Path

from novelflow.convert import convert_pdf


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="novelflow",
        description="Convert a PDF novel to readable markdown (PyMuPDF extract + cleanup in one step).",
    )
    parser.add_argument(
        "pdf",
        type=Path,
        help="Input PDF file",
    )
    parser.add_argument(
        "-o", "--output",
        type=Path,
        help="Output markdown path (default: <pdf-name>.readable.md)",
    )
    parser.add_argument(
        "--keep-raw",
        action="store_true",
        help="Also save raw extracted text before cleanup as <pdf-name>.raw.md",
    )
    args = parser.parse_args()

    try:
        convert_pdf(args.pdf, args.output, keep_raw=args.keep_raw)
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
