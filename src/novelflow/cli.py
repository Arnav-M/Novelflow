"""Command-line interface for novelflow."""

import argparse
import sys
from pathlib import Path

from novelflow.audiobook import create_audiobook
from novelflow.convert import convert_pdf
from novelflow.tts_voices import default_voice, voices_for_engine


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="novelflow",
        description="Convert a PDF novel to readable markdown and optional audiobook.",
    )
    parser.add_argument(
        "input",
        type=Path,
        nargs="?",
        help="Input PDF, or readable .md when using --from-markdown",
    )
    parser.add_argument(
        "-o", "--output",
        type=Path,
        help="Output path (markdown or audiobook depending on mode)",
    )
    parser.add_argument(
        "--keep-raw",
        action="store_true",
        help="Also save raw extracted text before cleanup as <pdf-name>.raw.md",
    )
    parser.add_argument(
        "--from-markdown",
        action="store_true",
        help="Treat input as readable markdown; skip PDF conversion.",
    )
    parser.add_argument(
        "--audiobook",
        action="store_true",
        help="Create a chapter-marked audiobook (after PDF conversion, or from --from-markdown).",
    )
    parser.add_argument(
        "--tts-engine",
        choices=["edge"],
        default="edge",
        help="TTS engine (Edge online neural voices).",
    )
    parser.add_argument(
        "--voice",
        help="Voice id (see --list-voices).",
    )
    parser.add_argument(
        "--audio-format",
        choices=["m4b", "mp3", "m4a"],
        default="m4b",
        help="Audiobook format (default: m4b with chapter markers).",
    )
    parser.add_argument(
        "--list-voices",
        action="store_true",
        help="List voices for --tts-engine and exit.",
    )
    parser.add_argument(
        "--skip-section",
        action="append",
        default=[],
        metavar="SECTION_ID",
        help="Exclude section id from audiobook (repeatable).",
    )
    parser.add_argument(
        "--all-sections",
        action="store_true",
        help="Include dedication, contents, acknowledgements, etc. (default: title + chapters only).",
    )
    args = parser.parse_args()

    if args.list_voices:
        for voice in voices_for_engine(args.tts_engine):
            print(f"{voice.id}\t{voice.label}\t{voice.locale}")
        return

    if args.input is None:
        parser.print_help()
        sys.exit(2)

    disabled = set(args.skip_section or [])
    voice = args.voice or default_voice(args.tts_engine)
    chapters_only = not args.all_sections
    explicit_disabled = disabled if (disabled or args.all_sections) else None

    try:
        if args.from_markdown:
            if not args.audiobook:
                print("Error: --from-markdown requires --audiobook", file=sys.stderr)
                sys.exit(1)
            create_audiobook(
                args.input,
                args.output,
                engine=args.tts_engine,
                voice=voice,
                audio_format=args.audio_format,
                disabled_section_ids=explicit_disabled,
                chapters_and_title_only=chapters_only and not disabled,
            )
        else:
            convert_pdf(
                args.input,
                args.output,
                keep_raw=args.keep_raw,
                audiobook=args.audiobook,
                tts_engine=args.tts_engine,
                tts_voice=voice,
                audio_format=args.audio_format,
                disabled_section_ids=explicit_disabled,
                chapters_and_title_only=chapters_only and not disabled,
            )
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
