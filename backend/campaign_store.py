"""Campaign 持久化层 v0.1（P0-S2A：Campaign Core Identity & Strategy Boundary）。

只负责 Campaign 记录的存储与读取，不做持仓/交易/生命周期迁移/AI 分析。

设计基线复用仓库既有加固 SQLite store 骨架（alert_rule_store）：
- 模块 import 零副作用：不创建目录、不连接 SQLite、不建库、不迁移；
- 写操作才允许目录创建与 schema 初始化，且初始化资格只能通过
  ``O_EXCL`` 原子文件创建获得（``path.exists()`` 不构成权限）；
- 事务：``BEGIN IMMEDIATE`` → COMMIT，异常回滚，绝不留下 half record；
- 读操作走 ``?mode=ro`` 只读 URI，数据库文件不存在时返回空（不自动建库）；
- schema 结构校验 fail-closed：表集合 / schema_version / 列 / 索引 / CHECK 约束
  任一不匹配 → ``CampaignStoreCorruptedError``，不自动迁移或重建；
- 时间戳统一 UTC ``YYYY-MM-DDTHH:MM:SS.ffffffZ``。

Campaign 身份契约（P0-S2A）：
- ``campaign_id`` 由服务端生成（``campaign_{uuid4hex}``），仓库持久化主键；
- 同一 ``security_code`` 允许多个 Campaign（无 UNIQUE(security_code)）；
- ``strategy`` ∈ SHORT/SWING/MEDIUM，DB 层 CHECK 约束结构性不可变；
- ``status`` ∈ 8 个 North Star 冻结枚举，DB 层 CHECK 约束；
  create 的 status 由服务端决定（DRAFT），存储层对非法 status fail-closed，
  绝不自动转为 DRAFT。
"""

from __future__ import annotations

import os
import re
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from alert_rules import CODE_PATTERN

CAMPAIGN_STORE_SCHEMA_VERSION = "campaign-store.v0.1"

# North Star 冻结枚举（P0-S2A 只实现 enum + 持久化，不做 transition engine）
STRATEGIES = ("SHORT", "SWING", "MEDIUM")
STATUSES = (
    "DRAFT",
    "RESEARCHING",
    "PRE-ENTRY",
    "ACTIVE",
    "REDUCING",
    "CLOSED",
    "REJECTED",
    "EXPIRED",
)

_TIMESTAMP_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z$"
)
_TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"

# campaign_id 由服务端生成：campaign_ + 32 位小写 hex（uuid4）
_CAMPAIGN_ID_RE = re.compile(r"^campaign_[0-9a-f]{32}$")
# transition_id 由服务端生成：campaign_transition_ + 32 位小写 hex（uuid4）
_TRANSITION_ID_RE = re.compile(r"^campaign_transition_[0-9a-f]{32}$")
# thesis_id = evidence_thesis_store.new_id() = uuid4().hex（32 位小写 hex）
_THESIS_ID_RE = re.compile(r"^[0-9a-f]{32}$")

# ---- P0-S2B 冻结的 Lifecycle v0.1 Transition Graph（不得扩大）----
# DRAFT→(RESEARCHING,REJECTED,EXPIRED)；RESEARCHING→(PRE-ENTRY,REJECTED,EXPIRED)；
# PRE-ENTRY→(ACTIVE,REJECTED,EXPIRED)；ACTIVE→(REDUCING,CLOSED)；REDUCING→(CLOSED)；
# CLOSED/REJECTED/EXPIRED 为终态，无出边；未列出/反向/same-state 一律 fail closed。
_TRANSITION_GRAPH: dict[str, tuple[str, ...]] = {
    "DRAFT": ("RESEARCHING", "REJECTED", "EXPIRED"),
    "RESEARCHING": ("PRE-ENTRY", "REJECTED", "EXPIRED"),
    "PRE-ENTRY": ("ACTIVE", "REJECTED", "EXPIRED"),
    "ACTIVE": ("REDUCING", "CLOSED"),
    "REDUCING": ("CLOSED",),
    "CLOSED": (),
    "REJECTED": (),
    "EXPIRED": (),
}

_ROW_COLUMNS = (
    "campaign_id",
    "security_code",
    "strategy",
    "status",
    "created_at",
)
_SELECT_COLUMNS = ", ".join(_ROW_COLUMNS)

_TRANSITION_ROW_COLUMNS = (
    "transition_id",
    "campaign_id",
    "from_status",
    "to_status",
    "transitioned_at",
)
_SELECT_TRANSITION_COLUMNS = ", ".join(_TRANSITION_ROW_COLUMNS)

_BINDING_ROW_COLUMNS = (
    "campaign_id",
    "thesis_id",
    "thesis_revision_at_bind",
    "campaign_strategy_at_bind",
    "bound_at",
)
_SELECT_BINDING_COLUMNS = ", ".join(_BINDING_ROW_COLUMNS)

