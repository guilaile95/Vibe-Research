"""Account event SQLite storage layer (ACCOUNT_OPENING / LEGACY_POSITION_OPENING / CORRECTION).

与 trade_ledger_store 同一 SQLite 库（trade_ledger.sqlite3）内独立建表 account_events，
记录账户事实链（账户开立、Vibe 前持仓导入、修正事件）。
"""
from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

_LOCK = threading.Lock()

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS account_events (
    event_id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL CHECK (event_type IN ('ACCOUNT_OPENING','LEGACY_POSITION_OPENING','CORRECTION')),
    code TEXT,
    name TEXT,
    shares INTEGER,
    cost_basis REAL,
    opening_cash REAL,
    ledger_start_at TEXT,
    origin TEXT,
    acquired_before_vibe INTEGER,
    historical_trades TEXT,
    provenance TEXT NOT NULL,
    target_event_id TEXT,
    target_event_type TEXT,
    before_payload TEXT,
    after_payload TEXT,
    reason TEXT,
    note TEXT,
    created_at TEXT NOT NULL,
    voided_at TEXT,
    void_reason TEXT
)
"""

_INSERT_SQL = """
INSERT INTO account_events (
    event_id, event_type, code, name, shares, cost_basis, opening_cash,
    ledger_start_at, origin, acquired_before_vibe, historical_trades,
    provenance, target_event_id, target_event_type, before_payload, after_payload,
    reason, note, created_at, voided_at, void_reason
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

_SELECT_BY_ID = "SELECT * FROM account_events WHERE event_id = ?"
_SELECT_LIST_BASE = "SELECT * FROM account_events"
_COUNT_BASE = "SELECT COUNT(*) AS n FROM account_events"


class AccountEventStoreError(RuntimeError):
    pass


class AccountEventCorruptedError(AccountEventStoreError):
    def __init__(self):
        super().__init__("账户事件数据损坏，无法读取")


class AccountEventNotFoundError(AccountEventStoreError, LookupError):
    pass


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


def _table_exists(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        ("account_events",),
    ).fetchone()
    return row is not None


def table_exists_on_connection(conn: sqlite3.Connection, table_name: str) -> bool:
    """Check table existence on a caller-owned connection (no lock/commit)."""
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def count_active_corrections_on_connection(
    conn: sqlite3.Connection,
    target_event_type: str,
    target_event_id: str,
) -> int:
    """Count non-voided CORRECTION events targeting a given object (caller-owned conn)."""
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM account_events"
        " WHERE event_type = 'CORRECTION' AND target_event_type = ?"
        " AND target_event_id = ? AND voided_at IS NULL",
        (target_event_type, target_event_id),
    ).fetchone()
    return int(row["n"]) if row else 0


def void_corrections_on_connection(
    conn: sqlite3.Connection,
    target_event_type: str,
    target_event_id: str,
    now_iso: str,
    reason: str,
) -> int:
    """Void all non-voided CORRECTION events targeting an object (caller-owned conn).

    返回实际作废条数；由调用方在同一事务中提交（用于跨表原子 void cascade）。
    """
    cur = conn.execute(
        "UPDATE account_events SET voided_at = ?, void_reason = ?"
        " WHERE event_type = 'CORRECTION' AND target_event_type = ?"
        " AND target_event_id = ? AND voided_at IS NULL",
        (now_iso, reason, target_event_type, target_event_id),
    )
    return cur.rowcount


def insert_event(db_path: str | Path, event: dict[str, Any]) -> None:
    with _LOCK:
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with _connect(path) as conn:
                _ensure_table(conn)
                conn.execute(_INSERT_SQL, (
                    event["event_id"],
                    event["event_type"],
                    event.get("code"),
                    event.get("name"),
                    event.get("shares"),
                    event.get("cost_basis"),
                    event.get("opening_cash"),
                    event.get("ledger_start_at"),
                    event.get("origin"),
                    event.get("acquired_before_vibe"),
                    event.get("historical_trades"),
                    event.get("provenance"),
                    event.get("target_event_id"),
                    event.get("target_event_type"),
                    event.get("before_payload"),
                    event.get("after_payload"),
                    event.get("reason"),
                    event.get("note"),
                    event["created_at"],
                    None,
                    None,
                ))
                conn.commit()
        except sqlite3.DatabaseError as exc:
            raise AccountEventCorruptedError() from exc


