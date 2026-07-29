"""Decision feedback SQLite storage layer."""
from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_LOCK = threading.Lock()

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS decision_feedback (
    feedback_id TEXT PRIMARY KEY,
    code TEXT NOT NULL,
    advice_trade_date TEXT NOT NULL,
    advice_generated_at TEXT NOT NULL,
    trade_id TEXT,
    adoption_status TEXT NOT NULL,
    outcome_status TEXT NOT NULL,
    note TEXT,
    created_at TEXT NOT NULL,
    voided_at TEXT,
    void_reason TEXT
)
"""

_INSERT_SQL = """
INSERT INTO decision_feedback (
    feedback_id, code, advice_trade_date, advice_generated_at, trade_id,
    adoption_status, outcome_status, note, created_at, voided_at, void_reason
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

_SELECT_BY_ID = "SELECT * FROM decision_feedback WHERE feedback_id = ?"
_SELECT_LIST_BASE = "SELECT * FROM decision_feedback"
_VOID_UPDATE_SQL = """
UPDATE decision_feedback
   SET voided_at = ?, void_reason = ?
 WHERE feedback_id = ? AND voided_at IS NULL
"""


class DecisionFeedbackError(RuntimeError):
    pass


class DecisionFeedbackCorruptedError(DecisionFeedbackError):
    MESSAGE = "决策反馈数据损坏，已停止读写"

    def __init__(self):
        super().__init__(self.MESSAGE)


class DecisionFeedbackNotFoundError(DecisionFeedbackError, LookupError):
    pass


class DecisionFeedbackAlreadyVoidedError(DecisionFeedbackError):
    def __init__(self):
        super().__init__("决策反馈已作废")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _connect(db_path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(Path(db_path)), timeout=30.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _connect_readonly(db_path: str | Path) -> sqlite3.Connection:
    path = Path(db_path).resolve()
    uri = f"{path.as_uri()}?mode=ro"
    conn = sqlite3.connect(uri, timeout=30.0, uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def _ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute(_CREATE_TABLE_SQL)


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return dict(row)


def insert_record(db_path: str | Path, record: dict[str, Any]) -> None:
    with _LOCK:
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = None
        try:
            conn = _connect(path)
            conn.execute("BEGIN IMMEDIATE")
            _ensure_table(conn)
            conn.execute(
                _INSERT_SQL,
                (
                    record["feedback_id"],
                    record["code"],
                    record["advice_trade_date"],
                    record["advice_generated_at"],
                    record.get("trade_id"),
                    record["adoption_status"],
                    record["outcome_status"],
                    record.get("note"),
                    record["created_at"],
                    record.get("voided_at"),
                    record.get("void_reason"),
                ),
            )
            conn.execute("COMMIT")
        except (sqlite3.DatabaseError, sqlite3.OperationalError) as exc:
            if conn:
                try:
                    conn.execute("ROLLBACK")
                except Exception:
                    pass
            raise DecisionFeedbackCorruptedError() from exc
        finally:
            if conn:
                conn.close()


def get_record(db_path: str | Path, feedback_id: str) -> dict[str, Any] | None:
    path = Path(db_path)
    if not path.is_file():
        return None
    try:
        with _connect_readonly(path) as conn:
            table = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                ("decision_feedback",),
            ).fetchone()
            if table is None:
                return None
            row = conn.execute(_SELECT_BY_ID, (feedback_id,)).fetchone()
            return _row_to_dict(row) if row else None
    except (sqlite3.DatabaseError, sqlite3.OperationalError) as exc:
        raise DecisionFeedbackCorruptedError() from exc


def list_records(
    db_path: str | Path,
    *,
    code: str | None = None,
    adoption_status: str | None = None,
    outcome_status: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    include_voided: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    path = Path(db_path)
    if not path.is_file():
        return []
    try:
        with _connect_readonly(path) as conn:
            table = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                ("decision_feedback",),
            ).fetchone()
            if table is None:
                return []
            sql = _SELECT_LIST_BASE
            clauses: list[str] = []
            params: list[Any] = []
            if not include_voided:
                clauses.append("voided_at IS NULL")
            if code is not None:
                clauses.append("code = ?")
                params.append(code)
            if adoption_status is not None:
                clauses.append("adoption_status = ?")
                params.append(adoption_status)
            if outcome_status is not None:
                clauses.append("outcome_status = ?")
                params.append(outcome_status)
            if date_from is not None:
                clauses.append("date(created_at) >= ?")
                params.append(date_from)
            if date_to is not None:
                clauses.append("date(created_at) <= ?")
                params.append(date_to)
            if clauses:
                sql += " WHERE " + " AND ".join(clauses)
            sql += " ORDER BY created_at DESC"
            if limit is not None:
                sql += " LIMIT ?"
                params.append(limit)
            if offset:
                sql += " OFFSET ?"
                params.append(offset)
            rows = conn.execute(sql, params).fetchall()
            return [_row_to_dict(r) for r in rows]
    except (sqlite3.DatabaseError, sqlite3.OperationalError) as exc:
        raise DecisionFeedbackCorruptedError() from exc


def void_record(
    db_path: str | Path,
    feedback_id: str,
    *,
    void_reason: str | None = None,
) -> dict[str, Any]:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = None
    try:
        conn = _connect(path)
        conn.execute("BEGIN IMMEDIATE")
        _ensure_table(conn)

        row = conn.execute(_SELECT_BY_ID, (feedback_id,)).fetchone()
        if row is None:
            conn.execute("ROLLBACK")
            raise DecisionFeedbackNotFoundError("决策反馈不存在")

        existing = _row_to_dict(row)
        if existing.get("voided_at") is not None:
            conn.execute("ROLLBACK")
            raise DecisionFeedbackAlreadyVoidedError()

        now = _utc_now()
        cursor = conn.execute(
            _VOID_UPDATE_SQL,
            (now, void_reason, feedback_id),
        )
        if cursor.rowcount == 0:
            row_check = conn.execute(_SELECT_BY_ID, (feedback_id,)).fetchone()
            conn.execute("ROLLBACK")
            if row_check and dict(row_check).get("voided_at") is not None:
                raise DecisionFeedbackAlreadyVoidedError()
            raise DecisionFeedbackNotFoundError("决策反馈不存在")

        updated_row = conn.execute(_SELECT_BY_ID, (feedback_id,)).fetchone()
        conn.execute("COMMIT")
        return _row_to_dict(updated_row)
    except (DecisionFeedbackNotFoundError, DecisionFeedbackAlreadyVoidedError):
        raise
    except (sqlite3.DatabaseError, sqlite3.OperationalError) as exc:
        if conn:
            try:
                conn.execute("ROLLBACK")
            except Exception:
                pass
        raise DecisionFeedbackCorruptedError() from exc
    finally:
        if conn:
            conn.close()
