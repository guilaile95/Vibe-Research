"""P0-DCH1 append-only Decision Challenge packet store.

Companion ledger only.  Does not modify Frozen Decision or Trade Ledger schema.
Read of a missing database has no filesystem side effects.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import decision_challenge_projection as domain

SCHEMA_VERSION = "decision-challenge-packet.v0.1"

_LOCK = threading.Lock()

_CREATE_SCHEMA_META = """
CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
)
"""

_CREATE_PACKETS = """
CREATE TABLE IF NOT EXISTS decision_challenges (
    challenge_id TEXT PRIMARY KEY,
    campaign_id TEXT NOT NULL,
    proposal_fingerprint TEXT NOT NULL UNIQUE,
    proposal_as_of TEXT NOT NULL,
    packet_hash TEXT NOT NULL,
    packet_json TEXT NOT NULL,
    finalized_at TEXT NOT NULL,
    created_at TEXT NOT NULL
)
"""

_ALL_DDL = (_CREATE_SCHEMA_META, _CREATE_PACKETS)
_EXPECTED_TABLES = frozenset({"schema_meta", "decision_challenges"})
_SCHEMA_META_COLUMNS = {
    "key": ("TEXT", False, True),
    "value": ("TEXT", True, False),
}
_PACKET_COLUMNS = {
    "challenge_id": ("TEXT", False, True),
    "campaign_id": ("TEXT", True, False),
    "proposal_fingerprint": ("TEXT", True, False),
    "proposal_as_of": ("TEXT", True, False),
    "packet_hash": ("TEXT", True, False),
    "packet_json": ("TEXT", True, False),
    "finalized_at": ("TEXT", True, False),
    "created_at": ("TEXT", True, False),
}


class DecisionChallengeStoreError(RuntimeError):
    """Challenge store base error."""


class DecisionChallengeStoreCorruptedError(DecisionChallengeStoreError):
    """Schema, row, or hash integrity failure."""


class DecisionChallengeConflictError(DecisionChallengeStoreError, ValueError):
    """Conflicting replay for the same proposal fingerprint."""


def resolve_decision_challenge_db_path(explicit_path: str | Path | None = None) -> Path:
    """Parse path only. Never touches the filesystem."""

    if explicit_path:
        return Path(explicit_path)
    env_db = os.environ.get("VIBE_RESEARCH_DECISION_CHALLENGE_DB", "").strip()
    if env_db:
        return Path(env_db)
    env_dir = os.environ.get("VR_DATA_DIR", "").strip()
    if env_dir:
        return Path(env_dir) / "decision_challenges.sqlite3"
    return Path.home() / ".vibe-research" / "decision_challenges.sqlite3"


def _as_path(db_path: str | Path) -> str:
    if isinstance(db_path, Path):
        return str(db_path)
    if not isinstance(db_path, str):
        raise TypeError("db_path must be a string or Path")
    return db_path


def _db_file_exists(db_path: str | Path) -> bool:
    try:
        return Path(_as_path(db_path)).is_file()
    except TypeError:
        return False


def _ensure_parent_dir(db_path: str | Path) -> None:
    path = _as_path(db_path)
    if path == ":memory:":
        return
    parent = Path(path).parent
    if str(parent) and str(parent) != ".":
        parent.mkdir(parents=True, exist_ok=True)


def _connect(db_path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(_as_path(db_path), timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def _connect_readonly(db_path: str | Path) -> sqlite3.Connection:
    path = Path(_as_path(db_path)).resolve()
    conn = sqlite3.connect(f"{path.as_uri()}?mode=ro", timeout=5, uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (name,),
    ).fetchone()
    return row is not None


def _assert_table_contract(
    conn: sqlite3.Connection,
    table_name: str,
    expected: Mapping[str, tuple[str, bool, bool]],
) -> None:
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    actual = {
        row["name"]: (row["type"].upper(), bool(row["notnull"]), bool(row["pk"]))
        for row in rows
    }
    if set(actual) != set(expected):
        raise DecisionChallengeStoreCorruptedError(
            f"{table_name} columns do not match v0.1: {sorted(actual)}"
        )
    for name, (etype, enotnull, epk) in expected.items():
        atype, anotnull, apk = actual[name]
        if atype != etype or anotnull != enotnull or apk != epk:
            raise DecisionChallengeStoreCorruptedError(
                f"{table_name}.{name} does not match contract"
            )


def _assert_schema(conn: sqlite3.Connection) -> None:
    tables = {
        row["name"]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    if tables != set(_EXPECTED_TABLES):
        raise DecisionChallengeStoreCorruptedError(
            f"application tables do not match v0.1: {sorted(tables)}"
        )
    _assert_table_contract(conn, "schema_meta", _SCHEMA_META_COLUMNS)
    _assert_table_contract(conn, "decision_challenges", _PACKET_COLUMNS)
    triggers = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'trigger'"
    ).fetchall()
    if triggers:
        raise DecisionChallengeStoreCorruptedError("triggers are not allowed")
    views = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'view'"
    ).fetchall()
    if views:
        raise DecisionChallengeStoreCorruptedError("views are not allowed")


def _read_schema_version(conn: sqlite3.Connection) -> str | None:
    row = conn.execute(
        "SELECT value FROM schema_meta WHERE key = 'schema_version'"
    ).fetchone()
    return row["value"] if row else None


def _validate_and_prepare_schema(conn: sqlite3.Connection, is_write: bool) -> None:
    if _table_exists(conn, "schema_meta"):
        version = _read_schema_version(conn)
        if version is None:
            raise DecisionChallengeStoreCorruptedError(
                "schema_meta exists without schema_version"
            )
        if version != SCHEMA_VERSION:
            raise DecisionChallengeStoreCorruptedError(
                f"unsupported schema version: {version}"
            )
        _assert_schema(conn)
        return
    has_any_table = (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' "
            "AND name != 'sqlite_sequence' LIMIT 1"
        ).fetchone()
        is not None
    )
    if has_any_table:
        raise DecisionChallengeStoreCorruptedError(
            "non-empty database is missing schema_meta"
        )
    if is_write:
        for ddl in _ALL_DDL:
            conn.execute(ddl)
        conn.execute(
            "INSERT INTO schema_meta(key, value) VALUES ('schema_version', ?)",
            (SCHEMA_VERSION,),
        )


def initialize_store(db_path: str | Path) -> None:
    path = _as_path(db_path)
    if path == ":memory:":
        conn = _connect(path)
        try:
            with conn:
                conn.execute("PRAGMA journal_mode = WAL")
                _validate_and_prepare_schema(conn, is_write=True)
        finally:
            conn.close()
        return
    if _db_file_exists(path):
        conn = _connect_readonly(path)
        try:
            _validate_and_prepare_schema(conn, is_write=False)
        finally:
            conn.close()
    _ensure_parent_dir(path)
    conn = _connect(path)
    try:
        with conn:
            _validate_and_prepare_schema(conn, is_write=True)
        conn.execute("PRAGMA journal_mode = WAL")
    finally:
        conn.close()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def _row_to_packet(row: sqlite3.Row) -> dict[str, Any]:
    try:
        raw = json.loads(row["packet_json"])
    except (TypeError, json.JSONDecodeError) as exc:
        raise DecisionChallengeStoreCorruptedError("packet_json is not valid JSON") from exc
    try:
        packet = domain.challenge_packet_from_mapping(raw)
    except domain.DecisionChallengeValidationError as exc:
        raise DecisionChallengeStoreCorruptedError("stored packet failed validation") from exc
    if packet["packet_hash"] != row["packet_hash"]:
        raise DecisionChallengeStoreCorruptedError("stored packet_hash mismatch")
    if packet["challenge_id"] != row["challenge_id"]:
        raise DecisionChallengeStoreCorruptedError("stored challenge_id mismatch")
    return packet


def get_challenge(
    challenge_id: str,
    *,
    db_path: str | Path | None = None,
) -> dict[str, Any] | None:
    cid = domain.require_challenge_id(challenge_id)
    path = resolve_decision_challenge_db_path(db_path)
    if not _db_file_exists(path):
        return None
    conn = _connect_readonly(path)
    try:
        _validate_and_prepare_schema(conn, is_write=False)
        row = conn.execute(
            "SELECT * FROM decision_challenges WHERE challenge_id = ?",
            (cid,),
        ).fetchone()
        if row is None:
            return None
        return _row_to_packet(row)
    except sqlite3.DatabaseError as exc:
        raise DecisionChallengeStoreCorruptedError("challenge read failed") from exc
    finally:
        conn.close()


def get_challenge_by_fingerprint(
    proposal_fingerprint: str,
    *,
    db_path: str | Path | None = None,
) -> dict[str, Any] | None:
    fingerprint = domain.require_fingerprint(proposal_fingerprint)
    path = resolve_decision_challenge_db_path(db_path)
    if not _db_file_exists(path):
        return None
    conn = _connect_readonly(path)
    try:
        _validate_and_prepare_schema(conn, is_write=False)
        row = conn.execute(
            "SELECT * FROM decision_challenges WHERE proposal_fingerprint = ?",
            (fingerprint,),
        ).fetchone()
        if row is None:
            return None
        return _row_to_packet(row)
    except sqlite3.DatabaseError as exc:
        raise DecisionChallengeStoreCorruptedError("challenge read failed") from exc
    finally:
        conn.close()


def append_challenge(
    packet: Mapping[str, Any],
    *,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Append one finalized packet. Exact replay returns the existing row."""

    validated = domain.challenge_packet_from_mapping(packet)
    path = resolve_decision_challenge_db_path(db_path)
    incoming_semantic = domain.semantic_replay_payload(validated)
    with _LOCK:
        initialize_store(path)
        conn = _connect(path)
        try:
            _validate_and_prepare_schema(conn, is_write=False)
            existing = conn.execute(
                "SELECT * FROM decision_challenges WHERE proposal_fingerprint = ?",
                (validated["proposal_fingerprint"],),
            ).fetchone()
            if existing is not None:
                stored = _row_to_packet(existing)
                if domain.semantic_replay_payload(stored) != incoming_semantic:
                    raise DecisionChallengeConflictError(
                        "conflicting challenge replay for this proposal fingerprint"
                    )
                return stored
            by_id = conn.execute(
                "SELECT * FROM decision_challenges WHERE challenge_id = ?",
                (validated["challenge_id"],),
            ).fetchone()
            if by_id is not None:
                raise DecisionChallengeConflictError(
                    "challenge_id already exists with a different fingerprint"
                )
            with conn:
                conn.execute(
                    """
                    INSERT INTO decision_challenges (
                        challenge_id, campaign_id, proposal_fingerprint,
                        proposal_as_of, packet_hash, packet_json,
                        finalized_at, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        validated["challenge_id"],
                        validated["campaign_id"],
                        validated["proposal_fingerprint"],
                        validated["proposal_as_of"],
                        validated["packet_hash"],
                        domain.canonical_json(validated),
                        validated["finalized_at"],
                        _utc_now(),
                    ),
                )
            return validated
        except DecisionChallengeStoreError:
            raise
        except sqlite3.IntegrityError as exc:
            raise DecisionChallengeConflictError(
                "challenge append violated uniqueness"
            ) from exc
        except sqlite3.DatabaseError as exc:
            raise DecisionChallengeStoreCorruptedError("challenge write failed") from exc
        finally:
            conn.close()


__all__ = [
    "DecisionChallengeConflictError",
    "DecisionChallengeStoreCorruptedError",
    "DecisionChallengeStoreError",
    "SCHEMA_VERSION",
    "append_challenge",
    "get_challenge",
    "get_challenge_by_fingerprint",
    "initialize_store",
    "resolve_decision_challenge_db_path",
]
