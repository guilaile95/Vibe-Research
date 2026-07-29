"""Signal ledger SQLite storage layer.

Provides storage and query mechanisms for signal entries and final decision outcomes
associated with decision runs in decision_trace.sqlite3.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Mapping

import decision_trace_store as trace_store

_LOCK = threading.Lock()


class SignalLedgerError(RuntimeError):
    """Base exception for signal ledger errors."""


class SignalLedgerCorruptedError(SignalLedgerError):
    """Raised when signal ledger database data is corrupted."""

    MESSAGE = "信号账本数据损坏，已停止读写"

    def __init__(self, message: str | None = None):
        super().__init__(message or self.MESSAGE)


class SignalLedgerNotFoundError(SignalLedgerError, LookupError):
    """Raised when a signal ledger record is not found."""


def save_signal_ledger_bundle(
    decision_run_id: str,
    signal_entries: list[Mapping[str, Any]],
    decision_outcomes: list[Mapping[str, Any]],
    trade_date: str | None = None,
    generated_at: str | None = None,
    db_path: str | Path | None = None,
) -> None:
    """Save signal entries and decision outcomes atomically into decision_trace DB."""
    path = trace_store.resolve_decision_trace_db_path(db_path)
    trace_store.init_db(path)

    with _LOCK:
        try:
            conn = trace_store._get_write_connection(path)
            try:
                with conn:
                    # Ensure decision_runs record exists
                    now_str = trace_store._utc_now()
                    conn.execute(
                        """
                        INSERT INTO decision_runs (
                            decision_run_id, trade_date, generated_at, result_type,
                            schema_version, market_status, source_fingerprint, trace_status, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(decision_run_id) DO NOTHING
                        """,
                        (
                            decision_run_id,
                            trade_date or now_str[:10],
                            generated_at or now_str,
                            "portfolio_advice",
                            "v1",
                            "normal",
                            None,
                            "archived",
                            now_str,
                        ),
                    )

                    # Upsert signal entries
                    for se in signal_entries:
                        payload_str = (
                            json.dumps(se["payload_json"], ensure_ascii=False)
                            if isinstance(se.get("payload_json"), (dict, list))
                            else str(se.get("payload_json") or "{}")
                        )
                        conn.execute(
                            """
                            INSERT INTO signal_entries (
                                entry_id, decision_run_id, stage, code, signal_type,
                                severity, payload_json, created_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                            ON CONFLICT(entry_id) DO UPDATE SET
                                stage=excluded.stage,
                                code=excluded.code,
                                signal_type=excluded.signal_type,
                                severity=excluded.severity,
                                payload_json=excluded.payload_json,
                                created_at=excluded.created_at
                            """,
                            (
                                se["entry_id"],
                                decision_run_id,
                                se["stage"],
                                se.get("code"),
                                se["signal_type"],
                                se["severity"],
                                payload_str,
                                se["created_at"],
                            ),
                        )

                    # Upsert decision outcomes
                    for do in decision_outcomes:
                        constraints_str = (
                            json.dumps(do.get("constraints_applied_json") or [], ensure_ascii=False)
                            if isinstance(do.get("constraints_applied_json"), list)
                            else str(do.get("constraints_applied_json") or "[]")
                        )
                        conn.execute(
                            """
                            INSERT INTO decision_outcomes (
                                outcome_id, decision_run_id, code, action,
                                target_ratio, reason, constraints_applied_json, created_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                            ON CONFLICT(outcome_id) DO UPDATE SET
                                code=excluded.code,
                                action=excluded.action,
                                target_ratio=excluded.target_ratio,
                                reason=excluded.reason,
                                constraints_applied_json=excluded.constraints_applied_json,
                                created_at=excluded.created_at
                            """,
                            (
                                do["outcome_id"],
                                decision_run_id,
                                do["code"],
                                do["action"],
                                do.get("target_ratio"),
                                do["reason"],
                                constraints_str,
                                do["created_at"],
                            ),
                        )
            finally:
                conn.close()
        except sqlite3.DatabaseError as exc:
            raise SignalLedgerCorruptedError() from exc


def query_signal_entries(
    decision_run_id: str | None = None,
    stage: str | None = None,
    code: str | None = None,
    severity: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Query signal entries with filtering and pagination."""
    path = trace_store.resolve_decision_trace_db_path(db_path)
    limit = max(1, min(limit, 200))
    offset = max(0, offset)

    try:
        conn = trace_store._get_read_connection(path)
        try:
            where_clauses: list[str] = []
            params: list[Any] = []

            if decision_run_id:
                where_clauses.append("decision_run_id = ?")
                params.append(decision_run_id)

            if stage:
                where_clauses.append("stage = ?")
                params.append(stage)

            if code:
                where_clauses.append("code = ?")
                params.append(code)

            if severity:
                where_clauses.append("severity = ?")
                params.append(severity)

            where_sql = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

            count_sql = f"SELECT COUNT(*) as cnt FROM signal_entries {where_sql}"
            total = conn.execute(count_sql, params).fetchone()["cnt"]

            query_sql = f"""
                SELECT * FROM signal_entries
                {where_sql}
                ORDER BY created_at ASC
                LIMIT ? OFFSET ?
            """
            rows = conn.execute(query_sql, params + [limit, offset]).fetchall()

            entries = []
            for r in rows:
                d = dict(r)
                try:
                    d["payload_json"] = json.loads(d["payload_json"])
                except Exception:
                    pass
                entries.append(d)

            return {
                "items": entries,
                "total": total,
                "limit": limit,
                "offset": offset,
            }
        finally:
            conn.close()
    except sqlite3.DatabaseError as exc:
        raise SignalLedgerCorruptedError() from exc


def get_run_signal_ledger(
    decision_run_id: str,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Retrieve full timeline for a decision run, including run info, signals, and outcomes."""
    path = trace_store.resolve_decision_trace_db_path(db_path)
    try:
        conn = trace_store._get_read_connection(path)
        try:
            run_row = conn.execute(
                "SELECT * FROM decision_runs WHERE decision_run_id = ?",
                (decision_run_id,),
            ).fetchone()

            if not run_row:
                raise SignalLedgerNotFoundError(f"Decision run {decision_run_id} not found")

            run_dict = dict(run_row)

            signal_rows = conn.execute(
                "SELECT * FROM signal_entries WHERE decision_run_id = ? ORDER BY created_at ASC",
                (decision_run_id,),
            ).fetchall()

            signals = []
            for r in signal_rows:
                d = dict(r)
                try:
                    d["payload_json"] = json.loads(d["payload_json"])
                except Exception:
                    pass
                signals.append(d)

            outcome_rows = conn.execute(
                "SELECT * FROM decision_outcomes WHERE decision_run_id = ? ORDER BY created_at ASC",
                (decision_run_id,),
            ).fetchall()

            outcomes = []
            for r in outcome_rows:
                d = dict(r)
                try:
                    d["constraints_applied_json"] = json.loads(d["constraints_applied_json"])
                except Exception:
                    pass
                outcomes.append(d)

            return {
                "run": run_dict,
                "signal_entries": signals,
                "decision_outcomes": outcomes,
            }
        finally:
            conn.close()
    except SignalLedgerNotFoundError:
        raise
    except sqlite3.DatabaseError as exc:
        raise SignalLedgerCorruptedError() from exc