_REQUIRED_COLUMNS: dict[str, tuple[str, int, int]] = {
    "campaign_id": ("TEXT", 0, 1),
    "security_code": ("TEXT", 1, 0),
    "strategy": ("TEXT", 1, 0),
    "status": ("TEXT", 1, 0),
    "created_at": ("TEXT", 1, 0),
}
_REQUIRED_TRANSITION_COLUMNS: dict[str, tuple[str, int, int]] = {
    "transition_id": ("TEXT", 0, 1),
    "campaign_id": ("TEXT", 1, 0),
    "from_status": ("TEXT", 1, 0),
    "to_status": ("TEXT", 1, 0),
    "transitioned_at": ("TEXT", 1, 0),
}
_REQUIRED_BINDING_COLUMNS: dict[str, tuple[str, int, int]] = {
    "campaign_id": ("TEXT", 0, 1),
    "thesis_id": ("TEXT", 1, 0),
    "thesis_revision_at_bind": ("INTEGER", 1, 0),
    "campaign_strategy_at_bind": ("TEXT", 1, 0),
    "bound_at": ("TEXT", 1, 0),
}
_REQUIRED_INDEXES = {
    "idx_campaigns_security_code": "CREATE INDEX idx_campaigns_security_code ON campaigns (security_code)",
    "idx_campaigns_created_at": "CREATE INDEX idx_campaigns_created_at ON campaigns (created_at)",
}
_REQUIRED_TRANSITION_INDEXES = {
    "idx_campaign_transitions_campaign": (
        "CREATE INDEX idx_campaign_transitions_campaign "
        "ON campaign_transitions (campaign_id)"
    ),
    "idx_campaign_transitions_time": (
        "CREATE INDEX idx_campaign_transitions_time "
        "ON campaign_transitions (transitioned_at)"
    ),
}

_DDL = (
    "CREATE TABLE IF NOT EXISTS schema_meta ("
    "  key TEXT PRIMARY KEY,"
    "  value TEXT NOT NULL"
    ")",
    "CREATE TABLE IF NOT EXISTS campaigns ("
    "  campaign_id TEXT PRIMARY KEY,"
    "  security_code TEXT NOT NULL,"
    "  strategy TEXT NOT NULL"
    "    CHECK (strategy IN ('SHORT', 'SWING', 'MEDIUM')),"
    "  status TEXT NOT NULL"
    "    CHECK (status IN ('DRAFT', 'RESEARCHING', 'PRE-ENTRY', 'ACTIVE',"
    "                      'REDUCING', 'CLOSED', 'REJECTED', 'EXPIRED')),"
    "  created_at TEXT NOT NULL"
    ")",
    "CREATE INDEX IF NOT EXISTS idx_campaigns_security_code "
    "ON campaigns (security_code)",
    "CREATE INDEX IF NOT EXISTS idx_campaigns_created_at "
    "ON campaigns (created_at)",
    "CREATE TABLE IF NOT EXISTS campaign_transitions ("
    "  transition_id TEXT PRIMARY KEY,"
    "  campaign_id TEXT NOT NULL,"
    "  from_status TEXT NOT NULL"
    "    CHECK (from_status IN ('DRAFT', 'RESEARCHING', 'PRE-ENTRY', 'ACTIVE',"
    "                           'REDUCING', 'CLOSED', 'REJECTED', 'EXPIRED')),"
    "  to_status TEXT NOT NULL"
    "    CHECK (to_status IN ('DRAFT', 'RESEARCHING', 'PRE-ENTRY', 'ACTIVE',"
    "                         'REDUCING', 'CLOSED', 'REJECTED', 'EXPIRED')),"
    "  transitioned_at TEXT NOT NULL"
    ")",
    "CREATE INDEX IF NOT EXISTS idx_campaign_transitions_campaign "
    "ON campaign_transitions (campaign_id)",
    "CREATE INDEX IF NOT EXISTS idx_campaign_transitions_time "
    "ON campaign_transitions (transitioned_at)",
    "CREATE TABLE IF NOT EXISTS campaign_thesis_bindings ("
    "  campaign_id TEXT PRIMARY KEY,"
    "  thesis_id TEXT NOT NULL UNIQUE,"
    "  thesis_revision_at_bind INTEGER NOT NULL"
    "    CHECK (thesis_revision_at_bind > 0),"
    "  campaign_strategy_at_bind TEXT NOT NULL"
    "    CHECK (campaign_strategy_at_bind IN ('SHORT', 'SWING', 'MEDIUM')),"
    "  bound_at TEXT NOT NULL"
    ")",
)

# 合法并发初始化等待参数：总量不超过 SQLite busy timeout 量级。
_OPEN_WAIT_TOTAL_SECONDS = 10.0
_OPEN_WAIT_INTERVAL_SECONDS = 0.02


class CampaignStoreError(RuntimeError):
    """Campaign 存储错误基类。"""


class CampaignStoreCorruptedError(CampaignStoreError):
    """数据库文件或行数据不可信任时抛出，不得解释为空数据。"""

    MESSAGE = "Campaign 数据损坏，已停止读写"

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.MESSAGE)


class CampaignStoreInputError(CampaignStoreError, ValueError):
    """调用方入参不满足存储合同。"""


class CampaignAlreadyExistsError(CampaignStoreError):
    """同一 campaign_id 已存在；不得覆盖旧 Campaign。"""


