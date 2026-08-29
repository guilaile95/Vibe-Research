"""Side-effect-free path contract for the Research Data Plane."""

from __future__ import annotations

import os
from pathlib import Path


RESEARCH_DATA_DIR_ENV = "VIBE_RESEARCH_RESEARCH_DATA_DIR"


def resolve_research_data_root(root: str | Path | None = None) -> Path:
    """Resolve the Research Data Plane root without creating it."""
    if root is not None:
        return Path(root)
    configured = os.environ.get(RESEARCH_DATA_DIR_ENV, "").strip()
    if configured:
        return Path(configured)
    data_dir = os.environ.get("VR_DATA_DIR", "").strip()
    if data_dir:
        return Path(data_dir) / "research_data_plane"
    return Path.home() / ".vibe-research" / "research_data_plane"
