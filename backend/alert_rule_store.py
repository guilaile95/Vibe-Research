"""告警规则 SQLite 持久化层 v0.1。

只负责规则记录的存储与 CRUD，不做规则求值、通知、调度或历史事件。
模块 import 不创建目录、不创建数据库、不连接 SQLite、不执行迁移。
"""

from __future__ import annotations

import os
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, StrictInt, StrictStr, field_validator

from alert_rules import CODE_PATTERN, RULE_ID_PATTERN, AlertRule

ALERT_RULE_STORE_SCHEMA_VERSION = "alert-rule-store.v0.1"
ALERT_RULE_RECORD_SCHEMA_VERSION = "alert-rule-record.v0.1"

_TIMESTAMP_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z$"
)
_TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"
_MIN_TICK = timedelta(microseconds=1)

_ROW_COLUMNS = (
    "rule_id",
    "code",
    "enabled",
    "condition_kind",
    "rule_json",
    "revision",
    "created_at",
    "updated_at",
    "deleted_at",
)
_SELECT_COLUMNS = ", ".join(_ROW_COLUMNS)

LIST_LIMIT_MIN = 1
LIST_LIMIT_MAX = 200


class AlertRuleStoreError(RuntimeError):
    """告警规则存储错误基类。"""


class AlertRuleStoreCorruptedError(AlertRuleStoreError):
    """数据库文件或行数据不可信任时抛出，不得解释为空数据。"""

    MESSAGE = "告警规则数据损坏，已停止读写"

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.MESSAGE)


class AlertRuleStoreInputError(AlertRuleStoreError, ValueError):
    """调用方入参不满足存储合同。"""


class AlertRuleAlreadyExistsError(AlertRuleStoreError):
    """同一 rule_id 已存在，包括已软删除记录。"""


class AlertRuleNotFoundError(AlertRuleStoreError, LookupError):
    """目标规则不存在或已软删除。"""


class AlertRuleRevisionConflictError(AlertRuleStoreError):
    """乐观锁 revision 不匹配。"""


def alert_rule_db_path() -> str:
    """解析规则数据库路径，不创建任何目录或文件。

    优先级：
    1. `VIBE_RESEARCH_ALERT_RULE_DB`
    2. `VR_DATA_DIR/alert_rules.sqlite3`
    3. `~/.vibe-research/alert_rules.sqlite3`
    """
    env_db = os.environ.get("VIBE_RESEARCH_ALERT_RULE_DB", "").strip()
    if env_db:
        return str(Path(env_db))
    env_dir = os.environ.get("VR_DATA_DIR", "").strip()
    if env_dir:
        return str(Path(env_dir) / "alert_rules.sqlite3")
    return str(Path.home() / ".vibe-research" / "alert_rules.sqlite3")


def _validate_timestamp(value: Any) -> str:
    if not isinstance(value, str) or not _TIMESTAMP_RE.fullmatch(value):
        raise ValueError("timestamp must match YYYY-MM-DDTHH:MM:SS.ffffffZ")
    try:
        datetime.strptime(value, _TIMESTAMP_FORMAT)
    except ValueError as exc:
        raise ValueError("timestamp must be a real UTC instant") from exc
    return value


def _parse_timestamp(value: str) -> datetime:
    return datetime.strptime(_validate_timestamp(value), _TIMESTAMP_FORMAT).replace(
        tzinfo=timezone.utc
    )


def _format_timestamp(moment: datetime) -> str:
    if not isinstance(moment, datetime):
        raise AlertRuleStoreInputError("now must be a datetime")
    if moment.tzinfo is None or moment.tzinfo.utcoffset(moment) is None:
        raise AlertRuleStoreInputError("now must be timezone-aware")
    return moment.astimezone(timezone.utc).strftime(_TIMESTAMP_FORMAT)


def _observation_timestamp(now: datetime | None) -> str:
    if now is None:
        return _format_timestamp(datetime.now(timezone.utc))
    return _format_timestamp(now)


