"""Decision trace and evidence SQLite storage layer.

Provides storage for decision runs, evidence items, and explanation items.
Handles schema initialization, read-only queries, write transactions,
and corruption protection.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

SCHEMA_VERSION = "decision_trace_v1"
_LOCK = threading.Lock()


class DecisionTraceError(RuntimeError):
    """Base exception for decision trace store errors."""


class DecisionTraceCorruptedError(DecisionTraceError):
    """Raised when the decision trace database file or table data is corrupted."""

    MESSAGE = "决策追踪数据损坏，已停止读写"

    def __init__(self, message: str | None = None):
        super().__init__(message or self.MESSAGE)


class DecisionTraceNotFoundError(DecisionTraceError, LookupError):
    """Raised when a requested decision trace run or record is not found."""


def resolve_decision_trace_db_path(explicit_path: str | Path | None = None) -> Path:
    """Resolve database path with environment variable overrides.

    Priority:
    1. Explicit argument `explicit_path` if non-empty
    2. Environment variable `VIBE_RESEARCH_DECISION_TRACE_DB`
    3. Environment variable `VR_DATA_DIR` / decision_trace.sqlite3
    4. Default: ~/.vibe-research/decision_trace.sqlite3
    """
    if explicit_path:
        return Path(explicit_path)
    env_db = os.environ.get("VIBE_RESEARCH_DECISION_TRACE_DB", "").strip()
    if env_db:
        return Path(env_db)
    env_dir = os.environ.get("VR_DATA_DIR", "").strip()
    if env_dir:
        return Path(env_dir) / "decision_trace.sqlite3"
    return Path.home() / ".vibe-research" / "decision_trace.sqlite3"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _get_write_connection(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=10.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=5000;")
    conn.row_factory = sqlite3.Row
    return conn


def _get_read_connection(db_path: Path) -> sqlite3.Connection:
    if not db_path.exists():
        # If DB file does not exist, initialize it first so read queries can run safely
        init_db(db_path)
    uri = f"file:{db_path.resolve()}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True, timeout=5.0)
        conn.execute("PRAGMA query_only = ON;")
        conn.execute("PRAGMA busy_timeout = 5000;")
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.DatabaseError as exc:
        raise DecisionTraceCorruptedError() from exc


def init_db(db_path: str | Path | None = None) -> None:
    """Initialize schema, tables, and indexes if they do not exist."""
    path = resolve_decision_trace_db_path(db_path)
    with _LOCK:
        try:
            conn = _get_write_connection(path)
            try:
                with conn:
                    conn.execute(
                        """
                        CREATE TABLE IF NOT EXISTS schema_meta (
                            key TEXT PRIMARY KEY,
                            value TEXT NOT NULL,
                            updated_at TEXT NOT NULL
                        )
                        """
                    )
                    conn.execute(
                        """
                        CREATE TABLE IF NOT EXISTS decision_runs (
                            decision_run_id TEXT PRIMARY KEY,
                            trade_date TEXT NOT NULL,
                            generated_at TEXT NOT NULL,
                            result_type TEXT NOT NULL,
                            schema_version TEXT NOT NULL,
                            market_status TEXT,
                            source_fingerprint TEXT,
                            trace_status TEXT NOT NULL,
                            created_at TEXT NOT NULL
                        )
                        """
                    )
                    conn.execute(
                        """
                        CREATE TABLE IF NOT EXISTS evidence_items (
                            evidence_id TEXT PRIMARY KEY,
                            decision_run_id TEXT NOT NULL,
                            scope TEXT NOT NULL,
                            code TEXT,
                            evidence_key TEXT NOT NULL,
                            value_json TEXT NOT NULL,
                            unit TEXT,
                            source_module TEXT NOT NULL,
                            observed_at TEXT,
                            quality_status TEXT NOT NULL,
                            source_ref_json TEXT,
                            created_at TEXT NOT NULL
                        )
                        """
                    )
                    conn.execute(
                        """
                        CREATE TABLE IF NOT EXISTS explanation_items (
                            explanation_id TEXT PRIMARY KEY,
                            decision_run_id TEXT NOT NULL,
                            code TEXT,
                            conclusion_type TEXT NOT NULL,
                            conclusion_value TEXT NOT NULL,
                            explanation_text TEXT NOT NULL,
                            supporting_evidence_ids TEXT NOT NULL,
                            limiting_evidence_ids TEXT NOT NULL,
                            rule_id TEXT,
                            created_at TEXT NOT NULL
                        )
                        """
                    )
                    conn.execute(
                        """
                        CREATE TABLE IF NOT EXISTS signal_entries (
                            entry_id TEXT PRIMARY KEY,
                            decision_run_id TEXT NOT NULL,
                            stage TEXT NOT NULL,
                            code TEXT,
                            signal_type TEXT NOT NULL,
                            severity TEXT NOT NULL,
                            payload_json TEXT NOT NULL,
                            created_at TEXT NOT NULL
                        )
                        """
                    )
                    conn.execute(
                        """
                        CREATE TABLE IF NOT EXISTS decision_outcomes (
                            outcome_id TEXT PRIMARY KEY,
                            decision_run_id TEXT NOT NULL,
                            code TEXT NOT NULL,
                            action TEXT NOT NULL,
                            target_ratio REAL,
                            reason TEXT NOT NULL,
                            constraints_applied_json TEXT NOT NULL,
                            created_at TEXT NOT NULL
                        )
                        """
                    )
                    conn.execute(
                        "CREATE INDEX IF NOT EXISTS idx_decision_runs_trade_date ON decision_runs(trade_date)"
                    )
                    conn.execute(
                        "CREATE INDEX IF NOT EXISTS idx_evidence_items_run_code ON evidence_items(decision_run_id, code)"
                    )
                    conn.execute(
                        "CREATE INDEX IF NOT EXISTS idx_explanation_items_run_code ON explanation_items(decision_run_id, code)"
                    )
                    conn.execute(
                        "CREATE INDEX IF NOT EXISTS idx_signal_entries_run ON signal_entries(decision_run_id)"
                    )
                    conn.execute(
                        "CREATE INDEX IF NOT EXISTS idx_signal_entries_run_stage ON signal_entries(decision_run_id, stage)"
                    )
                    conn.execute(
                        "CREATE INDEX IF NOT EXISTS idx_decision_outcomes_run ON decision_outcomes(decision_run_id)"
                    )
                    conn.execute(
                        "CREATE INDEX IF NOT EXISTS idx_decision_outcomes_run_code ON decision_outcomes(decision_run_id, code)"
                    )
                    now_str = _utc_now()
                    conn.execute(
                        """
                        INSERT INTO schema_meta (key, value, updated_at)
                        VALUES ('schema_version', ?, ?)
                        ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
                        """,
                        (SCHEMA_VERSION, now_str),
                    )
            finally:
                conn.close()
        except sqlite3.DatabaseError as exc:
            raise DecisionTraceCorruptedError() from exc


def save_decision_run_bundle(
    run_record: Mapping[str, Any],
    evidence_items: list[Mapping[str, Any]],
    explanation_items: list[Mapping[str, Any]],
    db_path: str | Path | None = None,
) -> None:
    """Save a decision run record and its associated evidence and explanation items atomically.

    Supports idempotent re-writing (UPSERT / REPLACE).
    """
    path = resolve_decision_trace_db_path(db_path)
    init_db(path)

    with _LOCK:
        try:
            conn = _get_write_connection(path)
            try:
                with conn:
                    # Insert or replace decision run
                    conn.execute(
                        """
                        INSERT INTO decision_runs (
                            decision_run_id, trade_date, generated_at, result_type,
                            schema_version, market_status, source_fingerprint,
                            trace_status, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(decision_run_id) DO UPDATE SET
                            trade_date=excluded.trade_date,
                            generated_at=excluded.generated_at,
                            result_type=excluded.result_type,
                            schema_version=excluded.schema_version,
                            market_status=excluded.market_status,
                            source_fingerprint=excluded.source_fingerprint,
                            trace_status=excluded.trace_status,
                            created_at=excluded.created_at
                        """,
                        (
                            run_record["decision_run_id"],
                            run_record["trade_date"],
                            run_record["generated_at"],
                            run_record.get("result_type", "portfolio_advice"),
                            run_record.get("schema_version", SCHEMA_VERSION),
                            run_record.get("market_status"),
                            run_record.get("source_fingerprint"),
                            run_record.get("trace_status", "archived"),
                            run_record.get("created_at", _utc_now()),
                        ),
                    )

                    # Delete existing evidence and explanation items for idempotency
                    run_id = run_record["decision_run_id"]
                    conn.execute("DELETE FROM evidence_items WHERE decision_run_id = ?", (run_id,))
                    conn.execute("DELETE FROM explanation_items WHERE decision_run_id = ?", (run_id,))

                    for item in evidence_items:
                        val_json = item["value_json"] if isinstance(item["value_json"], str) else json.dumps(item["value_json"], ensure_ascii=False)
                        ref_json = item.get("source_ref_json")
                        if ref_json is not None and not isinstance(ref_json, str):
                            ref_json = json.dumps(ref_json, ensure_ascii=False)

                        conn.execute(
                            """
                            INSERT INTO evidence_items (
                                evidence_id, decision_run_id, scope, code,
                                evidence_key, value_json, unit, source_module,
                                observed_at, quality_status, source_ref_json, created_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                item["evidence_id"],
                                run_id,
                                item["scope"],
                                item.get("code"),
                                item["evidence_key"],
                                val_json,
                                item.get("unit"),
                                item["source_module"],
                                item.get("observed_at"),
                                item.get("quality_status", "valid"),
                                ref_json,
                                item.get("created_at", _utc_now()),
                            ),
                        )

                    for item in explanation_items:
                        sup_ids = item["supporting_evidence_ids"]
                        if not isinstance(sup_ids, str):
                            sup_ids = json.dumps(sup_ids, ensure_ascii=False)

                        lim_ids = item["limiting_evidence_ids"]
                        if not isinstance(lim_ids, str):
                            lim_ids = json.dumps(lim_ids, ensure_ascii=False)

                        conn.execute(
                            """
                            INSERT INTO explanation_items (
                                explanation_id, decision_run_id, code,
                                conclusion_type, conclusion_value, explanation_text,
                                supporting_evidence_ids, limiting_evidence_ids,
                                rule_id, created_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                item["explanation_id"],
                                run_id,
                                item.get("code"),
                                item["conclusion_type"],
                                item["conclusion_value"],
                                item["explanation_text"],
                                sup_ids,
                                lim_ids,
                                item.get("rule_id"),
                                item.get("created_at", _utc_now()),
                            ),
                        )
            finally:
                conn.close()
        except sqlite3.DatabaseError as exc:
            raise DecisionTraceCorruptedError() from exc


def get_decision_run(
    decision_run_id: str, db_path: str | Path | None = None
) -> dict[str, Any] | None:
    """Retrieve decision run record and all associated evidence/explanations by decision_run_id."""
    path = resolve_decision_trace_db_path(db_path)
    try:
        conn = _get_read_connection(path)
        try:
            row = conn.execute(
                "SELECT * FROM decision_runs WHERE decision_run_id = ?", (decision_run_id,)
            ).fetchone()
            if not row:
                return None

            run_dict = dict(row)

            ev_rows = conn.execute(
                "SELECT * FROM evidence_items WHERE decision_run_id = ? ORDER BY created_at ASC",
                (decision_run_id,),
            ).fetchall()
            exp_rows = conn.execute(
                "SELECT * FROM explanation_items WHERE decision_run_id = ? ORDER BY created_at ASC",
                (decision_run_id,),
            ).fetchall()

            evidence_items = []
            for ev in ev_rows:
                d = dict(ev)
                try:
                    d["value_json"] = json.loads(d["value_json"])
                except Exception:
                    pass
                if d.get("source_ref_json"):
                    try:
                        d["source_ref_json"] = json.loads(d["source_ref_json"])
                    except Exception:
                        pass
                evidence_items.append(d)

            explanation_items = []
            for exp in exp_rows:
                d = dict(exp)
                try:
                    d["supporting_evidence_ids"] = json.loads(d["supporting_evidence_ids"])
                except Exception:
                    d["supporting_evidence_ids"] = []
                try:
                    d["limiting_evidence_ids"] = json.loads(d["limiting_evidence_ids"])
                except Exception:
                    d["limiting_evidence_ids"] = []
                explanation_items.append(d)

            return {
                "decision_run": run_dict,
                "evidence_items": evidence_items,
                "explanation_items": explanation_items,
            }
        finally:
            conn.close()
    except sqlite3.DatabaseError as exc:
        raise DecisionTraceCorruptedError() from exc


def list_evidence_items(
    code: str | None = None,
    trade_date: str | None = None,
    quality_status: str | None = None,
    trace_status: str | None = None,
    result_type: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Query evidence items with filtering and pagination.

    result_type 为可选筛选（如 "portfolio_advice" / "top_risk_analysis"），
    不传时保持原始行为。
    """
    path = resolve_decision_trace_db_path(db_path)
    try:
        conn = _get_read_connection(path)
        try:
            where_clauses: list[str] = []
            params: list[Any] = []

            if code:
                where_clauses.append("e.code = ?")
                params.append(code)

            if trade_date:
                where_clauses.append("r.trade_date = ?")
                params.append(trade_date)

            if quality_status:
                where_clauses.append("e.quality_status = ?")
                params.append(quality_status)

            if trace_status:
                where_clauses.append("r.trace_status = ?")
                params.append(trace_status)

            if result_type:
                where_clauses.append("r.result_type = ?")
                params.append(result_type)

            where_sql = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

            count_sql = f"""
                SELECT COUNT(*) as cnt
                FROM evidence_items e
                JOIN decision_runs r ON e.decision_run_id = r.decision_run_id
                {where_sql}
            """
            total = conn.execute(count_sql, params).fetchone()["cnt"]

            query_sql = f"""
                SELECT e.*, r.trade_date, r.trace_status, r.result_type
                FROM evidence_items e
                JOIN decision_runs r ON e.decision_run_id = r.decision_run_id
                {where_sql}
                ORDER BY e.created_at DESC
                LIMIT ? OFFSET ?
            """
            rows = conn.execute(query_sql, params + [limit, offset]).fetchall()

            items = []
            for r in rows:
                d = dict(r)
                try:
                    d["value_json"] = json.loads(d["value_json"])
                except Exception:
                    pass
                if d.get("source_ref_json"):
                    try:
                        d["source_ref_json"] = json.loads(d["source_ref_json"])
                    except Exception:
                        pass
                items.append(d)

            return {
                "items": items,
                "total": total,
                "limit": limit,
                "offset": offset,
            }
        finally:
            conn.close()
    except sqlite3.DatabaseError as exc:
        raise DecisionTraceCorruptedError() from exc
