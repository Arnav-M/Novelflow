"""Resolve user data paths (models, caches) for dev and frozen builds."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def user_data_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    path = base / "Novelflow"
    path.mkdir(parents=True, exist_ok=True)
    return path
