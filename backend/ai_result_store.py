"""SQLite persistence for validated AI-generated results.

This module owns only deterministic JSON and SQL.  Callers must provide the
database path and validate business fields before writing.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping


class AiResultPayloadCorruptedError(RuntimeError):
    """A stored payload cannot be decoded safely."""

    def __init__(self):
        super().__init__("已保存的 AI 结果数据损坏，无法读取")


class AiResultWriteCancelledError(RuntimeError):
    """The caller disconnected before the write transaction committed."""

    def __init__(self):
        super().__init__("AI 结果保存已取消")


_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS ai_generated_results (
    result_type TEXT NOT NULL
        CHECK (result_type IN ('daily_review_ai', 'portfolio_advice')),
    trade_date TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    generated_at TEXT NOT NULL,
    model_provider TEXT NOT NULL,
    model_name TEXT NOT NULL,
    input_fingerprint TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (result_type, trade_date)
)
"""

_UPSERT_SQL = """
INSERT INTO ai_generated_results (
    result_type, trade_date, schema_version, payload_json, generated_at,
    model_provider, model_name, input_fingerprint, created_at, updated_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(result_type, trade_date) DO UPDATE SET
    schema_version = excluded.schema_version,
    payload_json = excluded.payload_json,
    generated_at = excluded.generated_at,
    model_provider = excluded.model_provider,
    model_name = excluded.model_name,
    input_fingerprint = excluded.input_fingerprint,
    updated_at = excluded.updated_at
"""

_SELECT_COLUMNS = """
result_type, trade_date, schema_version, payload_json, generated_at,
model_provider, model_name, input_fingerprint, created_at, updated_at
"""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _connect(db_path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(Path(db_path)), timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def _connect_readonly(db_path: str | Path) -> sqlite3.Connection:
    uri = f"{Path(db_path).resolve().as_uri()}?mode=ro"
    conn = sqlite3.connect(uri, timeout=30.0, uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def serialize_payload(payload: Any) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def initialize_store(db_path: str | Path) -> None:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _connect(path) as conn:
        conn.execute(_CREATE_TABLE_SQL)


def _decode_row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    try:
        payload = json.loads(row["payload_json"])
    except (json.JSONDecodeError, UnicodeError, TypeError, ValueError):
        raise AiResultPayloadCorruptedError() from None
    if not isinstance(payload, dict):
        raise AiResultPayloadCorruptedError()
    return {
        "result_type": row["result_type"],
        "trade_date": row["trade_date"],
        "schema_version": row["schema_version"],
        "payload": payload,
        "generated_at": row["generated_at"],
        "model_provider": row["model_provider"],
        "model_name": row["model_name"],
        "input_fingerprint": row["input_fingerprint"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def upsert_result(
    db_path: str | Path,
    record: Mapping[str, Any],
    *,
    should_cancel: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """Atomically insert or replace the latest result for a type/trade date."""
    payload_json = serialize_payload(record["payload"])
    initialize_store(db_path)
    now = _utc_now()
    values = (
        record["result_type"],
        record["trade_date"],
        record["schema_version"],
        payload_json,
        record["generated_at"],
        record["model_provider"],
        record["model_name"],
        record.get("input_fingerprint"),
        now,
        now,
    )
    conn = _connect(db_path)
    try:
        if should_cancel is not None and should_cancel():
            raise AiResultWriteCancelledError()
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(_UPSERT_SQL, values)
        if should_cancel is not None and should_cancel():
            raise AiResultWriteCancelledError()
        row = conn.execute(
            f"SELECT {_SELECT_COLUMNS} FROM ai_generated_results "
            "WHERE result_type = ? AND trade_date = ?",
            (record["result_type"], record["trade_date"]),
        ).fetchone()
        if should_cancel is not None and should_cancel():
            raise AiResultWriteCancelledError()
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()
    decoded = _decode_row(row)
    if decoded is None:  # defensive: the transaction just inserted this key
        raise RuntimeError("AI 结果保存后读取失败")
    return decoded


def get_result(
    db_path: str | Path,
    result_type: str,
    trade_date: str,
) -> dict[str, Any] | None:
    path = Path(db_path)
    if not path.is_file():
        return None
    with _connect_readonly(path) as conn:
        table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            ("ai_generated_results",),
        ).fetchone()
        if table is None:
            return None
        row = conn.execute(
            f"SELECT {_SELECT_COLUMNS} FROM ai_generated_results "
            "WHERE result_type = ? AND trade_date = ?",
            (result_type, trade_date),
        ).fetchone()
    return _decode_row(row)

def get_latest_result(
    db_path: str | Path,
    result_type: str,
) -> dict[str, Any] | None:
    path = Path(db_path)
    if not path.is_file():
        return None
    with _connect_readonly(path) as conn:
        table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            ("ai_generated_results",),
        ).fetchone()
        if table is None:
            return None
        row = conn.execute(
            f"SELECT {_SELECT_COLUMNS} FROM ai_generated_results "
            "WHERE result_type = ? ORDER BY trade_date DESC, updated_at DESC LIMIT 1",
            (result_type,),
        ).fetchone()
    return _decode_row(row)
