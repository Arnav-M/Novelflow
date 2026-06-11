"""Tests for TTS chunk splitting."""

from novelflow.tts_text import split_for_tts


def test_short_text_single_chunk():
    assert split_for_tts("Hello world.") == ["Hello world."]


def test_splits_long_text():
    sentence = "This is a sentence. "
    text = sentence * 300
    chunks = split_for_tts(text, max_chars=500)
    assert len(chunks) > 1
    assert all(len(c) <= 500 for c in chunks)