class CampaignTransitionConflictError(CampaignStoreError):
    """expected_status 与实际不符，或 from→to 不属于冻结 transition graph。"""


class CampaignThesisBindingConflictError(CampaignStoreError):
    """Campaign 已有 binding，或 thesis_id 已绑定其他 Campaign。"""


class CampaignNotFoundError(CampaignStoreError, LookupError):
    """目标 Campaign 不存在。"""


def campaign_db_path() -> str:
    """解析 Campaign 数据库路径，不创建任何目录或文件。

    优先级：
    1. `VIBE_RESEARCH_CAMPAIGN_DB`
    2. `VR_DATA_DIR/campaigns.sqlite3`
    3. `~/.vibe-research/campaigns.sqlite3`
    """
    env_db = os.environ.get("VIBE_RESEARCH_CAMPAIGN_DB", "").strip()
    if env_db:
        return str(Path(env_db))
    env_dir = os.environ.get("VR_DATA_DIR", "").strip()
    if env_dir:
        return str(Path(env_dir) / "campaigns.sqlite3")
    return str(Path.home() / ".vibe-research" / "campaigns.sqlite3")


# ---------------------------------------------------------------------------
# 时间戳 / 字段校验（入参 fail-closed）
# ---------------------------------------------------------------------------


def _validate_timestamp(value: Any) -> str:
    if not isinstance(value, str) or not _TIMESTAMP_RE.fullmatch(value):
        raise ValueError("created_at must match YYYY-MM-DDTHH:MM:SS.ffffffZ")
    try:
        datetime.strptime(value, _TIMESTAMP_FORMAT)
    except ValueError as exc:
        raise ValueError("created_at must be a real UTC instant") from exc
    return value


def _format_timestamp(moment: datetime) -> str:
    if not isinstance(moment, datetime):
        raise CampaignStoreInputError("now must be a datetime")
    if moment.tzinfo is None or moment.tzinfo.utcoffset(moment) is None:
        raise CampaignStoreInputError("now must be timezone-aware")
    return moment.astimezone(timezone.utc).strftime(_TIMESTAMP_FORMAT)


def _validated_campaign_id(value: Any) -> str:
    if not isinstance(value, str) or not _CAMPAIGN_ID_RE.fullmatch(value.strip()):
        raise CampaignStoreInputError("campaign_id must match campaign_<32 hex>")
    return value.strip()


def _validated_security_code(value: Any) -> str:
    if not isinstance(value, str) or not CODE_PATTERN.fullmatch(value.strip()):
        raise CampaignStoreInputError("security_code must be a 6-digit A-share code")
    return value.strip()


def _validated_strategy(value: Any) -> str:
    if not isinstance(value, str) or value not in STRATEGIES:
        raise CampaignStoreInputError(
            "strategy must be one of SHORT/SWING/MEDIUM (no silent normalization)"
        )
    return value


def _validated_status(value: Any) -> str:
    if not isinstance(value, str) or value not in STATUSES:
        raise CampaignStoreInputError(
            "status must be one of the North Star frozen enum (no auto-DRAFT fallback)"
        )
    return value


def _validated_transition_id(value: Any) -> str:
    if not isinstance(value, str) or not _TRANSITION_ID_RE.fullmatch(value.strip()):
        raise CampaignStoreInputError(
            "transition_id must match campaign_transition_<32 hex>"
        )
    return value.strip()


def _validated_thesis_id(value: Any) -> str:
    if not isinstance(value, str) or not _THESIS_ID_RE.fullmatch(value.strip()):
        raise CampaignStoreInputError("thesis_id must be a 32-hex evidence thesis id")
    return value.strip()


def _validated_revision(value: Any) -> int:
    """thesis revision anchor：strict positive integer（校验前不转换）。"""
    if isinstance(value, bool) or not isinstance(value, int):
        raise CampaignStoreInputError("thesis_revision_at_bind must be a positive integer")
    if value <= 0:
        raise CampaignStoreInputError("thesis_revision_at_bind must be > 0")
    return value


def _is_allowed_transition(from_status: str, to_status: str) -> bool:
    """冻结 graph 成员判定：未列出 / 反向 / same-state 一律 False。"""
    return to_status in _TRANSITION_GRAPH.get(from_status, ())


def next_actions(status: str) -> tuple[str, ...]:
    """frozen graph 的下一合法动作（graph 声明顺序；terminal → 空）。

    纯内存派生，frozen graph 的唯一权威在本文件；非法 status → InputError。
    """
    return _TRANSITION_GRAPH.get(_validated_status(status), ())


# ---------------------------------------------------------------------------
# schema 结构校验（fail-closed，不自动迁移）
# ---------------------------------------------------------------------------


