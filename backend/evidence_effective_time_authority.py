"""Evidence Effective-Time Authority producer (P0-ET1).

This module is the deterministic producer boundary for temporal provenance on
the existing Formal Evidence ledger.  It never infers effective time from
observation, record creation, or ingestion time and it never accepts a
caller-declared evaluation state.

The existing ``evidence_records`` row remains the Evidence body/identity
authority.  This module stores only immutable factual temporal intake rows in a
small companion table in the same SQLite ledger and derives the readback from
those rows.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import decision_evidence_delta_projection as ec1
import evidence_thesis_store as evidence_store

SCHEMA_VERSION = "evidence_temporal_authority.v0.1"

PROVEN = "PROVEN"
UNPROVEN = "UNPROVEN"
ERROR = "ERROR"

SOURCE_PUBLISHED_AT = "SOURCE_PUBLISHED_AT"
EVENT_OCCURRED_AT = "EVENT_OCCURRED_AT"
NONE = "NONE"

EVALUATED = "EVALUATED"
NOT_EVALUATED = "NOT_EVALUATED"

_EVIDENCE_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_CANONICAL_UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$")
_TEMPORAL_TABLE = "evidence_temporal_intakes"

_CREATE_TEMPORAL_TABLE = f"""
CREATE TABLE IF NOT EXISTS {_TEMPORAL_TABLE} (
    intake_id TEXT PRIMARY KEY NOT NULL,
    evidence_id TEXT NOT NULL,
    source_identity TEXT,
    event_identity TEXT,
    source_published_at TEXT,
    event_occurred_at TEXT,
    observed_at TEXT,
    created_at TEXT,
    ingested_at TEXT,
    payload_hash TEXT NOT NULL UNIQUE,
    recorded_at TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    FOREIGN KEY (evidence_id) REFERENCES evidence_records(id)
)
"""
_CREATE_TEMPORAL_EVIDENCE_INDEX = f"""
CREATE INDEX IF NOT EXISTS idx_{_TEMPORAL_TABLE}_evidence
ON {_TEMPORAL_TABLE}(evidence_id, recorded_at, intake_id)
"""

_EXPECTED_COLUMNS = (
    ("intake_id", "TEXT", 1, None, 1),
    ("evidence_id", "TEXT", 1, None, 0),
    ("source_identity", "TEXT", 0, None, 0),
    ("event_identity", "TEXT", 0, None, 0),
    ("source_published_at", "TEXT", 0, None, 0),
    ("event_occurred_at", "TEXT", 0, None, 0),
    ("observed_at", "TEXT", 0, None, 0),
    ("created_at", "TEXT", 0, None, 0),
    ("ingested_at", "TEXT", 0, None, 0),
    ("payload_hash", "TEXT", 1, None, 0),
    ("recorded_at", "TEXT", 1, None, 0),
    ("schema_version", "TEXT", 1, None, 0),
)
_EXPECTED_INDEX_COLUMNS = ("evidence_id", "recorded_at", "intake_id")
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")

PROVEN_PRODUCTION_PATH = "NOT_IMPLEMENTED"
TRUSTED_SOURCE_PRODUCER = "NOT_IMPLEMENTED"
TRUSTED_EVENT_PRODUCER = "NOT_IMPLEMENTED"


class TemporalAuthorityError(ValueError):
    """Malformed temporal input or an invalid Evidence identity."""


class TemporalAuthorityCorruptedError(RuntimeError):
    """Temporal companion data is inconsistent or cannot be read safely."""


@dataclass(frozen=True)
class TemporalIntake:
    """Factual temporal metadata accepted from a source/event intake."""

    evidence_id: str
    source_identity: str | None = None
    event_identity: str | None = None
    source_published_at: str | None = None
    event_occurred_at: str | None = None
    observed_at: str | None = None
    created_at: str | None = None
    ingested_at: str | None = None

    def __post_init__(self) -> None:
        if type(self.evidence_id) is not str or not _EVIDENCE_ID_RE.fullmatch(self.evidence_id):
            raise TemporalAuthorityError("evidence_id 必须是32位小写hex")
        for field in (
            "source_identity",
            "event_identity",
            "source_published_at",
            "event_occurred_at",
            "observed_at",
            "created_at",
            "ingested_at",
        ):
            value = getattr(self, field)
            if value is not None and (type(value) is not str or value != value.strip() or not value):
                raise TemporalAuthorityError(f"{field} 必须是非空规范文本或 null")
        for field in ("source_published_at", "event_occurred_at", "observed_at", "created_at", "ingested_at"):
            value = getattr(self, field)
            if value is not None:
                # Canonicalize before any database transaction.  This makes a
                # malformed public intake a 422 with zero durable writes.
                object.__setattr__(self, field, _canonical_timestamp(value, field))

    def payload(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "source_identity": self.source_identity,
            "event_identity": self.event_identity,
            "source_published_at": self.source_published_at,
            "event_occurred_at": self.event_occurred_at,
            "observed_at": self.observed_at,
            "created_at": self.created_at,
            "ingested_at": self.ingested_at,
        }


@dataclass(frozen=True)
class TemporalAuthorityResult:
    evidence_id: str
    temporal_state: str
    effective_at: str | None
    temporal_basis: str
    authority_refs: tuple[str, ...]
    reason_codes: tuple[str, ...]
    ec1_evaluation: str
    ec1_safe_item: ec1.NormalizedEvidenceItem | None
    observed_time_is_not_effective_time: bool = True

    def to_dict(self) -> dict[str, Any]:
        safe = None
        if self.ec1_safe_item is not None:
            safe = {
                "evidence_id": self.ec1_safe_item.evidence_id,
                "scope_kind": self.ec1_safe_item.scope_kind,
                "scope_id": self.ec1_safe_item.scope_id,
                "effective_at": self.ec1_safe_item.effective_at,
                "retrieved_at": self.ec1_safe_item.retrieved_at,
                "time_semantics": self.ec1_safe_item.time_semantics,
                "authority_refs": list(self.ec1_safe_item.authority_refs),
            }
        return {
            "schema_version": SCHEMA_VERSION,
            "evidence_id": self.evidence_id,
            "temporal_state": self.temporal_state,
            "effective_at": self.effective_at,
            "temporal_basis": self.temporal_basis,
            "authority_refs": list(self.authority_refs),
            "reason_codes": list(self.reason_codes),
            "ec1_evaluation": self.ec1_evaluation,
            "ec1_safe_item": safe,
            "observed_time_is_not_effective_time": self.observed_time_is_not_effective_time,
        }


def _parse_timestamp(value: str | None, field: str) -> datetime | None:
    if value is None:
        return None
    if _CANONICAL_UTC_RE.fullmatch(value) is None:
        raise TemporalAuthorityError(f"{field} 必须是canonical UTC时间戳")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise TemporalAuthorityError(f"{field} 不是有效UTC时间") from exc
    return parsed


def _canonical_timestamp(value: str | None, field: str) -> str | None:
    parsed = _parse_timestamp(value, field)
    return parsed.isoformat(timespec="microseconds").replace("+00:00", "Z") if parsed else None


def _payload_hash(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(dict(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _row_to_intake(row: Mapping[str, Any], expected_evidence_id: str) -> tuple[TemporalIntake, str]:
    """Rebuild and hash-check one persisted factual row before projection."""
    intake_id = row.get("intake_id")
    evidence_id = row.get("evidence_id")
    if (
        type(intake_id) is not str
        or not _EVIDENCE_ID_RE.fullmatch(intake_id)
        or evidence_id != expected_evidence_id
    ):
        raise TemporalAuthorityCorruptedError("Evidence temporal authority row identity is malformed")
    if row.get("schema_version") != SCHEMA_VERSION:
        raise TemporalAuthorityCorruptedError("Evidence temporal authority row schema_version is unsupported")
    persisted_hash = row.get("payload_hash")
    if type(persisted_hash) is not str or _HASH_RE.fullmatch(persisted_hash) is None:
        raise TemporalAuthorityCorruptedError("Evidence temporal authority payload_hash is malformed")
    try:
        recorded_at = row.get("recorded_at")
        _parse_timestamp(recorded_at, "recorded_at")
        intake = TemporalIntake(
            evidence_id=evidence_id,
            source_identity=row.get("source_identity"),
            event_identity=row.get("event_identity"),
            source_published_at=row.get("source_published_at"),
            event_occurred_at=row.get("event_occurred_at"),
            observed_at=row.get("observed_at"),
            created_at=row.get("created_at"),
            ingested_at=row.get("ingested_at"),
        )
    except TemporalAuthorityError as exc:
        raise TemporalAuthorityCorruptedError("Evidence temporal authority factual row is malformed") from exc
    recomputed = _payload_hash(intake.payload())
    if recomputed != persisted_hash:
        raise TemporalAuthorityCorruptedError("Evidence temporal authority payload_hash mismatch")
    return intake, intake_id


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _schema_object_type(conn: sqlite3.Connection) -> str | None:
    row = conn.execute(
        "SELECT type FROM sqlite_master WHERE name = ?",
        (_TEMPORAL_TABLE,),
    ).fetchone()
    return str(row[0]) if row is not None else None


def _assert_temporal_schema(conn: sqlite3.Connection) -> None:
    """Assert the exact ET1 extension schema; never repair an existing table."""
    if _schema_object_type(conn) != "table":
        raise TemporalAuthorityCorruptedError("Evidence temporal authority schema missing or is not a table")

    triggers = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'trigger' AND tbl_name = ? ORDER BY name",
        (_TEMPORAL_TABLE,),
    ).fetchall()
    if triggers:
        names = ", ".join(str(row[0]) for row in triggers)
        raise TemporalAuthorityCorruptedError(
            f"Evidence temporal authority must have zero triggers; found: {names}"
        )

    columns = tuple(
        (str(row[1]), str(row[2]), int(row[3]), row[4], int(row[5]))
        for row in conn.execute(f"PRAGMA table_info({_TEMPORAL_TABLE})").fetchall()
    )
    if columns != _EXPECTED_COLUMNS:
        raise TemporalAuthorityCorruptedError("Evidence temporal authority columns are malformed")

    foreign_keys = tuple(
        (str(row[2]), str(row[3]), str(row[4]))
        for row in conn.execute(f"PRAGMA foreign_key_list({_TEMPORAL_TABLE})").fetchall()
    )
    if foreign_keys != (("evidence_records", "evidence_id", "id"),):
        raise TemporalAuthorityCorruptedError("Evidence temporal authority foreign key is malformed")

    indexes = []
    for row in conn.execute(f"PRAGMA index_list({_TEMPORAL_TABLE})").fetchall():
        name = str(row[1])
        unique = int(row[2])
        origin = str(row[3])
        partial = int(row[4]) if len(row) > 4 else 0
        index_columns = tuple(
            str(info[2]) for info in conn.execute(f"PRAGMA index_info({name})").fetchall()
        )
        indexes.append((name, unique, origin, partial, index_columns))

    required = (
        (
            f"idx_{_TEMPORAL_TABLE}_evidence",
            0,
            "c",
            0,
            _EXPECTED_INDEX_COLUMNS,
        ),
    )
    if required[0] not in indexes:
        raise TemporalAuthorityCorruptedError("Evidence temporal authority evidence index is malformed")
    # The payload_hash UNIQUE contract is represented by SQLite's one
    # autoindex.  Do not accept a manually-created partial/non-unique variant.
    unique_hash_indexes = [
        item for item in indexes
        if item[1] == 1 and item[2] == "u" and item[3] == 0 and item[4] == ("payload_hash",)
    ]
    if len(unique_hash_indexes) != 1:
        raise TemporalAuthorityCorruptedError("Evidence temporal authority payload_hash UNIQUE is malformed")
    primary_key_indexes = [
        item for item in indexes
        if item[1] == 1 and item[2] == "pk" and item[3] == 0 and item[4] == ("intake_id",)
    ]
    if len(primary_key_indexes) != 1:
        raise TemporalAuthorityCorruptedError("Evidence temporal authority primary key index is malformed")
    allowed = {required[0], unique_hash_indexes[0], primary_key_indexes[0]}
    if set(indexes) != allowed:
        raise TemporalAuthorityCorruptedError("Evidence temporal authority has unexpected indexes")


def _ensure_temporal_schema_for_write(conn: sqlite3.Connection) -> None:
    """Create the extension only on first write; reject every existing mismatch."""
    if _schema_object_type(conn) is None:
        conn.execute(_CREATE_TEMPORAL_TABLE)
        conn.execute(_CREATE_TEMPORAL_EVIDENCE_INDEX)
    _assert_temporal_schema(conn)


def record_temporal_intake(
    intake: TemporalIntake,
    *,
    db_path: str | Path,
) -> dict[str, Any]:
    """Persist factual temporal metadata, idempotently and append-only."""
    payload = intake.payload()
    payload_hash = _payload_hash(payload)

    def _write(conn: sqlite3.Connection) -> dict[str, Any]:
        _ensure_temporal_schema_for_write(conn)
        evidence = evidence_store._get_evidence_row(conn, intake.evidence_id)
        if evidence is None:
            raise TemporalAuthorityError(f"证据 {intake.evidence_id} 不存在")
        # Validate every existing row for this Evidence before even checking
        # the idempotent hash path.  A corrupt old row must never be hidden by
        # a replay or bypassed by a different new intake.
        _validate_existing_rows(conn, intake.evidence_id)
        existing = conn.execute(
            f"SELECT * FROM {_TEMPORAL_TABLE} WHERE payload_hash = ?", (payload_hash,)
        ).fetchone()
        if existing is None:
            conn.execute(
                f"""
                INSERT INTO {_TEMPORAL_TABLE} (
                    intake_id, evidence_id, source_identity, event_identity,
                    source_published_at, event_occurred_at, observed_at,
                    created_at, ingested_at, payload_hash, recorded_at, schema_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    evidence_store.new_id(),
                    intake.evidence_id,
                    intake.source_identity,
                    intake.event_identity,
                    intake.source_published_at,
                    intake.event_occurred_at,
                    intake.observed_at,
                    intake.created_at,
                    intake.ingested_at,
                    payload_hash,
                    _utc_now(),
                    SCHEMA_VERSION,
                ),
            )
        else:
            # The hash lookup may find a row outside the target Evidence only
            # if the database has been tampered with.  Reuse the same row
            # validator and identity check before returning idempotent success.
            _row_to_intake(dict(existing), intake.evidence_id)
        return {"evidence_id": intake.evidence_id, "payload_hash": payload_hash}

    try:
        return evidence_store.write_transaction(db_path, _write)
    except evidence_store.EvidenceLedgerCorruptedError as exc:
        raise TemporalAuthorityCorruptedError() from exc


