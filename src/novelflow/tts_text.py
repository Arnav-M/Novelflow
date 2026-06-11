"""Split long prose into TTS-safe chunks."""

from __future__ import annotations

import re

MAX_CHUNK_CHARS = 2800
SENTENCE_SPLIT = re.compile(r'(?<=[.!?])\s+')


def split_for_tts(text: str, max_chars: int = MAX_CHUNK_CHARS) -> list[str]:
    """Split text on sentence boundaries, respecting max chunk size."""
    text = text.strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    sentences = SENTENCE_SPLIT.split(text)
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        extra = len(sentence) + (1 if current else 0)
        if current and current_len + extra > max_chars:
            chunks.append(" ".join(current))
            current = [sentence]
            current_len = len(sentence)
        else:
            current.append(sentence)
            current_len += extra

    if current:
        chunks.append(" ".join(current))

    if not chunks:
        return [text[:max_chars]]
    return chunks
