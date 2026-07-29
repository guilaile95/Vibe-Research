"""Decision feedback analytics service (P2-4A).

Aggregates adoption and outcome statistics from the decision_feedback table.
All operations are read-only.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import decision_feedback_service as _fb_svc
import decision_feedback_store as _fb_store

_ADOPTION_ZERO: dict[str, int] = {
    "followed": 0,
    "partially_followed": 0,
    "not_followed": 0,
    "not_applicable": 0,
}

_OUTCOME_ZERO: dict[str, int] = {
    "better_than_expected": 0,
    "as_expected": 0,
    "worse_than_expected": 0,
    "not_evaluated": 0,
}


def _connect_ro(db_path: Path) -> sqlite3.Connection:
    """Open read-only connection."""
    uri = f"{db_path.resolve().as_uri()}?mode=ro"
    conn = sqlite3.connect(uri, timeout=5.0, uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def _table_exists(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        ("decision_feedback",),
    ).fetchone()
    return row is not None


def _build_date_clauses(
    date_from: str | None,
    date_to: str | None,
    params: list[Any],
) -> list[str]:
    clauses: list[str] = []
    if date_from is not None:
        clauses.append("date(created_at) >= ?")
        params.append(date_from)
    if date_to is not None:
        clauses.append("date(created_at) <= ?")
        params.append(date_to)
    return clauses


def get_adoption_summary(
    *,
    date_from: str | None = None,
    date_to: str | None = None,
    db_path: Path | None = None,
) -> dict[str, Any]:
    """Return adoption status distribution (excluding voided records).

    Returns:
        {
          "total": int,
          "counts": {
            "followed": int, "partially_followed": int,
            "not_followed": int, "not_applicable": int
          },
          "adoption_rate": float | None,
          "date_from": str | None,
          "date_to": str | None,
        }
    """
    empty = {
        "total": 0,
        "counts": dict(_ADOPTION_ZERO),
        "adoption_rate": None,
        "date_from": date_from,
        "date_to": date_to,
    }

    resolved = _fb_svc.resolve_db_path(db_path)
    if not resolved.is_file():
        return empty

    try:
        with _connect_ro(resolved) as conn:
            if not _table_exists(conn):
                return empty

            params: list[Any] = []
            clauses: list[str] = ["voided_at IS NULL"]
            clauses.extend(_build_date_clauses(date_from, date_to, params))

            where = " WHERE " + " AND ".join(clauses)
            sql = (
                "SELECT adoption_status, COUNT(*) as cnt FROM decision_feedback"
                + where
                + " GROUP BY adoption_status"
            )
            rows = conn.execute(sql, params).fetchall()

            counts = dict(_ADOPTION_ZERO)
            for row in rows:
                status = row["adoption_status"]
                if status in counts:
                    counts[status] = row["cnt"]

            total = sum(counts.values())
            if total == 0:
                adoption_rate = None
            else:
                adoption_rate = (counts["followed"] + counts["partially_followed"]) / total

            return {
                "total": total,
                "counts": counts,
                "adoption_rate": adoption_rate,
                "date_from": date_from,
                "date_to": date_to,
            }
    except (sqlite3.DatabaseError, sqlite3.OperationalError) as exc:
        raise _fb_store.DecisionFeedbackCorruptedError() from exc


def get_outcome_summary(
    *,
    adoption_status: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    db_path: Path | None = None,
) -> dict[str, Any]:
    """Return outcome status distribution (excluding voided records).

    Returns:
        {
          "total": int,
          "counts": {
            "better_than_expected": int, "as_expected": int,
            "worse_than_expected": int, "not_evaluated": int
          },
          "positive_rate": float | None,
          "adoption_status": str | None,
          "date_from": str | None,
          "date_to": str | None,
        }
    """
    empty = {
        "total": 0,
        "counts": dict(_OUTCOME_ZERO),
        "positive_rate": None,
        "adoption_status": adoption_status,
        "date_from": date_from,
        "date_to": date_to,
    }

    resolved = _fb_svc.resolve_db_path(db_path)
    if not resolved.is_file():
        return empty

    try:
        with _connect_ro(resolved) as conn:
            if not _table_exists(conn):
                return empty

            params: list[Any] = []
            clauses: list[str] = ["voided_at IS NULL"]
            if adoption_status is not None:
                clauses.append("adoption_status = ?")
                params.append(adoption_status)
            clauses.extend(_build_date_clauses(date_from, date_to, params))

            where = " WHERE " + " AND ".join(clauses)
            sql = (
                "SELECT outcome_status, COUNT(*) as cnt FROM decision_feedback"
                + where
                + " GROUP BY outcome_status"
            )
            rows = conn.execute(sql, params).fetchall()

            counts = dict(_OUTCOME_ZERO)
            for row in rows:
                status = row["outcome_status"]
                if status in counts:
                    counts[status] = row["cnt"]

            total = sum(counts.values())
            evaluated = total - counts["not_evaluated"]
            if evaluated == 0:
                positive_rate = None
            else:
                positive_rate = (counts["better_than_expected"] + counts["as_expected"]) / evaluated

            return {
                "total": total,
                "counts": counts,
                "positive_rate": positive_rate,
                "adoption_status": adoption_status,
                "date_from": date_from,
                "date_to": date_to,
            }
    except (sqlite3.DatabaseError, sqlite3.OperationalError) as exc:
        raise _fb_store.DecisionFeedbackCorruptedError() from exc


def get_stock_summary(
    *,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 20,
    db_path: Path | None = None,
) -> list[dict[str, Any]]:
    """Return per-stock adoption+outcome aggregation sorted by total desc.

    Each item:
        {
          "code": str,
          "total": int,
          "adoption_followed_count": int,  # followed + partially_followed
          "adoption_rate": float | None,
          "outcome_positive_count": int,   # better+as_expected (excl not_evaluated)
          "outcome_positive_rate": float | None,
        }
    """
    resolved = _fb_svc.resolve_db_path(db_path)
    if not resolved.is_file():
        return []

    try:
        with _connect_ro(resolved) as conn:
            if not _table_exists(conn):
                return []

            params: list[Any] = []
            clauses: list[str] = ["voided_at IS NULL"]
            clauses.extend(_build_date_clauses(date_from, date_to, params))

            where = " WHERE " + " AND ".join(clauses)
            sql = (
                "SELECT"
                "  code,"
                "  COUNT(*) AS total,"
                "  SUM(CASE WHEN adoption_status IN ('followed','partially_followed') THEN 1 ELSE 0 END) AS adoption_followed_count,"
                "  SUM(CASE WHEN outcome_status IN ('better_than_expected','as_expected') THEN 1 ELSE 0 END) AS outcome_positive_count,"
                "  SUM(CASE WHEN outcome_status = 'not_evaluated' THEN 1 ELSE 0 END) AS not_evaluated_count"
                " FROM decision_feedback"
                + where
                + " GROUP BY code ORDER BY total DESC LIMIT ?"
            )
            params.append(limit)
            rows = conn.execute(sql, params).fetchall()

            result = []
            for row in rows:
                total = row["total"]
                adoption_followed = row["adoption_followed_count"]
                outcome_positive = row["outcome_positive_count"]
                not_evaluated = row["not_evaluated_count"]
                evaluated = total - not_evaluated

                adoption_rate = adoption_followed / total if total > 0 else None
                outcome_positive_rate = outcome_positive / evaluated if evaluated > 0 else None

                result.append({
                    "code": row["code"],
                    "total": total,
                    "adoption_followed_count": adoption_followed,
                    "adoption_rate": adoption_rate,
                    "outcome_positive_count": outcome_positive,
                    "outcome_positive_rate": outcome_positive_rate,
                })

            return result
    except (sqlite3.DatabaseError, sqlite3.OperationalError) as exc:
        raise _fb_store.DecisionFeedbackCorruptedError() from exc
