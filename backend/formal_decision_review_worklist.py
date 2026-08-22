"""Deterministic Formal Decision Review Due Worklist projection.

This module is a read-only projection over already evaluated OL1 rows.  It does
not read a clock, perform I/O, persist queue state, or infer review dates.
"""

from __future__ import annotations

import copy
import re
from datetime import datetime
from typing import Any, Iterable, Mapping

SCHEMA_VERSION = "formal_decision_review_worklist.v0.2"
DUE_STATES = ("DUE", "NOT_DUE", "ERROR")
WORKLIST_GROUPS = ("due", "upcoming", "unavailable")
_DECISION_ID_RE = re.compile(r"^decision_[0-9a-f]{32}$")


class ReviewWorklistProjectionError(ValueError):
    """The worklist cannot be truthfully projected."""


def _parse_utc(value: object, field: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ReviewWorklistProjectionError(f"{field} must be a UTC instant")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ReviewWorklistProjectionError(f"{field} must be a UTC instant") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None or parsed.utcoffset().total_seconds() != 0:
        raise ReviewWorklistProjectionError(f"{field} must be a zero-offset UTC instant")
    return parsed


def _reason_codes(row: Mapping[str, Any]) -> list[str]:
    values = row.get("reason_codes")
    if values is None:
        return []
    if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
        raise ReviewWorklistProjectionError("reason_codes must be a list of strings")
    return list(values)


def _compact_item(
    row: Mapping[str, Any],
    *,
    due_state: str,
    group: str,
    error_code: str | None = None,
) -> dict[str, Any]:
    decision_id = row.get("decision_id")
    if not isinstance(decision_id, str) or _DECISION_ID_RE.fullmatch(decision_id) is None:
        raise ReviewWorklistProjectionError("decision_id is invalid")
    review_by = row.get("decision_review_by")
    _parse_utc(review_by, "decision_review_by")
    if due_state not in DUE_STATES:
        raise ReviewWorklistProjectionError("due_state is invalid")
    if group not in WORKLIST_GROUPS:
        raise ReviewWorklistProjectionError("worklist group is invalid")
    if group == "due" and due_state != "DUE":
        raise ReviewWorklistProjectionError("DUE row has an invalid canonical due state")
    if group == "upcoming" and due_state != "NOT_DUE":
        raise ReviewWorklistProjectionError("UPCOMING row has an invalid canonical due state")
    if group == "unavailable" and due_state != "ERROR":
        raise ReviewWorklistProjectionError("unavailable row has an invalid canonical due state")

    item = {
        "decision_id": decision_id,
        "decision_snapshot_hash": row.get("decision_snapshot_hash"),
        "security_code": row.get("security_code"),
        "strategy": row.get("strategy"),
        "campaign_id": row.get("campaign_id"),
        "decision_committed_at": row.get("decision_committed_at"),
        "decision_review_by": review_by,
        "decision_next_best_action": row.get("decision_next_best_action"),
        "due_state": due_state,
        "outcome_status": row.get("outcome_status"),
        "reason_codes": _reason_codes(row),
        "group": group,
    }
    if error_code is not None:
        item["error_code"] = error_code
    return item


def _sort_key(item: Mapping[str, Any]) -> tuple[str, str]:
    return (str(item["decision_review_by"]), str(item["decision_id"]))


def project_review_worklist(
    rows: Iterable[Mapping[str, Any]],
    *,
    evaluation_as_of: str,
) -> dict[str, Any]:
    """Project evaluated OL1 rows into the complete operational worklist.

    ``evaluation_as_of`` is deliberately explicit so callers cannot hide a
    wall-clock read inside this pure projection.
    """
    _parse_utc(evaluation_as_of, "evaluation_as_of")
    due: list[dict[str, Any]] = []
    upcoming: list[dict[str, Any]] = []
    unavailable: list[dict[str, Any]] = []
    seen: set[str] = set()

    for row in rows:
        if not isinstance(row, Mapping):
            raise ReviewWorklistProjectionError("worklist row must be a mapping")
        decision_id = row.get("decision_id")
        if decision_id in seen:
            raise ReviewWorklistProjectionError("duplicate decision_id in worklist")
        if isinstance(decision_id, str):
            seen.add(decision_id)

        raw_state = row.get("due_state")
        try:
            if raw_state == "DUE":
                due.append(_compact_item(row, due_state="DUE", group="due"))
            elif raw_state == "NOT_DUE":
                upcoming.append(_compact_item(row, due_state="NOT_DUE", group="upcoming"))
            elif raw_state == "ERROR":
                unavailable.append(
                    _compact_item(
                        row,
                        due_state="ERROR",
                        group="unavailable",
                        error_code=str(row.get("error_code") or "FORMAL_OUTCOME_ERROR"),
                    )
                )
            else:
                unavailable.append(
                    _compact_item(
                        row,
                        due_state="ERROR",
                        group="unavailable",
                        error_code="UNKNOWN_DUE_STATE",
                    )
                )
        except ReviewWorklistProjectionError:
            # A malformed row is itself unavailable, but only if its identity
            # and review boundary are still safe to display.
            try:
                unavailable.append(
                    _compact_item(
                        row,
                        due_state="ERROR",
                        group="unavailable",
                        error_code="MALFORMED_WORKLIST_ROW",
                    )
                )
            except ReviewWorklistProjectionError as exc:
                raise ReviewWorklistProjectionError("malformed worklist row") from exc

    due.sort(key=_sort_key)
    upcoming.sort(key=_sort_key)
    unavailable.sort(key=lambda item: str(item["decision_id"]))
    return {
        "schema_version": SCHEMA_VERSION,
        "evaluation_as_of": evaluation_as_of,
        "due": copy.deepcopy(due),
        "upcoming": copy.deepcopy(upcoming),
        "unavailable": copy.deepcopy(unavailable),
        "counts": {
            "due": len(due),
            "upcoming": len(upcoming),
            "unavailable": len(unavailable),
            "total": len(due) + len(upcoming) + len(unavailable),
        },
        "authority_refs": [
            "frozen_decision_store",
            "formal_decision_outcome",
            "formal_decision_review_worklist",
        ],
    }


__all__ = [
    "DUE_STATES",
    "ReviewWorklistProjectionError",
    "SCHEMA_VERSION",
    "WORKLIST_GROUPS",
    "project_review_worklist",
]
