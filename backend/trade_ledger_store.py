"""Trade ledger SQLite storage layer."""
from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_LOCK = threading.Lock()

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS trade_records (
    trade_id TEXT PRIMARY KEY,
    code TEXT NOT NULL,
    name TEXT NOT NULL,
    operation TEXT NOT NULL
        CHECK (operation IN ('buy', 'add', 'reduce', 'sell')),
    execution_status TEXT NOT NULL
        CHECK (execution_status IN ('full', 'partial', 'not_executed')),
    planned_price REAL,
    planned_quantity INTEGER,
    actual_price REAL,
    actual_quantity INTEGER NOT NULL DEFAULT 0,
    executed_at TEXT,
    fee REAL NOT NULL DEFAULT 0,
    other_cost REAL NOT NULL DEFAULT 0,
    unexecuted_reason TEXT,
    note TEXT,
    advice_trade_date TEXT,
    advice_generated_at TEXT,
    advice_snapshot TEXT,
    thesis_id TEXT,
    thesis_revision INTEGER,
    created_at TEXT NOT NULL,
    voided_at TEXT,
    void_reason TEXT
)
"""

_INSERT_SQL = """
INSERT INTO trade_records (
    trade_id, code, name, operation, execution_status,
    planned_price, planned_quantity, actual_price, actual_quantity, executed_at,
    fee, other_cost, unexecuted_reason, note,
    advice_trade_date, advice_generated_at, advice_snapshot,
    thesis_id, thesis_revision, created_at, voided_at, void_reason
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

_SELECT_BY_ID = "SELECT * FROM trade_records WHERE trade_id = ?"
_SELECT_LIST_BASE = "SELECT * FROM trade_records"
_VOID_UPDATE_SQL = """
UPDATE trade_records
   SET voided_at = ?, void_reason = ?
 WHERE trade_id = ? AND voided_at IS NULL
"""


class TradeLedgerError(RuntimeError):
    pass


class TradeLedgerCorruptedError(TradeLedgerError):
    def __init__(self):
        super().__init__("交易流水数据损坏，无法读取")


class TradeNotFoundError(TradeLedgerError, LookupError):
    pass


class TradeAlreadyVoidedError(TradeLedgerError):
    def __init__(self):
        super().__init__("交易记录已作废")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _connect(db_path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(Path(db_path)), timeout=30.0)
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
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def _ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute(_CREATE_TABLE_SQL)


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return dict(row)


def insert_record(db_path: str | Path, record: dict[str, Any]) -> None:
    with _LOCK:
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with _connect(path) as conn:
                _ensure_table(conn)
                conn.execute(_INSERT_SQL, (
                    record["trade_id"],
                    record["code"],
                    record["name"],
                    record["operation"],
                    record["execution_status"],
                    record.get("planned_price"),
                    record.get("planned_quantity"),
                    record.get("actual_price"),
                    record.get("actual_quantity", 0),
                    record.get("executed_at"),
                    record.get("fee", 0.0),
                    record.get("other_cost", 0.0),
                    record.get("unexecuted_reason"),
                    record.get("note"),
                    record.get("advice_trade_date"),
                    record.get("advice_generated_at"),
                    record.get("advice_snapshot"),
                    record.get("thesis_id"),
                    record.get("thesis_revision"),
                    record["created_at"],
                    None,
                    None,
                ))
                conn.commit()
        except sqlite3.DatabaseError as exc:
            raise TradeLedgerCorruptedError() from exc


def get_record(db_path: str | Path, trade_id: str) -> dict[str, Any] | None:
    path = Path(db_path)
    if not path.is_file():
        return None
    try:
        with _connect_readonly(path) as conn:
            table = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                ("trade_records",),
            ).fetchone()
            if table is None:
                return None
            row = conn.execute(_SELECT_BY_ID, (trade_id,)).fetchone()
            return _row_to_dict(row) if row else None
    except sqlite3.DatabaseError as exc:
        raise TradeLedgerCorruptedError() from exc


def list_records(
    db_path: str | Path,
    *,
    code: str | None = None,
    operation: str | None = None,
    execution_status: str | None = None,
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
                ("trade_records",),
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
            if operation is not None:
                clauses.append("operation = ?")
                params.append(operation)
            if execution_status is not None:
                clauses.append("execution_status = ?")
                params.append(execution_status)
            if date_from is not None:
                clauses.append("date(COALESCE(executed_at, created_at)) >= ?")
                params.append(date_from)
            if date_to is not None:
                clauses.append("date(COALESCE(executed_at, created_at)) <= ?")
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
    except sqlite3.DatabaseError as exc:
        raise TradeLedgerCorruptedError() from exc


def void_record_atomic(
    db_path: str | Path,
    trade_id: str,
    reason: str,
) -> dict[str, Any]:
    """Atomic void operation inside a single _LOCK and transaction."""
    with _LOCK:
        path = Path(db_path)
        if not path.is_file():
            raise TradeNotFoundError()
        try:
            with _connect(path) as conn:
                table = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                    ("trade_records",),
                ).fetchone()
                if table is None:
                    raise TradeNotFoundError()

                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute(_SELECT_BY_ID, (trade_id,)).fetchone()
                if row is None:
                    raise TradeNotFoundError()
                rec = _row_to_dict(row)
                if rec.get("voided_at") is not None:
                    raise TradeAlreadyVoidedError()

                now = _utc_now()
                conn.execute(_VOID_UPDATE_SQL, (now, reason, trade_id))
                updated_row = conn.execute(_SELECT_BY_ID, (trade_id,)).fetchone()
                conn.commit()
                return _row_to_dict(updated_row)
        except sqlite3.DatabaseError as exc:
            raise TradeLedgerCorruptedError() from exc
