"""Append-only storage for advisory Campaign decision drafts.

These records are model proposals, never Formal Decisions.  They are stored
separately so Preview/Commit can verify provenance without trusting browser
claims or overloading the date-keyed ``ai_results`` cache.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = "campaign-decision-draft-store.v0.1"
DRAFT_SCHEMA_VERSION = "campaign-decision-draft.v0.1"

_DRAFT_ID_RE = re.compile(r"^decision_draft_[0-9a-f]{32}$")
_CAMPAIGN_ID_RE = re.compile(r"^campaign_[0-9a-f]{32}$")
_THESIS_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_CODE_RE = re.compile(r"^\d{6}$")
_FP_RE = re.compile(r"^[0-9a-f]{64}$")
_STRATEGIES = {"SHORT", "SWING", "MEDIUM"}


class DecisionDraftStoreError(RuntimeError):
    pass


class DecisionDraftCorruptedError(DecisionDraftStoreError):
    pass


class DecisionDraftConflictError(DecisionDraftStoreError):
    pass


def resolve_db_path(explicit_path: str | Path | None = None) -> Path:
    if explicit_path is not None:
        return Path(explicit_path)
    configured = os.environ.get("VIBE_RESEARCH_DECISION_DRAFT_DB", "").strip()
    if configured:
        return Path(configured)
    data_dir = os.environ.get("VR_DATA_DIR", "").strip()
    if data_dir:
        return Path(data_dir) / "decision_drafts.sqlite3"
    return Path.home() / ".vibe-research" / "decision_drafts.sqlite3"


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _record_hash(record: Mapping[str, Any]) -> str:
    protected = {key: value for key, value in record.items() if key != "record_hash"}
    return hashlib.sha256(canonical_json(protected).encode("utf-8")).hexdigest()


def _validate(record: Mapping[str, Any]) -> dict[str, Any]:
    required = {
        "schema_version",
        "draft_id",
        "campaign_id",
        "security_code",
        "strategy",
        "thesis_id",
        "thesis_revision",
        "holding_fingerprint",
        "context_fingerprint",
        "context_as_of",
        "generated_at",
        "model_provider",
        "model_name",
        "prompt_version",
        "analysis_policy_version",
        "payload",
    }
    if set(record) != required and set(record) != required | {"record_hash"}:
        raise DecisionDraftCorruptedError("decision draft fields are invalid")
    if record.get("schema_version") != DRAFT_SCHEMA_VERSION:
        raise DecisionDraftCorruptedError("decision draft schema is incompatible")
    if not isinstance(record.get("draft_id"), str) or not _DRAFT_ID_RE.fullmatch(record["draft_id"]):
        raise DecisionDraftCorruptedError("decision draft id is invalid")
    if not isinstance(record.get("campaign_id"), str) or not _CAMPAIGN_ID_RE.fullmatch(record["campaign_id"]):
        raise DecisionDraftCorruptedError("decision draft Campaign id is invalid")
    if not isinstance(record.get("security_code"), str) or not _CODE_RE.fullmatch(record["security_code"]):
        raise DecisionDraftCorruptedError("decision draft security code is invalid")
    if record.get("strategy") not in _STRATEGIES:
        raise DecisionDraftCorruptedError("decision draft strategy is invalid")
    if not isinstance(record.get("thesis_id"), str) or not _THESIS_ID_RE.fullmatch(record["thesis_id"]):
        raise DecisionDraftCorruptedError("decision draft Thesis id is invalid")
    revision = record.get("thesis_revision")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision <= 0:
        raise DecisionDraftCorruptedError("decision draft Thesis revision is invalid")
    for field in ("holding_fingerprint", "context_fingerprint"):
        value = record.get(field)
        if not isinstance(value, str) or not _FP_RE.fullmatch(value):
            raise DecisionDraftCorruptedError(f"decision draft {field} is invalid")
    for field in (
        "context_as_of",
        "generated_at",
        "model_provider",
        "model_name",
        "prompt_version",
        "analysis_policy_version",
    ):
        value = record.get(field)
        if not isinstance(value, str) or not value.strip() or value != value.strip():
            raise DecisionDraftCorruptedError(f"decision draft {field} is invalid")
    if not isinstance(record.get("payload"), Mapping):
        raise DecisionDraftCorruptedError("decision draft payload is invalid")
    try:
        canonical_json(record["payload"])
    except (TypeError, ValueError) as exc:
        raise DecisionDraftCorruptedError("decision draft payload is not JSON-safe") from exc
    normalized = {key: record[key] for key in required}
    expected_hash = _record_hash(normalized)
    supplied_hash = record.get("record_hash")
    if supplied_hash is not None and supplied_hash != expected_hash:
        raise DecisionDraftCorruptedError("decision draft hash mismatch")
    normalized["record_hash"] = expected_hash
    return normalized


_DDL = """
CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS decision_drafts (
    draft_id TEXT PRIMARY KEY,
    campaign_id TEXT NOT NULL,
    security_code TEXT NOT NULL,
    strategy TEXT NOT NULL,
    thesis_id TEXT NOT NULL,
    thesis_revision INTEGER NOT NULL,
    generated_at TEXT NOT NULL,
    record_hash TEXT NOT NULL,
    record_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_decision_drafts_campaign
ON decision_drafts(campaign_id, generated_at);
"""


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_DDL)
    row = conn.execute(
        "SELECT value FROM schema_meta WHERE key = 'schema_version'"
    ).fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO schema_meta(key, value) VALUES('schema_version', ?)",
            (SCHEMA_VERSION,),
        )
    elif row["value"] != SCHEMA_VERSION:
        raise DecisionDraftCorruptedError("decision draft store schema is incompatible")


def append(record: Mapping[str, Any], db_path: str | Path | None = None) -> dict[str, Any]:
    normalized = _validate(record)
    path = resolve_db_path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _connect(path) as conn:
        _ensure_schema(conn)
        existing = conn.execute(
            "SELECT record_json FROM decision_drafts WHERE draft_id = ?",
            (normalized["draft_id"],),
        ).fetchone()
        encoded = canonical_json(normalized)
        if existing is not None:
            if existing["record_json"] != encoded:
                raise DecisionDraftConflictError("decision draft id already has different content")
            return normalized
        conn.execute(
            """INSERT INTO decision_drafts(
                draft_id, campaign_id, security_code, strategy, thesis_id,
                thesis_revision, generated_at, record_hash, record_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                normalized["draft_id"],
                normalized["campaign_id"],
                normalized["security_code"],
                normalized["strategy"],
                normalized["thesis_id"],
                normalized["thesis_revision"],
                normalized["generated_at"],
                normalized["record_hash"],
                encoded,
            ),
        )
    return normalized