def get_event(db_path: str | Path, event_id: str) -> dict[str, Any] | None:
    path = Path(db_path)
    if not path.is_file():
        return None
    try:
        with _connect_readonly(path) as conn:
            if not _table_exists(conn):
                return None
            row = conn.execute(_SELECT_BY_ID, (event_id,)).fetchone()
            return _row_to_dict(row) if row else None
    except sqlite3.DatabaseError as exc:
        raise AccountEventCorruptedError() from exc


def list_events(
    db_path: str | Path,
    *,
    include_voided: bool = False,
    event_type: str | None = None,
) -> list[dict[str, Any]]:
    path = Path(db_path)
    if not path.is_file():
        return []
    try:
        with _connect_readonly(path) as conn:
            if not _table_exists(conn):
                return []
            sql = _SELECT_LIST_BASE
            clauses: list[str] = []
            params: list[Any] = []
            if not include_voided:
                clauses.append("voided_at IS NULL")
            if event_type is not None:
                clauses.append("event_type = ?")
                params.append(event_type)
            if clauses:
                sql += " WHERE " + " AND ".join(clauses)
            sql += " ORDER BY created_at ASC"
            rows = conn.execute(sql, params).fetchall()
            return [_row_to_dict(r) for r in rows]
    except sqlite3.DatabaseError as exc:
        raise AccountEventCorruptedError() from exc


def count_non_voided(
    db_path: str | Path,
    *,
    event_type: str | None = None,
) -> int:
    path = Path(db_path)
    if not path.is_file():
        return 0
    try:
        with _connect_readonly(path) as conn:
            if not _table_exists(conn):
                return 0
            sql = _COUNT_BASE
            clauses: list[str] = ["voided_at IS NULL"]
            params: list[Any] = []
            if event_type is not None:
                clauses.append("event_type = ?")
                params.append(event_type)
            sql += " WHERE " + " AND ".join(clauses)
            row = conn.execute(sql, params).fetchone()
            return int(row["n"])
    except sqlite3.DatabaseError as exc:
        raise AccountEventCorruptedError() from exc


def atomic_bootstrap(
    db_path: str | Path,
    opening_event: dict[str, Any],
    position_events: list[dict[str, Any]],
    *,
    precheck: Callable[[sqlite3.Connection], None] | None = None,
) -> list[dict[str, Any]]:
    """Single _LOCK + transaction: create table, run optional precheck, then insert atomically.

    precheck 在同一写锁事务内执行（同一连接），可抛异常回滚，用于幂等/一致性守卫。
    """
    with _LOCK:
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with _connect(path) as conn:
                _ensure_table(conn)
                conn.execute("BEGIN IMMEDIATE")
                try:
                    if precheck is not None:
                        precheck(conn)
                    conn.execute(_INSERT_SQL, _event_params(opening_event))
                    for event in position_events:
                        conn.execute(_INSERT_SQL, _event_params(event))
                    conn.commit()
                except Exception:
                    conn.rollback()
                    raise
                inserted = [dict(opening_event)]
                inserted.extend(dict(e) for e in position_events)
                return inserted
        except sqlite3.DatabaseError as exc:
            raise AccountEventCorruptedError() from exc


def _event_params(event: dict[str, Any]) -> tuple:
    return (
        event["event_id"],
        event["event_type"],
        event.get("code"),
        event.get("name"),
        event.get("shares"),
        event.get("cost_basis"),
        event.get("opening_cash"),
        event.get("ledger_start_at"),
        event.get("origin"),
        event.get("acquired_before_vibe"),
        event.get("historical_trades"),
        event.get("provenance"),
        event.get("target_event_id"),
        event.get("target_event_type"),
        event.get("before_payload"),
        event.get("after_payload"),
        event.get("reason"),
        event.get("note"),
        event["created_at"],
        None,
        None,
    )