def _validate_existing_rows(conn: sqlite3.Connection, evidence_id: str) -> list[dict[str, Any]]:
    """Validate all durable rows for one Evidence before any write decision."""
    if _schema_object_type(conn) is None:
        return []
    _assert_temporal_schema(conn)
    rows = conn.execute(
        f"SELECT * FROM {_TEMPORAL_TABLE} WHERE evidence_id = ? ORDER BY recorded_at ASC, intake_id ASC",
        (evidence_id,),
    ).fetchall()
    payloads: list[dict[str, Any]] = []
    hashes: dict[str, str] = {}
    for row in rows:
        row_dict = dict(row)
        intake, intake_id = _row_to_intake(row_dict, evidence_id)
        payload_hash = str(row_dict["payload_hash"])
        previous_id = hashes.get(payload_hash)
        if previous_id is not None and previous_id != intake_id:
            raise TemporalAuthorityCorruptedError("Evidence temporal authority hash collision")
        hashes[payload_hash] = intake_id
        payloads.append(intake.payload())
    return payloads


def _read_rows(evidence_id: str, *, db_path: str | Path) -> list[dict[str, Any]]:
    def _read(conn: sqlite3.Connection) -> list[dict[str, Any]]:
        return _validate_existing_rows(conn, evidence_id)

    try:
        return evidence_store.read_transaction(db_path, _read)
    except FileNotFoundError:
        return []
    except evidence_store.EvidenceLedgerCorruptedError as exc:
        raise TemporalAuthorityCorruptedError() from exc


