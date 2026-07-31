"""SQLite persistence for Intel Daily Digests.

Deterministic storage, schema initialization, deduplication, and queries.
Does not import app/chat/services. Uses standard sqlite3.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from pathlib import Path
from typing import Any

_LOCK = threading.Lock()


class IntelDigestCorruptedError(RuntimeError):
    """Database file corrupted or unwritable."""

    MESSAGE = "Intel 摘要持久化数据损坏，无法读写"

    def __init__(self):
        super().__init__(self.MESSAGE)


_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS intel_daily_digests (
    digest_id TEXT PRIMARY KEY,
    digest_date TEXT NOT NULL,
    sector_key TEXT NOT NULL,
    sector_name TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('normal', 'partial')),
    summary_text TEXT NOT NULL,
    source_refs TEXT NOT NULL,
    input_fingerprint TEXT NOT NULL,
    generated_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(digest_date, sector_key, input_fingerprint)
)
"""

_CREATE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_intel_digests_latest
ON intel_daily_digests (sector_key, digest_date DESC, created_at DESC)
"""


def get_default_db_path() -> Path:
    env_dir = os.environ.get("VR_DATA_DIR", "").strip()
    if env_dir:
        base = Path(env_dir)
    else:
        base = Path.home() / ".vibe-research"
    return base / "intel_digest.sqlite3"


def _connect(db_path: str | Path) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def initialize_store(db_path: str | Path | None = None) -> None:
    path = Path(db_path) if db_path else get_default_db_path()
    with _LOCK:
        try:
            with _connect(path) as conn:
                conn.execute(_CREATE_TABLE_SQL)
                conn.execute(_CREATE_INDEX_SQL)
                conn.commit()
        except sqlite3.DatabaseError as e:
            raise IntelDigestCorruptedError() from e


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    source_refs_raw = row["source_refs"]
    try:
        source_refs = json.loads(source_refs_raw)
    except Exception:
        source_refs = source_refs_raw

    return {
        "digest_id": row["digest_id"],
        "digest_date": row["digest_date"],
        "sector_key": row["sector_key"],
        "sector_name": row["sector_name"],
        "status": row["status"],
        "summary_text": row["summary_text"],
        "source_refs": source_refs,
        "input_fingerprint": row["input_fingerprint"],
        "generated_at": row["generated_at"],
        "created_at": row["created_at"],
    }


def save_intel_digest(
    digest_data: dict[str, Any],
    db_path: str | Path | None = None,
) -> tuple[dict[str, Any], bool]:
    """
    Save an intel digest record.

    If a record with matching (digest_date, sector_key, input_fingerprint) exists,
    returns the existing record with deduped=True without overwriting.
    Otherwise inserts and returns the new record with deduped=False.
    """
    path = Path(db_path) if db_path else get_default_db_path()
    initialize_store(path)

    digest_id = digest_data["digest_id"]
    digest_date = digest_data["digest_date"]
    sector_key = digest_data["sector_key"]
    sector_name = digest_data["sector_name"]
    status = digest_data["status"]
    summary_text = digest_data["summary_text"]
    source_refs_str = (
        json.dumps(digest_data["source_refs"], ensure_ascii=False)
        if isinstance(digest_data["source_refs"], (list, dict))
        else str(digest_data["source_refs"])
    )
    input_fingerprint = digest_data["input_fingerprint"]
    generated_at = digest_data["generated_at"]
    created_at = digest_data["created_at"]

    with _LOCK:
        try:
            with _connect(path) as conn:
                # Check for existing record matching unique constraint (digest_date, sector_key, input_fingerprint)
                existing = conn.execute(
                    """
                    SELECT * FROM intel_daily_digests
                    WHERE digest_date = ? AND sector_key = ? AND input_fingerprint = ?
                    LIMIT 1
                    """,
                    (digest_date, sector_key, input_fingerprint),
                ).fetchone()

                if existing:
                    return _row_to_dict(existing), True

                # Insert new record
                conn.execute(
                    """
                    INSERT INTO intel_daily_digests (
                        digest_id, digest_date, sector_key, sector_name, status,
                        summary_text, source_refs, input_fingerprint, generated_at, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        digest_id,
                        digest_date,
                        sector_key,
                        sector_name,
                        status,
                        summary_text,
                        source_refs_str,
                        input_fingerprint,
                        generated_at,
                        created_at,
                    ),
                )
                conn.commit()

                # Fetch back inserted record
                row = conn.execute(
                    "SELECT * FROM intel_daily_digests WHERE digest_id = ?",
                    (digest_id,),
                ).fetchone()
                return _row_to_dict(row), False

        except sqlite3.DatabaseError as e:
            raise IntelDigestCorruptedError() from e


def get_latest_intel_digest(
    sector_key: str,
    db_path: str | Path | None = None,
) -> dict[str, Any] | None:
    path = Path(db_path) if db_path else get_default_db_path()
    initialize_store(path)

    with _LOCK:
        try:
            with _connect(path) as conn:
                row = conn.execute(
                    """
                    SELECT * FROM intel_daily_digests
                    WHERE sector_key = ?
                    ORDER BY digest_date DESC, created_at DESC
                    LIMIT 1
                    """,
                    (sector_key,),
                ).fetchone()
                return _row_to_dict(row) if row else None
        except sqlite3.DatabaseError as e:
            raise IntelDigestCorruptedError() from e


def get_intel_digest_by_date(
    sector_key: str,
    digest_date: str,
    db_path: str | Path | None = None,
) -> dict[str, Any] | None:
    path = Path(db_path) if db_path else get_default_db_path()
    initialize_store(path)

    with _LOCK:
        try:
            with _connect(path) as conn:
                row = conn.execute(
                    """
                    SELECT * FROM intel_daily_digests
                    WHERE sector_key = ? AND digest_date = ?
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (sector_key, digest_date),
                ).fetchone()
                return _row_to_dict(row) if row else None
        except sqlite3.DatabaseError as e:
            raise IntelDigestCorruptedError() from e
