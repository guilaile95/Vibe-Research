"""Account event SQLite storage layer (ACCOUNT_OPENING / LEGACY_POSITION_OPENING / CORRECTION / CASH_*).

与 trade_ledger_store 同一 SQLite 库（trade_ledger.sqlite3）内独立建表 account_events，
记录账户事实链（账户开立、Vibe 前持仓导入、修正事件、手工现金事件）。

event_type 不再由 DB CHECK 约束（演进集合，校验由 service 层白名单负责）；
旧表（3 值 CHECK、无 amount 列）首次写入时惰性迁移到新 schema（数据完整保留）。
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

_LOCK = threading.Lock()

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS account_events (
    event_id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
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
    amount REAL,
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
    reason, note, amount, created_at, voided_at, void_reason
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

_SELECT_BY_ID = "SELECT * FROM account_events WHERE event_id = ?"
_SELECT_LIST_BASE = "SELECT * FROM account_events"
_COUNT_BASE = "SELECT COUNT(*) AS n FROM account_events"

_LEGACY_CHECK_MARKER = "CHECK (event_type IN"

# 已移除 DB CHECK（演进集合），读路径必须 fail closed 校验持久化 event_type。
# 本模块是 account event 类型常量唯一来源（DRY：cash_event_service 复用）。
NON_CASH_EVENT_TYPES = frozenset({
    "ACCOUNT_OPENING",
    "LEGACY_POSITION_OPENING",
    "CORRECTION",
})
CASH_EVENT_TYPES = frozenset({
    "CASH_DEPOSIT",
    "CASH_WITHDRAWAL",
    "CASH_DIVIDEND",
    "CASH_FEE",
    "CASH_TAX",
})
KNOWN_EVENT_TYPES = NON_CASH_EVENT_TYPES | CASH_EVENT_TYPES

_CASH_PROVENANCE_EXPECTED = "MANUAL"


def validate_event_type(event_type: Any) -> None:
    """持久化 event_type 必须属于已知集合；未知类型（BOGUS 等）→ 数据损坏，fail closed。"""
    if event_type not in KNOWN_EVENT_TYPES:
        raise AccountEventCorruptedError()


def validate_persisted_cash_event(row: dict[str, Any]) -> None:
    """已落盘 CASH_* 事件必须满足持久化事实契约：
    event_type ∈ CASH_EVENT_TYPES；amount numeric/finite/>0（非 NULL/0/负）；provenance=MANUAL。
    不满足 → AccountEventCorruptedError（fail closed），不得静默忽略/解释成 0/反转方向。
    """
    etype = row.get("event_type")
    if etype not in CASH_EVENT_TYPES:
        raise AccountEventCorruptedError()
    amount = row.get("amount")
    if isinstance(amount, bool) or not isinstance(amount, (int, float)):
        raise AccountEventCorruptedError()
    number = float(amount)
    if number != number or number in (float("inf"), float("-inf")) or number <= 0:
        raise AccountEventCorruptedError()
    if row.get("provenance") != _CASH_PROVENANCE_EXPECTED:
        raise AccountEventCorruptedError()


def normalize_cash_amount(value: Any) -> float:
    """纯 cash amount 归一化（DRY：create / correction / persisted 共用同一规则）。

    RAW → numeric → finite → >0 → round 2dp → 归一化后仍必须 >0。
    非法抛 ValueError（由调用方包装为对应层错误：422 用户错误或 500 数据损坏）。
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("amount 必须是数字")
    number = float(value)
    if number != number or number in (float("inf"), float("-inf")):
        raise ValueError("amount 必须是有限数字")
    if number <= 0:
        raise ValueError("amount 必须大于 0（方向由 event_type 决定）")
    normalized = round(number, 2)
    if normalized <= 0:
        raise ValueError("amount 归一化到 2 位小数后必须大于 0")
    return normalized


def validate_effective_cash_events(
    events_by_key: dict[str, dict[str, Any]],
    corrections: dict[str, list[dict[str, Any]]],
) -> None:
    """读路径：应用 active corrections 后，CASH_* effective facts 必须保持有效，
    且针对 CASH_* 的 CORRECTION 的 before/after payload 必须合法。

    - effective CASH_* 事件：event_type ∈ CASH、amount numeric/finite/>0、provenance=MANUAL
      （after_payload 若含未知字段如 event_type 会污染 effective dict → 校验失败）
    - 针对 CASH_* 的 correction：after_payload 必须 JSON object 且仅含 amount（归一化 >0）；
      before_payload 必须 JSON object 且含合法 amount。
    任何损坏 → AccountEventCorruptedError（fail closed），不得忽略 correction / 回退 raw
    amount / or 0.0 / 静默跳过。
    """
    cash_target_ids: set[str] = set()
    for key, ev in events_by_key.items():
        if key.startswith("account_event:") and ev.get("event_type") in CASH_EVENT_TYPES:
            validate_persisted_cash_event(ev)
            cash_target_ids.add(ev["event_id"])
    for key, corrs in corrections.items():
        prefix, _, target_id = key.partition(":")
        if prefix != "account_event" or target_id not in cash_target_ids:
            continue
        for corr in corrs:
            _validate_cash_correction_payload(corr)


