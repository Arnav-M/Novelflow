"""Text-to-speech synthesis backend (Edge online neural TTS)."""

from __future__ import annotations

import asyncio
import shutil
import subprocess
import tempfile
from abc import ABC, abstractmethod
from collections.abc import Callable
from pathlib import Path

from novelflow.tts_config import EDGE_CHUNK_PARALLEL
from novelflow.tts_text import split_for_tts


class TTSEngine(ABC):
    name: str

    @abstractmethod
    def synthesize_section(
        self,
        text: str,
        output_path: Path,
        *,
        voice: str,
        progress: Callable[[str], None] | None = None,
        on_progress: Callable[[float], None] | None = None,
    ) -> Path:
        """Synthesize ``text`` to ``output_path``.

        ``on_progress`` (when given) receives the fraction (0.0–1.0) of this
        section that has been rendered, allowing callers to drive a real
        completion bar instead of a stage estimate.
        """
        ...


def _merge_audio_files(chunks: list[Path], output_path: Path) -> Path:
    if not chunks:
        raise ValueError("No audio chunks to merge")
    if len(chunks) == 1:
        shutil.copy2(chunks[0], output_path)
        return output_path

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError(
            "ffmpeg is required to merge audio chunks. "
            "Install ffmpeg and add it to your PATH."
        )

    with tempfile.TemporaryDirectory() as tmp:
        list_file = Path(tmp) / "concat.txt"
        list_file.write_text(
            "\n".join(f"file '{chunk.resolve().as_posix()}'" for chunk in chunks),
            encoding="utf-8",
        )
        subprocess.run(
            [ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(list_file),
             "-c", "copy", str(output_path)],
            check=True,
            capture_output=True,
        )
    return output_path


class EdgeTTSEngine(TTSEngine):
    name = "edge"

    def synthesize_section(
        self,
        text: str,
        output_path: Path,
        *,
        voice: str,
        progress: Callable[[str], None] | None = None,
        on_progress: Callable[[float], None] | None = None,
    ) -> Path:
        try:
            import edge_tts
        except ImportError as exc:
            raise RuntimeError(
                "edge-tts is not installed. Run: pip install novelflow[audiobook]"
            ) from exc

        chunks = split_for_tts(text)
        if not chunks:
            raise ValueError("No text to synthesize")

        total = len(chunks)
        done = 0

        async def _synthesize_chunk(
            sem: asyncio.Semaphore,
            idx: int,
            chunk: str,
        ) -> Path:
            nonlocal done
            async with sem:
                part = output_path.with_suffix(f".part{idx:04d}.mp3")
                communicate = edge_tts.Communicate(chunk, voice=voice)
                await communicate.save(str(part))
            done += 1
            if on_progress:
                # Reserve the last slice for the merge step.
                on_progress(0.95 * done / total)
            return part

        async def _run() -> list[Path]:
            sem = asyncio.Semaphore(EDGE_CHUNK_PARALLEL)
            tasks = [_synthesize_chunk(sem, idx, chunk) for idx, chunk in enumerate(chunks)]
            if progress:
                progress(f"  Edge TTS: {total} chunk(s), {EDGE_CHUNK_PARALLEL} parallel")
            return list(await asyncio.gather(*tasks))

        part_paths = asyncio.run(_run())
        _merge_audio_files(part_paths, output_path)
        for part in part_paths:
            part.unlink(missing_ok=True)
        if on_progress:
            on_progress(1.0)
        return output_path


def get_engine(name: str) -> TTSEngine:
    return EdgeTTSEngine()
