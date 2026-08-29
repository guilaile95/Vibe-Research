"""Shared, side-effect-free path contract for the daily-review SQLite DB."""

from __future__ import annotations

import os
import sys
from pathlib import Path


REVIEW_DB_ENV = "VIBE_RESEARCH_REVIEW_DB"


def resolve_review_db_path(db_path: str | Path | None = None) -> Path:
    """Resolve the shared review DB path without creating files or directories."""
    if db_path is not None:
        return _normalize_db_path(db_path)

    env_val = os.environ.get(REVIEW_DB_ENV)
    if env_val is not None and str(env_val).strip():
        return _normalize_db_path(str(env_val).strip())

    return _default_review_db_path()


def _normalize_db_path(value: str | Path) -> Path:
    if isinstance(value, Path):
        path = value.expanduser()
    elif isinstance(value, str):
        if not value.strip():
            raise ValueError("db_path 不能为空")
        path = Path(value).expanduser()
    else:
        raise TypeError("db_path 必须是字符串、Path或None")
    return path.resolve()


def _default_review_db_path() -> Path:
    """Return the platform user-data default for daily_reviews.sqlite3."""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA", "").strip()
        if not base:
            home = os.environ.get("USERPROFILE") or str(Path.home())
            base = str(Path(home) / "AppData" / "Local")
        return (Path(base) / "VibeResearch" / "daily_reviews.sqlite3").resolve()

    if sys.platform == "darwin":
        return (
            Path.home()
            / "Library"
            / "Application Support"
            / "VibeResearch"
            / "daily_reviews.sqlite3"
        ).resolve()

    xdg = os.environ.get("XDG_DATA_HOME", "").strip()
    if xdg:
        return (Path(xdg).expanduser() / "vibe-research" / "daily_reviews.sqlite3").resolve()
    return (Path.home() / ".local" / "share" / "vibe-research" / "daily_reviews.sqlite3").resolve()
