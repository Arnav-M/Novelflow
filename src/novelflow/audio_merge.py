"""Merge section audio into M4B/MP3 with chapter markers."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

AAC_BITRATE = os.environ.get("NOVELFLOW_AAC_BITRATE", "64k")


@dataclass
class ChapterMarker:
    title: str
    start_ms: int
    end_ms: int


def _probe_duration_ms(path: Path) -> int:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return 0
    try:
        result = subprocess.run(
            [
                ffprobe, "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", str(path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        return int(float(result.stdout.strip()) * 1000)
    except (ValueError, subprocess.CalledProcessError):
        return 0


def build_chapter_markers(section_files: list[tuple[str, Path]]) -> list[ChapterMarker]:
    """Probe each section's real duration (in parallel) and lay out chapters."""
    paths = [path for _, path in section_files]
    # ffprobe is I/O bound; probing sequentially is the slow part of "merging"
    # for books with dozens of chapters, so fan the probes out.
    with ThreadPoolExecutor(max_workers=min(8, max(1, len(paths)))) as pool:
        durations = list(pool.map(_probe_duration_ms, paths))

    markers: list[ChapterMarker] = []
    cursor = 0
    for (title, path), duration in zip(section_files, durations):
        if duration <= 0:
            # ~128 kbps MP3 ≈ 16 bytes/ms; better than a blind constant.
            duration = max(path.stat().st_size // 16, 1000)
        markers.append(ChapterMarker(title=title, start_ms=cursor, end_ms=cursor + duration))
        cursor += duration
    return markers


def write_ffmetadata(markers: list[ChapterMarker], path: Path) -> None:
    lines = [";FFMETADATA1"]
    for marker in markers:
        lines.extend([
            "[CHAPTER]",
            "TIMEBASE=1/1000",
            f"START={marker.start_ms}",
            f"END={marker.end_ms}",
            f"title={marker.title}",
        ])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _parse_ffmpeg_time(value: str) -> int | None:
    """Parse an ffmpeg ``out_time`` value (HH:MM:SS.micros) to milliseconds."""
    value = value.strip()
    if not value or value == "N/A":
        return None
    try:
        hours, minutes, seconds = value.split(":")
        return int((int(hours) * 3600 + int(minutes) * 60 + float(seconds)) * 1000)
    except ValueError:
        return None


def _run_ffmpeg(
    ffmpeg: str,
    args: list[str],
    output: Path,
    *,
    total_ms: int = 0,
    on_progress: Callable[[float], None] | None = None,
) -> None:
    """Run an ffmpeg command, optionally streaming real progress (0.0–1.0)."""
    if not on_progress or total_ms <= 0:
        subprocess.run([ffmpeg, "-y", *args, str(output)], check=True, capture_output=True)
        return

    cmd = [ffmpeg, "-y", *args, "-progress", "pipe:1", "-nostats", str(output)]
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
    )
    assert proc.stdout is not None
    for line in proc.stdout:
        line = line.strip()
        if line.startswith("out_time="):
            ms = _parse_ffmpeg_time(line.split("=", 1)[1])
            if ms is not None:
                on_progress(max(0.0, min(1.0, ms / total_ms)))
        elif line == "progress=end":
            on_progress(1.0)
    if proc.wait() != 0:
        raise subprocess.CalledProcessError(proc.returncode, cmd)


def _encode_section_aac(ffmpeg: str, src: Path, dst: Path, bitrate: str) -> Path:
    """Encode one section to a raw ADTS AAC stream (concatenates cleanly)."""
    subprocess.run(
        [ffmpeg, "-y", "-i", str(src),
         "-c:a", "aac", "-b:a", bitrate, "-ac", "1", "-f", "adts", str(dst)],
        check=True,
        capture_output=True,
    )
    return dst


