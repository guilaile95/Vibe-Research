"""Read-only, bounded Data Health relationship projection.

Only evidence_ledger storage membership and persisted Thesis→Evidence links
are registered here. Source-wide provider events do not identify a security.
This view owns neither evidence truth, Critical Data/FrozenGate nor repair.
"""
from __future__ import annotations

import sqlite3
from typing import Any
from urllib.parse import quote

SCHEMA_VERSION = "data-health-impact.v1"
MAX_LINK_ROWS = 200


def _empty(source_id: str, state: str, reason: str) -> dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, "source_id": source_id,
            "mapping_state": state, "reason_code": reason,
            "items": [], "truncated": False}


def project_ledger_links(rows: list[dict[str, Any]], *, truncated: bool = False) -> dict[str, Any]:
    """Project exact persisted links; reject ambiguous identities, never guess joins."""
    result = _empty("evidence_ledger", "mapped", "PERSISTED_LEDGER_LINKS")
    items: dict[str, dict[str, Any]] = {}
    seen: set[tuple[str, str]] = set()
    for row in rows:
        tid, eid = row["thesis_id"], row["evidence_id"]
        if not isinstance(tid, str) or not tid or not isinstance(eid, str) or not eid:
            return _empty("evidence_ledger", "unknown", "INVALID_RELATIONSHIP")
        key = (tid, eid)
        if key in seen:
            return _empty("evidence_ledger", "unknown", "AMBIGUOUS_RELATIONSHIP")
        seen.add(key)
        subject = (row["subject_type"], row["subject_id"])
        if subject[0] not in {"stock", "sector", "theme"} or not isinstance(subject[1], str) or not subject[1]:
            return _empty("evidence_ledger", "unknown", "INVALID_RELATIONSHIP")
        frozen = row["formal_state"] == "frozen"
        if tid not in items:
            items[tid] = {"thesis_id": tid, "title": row["title"],
                          "subject_type": subject[0], "subject_id": subject[1],
                          "frozen": frozen, "evidence": [],
                          "path": f"/thesis/{quote(tid, safe='')}"}
        elif (items[tid]["subject_type"], items[tid]["subject_id"], items[tid]["frozen"], items[tid]["title"]) != (*subject, frozen, row["title"]):
            return _empty("evidence_ledger", "unknown", "AMBIGUOUS_RELATIONSHIP")
        if row["live_evidence_id"] is None or row["deleted"] == 1:
            state = "missing"
        elif (row["evidence_subject_type"], row["evidence_subject_id"]) != subject:
            state = "subject_mismatch"
        else:
            state = "available"
        items[tid]["evidence"].append({
            "evidence_id": eid, "state": state,
            # A wrong-subject or missing live record is not a permitted drill-down.
            "path": f"/evidence/{quote(eid, safe='')}" if state == "available" else None,
        })
    result["items"] = list(items.values())
    result["truncated"] = truncated
    return result


def get_source_impact(source_id: str) -> dict[str, Any]:
    if source_id != "evidence_ledger":
        return _empty(source_id, "unmapped", "NO_REGISTERED_OBJECT_BINDING")
    import evidence_thesis_service as service
    import evidence_thesis_store as store

    try:
        with store.readonly_health_snapshot(service.resolve_db_path()) as conn:
            conn.execute("BEGIN")
            if store._read_schema_version(conn) != store.SCHEMA_VERSION:
                return _empty(source_id, "unknown", "LEDGER_SCHEMA_UNAVAILABLE")
            # LEFT JOIN exposes missing endpoints without inventing a subject
            # or changing frozen snapshots. An orphan Thesis is UNKNOWN.
            rows = conn.execute("""
                SELECT t.id AS thesis_id, t.title, t.subject_type, t.subject_id,
                       t.formal_state, l.evidence_id, e.id AS live_evidence_id,
                       e.subject_type AS evidence_subject_type,
                       e.subject_id AS evidence_subject_id, e.deleted
                FROM thesis_evidence_links l
                LEFT JOIN investment_theses t ON t.id = l.thesis_id
                LEFT JOIN evidence_records e ON e.id = l.evidence_id
                ORDER BY t.id, l.evidence_id LIMIT ?
            """, (MAX_LINK_ROWS + 1,)).fetchall()
            return project_ledger_links([dict(row) for row in rows[:MAX_LINK_ROWS]],
                                        truncated=len(rows) > MAX_LINK_ROWS)
    except (OSError, sqlite3.Error, store.EvidenceLedgerCorruptedError,
            store.EvidenceLedgerSchemaVersionError, store._ReadonlySnapshotUnavailable):
        return _empty(source_id, "unknown", "LEDGER_RELATIONSHIPS_UNAVAILABLE")