def _existing_tables(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    return {str(row[0]) for row in rows}


def _all_user_tables(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {str(row[0]) for row in rows}


def _canonical_sql(sql: str | None) -> str:
    return " ".join((sql or "").split())


def _validate_constraint_semantics(
    campaigns_sql: str, transitions_sql: str, bindings_sql: str
) -> None:
    """在独立内存库中重放三个表 DDL，证明 CHECK/UNIQUE 约束真实生效，
    否则 fail-closed。"""
    try:
        probe = sqlite3.connect(":memory:")
    except sqlite3.Error as exc:
        raise CampaignStoreCorruptedError() from exc
    try:
        probe.execute(campaigns_sql)
        probe.execute(transitions_sql)
        probe.execute(bindings_sql)
        probe.execute(
            "INSERT INTO campaigns (campaign_id, security_code, strategy, status, created_at) "
            "VALUES (?, '600519', 'SHORT', 'DRAFT', ?)",
            ("campaign_00000000000000000000000000000000",
             "2026-08-01T00:00:00.000000Z"),
        )
        probe.execute(
            "INSERT INTO campaign_transitions "
            "(transition_id, campaign_id, from_status, to_status, transitioned_at) "
            "VALUES (?, ?, 'DRAFT', 'RESEARCHING', ?)",
            ("campaign_transition_00000000000000000000000000000000",
             "campaign_00000000000000000000000000000000",
             "2026-08-01T00:00:00.000000Z"),
        )
        probe.execute(
            "INSERT INTO campaign_thesis_bindings "
            "(campaign_id, thesis_id, thesis_revision_at_bind,"
            " campaign_strategy_at_bind, bound_at) "
            "VALUES (?, ?, 1, 'SWING', ?)",
            ("campaign_00000000000000000000000000000000",
             "0" * 32, "2026-08-01T00:00:00.000000Z"),
        )
        bad_rows = (
            ("campaign_00000000000000000000000000000001", "BOGUS", "DRAFT"),
            ("campaign_00000000000000000000000000000002", "SHORT", "BOGUS"),
        )
        for bad in bad_rows:
            try:
                probe.execute(
                    "INSERT INTO campaigns "
                    "(campaign_id, security_code, strategy, status, created_at) "
                    "VALUES (?, '600519', ?, ?, '2026-08-01T00:00:00.000000Z')",
                    bad,
                )
            except sqlite3.IntegrityError:
                continue  # CHECK 正确拒绝
            raise CampaignStoreCorruptedError()
        for bad in (
            ("campaign_transition_00000000000000000000000000000001",
             "campaign_00000000000000000000000000000000", "BOGUS", "RESEARCHING"),
            ("campaign_transition_00000000000000000000000000000002",
             "campaign_00000000000000000000000000000000", "DRAFT", "BOGUS"),
        ):
            try:
                probe.execute(
                    "INSERT INTO campaign_transitions "
                    "(transition_id, campaign_id, from_status, to_status, transitioned_at) "
                    "VALUES (?, ?, ?, ?, '2026-08-01T00:00:00.000000Z')",
                    bad,
                )
            except sqlite3.IntegrityError:
                continue
            raise CampaignStoreCorruptedError()
        # bindings：revision <= 0 拒绝、strategy 非法拒绝、campaign_id 重复（PK）
        # 拒绝，并且不同 campaign_id 复用同一 thesis_id 时必须由 DB UNIQUE 拒绝。
        for bad in (
            ("campaign_00000000000000000000000000000001", "1" * 32, 0, "SWING"),
            ("campaign_00000000000000000000000000000002", "2" * 32, 1, "BOGUS"),
            ("campaign_00000000000000000000000000000000", "3" * 32, 1, "SWING"),
            ("campaign_00000000000000000000000000000001", "0" * 32, 1, "SWING"),
        ):
            try:
                probe.execute(
                    "INSERT INTO campaign_thesis_bindings "
                    "(campaign_id, thesis_id, thesis_revision_at_bind,"
                    " campaign_strategy_at_bind, bound_at) "
                    "VALUES (?, ?, ?, ?, '2026-08-01T00:00:00.000000Z')",
                    bad,
                )
            except sqlite3.IntegrityError:
                continue
            raise CampaignStoreCorruptedError()
    except sqlite3.Error as exc:
        raise CampaignStoreCorruptedError() from exc
    finally:
        probe.close()


def _assert_schema(conn: sqlite3.Connection) -> None:
    """校验已有 schema 结构完整性，任何异常都 fail-closed，不自动迁移或重建。"""
    tables = _existing_tables(conn)
    if tables != {
        "schema_meta",
        "campaigns",
        "campaign_transitions",
        "campaign_thesis_bindings",
    }:
        raise CampaignStoreCorruptedError()
    try:
        rows = conn.execute(
            "SELECT value FROM schema_meta WHERE key = ?", ("schema_version",)
        ).fetchall()
        if len(rows) != 1 or rows[0][0] != CAMPAIGN_STORE_SCHEMA_VERSION:
            raise CampaignStoreCorruptedError()

        col_rows = conn.execute("PRAGMA table_info(campaigns)").fetchall()
        col_map: dict[str, tuple[str, int, int]] = {}
        for crow in col_rows:
            col_map[crow[1]] = (str(crow[2]).upper(), crow[3], crow[5])
        for col_name, (exp_type, exp_notnull, exp_pk) in _REQUIRED_COLUMNS.items():
            if col_name not in col_map:
                raise CampaignStoreCorruptedError()
            actual_type, actual_notnull, actual_pk = col_map[col_name]
            if actual_type != exp_type or actual_notnull != exp_notnull:
                raise CampaignStoreCorruptedError()
            if (actual_pk > 0) != (exp_pk > 0):
                raise CampaignStoreCorruptedError()

        trans_col_rows = conn.execute(
            "PRAGMA table_info(campaign_transitions)"
        ).fetchall()
        trans_col_map: dict[str, tuple[str, int, int]] = {}
        for crow in trans_col_rows:
            trans_col_map[crow[1]] = (str(crow[2]).upper(), crow[3], crow[5])
        for col_name, (exp_type, exp_notnull, exp_pk) in _REQUIRED_TRANSITION_COLUMNS.items():
            if col_name not in trans_col_map:
                raise CampaignStoreCorruptedError()
            actual_type, actual_notnull, actual_pk = trans_col_map[col_name]
            if actual_type != exp_type or actual_notnull != exp_notnull:
                raise CampaignStoreCorruptedError()
            if (actual_pk > 0) != (exp_pk > 0):
                raise CampaignStoreCorruptedError()

        bind_col_rows = conn.execute(
            "PRAGMA table_info(campaign_thesis_bindings)"
        ).fetchall()
        bind_col_map: dict[str, tuple[str, int, int]] = {}
        for crow in bind_col_rows:
            bind_col_map[crow[1]] = (str(crow[2]).upper(), crow[3], crow[5])
        for col_name, (exp_type, exp_notnull, exp_pk) in _REQUIRED_BINDING_COLUMNS.items():
            if col_name not in bind_col_map:
                raise CampaignStoreCorruptedError()
            actual_type, actual_notnull, actual_pk = bind_col_map[col_name]
            if actual_type != exp_type or actual_notnull != exp_notnull:
                raise CampaignStoreCorruptedError()
            if (actual_pk > 0) != (exp_pk > 0):
                raise CampaignStoreCorruptedError()

        def _table_create_sql(name: str) -> str:
            row = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
                (name,),
            ).fetchone()
            if row is None or row[0] is None:
                raise CampaignStoreCorruptedError()
            return row[0]

        _validate_constraint_semantics(
            _table_create_sql("campaigns"),
            _table_create_sql("campaign_transitions"),
            _table_create_sql("campaign_thesis_bindings"),
        )

        idx_rows = conn.execute(
            "SELECT name, sql FROM sqlite_master "
            "WHERE type = 'index' AND tbl_name = 'campaigns'"
        ).fetchall()
        found_index_sql = {str(row[0]): row[1] for row in idx_rows}
        for idx_name, expected_sql in _REQUIRED_INDEXES.items():
            actual_sql = found_index_sql.get(idx_name)
            if actual_sql is None or _canonical_sql(actual_sql) != expected_sql:
                raise CampaignStoreCorruptedError()

        trans_idx_rows = conn.execute(
            "SELECT name, sql FROM sqlite_master "
            "WHERE type = 'index' AND tbl_name = 'campaign_transitions'"
        ).fetchall()
        found_trans_idx_sql = {str(row[0]): row[1] for row in trans_idx_rows}
        for idx_name, expected_sql in _REQUIRED_TRANSITION_INDEXES.items():
            actual_sql = found_trans_idx_sql.get(idx_name)
            if actual_sql is None or _canonical_sql(actual_sql) != expected_sql:
                raise CampaignStoreCorruptedError()

        conn.execute(f"SELECT {_SELECT_COLUMNS} FROM campaigns LIMIT 0").fetchall()
        conn.execute(
            f"SELECT {_SELECT_TRANSITION_COLUMNS} FROM campaign_transitions LIMIT 0"
        ).fetchall()
        conn.execute(
            f"SELECT {_SELECT_BINDING_COLUMNS} FROM campaign_thesis_bindings LIMIT 0"
        ).fetchall()
    except CampaignStoreCorruptedError:
        raise
    except sqlite3.Error as exc:
        raise CampaignStoreCorruptedError() from exc


# ---------------------------------------------------------------------------
# 连接管理
# ---------------------------------------------------------------------------


def _initialize(conn: sqlite3.Connection) -> None:
    """在已持有写锁的连接上执行 schema 初始化。调用方负责 BEGIN IMMEDIATE。"""
    try:
        for statement in _DDL:
            conn.execute(statement)
        conn.execute(
            "INSERT INTO schema_meta (key, value) VALUES (?, ?)",
            ("schema_version", CAMPAIGN_STORE_SCHEMA_VERSION),
        )
    except sqlite3.Error as exc:
        raise CampaignStoreError("Campaign 数据库初始化失败") from exc


def _safe_rollback(conn: sqlite3.Connection) -> None:
    try:
        conn.execute("ROLLBACK")
    except sqlite3.Error:
        pass


def _acquire_initialization_ownership(path: Path) -> bool:
    """通过原子文件创建获取初始化资格（O_EXCL）。"""
    flags = os.O_CREAT | os.O_EXCL | os.O_RDWR
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    try:
        fd = os.open(str(path), flags, 0o600)
    except FileExistsError:
        return False
    except OSError as exc:
        raise CampaignStoreError("Campaign 数据库不可用") from exc
    try:
        os.close(fd)
    except OSError as exc:
        raise CampaignStoreError("Campaign 数据库不可用") from exc
    return True


def _open_write_connection() -> sqlite3.Connection:
    """只有写操作才允许触发目录创建与 schema 初始化。

    初始化资格只能通过 O_EXCL 原子文件创建获得；等待者不得调用 _initialize。
    """
    path = Path(campaign_db_path())
    existed_at_start = path.exists()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise CampaignStoreError("Campaign 数据库不可用") from exc
    owned = _acquire_initialization_ownership(path)
    deadline = time.monotonic() + _OPEN_WAIT_TOTAL_SECONDS
    while True:
        try:
            conn = sqlite3.connect(str(path), isolation_level=None, timeout=10.0)
        except (sqlite3.Error, OSError) as exc:
            raise CampaignStoreError("Campaign 数据库不可用") from exc
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("BEGIN IMMEDIATE")
        except sqlite3.Error as exc:
            conn.close()
            raise CampaignStoreCorruptedError() from exc
        try:
            tables = _existing_tables(conn)
            if tables == {
                "schema_meta",
                "campaigns",
                "campaign_transitions",
                "campaign_thesis_bindings",
            }:
                _assert_schema(conn)
                conn.execute("COMMIT")
                return conn
            if tables or _all_user_tables(conn):
                # 无关表或部分项目 schema：任何情况下都不得初始化，直接 fail-closed。
                raise CampaignStoreCorruptedError()
            if owned:
                _initialize(conn)
                conn.execute("COMMIT")
                return conn
            if existed_at_start:
                raise CampaignStoreCorruptedError()
            if time.monotonic() >= deadline:
                raise CampaignStoreCorruptedError()
            _safe_rollback(conn)
            conn.close()
            time.sleep(_OPEN_WAIT_INTERVAL_SECONDS)
            continue
        except CampaignStoreError:
            _safe_rollback(conn)
            conn.close()
            raise
        except sqlite3.Error as exc:
            _safe_rollback(conn)
            conn.close()
            raise CampaignStoreError("Campaign 数据库不可用") from exc
        except BaseException:
            _safe_rollback(conn)
            conn.close()
            raise


def _read_only_uri(path: Path) -> str:
    resolved = path.resolve()
    return f"{resolved.as_uri()}?mode=ro"


def _open_read_connection() -> sqlite3.Connection | None:
    """只读连接；数据库文件不存在时返回 None，且不产生任何写副作用。"""
    path = Path(campaign_db_path())
    if not path.is_file():
        return None
    try:
        uri = _read_only_uri(path)
        conn = sqlite3.connect(uri, uri=True, timeout=10.0)
    except (sqlite3.Error, OSError) as exc:
        raise CampaignStoreCorruptedError() from exc
    conn.row_factory = sqlite3.Row
    try:
        _assert_schema(conn)
    except BaseException:
        conn.close()
        raise
    return conn


def _record_from_row(row: sqlite3.Row) -> dict:
    """行 → 记录；行数据不可信（非法枚举/代码/时间戳）→ fail-closed。"""
    try:
        record = {
            "campaign_id": _validated_campaign_id(row["campaign_id"]),
            "security_code": _validated_security_code(row["security_code"]),
            "strategy": _validated_strategy(row["strategy"]),
            "status": _validated_status(row["status"]),
            "created_at": _validate_timestamp(row["created_at"]),
        }
    except (CampaignStoreInputError, ValueError):
        raise CampaignStoreCorruptedError() from None
    return record


def _transition_from_row(row: sqlite3.Row) -> dict:
    """transition 行 → 记录；行数据不可信 → fail-closed。"""
    try:
        return {
            "transition_id": _validated_transition_id(row["transition_id"]),
            "campaign_id": _validated_campaign_id(row["campaign_id"]),
            "from_status": _validated_status(row["from_status"]),
            "to_status": _validated_status(row["to_status"]),
            "transitioned_at": _validate_timestamp(row["transitioned_at"]),
        }
    except (CampaignStoreInputError, ValueError):
        raise CampaignStoreCorruptedError() from None


def _binding_from_row(row: sqlite3.Row) -> dict:
    """binding 行 → 记录；行数据不可信 → fail-closed。"""
    try:
        return {
            "campaign_id": _validated_campaign_id(row["campaign_id"]),
            "thesis_id": _validated_thesis_id(row["thesis_id"]),
            "thesis_revision_at_bind": _validated_revision(
                row["thesis_revision_at_bind"]
            ),
            "campaign_strategy_at_bind": _validated_strategy(
                row["campaign_strategy_at_bind"]
            ),
            "bound_at": _validate_timestamp(row["bound_at"]),
        }
    except (CampaignStoreInputError, ValueError):
        raise CampaignStoreCorruptedError() from None


# ---------------------------------------------------------------------------
# CRUD（P0-S2A：create / get / list；无 update / delete —— Strategy 结构性不可变）
# ---------------------------------------------------------------------------


def create_campaign(
    *,
    campaign_id: str,
    security_code: str,
    strategy: str,
    status: str,
    created_at: str,
) -> dict:
    """原子创建 Campaign 记录；返回持久化后的记录。

    - ``campaign_id`` 重复 → ``CampaignAlreadyExistsError``（显式冲突，绝不覆盖）；
    - 任一入参非法 → ``CampaignStoreInputError``；
    - 原子性：单条 INSERT 在 ``BEGIN IMMEDIATE`` 内，失败不留 half record。
    """
    cid = _validated_campaign_id(campaign_id)
    code = _validated_security_code(security_code)
    strat = _validated_strategy(strategy)
    stat = _validated_status(status)
    try:
        created = _validate_timestamp(created_at)
    except ValueError as exc:
        raise CampaignStoreInputError(str(exc)) from exc

    conn = _open_write_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute(
                f"INSERT INTO campaigns ({_SELECT_COLUMNS}) VALUES (?, ?, ?, ?, ?)",
                (cid, code, strat, stat, created),
            )
        except sqlite3.IntegrityError as exc:
            raise CampaignAlreadyExistsError(
                f"campaign {cid} already exists (no overwrite)"
            ) from exc
        conn.execute("COMMIT")
    except BaseException:
        _safe_rollback(conn)
        conn.close()
        raise
    conn.close()
    return {
        "campaign_id": cid,
        "security_code": code,
        "strategy": strat,
        "status": stat,
        "created_at": created,
    }


def get_campaign(campaign_id: str) -> dict | None:
    """按 campaign_id 精确读取；不存在返回 None；ID 格式非法 → InputError。"""
    cid = _validated_campaign_id(campaign_id)
    conn = _open_read_connection()
    if conn is None:
        return None
    try:
        row = conn.execute(
            f"SELECT {_SELECT_COLUMNS} FROM campaigns WHERE campaign_id = ?", (cid,)
        ).fetchone()
    except sqlite3.Error as exc:
        raise CampaignStoreCorruptedError() from exc
    finally:
        conn.close()
    return _record_from_row(row) if row is not None else None


def list_campaigns(
    *,
    security_code: str | None = None,
    strategy: str | None = None,
    status: str | None = None,
) -> list[dict]:
    """确定性查询：created_at ASC, campaign_id ASC 全序。

    可选过滤：security_code / strategy / status；非法过滤值 → InputError。
    """
    where: list[str] = []
    params: list[str] = []
    if security_code is not None:
        where.append("security_code = ?")
        params.append(_validated_security_code(security_code))
    if strategy is not None:
        where.append("strategy = ?")
        params.append(_validated_strategy(strategy))
    if status is not None:
        where.append("status = ?")
        params.append(_validated_status(status))

    sql = f"SELECT {_SELECT_COLUMNS} FROM campaigns"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY created_at ASC, campaign_id ASC"

    conn = _open_read_connection()
    if conn is None:
        return []
    try:
        rows = conn.execute(sql, params).fetchall()
    except sqlite3.Error as exc:
        raise CampaignStoreCorruptedError() from exc
    finally:
        conn.close()
    return [_record_from_row(row) for row in rows]


def transition_campaign(
    *,
    campaign_id: str,
    expected_status: str,
    to_status: str,
    transition_id: str,
    transitioned_at: str,
) -> tuple[dict, dict]:
    """原子执行 Campaign 状态迁移（同一 SQLite 事务，BEGIN IMMEDIATE）。

    顺序：
    1. 读取当前 Campaign（不存在 → CampaignNotFoundError）；
    2. 当前 status != expected_status → CampaignTransitionConflictError（CAS）；
    3. from→to 不属于冻结 graph（含反向 / same-state / 终态出边）→ Conflict；
    4. 写 transition audit 记录（transition_id 重复 → CampaignAlreadyExistsError）；
    5. 原子更新 campaigns.status；
    6. COMMIT。

    任何一步失败 → ROLLBACK：绝不允许「status 变了但 audit 没写」或
    「audit 写了但 status 没变」。返回 (迁移后 Campaign, transition 记录)。
    """
    cid = _validated_campaign_id(campaign_id)
    exp = _validated_status(expected_status)
    to = _validated_status(to_status)
    tid = _validated_transition_id(transition_id)
    try:
        trans_at = _validate_timestamp(transitioned_at)
    except ValueError as exc:
        raise CampaignStoreInputError(str(exc)) from exc

    conn = _open_write_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT status FROM campaigns WHERE campaign_id = ?", (cid,)
        ).fetchone()
        if row is None:
            raise CampaignNotFoundError(f"campaign {cid} not found")
        try:
            current = _validated_status(str(row["status"]))
        except CampaignStoreInputError:
            raise CampaignStoreCorruptedError() from None
        if current != exp:
            raise CampaignTransitionConflictError(
                f"expected_status {exp!r} but current is {current!r}"
            )
        if not _is_allowed_transition(current, to):
            raise CampaignTransitionConflictError(
                f"transition {current} -> {to} not allowed by frozen graph"
            )
        try:
            conn.execute(
                "INSERT INTO campaign_transitions "
                f"({_SELECT_TRANSITION_COLUMNS}) VALUES (?, ?, ?, ?, ?)",
                (tid, cid, current, to, trans_at),
            )
        except sqlite3.IntegrityError as exc:
            raise CampaignAlreadyExistsError(
                f"transition {tid} already exists (no overwrite)"
            ) from exc
        conn.execute(
            "UPDATE campaigns SET status = ? WHERE campaign_id = ?", (to, cid)
        )
        conn.execute("COMMIT")
    except BaseException:
        _safe_rollback(conn)
        conn.close()
        raise
    conn.close()

    transition = {
        "transition_id": tid,
        "campaign_id": cid,
        "from_status": current,
        "to_status": to,
        "transitioned_at": trans_at,
    }
    campaign = get_campaign(cid)
    if campaign is None:
        raise CampaignStoreCorruptedError()  # 事务后必须存在
    return campaign, transition