def _validate_cash_correction_payload(corr: dict[str, Any]) -> None:
    """针对 CASH_* 的 correction：after_payload 仅 amount 且归一化 >0；before_payload 含合法 amount。"""
    try:
        after = json.loads(corr["after_payload"])
        before = json.loads(corr["before_payload"])
    except (TypeError, ValueError) as exc:
        raise AccountEventCorruptedError() from exc
    if not isinstance(after, dict) or set(after.keys()) != {"amount"}:
        raise AccountEventCorruptedError()
    if not isinstance(before, dict) or set(before.keys()) != {"amount"}:
        raise AccountEventCorruptedError()
    for payload in (after, before):
        try:
            normalize_cash_amount(payload["amount"])
        except (ValueError, KeyError) as exc:
            raise AccountEventCorruptedError() from exc


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
    _migrate_legacy_schema(conn)


def _table_sql(conn: sqlite3.Connection, table_name: str) -> str | None:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return str(row[0]) if row else None


def _migrate_legacy_schema(conn: sqlite3.Connection) -> None:
    """旧 account_events 表（3 值 CHECK、无 amount 列）单次惰性迁移到新 schema。

    数据完整保留（显式列拷贝，amount 默认 NULL），非破坏性；事务内执行，失败回滚。
    新表 event_type 无 CHECK（service 层白名单校验负责），可容纳 CASH_* 事件。
    """
    sql = _table_sql(conn, "account_events")
    if sql is None:
        return
    has_amount = "amount" in sql
    has_legacy_check = _LEGACY_CHECK_MARKER in sql
    if has_amount and not has_legacy_check:
        return  # 已是新 schema
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute("ALTER TABLE account_events RENAME TO account_events_legacy")
        conn.execute(_CREATE_TABLE_SQL)
        conn.execute(
            "INSERT INTO account_events ("
            " event_id, event_type, code, name, shares, cost_basis, opening_cash,"
            " ledger_start_at, origin, acquired_before_vibe, historical_trades,"
            " provenance, target_event_id, target_event_type, before_payload, after_payload,"
            " reason, note, created_at, voided_at, void_reason"
            ") SELECT "
            " event_id, event_type, code, name, shares, cost_basis, opening_cash,"
            " ledger_start_at, origin, acquired_before_vibe, historical_trades,"
            " provenance, target_event_id, target_event_type, before_payload, after_payload,"
            " reason, note, created_at, voided_at, void_reason"
            " FROM account_events_legacy"
        )
        conn.execute("DROP TABLE account_events_legacy")
        conn.commit()
    except Exception:
        conn.rollback()
        raise


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


def get_event_on_connection(
    conn: sqlite3.Connection,
    event_id: str,
) -> dict[str, Any] | None:
    """Read an account event on a caller-owned connection (no lock/commit)."""
    row = conn.execute(_SELECT_BY_ID, (event_id,)).fetchone()
    return _row_to_dict(row) if row else None


def list_corrections_on_connection(
    conn: sqlite3.Connection,
    target_event_type: str,
    target_event_id: str,
) -> list[dict[str, Any]]:
    """Read all active CORRECTION events targeting an object on a caller-owned connection.

    确定性顺序：created_at ASC, rowid ASC —— 同事务内可稳定复现的审计链顺序
    （created_at 相同时以 SQLite rowid 打破平局，不新增 schema/framework）。
    """
    if not table_exists_on_connection(conn, "account_events"):
        return []
    rows = conn.execute(
        "SELECT * FROM account_events"
        " WHERE event_type = 'CORRECTION' AND target_event_type = ?"
        " AND target_event_id = ? AND voided_at IS NULL"
        " ORDER BY created_at ASC, rowid ASC",
        (target_event_type, target_event_id),
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


def insert_event_on_connection(
    conn: sqlite3.Connection,
    event: dict[str, Any],
) -> None:
    """Insert an account event on a caller-owned connection (no commit; caller owns transaction).

    表不存在时惰性创建（CREATE TABLE IF NOT EXISTS）；用于 correction 与 target 校验
    同事务提交（R6 原子化）。
    """
    _ensure_table(conn)
    conn.execute(_INSERT_SQL, _event_params(event))


def ensure_migrated(db_path: str | Path) -> None:
    """在调用方开事务之前确保 account_events 表已是最新 schema（含旧表惰性迁移）。

    caller-owned 事务路径（create_correction / void_trade_with_cascade 先 BEGIN IMMEDIATE）
    不能在事务内触发迁移（嵌套 BEGIN 会失败），因此必须先在此独立连接上完成迁移。
    """
    with _LOCK:
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with _connect(path) as conn:
                _ensure_table(conn)
                conn.commit()
        except sqlite3.DatabaseError as exc:
            raise AccountEventCorruptedError() from exc


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
                    event.get("amount"),
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
            # 显式全序：created_at 相同时以 rowid 打破平局（严格 total order，不是仅 created_at）
            sql += " ORDER BY created_at ASC, rowid ASC"
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
        event.get("amount"),
        event["created_at"],
        None,
        None,
    )