class AlertRuleRecord(BaseModel):
    """规则存储记录，读写两侧共用同一套不变量。"""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal["alert-rule-record.v0.1"] = ALERT_RULE_RECORD_SCHEMA_VERSION
    rule: AlertRule
    revision: StrictInt
    created_at: StrictStr
    updated_at: StrictStr
    deleted_at: StrictStr | None

    @field_validator("revision")
    @classmethod
    def _check_revision(cls, value: int) -> int:
        if value < 1:
            raise ValueError("revision must be >= 1")
        return value

    @field_validator("created_at", "updated_at")
    @classmethod
    def _check_required_timestamp(cls, value: str) -> str:
        return _validate_timestamp(value)

    @field_validator("deleted_at")
    @classmethod
    def _check_optional_timestamp(cls, value: str | None) -> str | None:
        return None if value is None else _validate_timestamp(value)


_DDL = (
    """
    CREATE TABLE schema_meta (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE alert_rules (
        rule_id TEXT PRIMARY KEY,
        code TEXT NOT NULL,
        enabled INTEGER NOT NULL CHECK (enabled IN (0, 1)),
        condition_kind TEXT NOT NULL,
        rule_json TEXT NOT NULL,
        revision INTEGER NOT NULL CHECK (revision >= 1),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        deleted_at TEXT
    )
    """,
    "CREATE INDEX idx_alert_rules_code ON alert_rules (code)",
    "CREATE INDEX idx_alert_rules_enabled ON alert_rules (enabled)",
    "CREATE INDEX idx_alert_rules_updated_at ON alert_rules (updated_at)",
)


def _existing_tables(conn: sqlite3.Connection) -> set[str]:
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name IN (?, ?)",
            ("schema_meta", "alert_rules"),
        ).fetchall()
    except sqlite3.Error as exc:
        raise AlertRuleStoreCorruptedError() from exc
    return {row[0] for row in rows}


def _all_user_tables(conn: sqlite3.Connection) -> set[str]:
    """Return all user-defined table names (excluding sqlite internal)."""
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' "
            "AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
    except sqlite3.Error as exc:
        raise AlertRuleStoreCorruptedError() from exc
    return {row[0] for row in rows}


_REQUIRED_COLUMNS: dict[str, tuple[str, int, int]] = {
    # name -> (type, notnull, pk)
    "rule_id": ("TEXT", 0, 1),
    "code": ("TEXT", 1, 0),
    "enabled": ("INTEGER", 1, 0),
    "condition_kind": ("TEXT", 1, 0),
    "rule_json": ("TEXT", 1, 0),
    "revision": ("INTEGER", 1, 0),
    "created_at": ("TEXT", 1, 0),
    "updated_at": ("TEXT", 1, 0),
    "deleted_at": ("TEXT", 0, 0),
}

_REQUIRED_INDEXES: dict[str, str] = {
    "idx_alert_rules_code": "createindexidx_alert_rules_codeonalert_rules(code)",
    "idx_alert_rules_enabled": "createindexidx_alert_rules_enabledonalert_rules(enabled)",
    "idx_alert_rules_updated_at": (
        "createindexidx_alert_rules_updated_atonalert_rules(updated_at)"
    ),
}


def _canonical_sql(sql: str) -> str:
    """把 SQLite 保存的 DDL 归一化为小写无空白形式，容忍等价格式差异。"""
    return "".join(sql.split()).lower()