def list_campaign_transitions(campaign_id: str) -> list[dict]:
    """Campaign 的 transition 历史：transitioned_at ASC, transition_id ASC 全序。

    Campaign 不存在 → 空列表（与 list_campaigns 语义一致，不抛 NotFound）。
    """
    cid = _validated_campaign_id(campaign_id)
    conn = _open_read_connection()
    if conn is None:
        return []
    try:
        rows = conn.execute(
            "SELECT "
            f"{_SELECT_TRANSITION_COLUMNS} FROM campaign_transitions "
            "WHERE campaign_id = ? "
            "ORDER BY transitioned_at ASC, transition_id ASC",
            (cid,),
        ).fetchall()
    except sqlite3.Error as exc:
        raise CampaignStoreCorruptedError() from exc
    finally:
        conn.close()
    return [_transition_from_row(row) for row in rows]


def bind_campaign_thesis(
    *,
    campaign_id: str,
    thesis_id: str,
    thesis_revision_at_bind: int,
    campaign_strategy_at_bind: str,
    bound_at: str,
) -> dict:
    """原子创建 Campaign ↔ Thesis 绑定（同一 SQLite 事务，BEGIN IMMEDIATE）。

    顺序：
    1. 读取 Campaign（不存在 → CampaignNotFoundError）；
    2. Campaign 已有 binding → CampaignThesisBindingConflictError；
    3. thesis_id 已绑定其他 Campaign → Conflict（ONE THESIS → ONE CAMPAIGN）；
    4. INSERT campaign_thesis_bindings（campaign_id PK / thesis_id UNIQUE）；
    5. COMMIT。

    失败 → ROLLBACK：绝不留下半条 binding / 覆盖旧 binding / silent replace。

    Evidence Thesis 的 existence / subject / revision 校验在 service 层
    通过 canonical read API 完成（本库不建跨数据库 FK）。
    """
    cid = _validated_campaign_id(campaign_id)
    tid = _validated_thesis_id(thesis_id)
    revision = _validated_revision(thesis_revision_at_bind)
    strategy = _validated_strategy(campaign_strategy_at_bind)
    try:
        bound = _validate_timestamp(bound_at)
    except ValueError as exc:
        raise CampaignStoreInputError(str(exc)) from exc

    conn = _open_write_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT campaign_id FROM campaigns WHERE campaign_id = ?", (cid,)
        ).fetchone()
        if row is None:
            raise CampaignNotFoundError(f"campaign {cid} not found")
        already = conn.execute(
            "SELECT campaign_id FROM campaign_thesis_bindings WHERE campaign_id = ?",
            (cid,),
        ).fetchone()
        if already is not None:
            raise CampaignThesisBindingConflictError(
                f"campaign {cid} already has a thesis binding"
            )
        thesis_owner = conn.execute(
            "SELECT campaign_id FROM campaign_thesis_bindings WHERE thesis_id = ?",
            (tid,),
        ).fetchone()
        if thesis_owner is not None:
            raise CampaignThesisBindingConflictError(
                f"thesis {tid} already bound to campaign {thesis_owner['campaign_id']}"
            )
        try:
            conn.execute(
                "INSERT INTO campaign_thesis_bindings "
                f"({_SELECT_BINDING_COLUMNS}) VALUES (?, ?, ?, ?, ?)",
                (cid, tid, revision, strategy, bound),
            )
        except sqlite3.IntegrityError as exc:
            raise CampaignThesisBindingConflictError(
                f"binding insert conflicted for campaign {cid}"
            ) from exc
        conn.execute("COMMIT")
    except BaseException:
        _safe_rollback(conn)
        conn.close()
        raise
    conn.close()
    return {
        "campaign_id": cid,
        "thesis_id": tid,
        "thesis_revision_at_bind": revision,
        "campaign_strategy_at_bind": strategy,
        "bound_at": bound,
    }


def get_campaign_thesis_binding(campaign_id: str) -> dict | None:
    """读取 Campaign 的 thesis binding；不存在 → None。"""
    cid = _validated_campaign_id(campaign_id)
    conn = _open_read_connection()
    if conn is None:
        return None
    try:
        row = conn.execute(
            "SELECT "
            f"{_SELECT_BINDING_COLUMNS} FROM campaign_thesis_bindings "
            "WHERE campaign_id = ?",
            (cid,),
        ).fetchone()
    except sqlite3.Error as exc:
        raise CampaignStoreCorruptedError() from exc
    finally:
        conn.close()
    return _binding_from_row(row) if row is not None else None