def _make_ec1_item(
    evidence: Mapping[str, Any],
    *,
    effective_at: str | None,
    authority_refs: tuple[str, ...],
    observed_at: str | None,
) -> ec1.NormalizedEvidenceItem | None:
    if evidence.get("subject_type") != "stock":
        return None
    scope_id = evidence.get("subject_id")
    if type(scope_id) is not str or re.fullmatch(r"\d{6}", scope_id) is None:
        return None
    if effective_at is None:
        return ec1.NormalizedEvidenceItem(
            evidence_id=evidence["id"],
            scope_kind=ec1.SCOPE_SECURITY,
            scope_id=scope_id,
            effective_at=None,
            retrieved_at=observed_at,
            time_semantics=ec1.TIME_SEMANTICS_UNKNOWN,
            authority_refs=authority_refs,
        )
    return ec1.NormalizedEvidenceItem(
        evidence_id=evidence["id"],
        scope_kind=ec1.SCOPE_SECURITY,
        scope_id=scope_id,
        effective_at=effective_at,
        retrieved_at=observed_at,
        time_semantics=ec1.TIME_SEMANTICS_AUTHORITATIVE,
        authority_refs=authority_refs,
    )


def _result(
    evidence: Mapping[str, Any],
    *,
    state: str,
    effective_at: str | None,
    basis: str,
    refs: tuple[str, ...],
    reasons: tuple[str, ...],
    observed_at: str | None,
    ec1_evaluation: str,
) -> TemporalAuthorityResult:
    safe_item = None
    if state != ERROR:
        safe_item = _make_ec1_item(
            evidence,
            effective_at=effective_at if ec1_evaluation == EVALUATED else None,
            authority_refs=refs,
            observed_at=observed_at,
        )
    return TemporalAuthorityResult(
        evidence_id=evidence["id"],
        temporal_state=state,
        effective_at=effective_at,
        temporal_basis=basis,
        authority_refs=refs,
        reason_codes=reasons,
        ec1_evaluation=ec1_evaluation,
        ec1_safe_item=safe_item,
    )