def _assert_schema(conn: sqlite3.Connection) -> None:
    """校验已有 schema 结构完整性，任何异常都 fail-closed，不自动迁移或重建。"""
    tables = _existing_tables(conn)
    if tables != {"schema_meta", "alert_rules"}:
        raise AlertRuleStoreCorruptedError()
    try:
        # --- schema_meta validation ---
        rows = conn.execute(
            "SELECT value FROM schema_meta WHERE key = ?", ("schema_version",)
        ).fetchall()
        if len(rows) != 1 or rows[0][0] != ALERT_RULE_STORE_SCHEMA_VERSION:
            raise AlertRuleStoreCorruptedError()

        # --- alert_rules column validation via PRAGMA table_info ---
        col_rows = conn.execute("PRAGMA table_info(alert_rules)").fetchall()
        col_map: dict[str, tuple[str, int, int]] = {}
        for crow in col_rows:
            # cid, name, type, notnull, dflt_value, pk
            col_map[crow[1]] = (crow[2].upper(), crow[3], crow[5])
        for col_name, (exp_type, exp_notnull, exp_pk) in _REQUIRED_COLUMNS.items():
            if col_name not in col_map:
                raise AlertRuleStoreCorruptedError()
            actual_type, actual_notnull, actual_pk = col_map[col_name]
            if actual_type != exp_type:
                raise AlertRuleStoreCorruptedError()
            if actual_notnull != exp_notnull:
                raise AlertRuleStoreCorruptedError()
            if (actual_pk > 0) != (exp_pk > 0):
                raise AlertRuleStoreCorruptedError()

        # --- CHECK constraint validation via sqlite_master.sql ---
        sql_row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'alert_rules'"
        ).fetchone()
        if sql_row is None or sql_row[0] is None:
            raise AlertRuleStoreCorruptedError()
        create_sql = sql_row[0]
        canonical_sql = _canonical_sql(create_sql)
        if "check(enabledin(0,1))" not in canonical_sql:
            raise AlertRuleStoreCorruptedError()
        if "check(revision>=1)" not in canonical_sql:
            raise AlertRuleStoreCorruptedError()

        # --- Index validation ---
        idx_rows = conn.execute(
            "SELECT name, sql FROM sqlite_master "
            "WHERE type = 'index' AND tbl_name = 'alert_rules'"
        ).fetchall()
        found_index_sql = {row[0]: row[1] for row in idx_rows}
        for idx_name, expected_sql in _REQUIRED_INDEXES.items():
            actual_sql = found_index_sql.get(idx_name)
            if actual_sql is None:
                raise AlertRuleStoreCorruptedError()
            if _canonical_sql(actual_sql) != expected_sql:
                raise AlertRuleStoreCorruptedError()

        # --- Verify SELECT works ---
        conn.execute(f"SELECT {_SELECT_COLUMNS} FROM alert_rules LIMIT 0").fetchall()
    except AlertRuleStoreCorruptedError:
        raise
    except sqlite3.Error as exc:
        raise AlertRuleStoreCorruptedError() from exc


def _initialize(conn: sqlite3.Connection) -> None:
    """在已持有写锁的连接上执行 schema 初始化。调用方负责 BEGIN IMMEDIATE。"""
    try:
        for statement in _DDL:
            conn.execute(statement)
        conn.execute(
            "INSERT INTO schema_meta (key, value) VALUES (?, ?)",
            ("schema_version", ALERT_RULE_STORE_SCHEMA_VERSION),
        )
    except sqlite3.Error as exc:
        raise AlertRuleStoreError("告警规则数据库初始化失败") from exc


def _safe_rollback(conn: sqlite3.Connection) -> None:
    try:
        conn.execute("ROLLBACK")
    except sqlite3.Error:
        pass


def _open_write_connection() -> sqlite3.Connection:
    """只有写操作才允许触发目录创建与 schema 初始化。

    初始化资格：只有调用开始时路径确实不存在，才允许初始化。
    任何调用开始时已经存在的文件，都必须按已有数据库校验。
    使用 BEGIN IMMEDIATE 保护初始化竞态。
    """
    path = Path(alert_rule_db_path())
    path_existed_before = path.exists()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise AlertRuleStoreError("告警规则数据库不可用") from exc
    try:
        conn = sqlite3.connect(str(path), isolation_level=None, timeout=10.0)
    except (sqlite3.Error, OSError) as exc:
        raise AlertRuleStoreError("告警规则数据库不可用") from exc
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("BEGIN IMMEDIATE")
    except sqlite3.Error as exc:
        conn.close()
        raise AlertRuleStoreCorruptedError() from exc
    try:
        tables = _existing_tables(conn)
        if tables == {"schema_meta", "alert_rules"}:
            # Schema present — validate fully
            _assert_schema(conn)
        elif not tables and not _all_user_tables(conn):
            # Completely empty database
            if path_existed_before:
                # Pre-existing empty file: must NOT initialize
                raise AlertRuleStoreCorruptedError()
            # New path: we have initialization authority
            _initialize(conn)
        else:
            # Has some tables but not the complete project schema
            raise AlertRuleStoreCorruptedError()
        conn.execute("COMMIT")
    except AlertRuleStoreError:
        _safe_rollback(conn)
        conn.close()
        raise
    except sqlite3.Error as exc:
        _safe_rollback(conn)
        conn.close()
        raise AlertRuleStoreError("告警规则数据库不可用") from exc
    except BaseException:
        _safe_rollback(conn)
        conn.close()
        raise
    return conn


