"""Append-only explicit trade-origin resolutions (currently UNPLANNED only)."""

from __future__ import annotations

import os
import re
import sqlite3
from pathlib import Path
from typing import Any, Mapping

import formal_trade_attribution as fta

ORIGIN = "UNPLANNED"
_COLUMNS = ("resolution_id", "trade_id", "origin", "pre_trade_decision", "pre_trade_thesis", "created_at")
_RESOLUTION_ID_RE = re.compile(r"^trade_origin_[0-9a-f]{32}$")
_TRADE_ID_RE = re.compile(r"^[0-9a-f]{32}$")


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
    if not isinstance(record["resolution_id"], str) or not _RESOLUTION_ID_RE.fullmatch(record["resolution_id"]):
        raise TradeOriginStoreError("resolution_id invalid")
    if not isinstance(record["trade_id"], str) or not _TRADE_ID_RE.fullmatch(record["trade_id"]):
        raise TradeOriginStoreError("trade_id invalid")
    if not isinstance(record["created_at"], str) or not fta.is_canonical_utc_timestamp(record["created_at"]):
        raise TradeOriginStoreError("created_at must be canonical UTC")
    if record["origin"] != ORIGIN or record["pre_trade_decision"] != "NONE" or record["pre_trade_thesis"] != "NONE":
        raise TradeOriginStoreError("only explicit UNPLANNED/NONE origin is supported")
    return dict(record)


def _assert_schema(conn: sqlite3.Connection) -> None:
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if tables != {"trade_origin_resolutions"}:
        raise TradeOriginStoreCorruptedError("origin store schema corrupted")
    table_info = conn.execute("PRAGMA table_info(trade_origin_resolutions)").fetchall()
    columns = [r[1] for r in table_info]
    if columns != list(_COLUMNS):
        raise TradeOriginStoreCorruptedError("origin store columns corrupted")
    if table_info[0][5] != 1:
        raise TradeOriginStoreCorruptedError("resolution_id must be the primary key")
    expected = {
        "resolution_id": ("TEXT", False),
        "trade_id": ("TEXT", True),
        "origin": ("TEXT", True),
        "pre_trade_decision": ("TEXT", True),
        "pre_trade_thesis": ("TEXT", True),
        "created_at": ("TEXT", True),
    }
    for row in table_info:
        expected_type, expected_notnull = expected[row[1]]
        if row[2].upper() != expected_type or bool(row[3]) != expected_notnull:
            raise TradeOriginStoreCorruptedError("origin store column contract corrupted")
    indexes = conn.execute("PRAGMA index_list(trade_origin_resolutions)").fetchall()
    if not any(row[2] == 1 and [item[2] for item in conn.execute(f"PRAGMA index_info({row[1]})")] == ["trade_id"] for row in indexes):
        raise TradeOriginStoreCorruptedError("origin store must have UNIQUE(trade_id)")
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type IN ('trigger','view') LIMIT 1").fetchone():
        raise TradeOriginStoreCorruptedError("origin store forbids triggers/views")


def _row_to_record(row: sqlite3.Row | tuple[Any, ...]) -> dict[str, Any]:
    payload = dict(zip(_COLUMNS, row))
    try:
        return _validate(payload)
    except TradeOriginStoreError as exc:
        raise TradeOriginStoreCorruptedError(str(exc)) from exc


def _connect(path: Path, readonly: bool) -> sqlite3.Connection:
    if readonly:
        return sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=5)
    return sqlite3.connect(str(path), timeout=10, isolation_level=None)


def _readonly(path: Path) -> sqlite3.Connection | None:
    if not path.exists():
        return None
    if not path.is_file():
        raise TradeOriginStoreCorruptedError("origin store is not a file")
    conn: sqlite3.Connection | None = None
    try:
        conn = _connect(path, True)
        _assert_schema(conn)
        return conn
    except TradeOriginStoreError:
        try:
            if conn is not None:
                conn.close()
        except Exception: pass
        raise
    except sqlite3.Error as exc:
        try:
            if conn is not None:
                conn.close()
        except Exception: pass
        raise TradeOriginStoreCorruptedError() from exc


def write(*, db_path: str | Path, record: Mapping[str, Any]) -> dict[str, Any]:
    value = _validate(record)
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    existed = path.exists()
    conn = _connect(path, False)
    try:
        if existed:
            _assert_schema(conn)
        else:
            conn.execute("""CREATE TABLE trade_origin_resolutions (
                resolution_id TEXT PRIMARY KEY,
                trade_id TEXT NOT NULL UNIQUE,
                origin TEXT NOT NULL,
                pre_trade_decision TEXT NOT NULL,
                pre_trade_thesis TEXT NOT NULL,
                created_at TEXT NOT NULL
            )""")
            _assert_schema(conn)
        existing = conn.execute("SELECT * FROM trade_origin_resolutions WHERE resolution_id=? OR trade_id=?", (value["resolution_id"], value["trade_id"])).fetchone()
        if existing is not None:
            old = _row_to_record(existing)
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
        return None if row is None else _row_to_record(row)
    except sqlite3.Error as exc:
        raise TradeOriginStoreCorruptedError() from exc
    finally:
        conn.close()


def list_all(*, db_path: str | Path) -> list[dict[str, Any]]:
    conn = _readonly(Path(db_path))
    if conn is None:
        return []
    try:
        return [_row_to_record(row) for row in conn.execute("SELECT * FROM trade_origin_resolutions ORDER BY created_at, resolution_id")]
    except sqlite3.Error as exc:
        raise TradeOriginStoreCorruptedError() from exc
    finally:
        conn.close()
