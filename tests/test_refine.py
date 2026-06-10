"""Tests for novelflow refinement."""

from novelflow.refine import (
    deflatten_pipe_prose,
    is_scene_header,
    preprocess_raw_line,
    refine_markdown,
    split_compound_line,
)


def test_deflatten_pipe_prose():
    raw = (
        "Ben Hope is running for his life. | Enlisted | | by | the | beautiful | "
        "Leigh | Llewellyn | - | the | beautiful | opera | star"
    )
    out = deflatten_pipe_prose(raw)
    assert "|" not in out
    assert out.startswith("Ben Hope is running for his life.")
    assert "Enlisted" in out
    assert "Leigh" in out


def test_split_merged_scene_header():
    assert split_compound_line("Corfu, Greek Islands, June 2008The first day") == [
        "Corfu, Greek Islands, June 2008",
        "The first day",
    ]


def test_scene_header_patterns():
    hints: set[str] = set()
    assert is_scene_header("Corfu, Greek Islands, June 2008", hints)
    assert is_scene_header("The first day", hints)
    assert is_scene_header("Near Galway Bay, west coast of Ireland", hints)
    assert is_scene_header("12.03 a.m. Greek time", hints)
    assert is_scene_header("Austria", hints)
    assert is_scene_header("9 January", hints)
    assert is_scene_header("Southern Turkey", hints)
    assert is_scene_header("Eleven months later", hints)
    assert is_scene_header("The present day", hints)
    assert not is_scene_header(
        "Ben Hope had been standing there a long time in the darkening room.",
        hints,
    )
    assert not is_scene_header(
        "Benedict Hope gazed out of the window of the 747 and took another long",
        hints,
    )
    assert not is_scene_header(
        "Heini Müller huddled closer to the fire and warmed his hands. Snowflakes",
        hints,
    )


def test_refine_chapter_rejects_prose_fragments():
    raw = "\n".join([
        "Chapter Three",
        "Somewhere over France",
        "Two days later",
        "Benedict Hope gazed out of the window of the 747 and took another long",
        "pull from the miniature bottle of Glenfiddich.",
    ])
    out = refine_markdown(raw)
    assert "*Somewhere over France*" in out
    assert "*Two days later*" in out
    assert "*Benedict Hope gazed" not in out
    assert "Benedict Hope gazed out of the window" in out


def test_refine_chapter_scene_headers():
    raw = "\n".join([
        "Chapter One",
        "Corfu, Greek Islands, June 2008The first day",
        "It was night when they took her.",
        "They watched for three days.",
    ])
    out = refine_markdown(raw)
    assert "## Chapter One" in out
    assert "*Corfu, Greek Islands, June 2008*" in out
    assert "*The first day*" in out
    assert "It was night when they took her." in out


def test_preprocess_splits_and_deflattens():
    lines = preprocess_raw_line(
        "| An | ancient | murder | ... | A | clandestine | society | ... | A |"
    )
    assert len(lines) == 1
    assert "|" not in lines[0]
    assert "ancient" in lines[0]
