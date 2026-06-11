"""TTS runtime configuration and engine selection."""

from __future__ import annotations

import os

# Edge synthesizes chunks concurrently within a section, and sections
# concurrently within a book. These are the only knobs that matter for Edge.
EDGE_CHUNK_PARALLEL = int(os.environ.get("NOVELFLOW_EDGE_CHUNK_PARALLEL", "6"))
SECTION_PARALLEL = int(os.environ.get("NOVELFLOW_SECTION_PARALLEL", "4"))


def resolve_engine(engine: str) -> str:
    """Resolve engine aliases. Novelflow currently narrates with Edge only."""
    return "edge"


def section_workers(engine: str) -> int:
    """Number of sections to synthesize in parallel."""
    return SECTION_PARALLEL
