"""Append-only explicit trade-origin resolutions (currently UNPLANNED only)."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any, Mapping

ORIGIN = "UNPLANNED"
_COLUMNS = ("resolution_id", "trade_id", "origin", "pre_trade_decision", "pre_trade_thesis", "created_at")


class TradeOriginStoreError(RuntimeError):
    pass


class TradeOriginStoreConflictError(TradeOriginStoreError):
    pass


class TradeOriginStoreCorruptedError(TradeOriginStoreError):
    pass


def resolve_db_path(explicit_path: str | Path | None = None) -> Path:
    if explicit_path is not None:
        return Path(explicit_path)
    env = os.environ.get("VIBE_RESEARCH_TRADE_ORIGIN_DB", "").strip()
    if env:
        return Path(env)
    data_dir = os.environ.get("VR_DATA_DIR", "").strip()
    return (Path(data_dir) if data_dir else Path.home() / ".vibe-research") / "trade_origins.sqlite3"


def _validate(record: Mapping[str, Any]) -> dict[str, Any]:
    if set(record) != set(_COLUMNS):
        raise TradeOriginStoreError("origin record fields mismatch")
    for field in ("resolution_id", "trade_id", "created_at"):
        if not isinstance(record[field], str) or not record[field].strip() or record[field] != record[field].strip():
            raise TradeOriginStoreError(f"{field} invalid")
    if record["origin"] != ORIGIN or record["pre_trade_decision"] != "NONE" or record["pre_trade_thesis"] != "NONE":
        raise TradeOriginStoreError("only explicit UNPLANNED/NONE origin is supported")
    return dict(record)


def _connect(path: Path, readonly: bool) -> sqlite3.Connection:
    if readonly:
        return sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=5)
    return sqlite3.connect(str(path), timeout=10, isolation_level=None)


def _readonly(path: Path) -> sqlite3.Connection | None:
    if not path.exists():
        return None
    if not path.is_file():
        raise TradeOriginStoreCorruptedError("origin store is not a file")
    try:
        conn = _connect(path, True)
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if tables != {"trade_origin_resolutions"}:
            raise TradeOriginStoreCorruptedError("origin store schema corrupted")
        cols = [r[1] for r in conn.execute("PRAGMA table_info(trade_origin_resolutions)")]
        if cols != list(_COLUMNS):
            raise TradeOriginStoreCorruptedError("origin store columns corrupted")
        return conn
    except TradeOriginStoreError:
        try: conn.close()
        except Exception: pass
        raise
    except sqlite3.Error as exc:
        try: conn.close()
        except Exception: pass
        raise TradeOriginStoreCorruptedError() from exc


def write(*, db_path: str | Path, record: Mapping[str, Any]) -> dict[str, Any]:
    value = _validate(record)
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = _connect(path, False)
    try:
        conn.executescript(f"""
            CREATE TABLE IF NOT EXISTS trade_origin_resolutions (
                resolution_id TEXT PRIMARY KEY,
                trade_id TEXT NOT NULL UNIQUE,
                origin TEXT NOT NULL,
                pre_trade_decision TEXT NOT NULL,
                pre_trade_thesis TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        existing = conn.execute("SELECT * FROM trade_origin_resolutions WHERE resolution_id=? OR trade_id=?", (value["resolution_id"], value["trade_id"])).fetchone()
        if existing is not None:
            old = dict(zip(_COLUMNS, existing))
            if old != value:
                raise TradeOriginStoreConflictError("origin replay conflicts")
            return old
        conn.execute("INSERT INTO trade_origin_resolutions VALUES (?,?,?,?,?,?)", tuple(value[col] for col in _COLUMNS))
        return value
    except TradeOriginStoreError:
        raise
    except sqlite3.Error as exc:
        raise TradeOriginStoreCorruptedError() from exc
    finally:
        conn.close()


def get_for_trade(*, db_path: str | Path, trade_id: str) -> dict[str, Any] | None:
    conn = _readonly(Path(db_path))
    if conn is None:
        return None
    try:
        row = conn.execute("SELECT * FROM trade_origin_resolutions WHERE trade_id=?", (trade_id,)).fetchone()
        return None if row is None else dict(zip(_COLUMNS, row))
    except sqlite3.Error as exc:
        raise TradeOriginStoreCorruptedError() from exc
    finally:
        conn.close()


def list_all(*, db_path: str | Path) -> list[dict[str, Any]]:
    conn = _readonly(Path(db_path))
    if conn is None:
        return []
    try:
        return [dict(zip(_COLUMNS, row)) for row in conn.execute("SELECT * FROM trade_origin_resolutions ORDER BY created_at, resolution_id")]
    except sqlite3.Error as exc:
        raise TradeOriginStoreCorruptedError() from exc
    finally:
        conn.close()