def merge_audiobook(
    section_files: list[tuple[str, Path]],
    output_path: Path,
    *,
    audio_format: str = "m4b",
    on_progress: Callable[[float], None] | None = None,
) -> tuple[Path, list[ChapterMarker]]:
    """Concatenate section audio and embed chapter markers.

    MP3 output is muxed with ``-c copy`` (no quality loss, near-instant).
    M4B/M4A re-encodes to AAC, but does so **per section in parallel** across
    CPU cores and then stream-copies the pieces together — far faster than a
    single serial encode of the whole book on long titles.
    ``on_progress`` reports 0.0–1.0 of the merge phase.
    """
    if not section_files:
        raise ValueError("No audio sections to merge")

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError(
            "ffmpeg is required to build audiobook files. "
            "Install ffmpeg and add it to your PATH."
        )

    fmt = audio_format.lower().lstrip(".")
    if fmt not in {"m4b", "mp3", "m4a"}:
        raise ValueError(f"Unsupported audio format: {audio_format}")

    out = output_path if output_path.suffix else output_path.with_suffix(f".{fmt}")
    markers = build_chapter_markers(section_files)
    total_ms = markers[-1].end_ms if markers else 0
    if on_progress:
        on_progress(0.05)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        meta_file = tmp_path / "chapters.ffmeta"
        write_ffmetadata(markers, meta_file)

        if fmt == "mp3":
            # Sections are already finished MP3 — concat-copy then attach
            # chapters with a stream copy. No re-encode, effectively instant.
            list_file = tmp_path / "concat.txt"
            list_file.write_text(
                "\n".join(f"file '{path.resolve().as_posix()}'" for _, path in section_files),
                encoding="utf-8",
            )
            merged = tmp_path / "merged.mp3"
            subprocess.run(
                [ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(list_file),
                 "-c", "copy", str(merged)],
                check=True,
                capture_output=True,
            )
            if on_progress:
                on_progress(0.4)
            _run_ffmpeg(
                ffmpeg,
                ["-i", str(merged), "-i", str(meta_file),
                 "-map_metadata", "1", "-c", "copy"],
                out,
                total_ms=total_ms,
                on_progress=lambda f: on_progress(0.4 + 0.6 * f) if on_progress else None,
            )
        else:
            # Encode each section to AAC concurrently, then stream-copy the
            # pieces into the final container with chapters.
            encoded = [tmp_path / f"sec_{i:04d}.aac" for i in range(len(section_files))]
            total = len(section_files)
            done = 0
            lock = threading.Lock()
            workers = max(1, min(total, os.cpu_count() or 4))
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = {
                    pool.submit(_encode_section_aac, ffmpeg, path, encoded[i], AAC_BITRATE): i
                    for i, (_, path) in enumerate(section_files)
                }
                for future in as_completed(futures):
                    future.result()
                    with lock:
                        done += 1
                        current = done
                    if on_progress:
                        on_progress(0.05 + 0.85 * (current / total))

            list_file = tmp_path / "concat.txt"
            list_file.write_text(
                "\n".join(f"file '{enc.resolve().as_posix()}'" for enc in encoded),
                encoding="utf-8",
            )
            subprocess.run(
                [ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(list_file),
                 "-i", str(meta_file), "-map", "0:a", "-map_metadata", "1",
                 "-c", "copy", str(out)],
                check=True,
                capture_output=True,
            )

    if on_progress:
        on_progress(1.0)
    return out, markers


def update_manifest_timestamps(manifest_path: Path, markers: list[ChapterMarker]) -> None:
    """Attach start/end ms to manifest sections for in-app navigation."""
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    title_to_marker = {m.title: m for m in markers}
    for section in data.get("sections", []):
        if not section.get("enabled", True):
            section["start_ms"] = None
            section["end_ms"] = None
            continue
        marker = title_to_marker.get(section["title"])
        if marker:
            section["start_ms"] = marker.start_ms
            section["end_ms"] = marker.end_ms
    manifest_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
