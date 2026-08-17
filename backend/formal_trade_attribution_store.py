"""Append-only SQLite persistence for TB1 FormalTradeAttribution records.

This module is deliberately a storage-only boundary.  It validates every
record through ``formal_trade_attribution.from_dict`` and never looks up a
Trade, Campaign, Thesis, or Frozen Decision.  Reads of a missing ledger are
side-effect free; a corrupt existing ledger fails closed.
"""

from __future__ import annotations

import os
import sqlite3
import stat
import threading
import time
from pathlib import Path
from typing import Any, Mapping

from formal_trade_attribution import (
    AttributionSchemaVersionError,
    AttributionValidationError,
    FormalTradeAttribution,
    from_dict as tb1_from_dict,
)

STORE_SCHEMA_VERSION = "formal-trade-attribution-ledger.v0.1"
_TABLE = "formal_trade_attributions"
_COLUMNS = (
    "attribution_id", "trade_id", "decision_id", "decision_snapshot_hash",
    "security_code", "strategy", "campaign_id", "thesis_id",
    "thesis_revision", "decision_committed_at", "decision_review_by",
    "decision_next_best_action", "trade_operation", "trade_execution_status",
    "trade_executed_at", "trade_created_at", "created_at", "schema_version",
    "attribution_hash",
)
_LOCK = threading.Lock()

_SCHEMA_META_COLUMNS: dict[str, tuple[str, bool, bool]] = {
    "key": ("TEXT", False, True),
    "value": ("TEXT", True, False),
}

_ATTRIBUTION_COLUMNS: dict[str, tuple[str, bool, bool]] = {
    "attribution_id": ("TEXT", False, True),
    "trade_id": ("TEXT", True, False),
    "decision_id": ("TEXT", True, False),
    "decision_snapshot_hash": ("TEXT", True, False),
    "security_code": ("TEXT", True, False),
    "strategy": ("TEXT", True, False),
    "campaign_id": ("TEXT", True, False),
    "thesis_id": ("TEXT", True, False),
    "thesis_revision": ("INTEGER", True, False),
    "decision_committed_at": ("TEXT", True, False),
    "decision_review_by": ("TEXT", True, False),
    "decision_next_best_action": ("TEXT", True, False),
    "trade_operation": ("TEXT", True, False),
    "trade_execution_status": ("TEXT", True, False),
    "trade_executed_at": ("TEXT", False, False),
    "trade_created_at": ("TEXT", True, False),
    "created_at": ("TEXT", True, False),
    "schema_version": ("TEXT", True, False),
    "attribution_hash": ("TEXT", True, False),
}

_EXPECTED_INDEXES: dict[str, tuple[str, tuple[str, ...]]] = {
    "idx_fta_decision_id": (_TABLE, ("decision_id",)),
    "idx_fta_campaign_id": (_TABLE, ("campaign_id",)),
    "idx_fta_security_code": (_TABLE, ("security_code",)),
}


class FormalTradeAttributionStoreError(RuntimeError):
    """Base persistence error."""


class FormalTradeAttributionStoreCorruptedError(FormalTradeAttributionStoreError):
    """Existing file, schema, or row is not trustworthy."""


class FormalTradeAttributionStoreSchemaVersionError(FormalTradeAttributionStoreError):
    """No implicit storage migration is allowed."""


class FormalTradeAttributionStoreConflictError(FormalTradeAttributionStoreError):
    """A replay conflicts with an existing attribution."""


def resolve_formal_trade_attribution_db_path(*, explicit_path: str | Path | None = None) -> Path:
    if explicit_path is not None:
        return Path(explicit_path)
    env = os.environ.get("VIBE_RESEARCH_TRADE_ATTRIBUTION_DB", "").strip()
    if env:
        return Path(env)
    data_dir = os.environ.get("VR_DATA_DIR", "").strip()
    if data_dir:
        return Path(data_dir) / "formal_trade_attributions.sqlite3"
    return Path.home() / ".vibe-research" / "formal_trade_attributions.sqlite3"


def _path(value: str | Path) -> Path:
    if isinstance(value, Path):
        return value
    if isinstance(value, str) and value.strip():
        return Path(value)
    raise FormalTradeAttributionStoreError("db_path 必须是非空路径")