def _read_only_uri(path: Path) -> str:
    """构造安全的只读 SQLite file URI，正确转义特殊字符。"""
    resolved = path.resolve()
    # Use as_uri() for proper encoding, then append mode=ro
    base = resolved.as_uri()
    return f"{base}?mode=ro"


def _open_read_connection() -> sqlite3.Connection | None:
    """只读连接；数据库文件不存在时返回 None，且不产生任何写副作用。"""
    path = Path(alert_rule_db_path())
    if not path.is_file():
        return None
    try:
        uri = _read_only_uri(path)
        conn = sqlite3.connect(uri, uri=True, timeout=10.0)
    except (sqlite3.Error, OSError) as exc:
        raise AlertRuleStoreCorruptedError() from exc
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA query_only = ON")
        _assert_schema(conn)
    except AlertRuleStoreError:
        conn.close()
        raise
    except sqlite3.Error as exc:
        conn.close()
        raise AlertRuleStoreCorruptedError() from exc
    return conn


def _record_from_row(row: sqlite3.Row) -> AlertRuleRecord:
    """镜像列与 rule_json 必须互相印证，任一不一致视为损坏。"""
    rule_json = row["rule_json"]
    if not isinstance(rule_json, str):
        raise AlertRuleStoreCorruptedError()
    try:
        rule = AlertRule.model_validate_json(rule_json)
    except Exception as exc:
        raise AlertRuleStoreCorruptedError() from exc
    enabled_column = row["enabled"]
    if isinstance(enabled_column, bool) or enabled_column not in (0, 1):
        raise AlertRuleStoreCorruptedError()
    if (
        row["rule_id"] != rule.rule_id
        or row["code"] != rule.code
        or bool(enabled_column) != rule.enabled
        or row["condition_kind"] != rule.condition.kind
    ):
        raise AlertRuleStoreCorruptedError()
    try:
        return AlertRuleRecord(
            rule=rule,
            revision=row["revision"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            deleted_at=row["deleted_at"],
        )
    except Exception as exc:
        raise AlertRuleStoreCorruptedError() from exc


def _row_values(record: AlertRuleRecord) -> tuple[Any, ...]:
    rule = record.rule
    return (
        rule.rule_id,
        rule.code,
        1 if rule.enabled else 0,
        rule.condition.kind,
        rule.model_dump_json(),
        record.revision,
        record.created_at,
        record.updated_at,
        record.deleted_at,
    )


def _validated_rule_id(value: Any) -> str:
    if not isinstance(value, str) or not RULE_ID_PATTERN.fullmatch(value):
        raise AlertRuleStoreInputError(
            "rule_id must match ^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$"
        )
    return value


def _validated_code(value: Any) -> str:
    if not isinstance(value, str) or not CODE_PATTERN.fullmatch(value):
        raise AlertRuleStoreInputError("code must be exactly 6 ASCII digits")
    return value


def _validated_flag(value: Any, *, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise AlertRuleStoreInputError(f"{field_name} must be a bool")
    return value


def _validated_index(
    value: Any, *, field_name: str, minimum: int, maximum: int | None = None
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise AlertRuleStoreInputError(f"{field_name} must be an int")
    if value < minimum or (maximum is not None and value > maximum):
        raise AlertRuleStoreInputError(f"{field_name} is out of range")
    return value


def _validated_rule(value: Any, *, field_name: str) -> AlertRule:
    if not isinstance(value, AlertRule):
        raise AlertRuleStoreInputError(f"{field_name} must be an AlertRule")
    return value


def create_alert_rule(rule: AlertRule, *, now: datetime | None = None) -> AlertRuleRecord:
    """插入新规则；rule_id 已存在（含软删除）时拒绝，不复活也不覆盖。"""
    _validated_rule(rule, field_name="rule")
    observed = _observation_timestamp(now)
    record = AlertRuleRecord(
        rule=rule,
        revision=1,
        created_at=observed,
        updated_at=observed,
        deleted_at=None,
    )
    conn = _open_write_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            existing = conn.execute(
                "SELECT 1 FROM alert_rules WHERE rule_id = ?", (rule.rule_id,)
            ).fetchone()
            if existing is not None:
                raise AlertRuleAlreadyExistsError(f"alert rule already exists: {rule.rule_id}")
            placeholders = ", ".join("?" for _ in _ROW_COLUMNS)
            conn.execute(
                f"INSERT INTO alert_rules ({_SELECT_COLUMNS}) VALUES ({placeholders})",
                _row_values(record),
            )
            conn.execute("COMMIT")
        except AlertRuleStoreError:
            _safe_rollback(conn)
            raise
        except sqlite3.Error as exc:
            _safe_rollback(conn)
            raise AlertRuleStoreError("告警规则写入失败") from exc
    finally:
        conn.close()
    return record


def get_alert_rule(rule_id: str, *, include_deleted: bool = False) -> AlertRuleRecord | None:
    """按 rule_id 读取单条规则；数据库不存在时返回 None。"""
    validated_id = _validated_rule_id(rule_id)
    _validated_flag(include_deleted, field_name="include_deleted")
    conn = _open_read_connection()
    if conn is None:
        return None
    try:
        sql = f"SELECT {_SELECT_COLUMNS} FROM alert_rules WHERE rule_id = ?"
        if not include_deleted:
            sql += " AND deleted_at IS NULL"
        try:
            row = conn.execute(sql, (validated_id,)).fetchone()
        except sqlite3.Error as exc:
            raise AlertRuleStoreCorruptedError() from exc
    finally:
        conn.close()
    return None if row is None else _record_from_row(row)


def list_alert_rules(
    *,
    code: str | None = None,
    enabled: bool | None = None,
    include_deleted: bool = False,
    limit: int = 100,
    offset: int = 0,
) -> list[AlertRuleRecord]:
    """分页列出规则，排序固定为 updated_at DESC, rule_id ASC。"""
    _validated_flag(include_deleted, field_name="include_deleted")
    _validated_index(limit, field_name="limit", minimum=LIST_LIMIT_MIN, maximum=LIST_LIMIT_MAX)
    _validated_index(offset, field_name="offset", minimum=0)
    conditions: list[str] = []
    params: list[Any] = []
    if code is not None:
        conditions.append("code = ?")
        params.append(_validated_code(code))
    if enabled is not None:
        conditions.append("enabled = ?")
        params.append(1 if _validated_flag(enabled, field_name="enabled") else 0)
    if not include_deleted:
        conditions.append("deleted_at IS NULL")

    conn = _open_read_connection()
    if conn is None:
        return []
    try:
        sql = f"SELECT {_SELECT_COLUMNS} FROM alert_rules"
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        sql += " ORDER BY updated_at DESC, rule_id ASC LIMIT ? OFFSET ?"
        try:
            rows = conn.execute(sql, (*params, limit, offset)).fetchall()
        except sqlite3.Error as exc:
            raise AlertRuleStoreCorruptedError() from exc
    finally:
        conn.close()
    return [_record_from_row(row) for row in rows]


def _monotonic_timestamp(previous: str, requested: str) -> str:
    """保证 updated_at 严格单调，即使调用方给出更早的时间。"""
    if requested > previous:
        return requested
    try:
        return _format_timestamp(_parse_timestamp(previous) + _MIN_TICK)
    except (OverflowError, OSError) as exc:
        raise AlertRuleStoreError("时间戳超出可表示范围") from exc


def _live_record(conn: sqlite3.Connection, rule_id: str) -> AlertRuleRecord:
    row = conn.execute(
        f"SELECT {_SELECT_COLUMNS} FROM alert_rules WHERE rule_id = ?", (rule_id,)
    ).fetchone()
    if row is None:
        raise AlertRuleNotFoundError(f"alert rule not found: {rule_id}")
    record = _record_from_row(row)
    if record.deleted_at is not None:
        raise AlertRuleNotFoundError(f"alert rule not found: {rule_id}")
    return record


def replace_alert_rule(
    rule_id: str,
    replacement: AlertRule,
    *,
    expected_revision: int,
    now: datetime | None = None,
) -> AlertRuleRecord:
    """整体替换规则内容；软删除记录不可替换也不复活。"""
    validated_id = _validated_rule_id(rule_id)
    _validated_rule(replacement, field_name="replacement")
    if replacement.rule_id != validated_id:
        raise AlertRuleStoreInputError("rule_id must equal replacement.rule_id")
    _validated_index(expected_revision, field_name="expected_revision", minimum=1)
    requested = _observation_timestamp(now)

    conn = _open_write_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            current = _live_record(conn, validated_id)
            if current.revision != expected_revision:
                raise AlertRuleRevisionConflictError(
                    f"alert rule revision conflict: {validated_id}"
                )
            record = AlertRuleRecord(
                rule=replacement,
                revision=current.revision + 1,
                created_at=current.created_at,
                updated_at=_monotonic_timestamp(current.updated_at, requested),
                deleted_at=None,
            )
            cursor = conn.execute(
                "UPDATE alert_rules SET code = ?, enabled = ?, condition_kind = ?, "
                "rule_json = ?, revision = ?, updated_at = ? "
                "WHERE rule_id = ? AND revision = ? AND deleted_at IS NULL",
                (
                    replacement.code,
                    1 if replacement.enabled else 0,
                    replacement.condition.kind,
                    replacement.model_dump_json(),
                    record.revision,
                    record.updated_at,
                    validated_id,
                    expected_revision,
                ),
            )
            if cursor.rowcount != 1:
                raise AlertRuleRevisionConflictError(
                    f"alert rule revision conflict: {validated_id}"
                )
            conn.execute("COMMIT")
        except AlertRuleStoreError:
            _safe_rollback(conn)
            raise
        except sqlite3.Error as exc:
            _safe_rollback(conn)
            raise AlertRuleStoreError("告警规则更新失败") from exc
    finally:
        conn.close()
    return record


def delete_alert_rule(
    rule_id: str,
    *,
    expected_revision: int,
    now: datetime | None = None,
) -> AlertRuleRecord:
    """软删除规则；不做物理删除，重复删除必须失败。本轮不实现恢复。"""
    validated_id = _validated_rule_id(rule_id)
    _validated_index(expected_revision, field_name="expected_revision", minimum=1)
    requested = _observation_timestamp(now)

    conn = _open_write_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            current = _live_record(conn, validated_id)
            if current.revision != expected_revision:
                raise AlertRuleRevisionConflictError(
                    f"alert rule revision conflict: {validated_id}"
                )
            deleted_at = _monotonic_timestamp(current.updated_at, requested)
            record = AlertRuleRecord(
                rule=current.rule,
                revision=current.revision + 1,
                created_at=current.created_at,
                updated_at=deleted_at,
                deleted_at=deleted_at,
            )
            cursor = conn.execute(
                "UPDATE alert_rules SET revision = ?, updated_at = ?, deleted_at = ? "
                "WHERE rule_id = ? AND revision = ? AND deleted_at IS NULL",
                (
                    record.revision,
                    record.updated_at,
                    record.deleted_at,
                    validated_id,
                    expected_revision,
                ),
            )
            if cursor.rowcount != 1:
                raise AlertRuleRevisionConflictError(
                    f"alert rule revision conflict: {validated_id}"
                )
            conn.execute("COMMIT")
        except AlertRuleStoreError:
            _safe_rollback(conn)
            raise
        except sqlite3.Error as exc:
            _safe_rollback(conn)
            raise AlertRuleStoreError("告警规则删除失败") from exc
    finally:
        conn.close()
    return record
