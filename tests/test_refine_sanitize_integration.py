"""Integration tests: sanitization + refinement."""

from novelflow.refine import refine_markdown


def test_refine_repairs_null_bytes_in_epigraph() -> None:
    raw = "\n".join([
        "Epigraph",
        "Someone has given me aqua to\x00ana and has",
        "calculated the precise time of my death.",
        "Chapter One",
        "Austria",
        "He would \x00nd the house empty.",
    ])
    out = refine_markdown(raw)
    assert "\x00" not in out
    assert "aqua tofana" in out
    assert "would find the house" in out


def test_refine_preserves_normal_prose_after_sanitize() -> None:
    raw = "\n".join([
        "Chapter One",
        "London",
        "Ben Hope opened the door.",
    ])
    out = refine_markdown(raw)
    assert "Ben Hope opened the door." in out
    assert "## Chapter One" in out
