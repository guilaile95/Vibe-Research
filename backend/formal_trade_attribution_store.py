"""Formal Trade Attribution Persistence Ledger v0.1 (P0-TB2).

Append-only SQLite ledger for already-validated P0-TB1 FormalTradeAttribution
records. Domain validation stays in ``formal_trade_attribution.from_dict``.

```text
TB2_ROLE = FORMAL_TRADE_ATTRIBUTION_PERSISTENCE_AUTHORITY
STORE_SCHEMA_VERSION = formal-trade-attribution-ledger.v0.1
DOMAIN_SCHEMA_VERSION = formal_trade_attribution.v0.1
```

Import has zero filesystem side effects. Reads never create files.
Writes initialize schema only after O_EXCL first-open ownership.

No UPDATE / DELETE / UPSERT / REPLACE. No Campaign / Trade Ledger / Frozen
Decision I/O. No attribution-id generation. No campaign inference.
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

_LOCK = threading.Lock()
_OPEN_WAIT_TOTAL_SECONDS = 10.0
_OPEN_WAIT_INTERVAL_SECONDS = 0.02
_DEFAULT_LIMIT = 100
_MAX_LIMIT = 500

_COLUMNS: tuple[str, ...] = (
    "attribution_id",
    "trade_id",
    "decision_id",
    "decision_snapshot_hash",
    "security_code",
    "strategy",
    "campaign_id",
    "thesis_id",
    "thesis_revision",
    "decision_committed_at",
    "decision_review_by",
    "decision_next_best_action",
    "trade_operation",
    "trade_execution_status",
    "trade_executed_at",
    "trade_created_at",
    "created_at",
    "schema_version",
    "attribution_hash",
)

_TABLE = "formal_trade_attributions"


class FormalTradeAttributionStoreError(RuntimeError):
    """TB2 persistence base error."""


class FormalTradeAttributionStoreCorruptedError(FormalTradeAttributionStoreError):
    """Ledger file / schema / row is corrupt. Fail closed."""

    MESSAGE = "正式交易归属账本数据损坏，已停止读写"

    def __init__(self, message: str | None = None):
        super().__init__(message or self.MESSAGE)


class FormalTradeAttributionStoreSchemaVersionError(FormalTradeAttributionStoreError):
    """Storage schema version mismatch. Fail closed. No migration."""

    MESSAGE = "正式交易归属账本 schema 版本不兼容"

    def __init__(self, message: str | None = None):
        super().__init__(message or self.MESSAGE)


class FormalTradeAttributionStoreConflictError(FormalTradeAttributionStoreError):
    """Exact-identity replay with different content, or one-trade/one-attribution clash."""


def resolve_formal_trade_attribution_db_path(
    *, explicit_path: str | Path | None = None
) -> Path:
    """Pure path resolution. No filesystem I/O."""
    if explicit_path:
        return Path(explicit_path)
    env_db = os.environ.get("VIBE_RESEARCH_TRADE_ATTRIBUTION_DB", "").strip()
    if env_db:
        return Path(env_db)
    env_dir = os.environ.get("VR_DATA_DIR", "").strip()
    if env_dir:
        return Path(env_dir) / "formal_trade_attributions.sqlite3"
    return Path.home() / ".vibe-research" / "formal_trade_attributions.sqlite3"


def _as_path(db_path: str | Path) -> Path:
    if isinstance(db_path, Path):
        return db_path
    if not isinstance(db_path, str) or not db_path.strip():
        raise FormalTradeAttributionStoreError("db_path 必须是非空字符串或 Path")
    return Path(db_path)


def _classify_ledger_path(db_path: str | Path) -> str:
    """Distinguish true missing regular file from I/O / non-file paths.

    Returns ``missing`` or ``file``. Any other filesystem object or OSError
    fails closed and is never treated as a missing ledger.
    """
    path = _as_path(db_path)
    try:
        st = path.stat()
    except FileNotFoundError:
        return "missing"
    except OSError as exc:
        raise FormalTradeAttributionStoreError(
            f"无法访问归属账本路径：{exc}"
        ) from exc
    if stat.S_ISREG(st.st_mode):
        return "file"
    raise FormalTradeAttributionStoreError(
        "归属账本路径存在但不是普通文件"
    )


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def _connect_readonly(path: Path) -> sqlite3.Connection:
    resolved = path.resolve()
    conn = sqlite3.connect(f"{resolved.as_uri()}?mode=ro", timeout=5, uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


_CREATE_SCHEMA_META = """
CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
)
"""

_CREATE_ATTRIBUTIONS = """
CREATE TABLE IF NOT EXISTS formal_trade_attributions (
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
)
"""

_IDX_DECISION = """
CREATE INDEX IF NOT EXISTS idx_fta_decision_id
ON formal_trade_attributions(decision_id)
"""
_IDX_CAMPAIGN = """
CREATE INDEX IF NOT EXISTS idx_fta_campaign_id
ON formal_trade_attributions(campaign_id)
"""
_IDX_SECURITY = """
CREATE INDEX IF NOT EXISTS idx_fta_security_code
ON formal_trade_attributions(security_code)
"""

_ALL_DDL = (
    _CREATE_SCHEMA_META,
    _CREATE_ATTRIBUTIONS,
    _IDX_DECISION,
    _IDX_CAMPAIGN,
    _IDX_SECURITY,
)

_EXPECTED_TABLES = frozenset({"schema_meta", "formal_trade_attributions"})

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


def _assert_table_contract(
    conn: sqlite3.Connection,
    table_name: str,
    expected: Mapping[str, tuple[str, bool, bool]],
) -> None:
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    actual = {
        row["name"]: (row["type"].upper(), bool(row["notnull"]), bool(row["pk"]))
        for row in rows
    }
    if set(actual) != set(expected):
        raise FormalTradeAttributionStoreCorruptedError(
            f"{table_name} 列集合不符合 v0.1 契约：{sorted(actual)}"
        )
    for name, (etype, enotnull, epk) in expected.items():
        atype, anotnull, apk = actual[name]
        if atype != etype or anotnull != enotnull or apk != epk:
            raise FormalTradeAttributionStoreCorruptedError(
                f"{table_name}.{name} 结构不符契约"
            )


def _assert_query_indexes(conn: sqlite3.Connection) -> None:
    for name, (table, columns) in _EXPECTED_INDEXES.items():
        row = conn.execute(
            "SELECT tbl_name, sql FROM sqlite_master "
            "WHERE type = 'index' AND name = ?",
            (name,),
        ).fetchone()
        if row is None:
            raise FormalTradeAttributionStoreCorruptedError(f"必需索引缺失：{name}")
        if row["sql"] is None:
            raise FormalTradeAttributionStoreCorruptedError(
                f"{name} 是自动索引，不符合契约"
            )
        if row["tbl_name"] != table:
            raise FormalTradeAttributionStoreCorruptedError(
                f"索引 {name} 指向错误表"
            )
        info = conn.execute(f"PRAGMA index_info({name})").fetchall()
        actual_columns = [r["name"] for r in info]
        if actual_columns != list(columns):
            raise FormalTradeAttributionStoreCorruptedError(
                f"索引 {name} 目标列不符"
            )
        listed = conn.execute(f"PRAGMA index_list({table})").fetchall()
        match = [r for r in listed if r["name"] == name]
        if not match:
            raise FormalTradeAttributionStoreCorruptedError(
                f"索引 {name} 不在 index_list 中"
            )
        idx = match[0]
        if idx["unique"] != 0 or idx["partial"] != 0 or idx["origin"] != "c":
            raise FormalTradeAttributionStoreCorruptedError(
                f"索引 {name} 不是普通 CREATE INDEX"
            )


def _assert_unique_trade_id(conn: sqlite3.Connection) -> None:
    listed = conn.execute(f"PRAGMA index_list({_TABLE})").fetchall()
    found = False
    for idx in listed:
        if idx["unique"] != 1:
            continue
        if idx["partial"] != 0:
            continue
        info = conn.execute(f"PRAGMA index_info({idx['name']})").fetchall()
        cols = [r["name"] for r in info]
        if cols == ["trade_id"]:
            found = True
            break
    if not found:
        raise FormalTradeAttributionStoreCorruptedError(
            "缺少完整 UNIQUE(trade_id) 约束（partial unique 不接受）"
        )


def _assert_schema(conn: sqlite3.Connection) -> None:
    try:
        tables = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        if tables != set(_EXPECTED_TABLES):
            raise FormalTradeAttributionStoreCorruptedError(
                f"应用表集合不符合 v0.1 契约：{sorted(tables)}"
            )
        _assert_table_contract(conn, "schema_meta", _SCHEMA_META_COLUMNS)
        _assert_table_contract(conn, _TABLE, _ATTRIBUTION_COLUMNS)
        _assert_query_indexes(conn)
        _assert_unique_trade_id(conn)
        triggers = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'trigger'"
        ).fetchall()
        if triggers:
            raise FormalTradeAttributionStoreCorruptedError(
                f"不允许存在触发器：{[r['name'] for r in triggers]}"
            )
        views = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'view'"
        ).fetchall()
        if views:
            raise FormalTradeAttributionStoreCorruptedError(
                f"不允许存在视图：{[r['name'] for r in views]}"
            )
    except FormalTradeAttributionStoreError:
        raise
    except sqlite3.DatabaseError as exc:
        raise FormalTradeAttributionStoreCorruptedError() from exc


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (name,),
    ).fetchone()
    return row is not None


def _read_store_schema_version(conn: sqlite3.Connection) -> str | None:
    row = conn.execute(
        "SELECT value FROM schema_meta WHERE key = 'schema_version'"
    ).fetchone()
    return row["value"] if row else None


def _validate_existing_schema(conn: sqlite3.Connection) -> None:
    if not _table_exists(conn, "schema_meta"):
        has_any = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' "
            "AND name != 'sqlite_sequence' LIMIT 1"
        ).fetchone()
        if has_any is not None:
            raise FormalTradeAttributionStoreCorruptedError(
                "非空数据库缺少 schema_meta"
            )
        raise FormalTradeAttributionStoreCorruptedError("缺少 schema_meta")
    version = _read_store_schema_version(conn)
    if version is None:
        raise FormalTradeAttributionStoreCorruptedError(
            "schema_meta 存在但缺少 schema_version"
        )
    if version != STORE_SCHEMA_VERSION:
        raise FormalTradeAttributionStoreSchemaVersionError(
            f"不支持的 schema 版本：{version}（期望 {STORE_SCHEMA_VERSION}）"
        )
    _assert_schema(conn)


def _initialize(conn: sqlite3.Connection) -> None:
    for ddl in _ALL_DDL:
        conn.execute(ddl)
    conn.execute(
        "INSERT INTO schema_meta(key, value) VALUES ('schema_version', ?)",
        (STORE_SCHEMA_VERSION,),
    )


def _acquire_initialization_ownership(path: Path) -> bool:
    flags = os.O_CREAT | os.O_EXCL | os.O_RDWR
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    try:
        fd = os.open(str(path), flags, 0o600)
    except FileExistsError:
        return False
    except OSError as exc:
        raise FormalTradeAttributionStoreError("归属账本不可用") from exc
    try:
        os.close(fd)
    except OSError as exc:
        raise FormalTradeAttributionStoreError("归属账本不可用") from exc
    return True


def _safe_rollback(conn: sqlite3.Connection) -> None:
    try:
        conn.execute("ROLLBACK")
    except sqlite3.Error:
        pass


def _open_write_connection(db_path: str | Path) -> sqlite3.Connection:
    path = _as_path(db_path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise FormalTradeAttributionStoreError("归属账本不可用") from exc
    owned = _acquire_initialization_ownership(path)
    deadline = time.monotonic() + _OPEN_WAIT_TOTAL_SECONDS
    while True:
        try:
            conn = sqlite3.connect(str(path), isolation_level=None, timeout=10.0)
        except (sqlite3.Error, OSError) as exc:
            raise FormalTradeAttributionStoreError("归属账本不可用") from exc
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("BEGIN IMMEDIATE")
        except sqlite3.Error as exc:
            conn.close()
            raise FormalTradeAttributionStoreCorruptedError() from exc
        try:
            tables = {
                row["name"]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
            if tables == set(_EXPECTED_TABLES):
                _validate_existing_schema(conn)
                conn.execute("COMMIT")
                return conn
            if tables:
                raise FormalTradeAttributionStoreCorruptedError()
            if owned:
                _initialize(conn)
                conn.execute("COMMIT")
                return conn
            if time.monotonic() >= deadline:
                raise FormalTradeAttributionStoreCorruptedError(
                    "INITIALIZATION_INCOMPLETE"
                )
            _safe_rollback(conn)
            conn.close()
            time.sleep(_OPEN_WAIT_INTERVAL_SECONDS)
            continue
        except FormalTradeAttributionStoreError:
            _safe_rollback(conn)
            conn.close()
            raise
        except sqlite3.Error as exc:
            _safe_rollback(conn)
            conn.close()
            raise FormalTradeAttributionStoreCorruptedError() from exc
        except BaseException:
            _safe_rollback(conn)
            conn.close()
            raise


def _open_readonly_if_exists(db_path: str | Path) -> sqlite3.Connection | None:
    kind = _classify_ledger_path(db_path)
    if kind == "missing":
        return None
    conn = None
    try:
        conn = _connect_readonly(_as_path(db_path))
        _validate_existing_schema(conn)
        return conn
    except FormalTradeAttributionStoreError:
        if conn is not None:
            conn.close()
        raise
    except (sqlite3.Error, OSError) as exc:
        if conn is not None:
            conn.close()
        raise FormalTradeAttributionStoreCorruptedError() from exc


def _validate_domain(record: Mapping[str, Any] | FormalTradeAttribution) -> dict[str, Any]:
    if isinstance(record, FormalTradeAttribution):
        payload = record.to_dict()
    elif isinstance(record, Mapping):
        payload = dict(record)
    else:
        raise FormalTradeAttributionStoreError("record 必须是 Mapping 或 FormalTradeAttribution")
    try:
        return tb1_from_dict(payload).to_dict()
    except (AttributionValidationError, AttributionSchemaVersionError) as exc:
        raise FormalTradeAttributionStoreError(str(exc)) from exc


def _row_to_record(row: sqlite3.Row) -> dict[str, Any]:
    payload = {col: row[col] for col in _COLUMNS}
    try:
        return tb1_from_dict(payload).to_dict()
    except (AttributionValidationError, AttributionSchemaVersionError) as exc:
        raise FormalTradeAttributionStoreCorruptedError(str(exc)) from exc


def _records_equal(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    return {k: left[k] for k in _COLUMNS} == {k: right[k] for k in _COLUMNS}


def _require_id(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise FormalTradeAttributionStoreError(f"{field} 必须是非空规范字符串")
    return value


def _require_limit_offset(*, limit: object, offset: object) -> tuple[int, int]:
    if isinstance(limit, bool) or isinstance(offset, bool):
        raise FormalTradeAttributionStoreError("limit/offset 不得为 bool")
    if not isinstance(limit, int) or not isinstance(offset, int):
        raise FormalTradeAttributionStoreError("limit/offset 必须是 int")
    if limit < 0 or offset < 0:
        raise FormalTradeAttributionStoreError("limit/offset 不得为负")
    if limit > _MAX_LIMIT:
        raise FormalTradeAttributionStoreError(
            f"limit 超过上限 {_MAX_LIMIT}（禁止 clamp）"
        )
    return limit, offset


def write_attribution(
    *, db_path: str | Path, record: Mapping[str, Any] | FormalTradeAttribution
) -> dict[str, Any]:
    """Persist a TB1-validated attribution. Exact replay is idempotent."""
    validated = _validate_domain(record)
    with _LOCK:
        conn = _open_write_connection(db_path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            existing_id = conn.execute(
                f"SELECT * FROM {_TABLE} WHERE attribution_id = ?",
                (validated["attribution_id"],),
            ).fetchone()
            if existing_id is not None:
                existing = _row_to_record(existing_id)
                if not _records_equal(existing, validated):
                    raise FormalTradeAttributionStoreConflictError(
                        f"attribution_id {validated['attribution_id']} 已存在且内容不一致"
                    )
                conn.execute("COMMIT")
                return existing
            existing_trade = conn.execute(
                f"SELECT * FROM {_TABLE} WHERE trade_id = ?",
                (validated["trade_id"],),
            ).fetchone()
            if existing_trade is not None:
                raise FormalTradeAttributionStoreConflictError(
                    f"trade_id {validated['trade_id']} 已存在不同归属"
                )
            values = tuple(validated[col] for col in _COLUMNS)
            try:
                conn.execute(
                    f"INSERT INTO {_TABLE} ({', '.join(_COLUMNS)}) "
                    f"VALUES ({', '.join('?' for _ in _COLUMNS)})",
                    values,
                )
            except sqlite3.IntegrityError as exc:
                conn.execute("ROLLBACK")
                raise FormalTradeAttributionStoreConflictError(
                    "归属冲突（UNIQUE 约束）"
                ) from exc
            conn.execute("COMMIT")
            return validated
        except FormalTradeAttributionStoreError:
            _safe_rollback(conn)
            raise
        except sqlite3.DatabaseError as exc:
            _safe_rollback(conn)
            raise FormalTradeAttributionStoreCorruptedError() from exc
        finally:
            conn.close()


def get_attribution(*, db_path: str | Path, attribution_id: str) -> dict[str, Any] | None:
    attribution_id = _require_id(attribution_id, "attribution_id")
    conn = _open_readonly_if_exists(db_path)
    if conn is None:
        return None
    try:
        row = conn.execute(
            f"SELECT * FROM {_TABLE} WHERE attribution_id = ?",
            (attribution_id,),
        ).fetchone()
        if row is None:
            return None
        return _row_to_record(row)
    except FormalTradeAttributionStoreError:
        raise
    except sqlite3.DatabaseError as exc:
        raise FormalTradeAttributionStoreCorruptedError() from exc
    finally:
        conn.close()


def get_attribution_for_trade(*, db_path: str | Path, trade_id: str) -> dict[str, Any] | None:
    trade_id = _require_id(trade_id, "trade_id")
    conn = _open_readonly_if_exists(db_path)
    if conn is None:
        return None
    try:
        row = conn.execute(
            f"SELECT * FROM {_TABLE} WHERE trade_id = ?",
            (trade_id,),
        ).fetchone()
        if row is None:
            return None
        return _row_to_record(row)
    except FormalTradeAttributionStoreError:
        raise
    except sqlite3.DatabaseError as exc:
        raise FormalTradeAttributionStoreCorruptedError() from exc
    finally:
        conn.close()


def list_attributions(
    *,
    db_path: str | Path,
    decision_id: str | None = None,
    campaign_id: str | None = None,
    security_code: str | None = None,
    limit: int = _DEFAULT_LIMIT,
    offset: int = 0,
) -> list[dict[str, Any]]:
    limit, offset = _require_limit_offset(limit=limit, offset=offset)
    conn = _open_readonly_if_exists(db_path)
    if conn is None:
        return []
    try:
        where = "WHERE 1=1"
        params: list[Any] = []
        if decision_id is not None:
            where += " AND decision_id = ?"
            params.append(_require_id(decision_id, "decision_id"))
        if campaign_id is not None:
            where += " AND campaign_id = ?"
            params.append(_require_id(campaign_id, "campaign_id"))
        if security_code is not None:
            where += " AND security_code = ?"
            params.append(_require_id(security_code, "security_code"))
        params.extend([limit, offset])
        rows = conn.execute(
            f"SELECT * FROM {_TABLE} {where} "
            "ORDER BY created_at ASC, attribution_id ASC LIMIT ? OFFSET ?",
            params,
        ).fetchall()
        return [_row_to_record(row) for row in rows]
    except FormalTradeAttributionStoreError:
        raise
    except sqlite3.DatabaseError as exc:
        raise FormalTradeAttributionStoreCorruptedError() from exc
    finally:
        conn.close()
