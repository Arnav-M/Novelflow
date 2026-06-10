"""Resolve bundled assets for dev installs and PyInstaller builds."""

from __future__ import annotations

import sys
from pathlib import Path


def package_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "novelflow"
    return Path(__file__).resolve().parent


def asset_path(name: str) -> Path:
    return package_root() / "assets" / name