def _connect(path: Path, *, readonly: bool = False) -> sqlite3.Connection:
    if readonly:
        conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=5)
    else:
        conn = sqlite3.connect(str(path), timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def _schema_contract(conn: sqlite3.Connection) -> None:
    try:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        if tables != {"schema_meta", _TABLE}:
            raise FormalTradeAttributionStoreCorruptedError("归属账本表集合损坏")
        _assert_table_contract(conn, "schema_meta", _SCHEMA_META_COLUMNS)
        _assert_table_contract(conn, _TABLE, _ATTRIBUTION_COLUMNS)
        _assert_query_indexes(conn)
        _assert_unique_trade_id(conn)
        if conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type IN ('trigger', 'view') LIMIT 1"
        ).fetchone():
            raise FormalTradeAttributionStoreCorruptedError(
                "归属账本禁止触发器/视图"
            )
        version = conn.execute(
            "SELECT value FROM schema_meta WHERE key = 'schema_version'"
        ).fetchone()
        if version is None:
            raise FormalTradeAttributionStoreCorruptedError("缺少 schema_version")
        if version[0] != STORE_SCHEMA_VERSION:
            raise FormalTradeAttributionStoreSchemaVersionError(
                f"不支持的归属账本版本：{version[0]}"
            )
    except FormalTradeAttributionStoreError:
        raise
    except sqlite3.DatabaseError as exc:
        raise FormalTradeAttributionStoreCorruptedError() from exc


def _assert_table_contract(
    conn: sqlite3.Connection,
    table_name: str,
    expected: Mapping[str, tuple[str, bool, bool]],
) -> None:
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    actual = {
        row[1]: (str(row[2]).upper(), bool(row[3]), bool(row[5]))
        for row in rows
    }
    if set(actual) != set(expected):
        raise FormalTradeAttributionStoreCorruptedError(
            f"{table_name} 列契约损坏"
        )
    for name, (expected_type, expected_notnull, expected_pk) in expected.items():
        actual_type, actual_notnull, actual_pk = actual[name]
        if (
            actual_type != expected_type
            or actual_notnull != expected_notnull
            or actual_pk != expected_pk
        ):
            raise FormalTradeAttributionStoreCorruptedError(
                f"{table_name}.{name} 结构不符合契约"
            )


def _assert_query_indexes(conn: sqlite3.Connection) -> None:
    for name, (expected_table, expected_columns) in _EXPECTED_INDEXES.items():
        row = conn.execute(
            "SELECT tbl_name, sql FROM sqlite_master "
            "WHERE type = 'index' AND name = ?",
            (name,),
        ).fetchone()
        if row is None or row[1] is None:
            raise FormalTradeAttributionStoreCorruptedError(
                f"缺少索引 {name}"
            )
        if row[0] != expected_table:
            raise FormalTradeAttributionStoreCorruptedError(
                f"索引 {name} 指向错误表"
            )
        actual_columns = [item[2] for item in conn.execute(
            f"PRAGMA index_info({name})"
        ).fetchall()]
        if actual_columns != list(expected_columns):
            raise FormalTradeAttributionStoreCorruptedError(
                f"索引 {name} 目标列不符"
            )
        matches = [
            item
            for item in conn.execute(
                f"PRAGMA index_list({expected_table})"
            ).fetchall()
            if item[1] == name
        ]
        if not matches:
            raise FormalTradeAttributionStoreCorruptedError(
                f"索引 {name} 不在 index_list 中"
            )
        index = matches[0]
        if index[2] != 0 or index[4] != 0 or index[3] != "c":
            raise FormalTradeAttributionStoreCorruptedError(
                f"索引 {name} 不是普通 CREATE INDEX"
            )


def _assert_unique_trade_id(conn: sqlite3.Connection) -> None:
    for index in conn.execute(f"PRAGMA index_list({_TABLE})").fetchall():
        if index[2] != 1 or index[4] != 0:
            continue
        columns = [item[2] for item in conn.execute(
            f"PRAGMA index_info({index[1]})"
        ).fetchall()]
        if columns == ["trade_id"]:
            return
    raise FormalTradeAttributionStoreCorruptedError(
        "缺少完整 UNIQUE(trade_id) 约束（partial unique 不接受）"
    )