def get(draft_id: str, db_path: str | Path | None = None) -> dict[str, Any] | None:
    if not isinstance(draft_id, str) or not _DRAFT_ID_RE.fullmatch(draft_id):
        raise DecisionDraftCorruptedError("decision draft id is invalid")
    path = resolve_db_path(db_path)
    if not path.is_file():
        return None
    uri = f"{path.resolve().as_uri()}?mode=ro"
    try:
        conn = sqlite3.connect(uri, timeout=5, uri=True)
        conn.row_factory = sqlite3.Row
        try:
            meta = conn.execute(
                "SELECT value FROM schema_meta WHERE key = 'schema_version'"
            ).fetchone()
            if meta is None or meta["value"] != SCHEMA_VERSION:
                raise DecisionDraftCorruptedError("decision draft store schema is incompatible")
            row = conn.execute(
                "SELECT record_json, record_hash FROM decision_drafts WHERE draft_id = ?",
                (draft_id,),
            ).fetchone()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        raise DecisionDraftCorruptedError("decision draft store is unreadable") from exc
    if row is None:
        return None
    try:
        raw = json.loads(row["record_json"])
    except (json.JSONDecodeError, TypeError) as exc:
        raise DecisionDraftCorruptedError("decision draft record is corrupted") from exc
    if not isinstance(raw, Mapping) or raw.get("record_hash") != row["record_hash"]:
        raise DecisionDraftCorruptedError("decision draft row integrity mismatch")
    return _validate(raw)


__all__ = [
    "DRAFT_SCHEMA_VERSION",
    "DecisionDraftConflictError",
    "DecisionDraftCorruptedError",
    "DecisionDraftStoreError",
    "append",
    "canonical_json",
    "get",
    "resolve_db_path",
]