def evaluate_temporal_authority(
    evidence: Mapping[str, Any],
    intakes: tuple[Mapping[str, Any], ...],
    *,
    evaluation_as_of: str | None = None,
) -> TemporalAuthorityResult:
    """Project public factual metadata without promoting it to authority.

    ET1 R1 deliberately has no trusted source/event producer in this base:
    there is no durable source/event record linked to ``evidence_records.id``
    that this module can verify.  Therefore every public intake remains
    asserted metadata and can only produce UNPROVEN/NOT_EVALUATED.
    """
    evidence_id = evidence.get("id")
    if type(evidence_id) is not str or not _EVIDENCE_ID_RE.fullmatch(evidence_id):
        raise TemporalAuthorityError("Evidence identity malformed")
    if evaluation_as_of is not None:
        _canonical_timestamp(evaluation_as_of, "evaluation_as_of")
    observed_values = [row.get("observed_at") for row in intakes if row.get("observed_at")]
    reasons = [
        "PUBLIC_METADATA_NOT_AUTHORITY",
        "SUBMITTED_METADATA_NOT_SOURCE_AUTHORITY",
        "NO_EFFECTIVE_TIME_AUTHORITY",
    ]
    if observed_values:
        reasons.append("OBSERVED_TIME_NOT_EFFECTIVE_TIME")
    if any(row.get("created_at") for row in intakes):
        reasons.append("CREATED_TIME_NOT_EFFECTIVE_TIME")
    if any(row.get("ingested_at") for row in intakes):
        reasons.append("INGESTED_TIME_NOT_EFFECTIVE_TIME")
    return _result(
        evidence,
        state=UNPROVEN,
        effective_at=None,
        basis=NONE,
        refs=(),
        reasons=tuple(dict.fromkeys(reasons)),
        observed_at=observed_values[-1] if observed_values else None,
        ec1_evaluation=NOT_EVALUATED,
    )


def get_temporal_authority(
    evidence_id: str,
    *,
    db_path: str | Path,
    evaluation_as_of: str | None = None,
) -> TemporalAuthorityResult | None:
    """Read existing Evidence identity/body and derive durable temporal status."""
    if type(evidence_id) is not str or not _EVIDENCE_ID_RE.fullmatch(evidence_id):
        raise TemporalAuthorityError("evidence_id 必须是32位小写hex")

    def _read(conn: sqlite3.Connection) -> dict[str, Any] | None:
        row = evidence_store._get_evidence_row(conn, evidence_id)
        if row is None:
            return None
        rows = _validate_existing_rows(conn, evidence_id)
        return {"evidence": evidence_store._evidence_row_to_dict(row), "rows": rows}

    try:
        found = evidence_store.read_transaction(db_path, _read)
    except FileNotFoundError:
        return None
    except evidence_store.EvidenceLedgerCorruptedError as exc:
        raise TemporalAuthorityCorruptedError() from exc
    if found is None:
        return None
    return evaluate_temporal_authority(
        found["evidence"], tuple(found["rows"]), evaluation_as_of=evaluation_as_of
    )