def _initialize(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
        os.close(fd)
        owner = True
    except FileExistsError:
        owner = False
    except OSError as exc:
        raise FormalTradeAttributionStoreError("归属账本不可用") from exc
    deadline = time.monotonic() + 10
    while True:
        conn: sqlite3.Connection | None = None
        try:
            conn = _connect(path)
            conn.execute("BEGIN IMMEDIATE")
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if tables == {"schema_meta", _TABLE}:
                _schema_contract(conn)
                conn.execute("COMMIT")
                return conn
            if tables:
                raise FormalTradeAttributionStoreCorruptedError("归属账本初始化数据损坏")
            if owner:
                conn.execute("CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
                conn.execute(f"""CREATE TABLE {_TABLE} (
                        attribution_id TEXT PRIMARY KEY,
                        trade_id TEXT NOT NULL UNIQUE,
                        decision_id TEXT NOT NULL,
                        decision_snapshot_hash TEXT NOT NULL,
                        security_code TEXT NOT NULL,
                        strategy TEXT NOT NULL,
                        campaign_id TEXT NOT NULL,
                        thesis_id TEXT NOT NULL,
                        thesis_revision INTEGER NOT NULL,
                        decision_committed_at TEXT NOT NULL,
                        decision_review_by TEXT NOT NULL,
                        decision_next_best_action TEXT NOT NULL,
                        trade_operation TEXT NOT NULL,
                        trade_execution_status TEXT NOT NULL,
                        trade_executed_at TEXT,
                        trade_created_at TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        schema_version TEXT NOT NULL,
                        attribution_hash TEXT NOT NULL
                    )""")
                conn.execute(f"CREATE INDEX idx_fta_decision_id ON {_TABLE}(decision_id)")
                conn.execute(f"CREATE INDEX idx_fta_campaign_id ON {_TABLE}(campaign_id)")
                conn.execute(f"CREATE INDEX idx_fta_security_code ON {_TABLE}(security_code)")
                conn.execute("INSERT INTO schema_meta(key,value) VALUES ('schema_version',?)", (STORE_SCHEMA_VERSION,))
                _schema_contract(conn)
                conn.execute("COMMIT")
                return conn
            conn.execute("ROLLBACK")
            conn.close()
            if time.monotonic() >= deadline:
                raise FormalTradeAttributionStoreCorruptedError("归属账本初始化未完成")
            time.sleep(0.02)
        except FormalTradeAttributionStoreError:
            try:
                if conn is not None:
                    conn.execute("ROLLBACK")
            except Exception: pass
            if conn is not None:
                conn.close()
            raise
        except sqlite3.Error as exc:
            try:
                if conn is not None:
                    conn.execute("ROLLBACK")
            except Exception: pass
            if conn is not None:
                conn.close()
            raise FormalTradeAttributionStoreCorruptedError() from exc


def _readonly_if_exists(db_path: str | Path) -> sqlite3.Connection | None:
    path = _path(db_path)
    try:
        mode = path.stat().st_mode
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise FormalTradeAttributionStoreError("归属账本路径不可访问") from exc
    if not stat.S_ISREG(mode):
        raise FormalTradeAttributionStoreCorruptedError("归属账本不是普通文件")
    try:
        conn = _connect(path, readonly=True)
        _schema_contract(conn)
        return conn
    except FormalTradeAttributionStoreError:
        try: conn.close()
        except Exception: pass
        raise
    except (sqlite3.Error, OSError) as exc:
        try: conn.close()
        except Exception: pass
        raise FormalTradeAttributionStoreCorruptedError() from exc


def _validated(record: Mapping[str, Any] | FormalTradeAttribution) -> dict[str, Any]:
    payload = record.to_dict() if isinstance(record, FormalTradeAttribution) else dict(record) if isinstance(record, Mapping) else None
    if payload is None:
        raise FormalTradeAttributionStoreError("record 必须是归属对象或 mapping")
    try:
        return tb1_from_dict(payload).to_dict()
    except (AttributionValidationError, AttributionSchemaVersionError) as exc:
        raise FormalTradeAttributionStoreError(str(exc)) from exc


def _row(row: sqlite3.Row) -> dict[str, Any]:
    try:
        return tb1_from_dict({column: row[column] for column in _COLUMNS}).to_dict()
    except (AttributionValidationError, AttributionSchemaVersionError) as exc:
        raise FormalTradeAttributionStoreCorruptedError(str(exc)) from exc


def write_attribution(*, db_path: str | Path, record: Mapping[str, Any] | FormalTradeAttribution) -> dict[str, Any]:
    value = _validated(record)
    with _LOCK:
        conn = _initialize(_path(db_path))
        try:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(f"SELECT * FROM {_TABLE} WHERE attribution_id=?", (value["attribution_id"],)).fetchone()
            if existing is not None:
                old = _row(existing)
                if old != value:
                    raise FormalTradeAttributionStoreConflictError("attribution_id 重放内容冲突")
                conn.execute("COMMIT")
                return old
            existing = conn.execute(f"SELECT 1 FROM {_TABLE} WHERE trade_id=?", (value["trade_id"],)).fetchone()
            if existing is not None:
                raise FormalTradeAttributionStoreConflictError("trade_id 已存在不同归属")
            conn.execute(
                f"INSERT INTO {_TABLE} ({','.join(_COLUMNS)}) VALUES ({','.join('?' for _ in _COLUMNS)})",
                tuple(value[col] for col in _COLUMNS),
            )
            conn.execute("COMMIT")
            return value
        except FormalTradeAttributionStoreError:
            try: conn.execute("ROLLBACK")
            except Exception: pass
            raise
        except sqlite3.Error as exc:
            try: conn.execute("ROLLBACK")
            except Exception: pass
            raise FormalTradeAttributionStoreCorruptedError() from exc
        finally:
            conn.close()


def _require_id(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise FormalTradeAttributionStoreError(f"{field} 必须是非空字符串")
    return value


def get_attribution(*, db_path: str | Path, attribution_id: str) -> dict[str, Any] | None:
    return _get_one(db_path, "attribution_id", _require_id(attribution_id, "attribution_id"))


def get_attribution_for_trade(*, db_path: str | Path, trade_id: str) -> dict[str, Any] | None:
    return _get_one(db_path, "trade_id", _require_id(trade_id, "trade_id"))


def _get_one(db_path: str | Path, column: str, value: str) -> dict[str, Any] | None:
    conn = _readonly_if_exists(db_path)
    if conn is None:
        return None
    try:
        row = conn.execute(f"SELECT * FROM {_TABLE} WHERE {column}=?", (value,)).fetchone()
        return None if row is None else _row(row)
    except sqlite3.Error as exc:
        raise FormalTradeAttributionStoreCorruptedError() from exc
    finally:
        conn.close()


def list_attributions(*, db_path: str | Path, decision_id: str | None = None,
                      campaign_id: str | None = None, security_code: str | None = None,
                      limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
    if isinstance(limit, bool) or isinstance(offset, bool) or not isinstance(limit, int) or not isinstance(offset, int) or limit < 0 or offset < 0 or limit > 500:
        raise FormalTradeAttributionStoreError("非法 limit/offset")
    conn = _readonly_if_exists(db_path)
    if conn is None:
        return []
    try:
        clauses, params = ["1=1"], []
        for name, value in (("decision_id", decision_id), ("campaign_id", campaign_id), ("security_code", security_code)):
            if value is not None:
                clauses.append(f"{name}=?")
                params.append(_require_id(value, name))
        params += [limit, offset]
        rows = conn.execute(f"SELECT * FROM {_TABLE} WHERE {' AND '.join(clauses)} ORDER BY created_at, attribution_id LIMIT ? OFFSET ?", params).fetchall()
        return [_row(row) for row in rows]
    except FormalTradeAttributionStoreError:
        raise
    except sqlite3.Error as exc:
        raise FormalTradeAttributionStoreCorruptedError() from exc
    finally:
        conn.close()
