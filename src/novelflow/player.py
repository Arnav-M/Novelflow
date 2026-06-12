"""In-app audiobook player backend.

Plays chapter audio with `pygame`. Chapters come from the ``.chapters.json``
sidecar written next to an audiobook; each chapter points at its source section
MP3 (kept in the work dir), which pygame can decode directly regardless of
whether the final book is an ``.m4b`` or ``.mp3``. When no chapter sidecar or
section files exist, a standalone MP3 is played as a single track.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Chapter:
    title: str
    duration_ms: int
    file: Path | None
    start_ms: int = 0


def _probe_duration_ms(path: Path) -> int:
    import shutil
    import subprocess

    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return 0
    try:
        out = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            check=True, capture_output=True, text=True,
        ).stdout.strip()
        return int(float(out) * 1000)
    except (ValueError, subprocess.CalledProcessError):
        return 0


AUDIOBOOK_EXTENSIONS = (".m4b", ".mp3", ".m4a")


def _chapters_from_sidecar(sidecar: Path) -> list[Chapter]:
    try:
        data = json.loads(sidecar.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    chapters: list[Chapter] = []
    for entry in data:
        file_str = entry.get("file")
        file_path = Path(file_str) if file_str else None
        if file_path is not None and not file_path.is_file():
            file_path = None
        duration = int(entry.get("end_ms", 0)) - int(entry.get("start_ms", 0))
        chapters.append(
            Chapter(
                title=entry.get("title", "Chapter"),
                duration_ms=max(duration, 0),
                file=file_path,
                start_ms=int(entry.get("start_ms", 0)),
            )
        )
    if chapters and all(c.file is not None for c in chapters):
        return chapters
    return []


def _audiobook_display_name(path: Path) -> str:
    name = path.name
    if name.endswith(".chapters.json"):
        return name.replace(".audiobook.chapters.json", "").replace(".chapters.json", "")
    if ".audiobook." in name:
        return name.split(".audiobook.", 1)[0]
    return path.stem


def scan_audiobook_folder(folder: Path) -> list[tuple[str, Path]]:
    """List audiobooks in ``folder`` as ``(label, load_path)`` pairs.

    Finds ``*.audiobook.{m4b,mp3,m4a}`` and, when the final file is missing,
    chapter sidecars whose section MP3s are still on disk (common after a long
    render that kept section audio but never merged).
    """
    folder = Path(folder)
    if not folder.is_dir():
        return []
    found: dict[str, Path] = {}
    for ext in AUDIOBOOK_EXTENSIONS:
        for path in folder.glob(f"*.audiobook{ext}"):
            found[path.stem] = path
    for sidecar in folder.glob("*.audiobook.chapters.json"):
        key = sidecar.name.removesuffix(".chapters.json")
        if key in found:
            continue
        chapters = _chapters_from_sidecar(sidecar)
        if chapters and all(c.file is not None and is_pygame_playable(c.file) for c in chapters):
            found[key] = sidecar
    return sorted(
        [(_audiobook_display_name(path), path) for path in found.values()],
        key=lambda item: item[0].lower(),
    )


def load_chapters(audio_path: Path, *, probe_durations: bool = True) -> list[Chapter]:
    """Build a playable chapter list for an audiobook or standalone audio file.

    Accepts a final audio file, a ``*.chapters.json`` sidecar, or a missing
    audio path whose sidecar still points at section MP3s on disk.

    ``probe_durations=False`` skips the (blocking) ffprobe fallback for
    standalone tracks; callers can fill in ``duration_ms`` asynchronously via
    :func:`probe_chapter_durations`.
    """
    audio_path = Path(audio_path)
    if audio_path.name.endswith(".chapters.json"):
        return _chapters_from_sidecar(audio_path)

    sidecar = audio_path.with_suffix(".chapters.json")
    if sidecar.is_file():
        chapters = _chapters_from_sidecar(sidecar)
        if chapters:
            return chapters

    # Fallback: a single standalone track (pygame plays mp3/ogg/wav).
    if audio_path.is_file():
        return [
            Chapter(
                title=audio_path.stem,
                duration_ms=_probe_duration_ms(audio_path) if probe_durations else 0,
                file=audio_path,
                start_ms=0,
            )
        ]
    return []


def probe_chapter_durations(chapters: list[Chapter]) -> bool:
    """Fill in missing ``duration_ms`` values via ffprobe. Returns True if any changed.

    Safe to call from a worker thread — it only mutates the plain dataclass
    fields, never touches the mixer or any UI.
    """
    changed = False
    for chapter in chapters:
        if chapter.duration_ms <= 0 and chapter.file is not None:
            duration = _probe_duration_ms(chapter.file)
            if duration > 0:
                chapter.duration_ms = duration
                changed = True
    return changed


def is_pygame_playable(path: Path) -> bool:
    """pygame.mixer.music decodes mp3/ogg/wav/flac but not m4b/m4a (AAC)."""
    return Path(path).suffix.lower() in {".mp3", ".ogg", ".wav", ".flac"}


def _speed_cache_dir() -> Path:
    import tempfile

    d = Path(tempfile.gettempdir()) / "novelflow_speed"
    d.mkdir(exist_ok=True)
    return d


def _speed_variant_path(source: Path, speed: float) -> Path:
    source = Path(source)
    try:
        size = source.stat().st_size
    except OSError:
        size = 0
    return _speed_cache_dir() / f"{source.stem}_{size}_{speed:.2f}.mp3"


def cached_speed_variant(source: Path, speed: float) -> Path | None:
    """Return an already-rendered speed variant without transcoding, if present."""
    if abs(speed - 1.0) < 0.01:
        return Path(source)
    out = _speed_variant_path(source, speed)
    return out if out.is_file() and out.stat().st_size > 1024 else None


def prune_speed_cache(*, max_age_days: float = 14.0, max_total_mb: float = 512.0) -> None:
    """Trim the speed-variant temp cache (old files first, then size cap)."""
    import time

    try:
        entries = []
        cutoff = time.time() - max_age_days * 86400
        for path in _speed_cache_dir().glob("*.mp3"):
            try:
                stat = path.stat()
            except OSError:
                continue
            if stat.st_mtime < cutoff:
                path.unlink(missing_ok=True)
            else:
                entries.append((stat.st_mtime, stat.st_size, path))
        entries.sort()  # oldest first
        total = sum(size for _mtime, size, _path in entries)
        budget = int(max_total_mb * 1024 * 1024)
        for _mtime, size, path in entries:
            if total <= budget:
                break
            path.unlink(missing_ok=True)
            total -= size
    except OSError:
        pass


def make_speed_variant(source: Path, speed: float) -> Path | None:
    """Return a tempo-adjusted copy of ``source`` (pitch preserved via atempo).

    Cached by source name + size + speed, so re-playing a chapter at a known
    speed is instant after the first render. Returns ``None`` if ffmpeg is
    unavailable or the transcode fails.
    """
    import shutil
    import subprocess

    source = Path(source)
    if abs(speed - 1.0) < 0.01:
        return source
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg or not source.is_file():
        return None
    out = _speed_variant_path(source, speed)
    if out.is_file() and out.stat().st_size > 1024:
        return out
    try:
        subprocess.run(
            [ffmpeg, "-y", "-i", str(source), "-filter:a", f"atempo={speed:.3f}",
             "-vn", str(out)],
            check=True, capture_output=True,
        )
    except (subprocess.CalledProcessError, OSError):
        return None
    return out if out.is_file() else None


class AudioPlayer:
    """Chapter-aware audio player built on ``pygame.mixer.music``.

    The mixer plays one file at a time; chapters that each map to their own
    section MP3 are played in sequence with automatic advance. Within a chapter,
    seeking uses pygame's start offset.
    """

    def __init__(self) -> None:
        self._mixer = None
        self.chapters: list[Chapter] = []
        self.index = 0
        self._offset_ms = 0  # seek base within the current chapter
        self._last_pos_ms = 0  # last observed position (survives mixer stop)
        self._playing = False
        self._loaded_file: Path | None = None
        self.speed = 1.0
        self.volume = 0.85

    def _ensure_mixer(self):
        if self._mixer is None:
            import pygame

            pygame.mixer.init()
            self._mixer = pygame.mixer.music
        return self._mixer

    @property
    def available(self) -> bool:
        try:
            import pygame  # noqa: F401

            return True
        except ImportError:
            return False

    def load(self, audio_path: Path, *, probe_durations: bool = True) -> list[Chapter]:
        self.stop()
        self.chapters = load_chapters(audio_path, probe_durations=probe_durations)
        self.index = 0
        self._offset_ms = 0
        self._loaded_file = None
        return self.chapters

    def _load_chapter_file(self, index: int) -> bool:
        if not (0 <= index < len(self.chapters)):
            return False
        chapter = self.chapters[index]
        if chapter.file is None or not is_pygame_playable(chapter.file):
            return False
        mixer = self._ensure_mixer()
        if self._loaded_file != chapter.file:
            mixer.load(str(chapter.file))
            self._loaded_file = chapter.file
        return True

    def play_chapter(self, index: int, start_ms: int = 0) -> bool:
        if not self._load_chapter_file(index):
            return False
        self.index = index
        self._offset_ms = max(0, start_ms)
        self._last_pos_ms = self._offset_ms
        mixer = self._ensure_mixer()
        mixer.set_volume(self.volume)
        mixer.play(start=self._offset_ms / 1000.0)
        self._playing = True
        return True

    def play_resolved(self, index: int, path: Path, start_ms: int = 0) -> bool:
        """Play an already-resolved file (original or speed-adjusted) for ``index``.

        Lets the caller decide which physical file backs a chapter (e.g. a
        cached time-stretched variant) while the player keeps chapter/position
        bookkeeping.
        """
        if path is None or not is_pygame_playable(path):
            return False
        mixer = self._ensure_mixer()
        self.index = index
        self._offset_ms = max(0, start_ms)
        self._last_pos_ms = self._offset_ms
        if self._loaded_file != path:
            mixer.load(str(path))
            self._loaded_file = path
        mixer.set_volume(self.volume)
        mixer.play(start=self._offset_ms / 1000.0)
        self._playing = True
        return True

    def set_speed(self, speed: float) -> None:
        self.speed = max(0.5, min(2.0, float(speed)))

    def effective_duration_ms(self, index: int) -> int:
        if 0 <= index < len(self.chapters):
            return max(int(self.chapters[index].duration_ms / self.speed), 1)
        return 1

    def toggle_pause(self) -> None:
        mixer = self._ensure_mixer()
        if self._playing:
            mixer.pause()
            self._playing = False
        else:
            if self._loaded_file is None and self.chapters:
                self.play_chapter(self.index)
            else:
                mixer.unpause()
                self._playing = True

    def play(self) -> bool:
        if self._loaded_file is None:
            return self.play_chapter(self.index)
        self._ensure_mixer().unpause()
        self._playing = True
        return True

    def pause(self) -> None:
        if self._mixer is not None and self._playing:
            self._mixer.pause()
            self._playing = False

    def stop(self) -> None:
        if self._mixer is not None:
            try:
                self._mixer.stop()
            except Exception:  # noqa: BLE001
                pass
        self._playing = False
        self._loaded_file = None
        self._offset_ms = 0
        self._last_pos_ms = 0

    def seek_within_chapter(self, ms: int) -> None:
        self.play_chapter(self.index, start_ms=ms)

    def next_chapter(self) -> bool:
        return self.play_chapter(self.index + 1)

    def prev_chapter(self) -> bool:
        return self.play_chapter(self.index - 1)

    @property
    def is_playing(self) -> bool:
        return self._playing

    def position_ms(self) -> int:
        """Elapsed ms within the current chapter (offset + mixer position)."""
        if self._mixer is None:
            return self._offset_ms
        pos = self._mixer.get_pos()  # ms since play(); -1 if not started/stopped
        if pos < 0:
            # Mixer already stopped (e.g. chapter just ended, or paused on some
            # backends) — report the last position we actually observed so
            # resume bookmarks don't snap back to the seek offset.
            return self._last_pos_ms if self._last_pos_ms > 0 else self._offset_ms
        self._last_pos_ms = self._offset_ms + pos
        return self._last_pos_ms

    def is_busy(self) -> bool:
        if self._mixer is None:
            return False
        try:
            return bool(self._mixer.get_busy())
        except Exception:  # noqa: BLE001
            return False

    def set_volume(self, volume: float) -> None:
        self.volume = max(0.0, min(1.0, volume))
        if self._mixer is not None:
            self._mixer.set_volume(self.volume)

    def play_preview(self, path: Path) -> None:
        """Play a short standalone clip (e.g. a voice sample).

        Uses the same music stream as chapter playback, so any loaded chapter is
        stopped and its state reset — the next chapter ``play`` reloads cleanly.
        """
        mixer = self._ensure_mixer()
        self.stop()
        mixer.load(str(path))
        mixer.play()
        self._loaded_file = None
        self._playing = False

    def close(self) -> None:
        self.stop()
        if self._mixer is not None:
            try:
                import pygame

                pygame.mixer.quit()
            except Exception:  # noqa: BLE001
                pass
            self._mixer = None
