"""正式投资决策冻结账本 SQLite 存储层（纯存储，不暴露 HTTP、不含业务规则）。

Frozen Decision Ledger 是不可变的历史承诺记录：用户显式确认后的正式决策快照。

- append-only：无 UPDATE / DELETE / UPSERT / REPLACE 路径
- 每条记录绑定确定性 SHA-256（canonical JSON protected snapshot）
- 只读路径在数据库缺失时返回空 / 未找到，绝不创建目录、DB、-wal、-shm
- 所有公开函数显式接收 db_path；不定义生产默认路径，避免 import 时写库
- 使用标准库 sqlite3，无 ORM；不 import 其他业务模块

Schema 版本策略：显式版本号 ``frozen-decision-ledger.v0.1``，版本不匹配一律
fail closed，无隐式迁移、无重建、无兼容垫片。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping

SCHEMA_VERSION = "frozen-decision-ledger.v0.1"

STRATEGIES = ("SHORT", "SWING", "MEDIUM")
NEXT_BEST_ACTIONS = (
    "BUY NOW",
    "BUY SMALL",
    "SCALE IN",
    "WAIT",
    "HOLD",
    "WATCH TO REDUCE",
    "REDUCE",
    "EXIT",
    "AVOID",
    "RESEARCH MORE",
)
VALIDITY_STATUS_AT_COMMIT = "CURRENT"

# decision_id = decision_ + 32 位小写 hex（uuid4），由服务端生成
_DECISION_ID_RE = re.compile(r"^decision_[0-9a-f]{32}$")
# 严格 6 位 A 股代码
_SECURITY_CODE_RE = re.compile(r"^\d{6}$")
# campaign_id = campaign_ + 32 位小写 hex（与 campaign_store 生成格式一致）
_CAMPAIGN_ID_RE = re.compile(r"^campaign_[0-9a-f]{32}$")
# thesis_id = 32 位小写 hex（与 evidence_thesis_store.new_id 生成格式一致）
_THESIS_ID_RE = re.compile(r"^[0-9a-f]{32}$")
# sha256 hex
_SNAPSHOT_HASH_RE = re.compile(r"^[0-9a-f]{64}$")

# snapshot 对象完整键集：确定性哈希覆盖的 protected snapshot
SNAPSHOT_KEYS = frozenset(
    {
        "snapshot_schema_version",
        "decision_id",
        "security_code",
        "strategy",
        "campaign_id",
        "committed_at",
        "thesis_id",
        "thesis_revision",
        "asset_view",
        "trade_view",
        "portfolio_view",
        "next_best_action",
        "action_envelope",
        "maintain_conditions",
        "upgrade_conditions",
        "downgrade_conditions",
        "invalidation_conditions",
        "strategy_horizon",
        "review_by",
        "key_assumptions",
        "event_invalidation_conditions",
        "validity_status_at_commit",
        "risk_policy_version",
        "opportunity_policy_version",
        "decision_policy_version",
        "behavior_model_version",
        "data_quality",
        "evidence_confidence",
        "inference_confidence",
        "decision_confidence",
        "evidence_refs",
        "risk_refs",
        "source_refs",
    }
)

# snapshot 内同时落独立查询列、且必须与 snapshot_json 逐字一致的字段
_LEAF_KEYS = frozenset(
    {
        "snapshot_schema_version",
        "decision_id",
        "security_code",
        "strategy",
        "campaign_id",
        "committed_at",
        "thesis_id",
        "thesis_revision",
        "next_best_action",
        "review_by",
        "validity_status_at_commit",
        "risk_policy_version",
        "opportunity_policy_version",
        "decision_policy_version",
        "behavior_model_version",
    }
)

_LOCK = threading.Lock()


class FrozenDecisionError(RuntimeError):
    """Frozen Decision Ledger 基础异常。"""


class FrozenDecisionCorruptedError(FrozenDecisionError):
    """数据库或快照内容损坏，已停止读写（fail closed）。"""

    MESSAGE = "正式决策账本数据损坏，已停止读写以避免覆盖"

    def __init__(self, message: str | None = None):
        super().__init__(message or self.MESSAGE)


class FrozenDecisionSchemaVersionError(FrozenDecisionError):
    """数据库 schema 版本不兼容，已停止读写（fail closed）。"""

    MESSAGE = "正式决策账本 schema 版本不兼容，已停止读写"

    def __init__(self, message: str | None = None):
        super().__init__(message or self.MESSAGE)


class FrozenDecisionConflictError(FrozenDecisionError):
    """相同 decision_id 的冲突重放：内容与已冻结快照不一致，拒绝写入。"""


# ---------------------------------------------------------------------------
# 确定性序列化与哈希
# ---------------------------------------------------------------------------

def canonical_json(value: Any) -> str:
    """项目确定性 canonical JSON 序列化契约（stdlib 实现）。

    - 递归属性排序（``sort_keys``）
    - 无空白分隔符
    - UTF-8 文本（``ensure_ascii=False``）
    - 拒绝 NaN / Infinity / 非 JSON 结构（``allow_nan=False``）

    语义基于 RFC 8785 (JCS) 的通用要求（属性排序 / 紧凑 / UTF-8 / 拒绝
    非有限数），但不声明完整 RFC 8785 合规：数字序列化采用 Python
    ``json.dumps`` 的确定性表示，覆盖本项目所需的一致性保证（同一对象
    必然产生相同字节；键顺序、空白、数字形态差异不影响一致性）。本契约
    为仓库内恒定契约，用于 snapshot 哈希与篡改检测。
    """
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def snapshot_hash(snapshot: Mapping[str, Any]) -> str:
    """确定性 SHA-256：对 canonical JSON 快照文本（UTF-8）取哈希。"""
    return hashlib.sha256(canonical_json(snapshot).encode("utf-8")).hexdigest()


def _utc_now_iso() -> str:
    """UTC ISO 8601 微秒精度，Z 后缀。"""
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


# ---------------------------------------------------------------------------
# 路径与连接
# ---------------------------------------------------------------------------

def resolve_frozen_decision_db_path(explicit_path: str | Path | None = None) -> Path:
    """解析账本路径。

    优先级：
    1. 显式参数 ``explicit_path``
    2. 环境变量 ``VIBE_RESEARCH_FROZEN_DECISION_DB``
    3. 环境变量 ``VR_DATA_DIR`` / frozen_decisions.sqlite3
    4. 默认：``~/.vibe-research/frozen_decisions.sqlite3``

    纯解析，不触碰文件系统。
    """
    if explicit_path:
        return Path(explicit_path)
    env_db = os.environ.get("VIBE_RESEARCH_FROZEN_DECISION_DB", "").strip()
    if env_db:
        return Path(env_db)
    env_dir = os.environ.get("VR_DATA_DIR", "").strip()
    if env_dir:
        return Path(env_dir) / "frozen_decisions.sqlite3"
    return Path.home() / ".vibe-research" / "frozen_decisions.sqlite3"


def _as_path(db_path: str | Path) -> str:
    if isinstance(db_path, Path):
        return str(db_path)
    if not isinstance(db_path, str):
        raise TypeError("db_path 必须是字符串或 Path")
    return db_path


def _ensure_parent_dir(db_path: str | Path) -> None:
    path = _as_path(db_path)
    if path == ":memory:":
        return
    parent = Path(path).parent
    if str(parent) and str(parent) != ".":
        parent.mkdir(parents=True, exist_ok=True)


def _db_file_exists(db_path: str | Path) -> bool:
    try:
        return Path(_as_path(db_path)).is_file()
    except TypeError:
        return False


def _connect(db_path: str | Path) -> sqlite3.Connection:
    path = _as_path(db_path)
    conn = sqlite3.connect(path, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def _connect_readonly(db_path: str | Path) -> sqlite3.Connection:
    """只读连接（mode=ro）：不创建、不修改任何文件（含 -wal / -shm）。"""
    path = Path(_as_path(db_path)).resolve()
    conn = sqlite3.connect(f"{path.as_uri()}?mode=ro", timeout=5, uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (name,),
    ).fetchone()
    return row is not None


# ---------------------------------------------------------------------------
# Schema 初始化与版本管理
# ---------------------------------------------------------------------------

_CREATE_SCHEMA_META = """
CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
)
"""

_CREATE_FROZEN_DECISIONS = """
CREATE TABLE IF NOT EXISTS frozen_decisions (
    decision_id TEXT PRIMARY KEY,
    security_code TEXT NOT NULL,
    strategy TEXT NOT NULL,
    campaign_id TEXT NOT NULL,
    committed_at TEXT NOT NULL,
    snapshot_schema_version TEXT NOT NULL,
    snapshot_hash TEXT NOT NULL,
    thesis_id TEXT NOT NULL,
    thesis_revision INTEGER NOT NULL,
    next_best_action TEXT NOT NULL,
    review_by TEXT NOT NULL,
    validity_status_at_commit TEXT NOT NULL,
    risk_policy_version TEXT NOT NULL,
    opportunity_policy_version TEXT NOT NULL,
    decision_policy_version TEXT NOT NULL,
    behavior_model_version TEXT NOT NULL,
    user_confirmed INTEGER NOT NULL,
    snapshot_json TEXT NOT NULL,
    created_at TEXT NOT NULL
)
"""

_IDX_SECURITY_CODE = """
CREATE INDEX IF NOT EXISTS idx_frozen_decisions_security_code
ON frozen_decisions(security_code)
"""
_IDX_STRATEGY = """
CREATE INDEX IF NOT EXISTS idx_frozen_decisions_strategy
ON frozen_decisions(strategy)
"""
_IDX_CAMPAIGN_ID = """
CREATE INDEX IF NOT EXISTS idx_frozen_decisions_campaign_id
ON frozen_decisions(campaign_id)
"""
_IDX_COMMITTED_AT = """
CREATE INDEX IF NOT EXISTS idx_frozen_decisions_committed_at
ON frozen_decisions(committed_at)
"""

_ALL_DDL = [
    _CREATE_SCHEMA_META,
    _CREATE_FROZEN_DECISIONS,
    _IDX_SECURITY_CODE,
    _IDX_STRATEGY,
    _IDX_CAMPAIGN_ID,
    _IDX_COMMITTED_AT,
]


# ---------------------------------------------------------------------------
# 应用 Schema 结构契约（frozen-decision-ledger.v0.1）
# ---------------------------------------------------------------------------

_EXPECTED_TABLES = frozenset({"schema_meta", "frozen_decisions"})

# 列名 → (声明类型, NOT NULL, PRIMARY KEY)
_SCHEMA_META_COLUMNS: dict[str, tuple[str, bool, bool]] = {
    "key": ("TEXT", False, True),
    "value": ("TEXT", True, False),
}

_FROZEN_DECISIONS_COLUMNS: dict[str, tuple[str, bool, bool]] = {
    "decision_id": ("TEXT", False, True),
    "security_code": ("TEXT", True, False),
    "strategy": ("TEXT", True, False),
    "campaign_id": ("TEXT", True, False),
    "committed_at": ("TEXT", True, False),
    "snapshot_schema_version": ("TEXT", True, False),
    "snapshot_hash": ("TEXT", True, False),
    "thesis_id": ("TEXT", True, False),
    "thesis_revision": ("INTEGER", True, False),
    "next_best_action": ("TEXT", True, False),
    "review_by": ("TEXT", True, False),
    "validity_status_at_commit": ("TEXT", True, False),
    "risk_policy_version": ("TEXT", True, False),
    "opportunity_policy_version": ("TEXT", True, False),
    "decision_policy_version": ("TEXT", True, False),
    "behavior_model_version": ("TEXT", True, False),
    "user_confirmed": ("INTEGER", True, False),
    "snapshot_json": ("TEXT", True, False),
    "created_at": ("TEXT", True, False),
}

# 索引名 → (目标表, (目标列,))
_EXPECTED_INDEXES: dict[str, tuple[str, tuple[str, ...]]] = {
    "idx_frozen_decisions_security_code": ("frozen_decisions", ("security_code",)),
    "idx_frozen_decisions_strategy": ("frozen_decisions", ("strategy",)),
    "idx_frozen_decisions_campaign_id": ("frozen_decisions", ("campaign_id",)),
    "idx_frozen_decisions_committed_at": ("frozen_decisions", ("committed_at",)),
}


def _assert_table_contract(
    conn: sqlite3.Connection,
    table_name: str,
    expected: Mapping[str, tuple[str, bool, bool]],
) -> None:
    """断言单表结构契约：精确列集合、声明类型、NOT NULL、PRIMARY KEY。

    表名只来自模块常量，无注入面。
    """
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    actual = {
        row["name"]: (row["type"].upper(), bool(row["notnull"]), bool(row["pk"]))
        for row in rows
    }
    if set(actual) != set(expected):
        raise FrozenDecisionCorruptedError(
            f"{table_name} 列集合不符合 v0.1 契约：{sorted(actual)}"
        )
    for name, (etype, enotnull, epk) in expected.items():
        atype, anotnull, apk = actual[name]
        if atype != etype or anotnull != enotnull or apk != epk:
            raise FrozenDecisionCorruptedError(
                f"{table_name}.{name} 结构不符契约"
                f"（type={atype} notnull={anotnull} pk={apk}）"
            )


def _assert_index_contract(conn: sqlite3.Connection) -> None:
    """断言必需索引契约：存在、非自动索引、指向预期表与目标列。

    不依赖索引名做最终判定：名称仅用于定位，tbl_name / index_info 列集合
    必须与契约一致；并通过 index_list 断言为普通 CREATE INDEX
    （unique=0、partial=0、origin='c'），防止同名同列的唯一/部分索引冒充。
    """
    for name, (table, columns) in _EXPECTED_INDEXES.items():
        row = conn.execute(
            "SELECT tbl_name, sql FROM sqlite_master "
            "WHERE type = 'index' AND name = ?",
            (name,),
        ).fetchone()
        if row is None:
            raise FrozenDecisionCorruptedError(f"必需索引缺失：{name}")
        if row["sql"] is None:
            raise FrozenDecisionCorruptedError(f"{name} 是自动索引，不符合契约")
        if row["tbl_name"] != table:
            raise FrozenDecisionCorruptedError(
                f"索引 {name} 指向错误表：{row['tbl_name']}"
            )
        info = conn.execute(f"PRAGMA index_info({name})").fetchall()
        actual_columns = [r["name"] for r in info]
        if actual_columns != list(columns):
            raise FrozenDecisionCorruptedError(
                f"索引 {name} 目标列不符：{actual_columns}（期望 {list(columns)}）"
            )
        # unique / partial / origin：v0.1 契约要求普通非唯一非部分 CREATE INDEX
        index_rows = conn.execute(f"PRAGMA index_list({table})").fetchall()
        match = [r for r in index_rows if r["name"] == name]
        if not match:
            raise FrozenDecisionCorruptedError(f"索引 {name} 不在 index_list 中")
        idx = match[0]
        if idx["unique"] != 0 or idx["partial"] != 0 or idx["origin"] != "c":
            raise FrozenDecisionCorruptedError(
                f"索引 {name} 不是普通 CREATE INDEX"
                f"（unique={idx['unique']} partial={idx['partial']} origin={idx['origin']}）"
            )


def _assert_schema(conn: sqlite3.Connection) -> None:
    """单一 schema 权威：现有库完整应用结构断言（只读，零突变）。

    - 应用表集合恰为 {schema_meta, frozen_decisions}，无意外表
    - schema_meta / frozen_decisions 的列集合、声明类型、NOT NULL、PK 契约
    - decision_id 必须是 frozen_decisions PRIMARY KEY
    - 4 个必需索引存在、指向预期表与列，且为普通 CREATE INDEX
      （unique=0、partial=0、origin='c'）
    - 零触发器：v0.1 定义零触发器，任何触发器（含对合法 INSERT 的
      恶意 DELETE 触发器）→ fail closed
    - 零视图：v0.1 定义零视图，任何意外视图 → fail closed

    任一不符 → FrozenDecisionCorruptedError（fail closed），不做任何修复。
    此函数为读 / 初始化预检 / 写预检共用的唯一权威实现。
    """
    try:
        tables = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        if tables != set(_EXPECTED_TABLES):
            raise FrozenDecisionCorruptedError(
                f"应用表集合不符合 v0.1 契约：{sorted(tables)}"
            )
        _assert_table_contract(conn, "schema_meta", _SCHEMA_META_COLUMNS)
        _assert_table_contract(conn, "frozen_decisions", _FROZEN_DECISIONS_COLUMNS)
        _assert_index_contract(conn)
        # 可执行对象：v0.1 定义零触发器，任何触发器都必须 fail closed
        triggers = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'trigger'"
        ).fetchall()
        if triggers:
            raise FrozenDecisionCorruptedError(
                f"不允许存在触发器：{[r['name'] for r in triggers]}"
            )
        # 视图：v0.1 定义零视图，任何意外视图都必须 fail closed
        views = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'view'"
        ).fetchall()
        if views:
            raise FrozenDecisionCorruptedError(
                f"不允许存在视图：{[r['name'] for r in views]}"
            )
    except FrozenDecisionError:
        raise
    except sqlite3.DatabaseError:
        raise FrozenDecisionCorruptedError()


def _read_schema_version(conn: sqlite3.Connection) -> str | None:
    row = conn.execute(
        "SELECT value FROM schema_meta WHERE key = 'schema_version'"
    ).fetchone()
    return row["value"] if row else None


def _validate_and_prepare_schema(conn: sqlite3.Connection, is_write: bool) -> None:
    """统一 Schema 校验与准备。

    - 已有 schema_meta：版本必须与代码版本完全一致，随后立即执行
      应用结构断言（_assert_schema），任一不符 fail closed
    - 非空数据库缺 schema_meta：视为损坏，fail closed
    - 全新空数据库：仅写路径执行 DDL 并写入版本
    - 任何校验失败均不执行 DDL
    """
    has_schema_meta = _table_exists(conn, "schema_meta")
    if has_schema_meta:
        version = _read_schema_version(conn)
        if version is None:
            raise FrozenDecisionCorruptedError("schema_meta 存在但缺少 schema_version")
        if version != SCHEMA_VERSION:
            raise FrozenDecisionSchemaVersionError(
                f"不支持的 schema 版本：{version}（期望 {SCHEMA_VERSION}）"
            )
        # 现有库：版本确认后立即做应用结构断言（单一权威，只读零突变）
        _assert_schema(conn)
        return

    has_any_table = (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' "
            "AND name != 'sqlite_sequence' LIMIT 1"
        ).fetchone()
        is not None
    )
    if has_any_table:
        raise FrozenDecisionCorruptedError("非空数据库缺少 schema_meta")

    if is_write:
        for ddl in _ALL_DDL:
            conn.execute(ddl)
        conn.execute(
            "INSERT INTO schema_meta(key, value) VALUES ('schema_version', ?)",
            (SCHEMA_VERSION,),
        )


def initialize_store(db_path: str | Path) -> None:
    """显式初始化存储（幂等）：创建目录、表、索引并写入 schema 版本。

    - 全新数据库：允许创建 schema 并设置 WAL
    - 已有数据库：先以只读方式确认 schema/版本与应用结构契约（零突变）；
      版本不匹配或结构损坏直接 fail closed，绝不触碰 journal / WAL / SHM / 文件内容
    - 仅版本与结构均确认匹配后才允许进入 WAL / 可写设置
    """
    path = _as_path(db_path)
    if path == ":memory:":
        conn = sqlite3.connect(path, timeout=5)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 5000")
        try:
            with conn:
                conn.execute("PRAGMA journal_mode = WAL")
                _validate_and_prepare_schema(conn, is_write=True)
        except (FrozenDecisionCorruptedError, FrozenDecisionSchemaVersionError):
            raise
        except sqlite3.DatabaseError:
            raise FrozenDecisionCorruptedError()
        finally:
            conn.close()
        return

    if _db_file_exists(path):
        # 已有数据库：只读确认 schema/版本，零突变
        conn = _connect_readonly(path)
        try:
            _validate_and_prepare_schema(conn, is_write=False)
        except FrozenDecisionError:
            raise
        except sqlite3.DatabaseError:
            raise FrozenDecisionCorruptedError()
        finally:
            conn.close()

    # 全新数据库（文件不存在）允许创建；已有数据库版本已确认匹配。
    # 先验证（已有库幂等、无 DDL），通过后才允许 WAL 设置。
    _ensure_parent_dir(path)
    conn = sqlite3.connect(path, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 5000")
    try:
        with conn:
            _validate_and_prepare_schema(conn, is_write=True)
        conn.execute("PRAGMA journal_mode = WAL")
    except (FrozenDecisionCorruptedError, FrozenDecisionSchemaVersionError):
        raise
    except sqlite3.DatabaseError:
        raise FrozenDecisionCorruptedError()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Snapshot 值级校验（写前防御 + 读后验证共用）
# ---------------------------------------------------------------------------

_CANONICAL_UTC_TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$")


def is_canonical_utc_timestamp(value: Any) -> bool:
    """严格 canonical UTC 时间戳：``YYYY-MM-DDTHH:MM:SS.ffffffZ``。

    仅接受微秒 6 位 + ``Z`` 后缀的规范表示；任何其他合法但非 canonical 的
    零偏移 ISO 形式（无微秒、偏移 +00:00 等）一律拒绝。读取路径对持久化
    时间戳不做任何静默规范化。
    """
    if not isinstance(value, str):
        return False
    if not _CANONICAL_UTC_TS_RE.fullmatch(value):
        return False
    try:
        datetime.fromisoformat(value)
    except ValueError:
        return False
    return True


def _validate_snapshot_values(snapshot: Mapping[str, Any]) -> None:
    """对 snapshot 对象做值级校验；任一不合法抛 FrozenDecisionCorruptedError。

    注意：此函数同时用于写前（调用方构造错误 → 以 FrozenDecisionError 报告）
    与读后（库内容损坏 → 以 FrozenDecisionCorruptedError 报告），保持同一套
    权威校验规则。
    """
    try:
        if snapshot["snapshot_schema_version"] != SCHEMA_VERSION:
            raise FrozenDecisionSchemaVersionError(
                f"不支持的 snapshot 版本：{snapshot['snapshot_schema_version']}"
            )
        if not _DECISION_ID_RE.fullmatch(snapshot["decision_id"]):
            raise FrozenDecisionCorruptedError("decision_id 不合法")
        if not _SECURITY_CODE_RE.fullmatch(snapshot["security_code"]):
            raise FrozenDecisionCorruptedError("security_code 不合法")
        if snapshot["strategy"] not in STRATEGIES:
            raise FrozenDecisionCorruptedError("strategy 不合法")
        if not _CAMPAIGN_ID_RE.fullmatch(snapshot["campaign_id"]):
            raise FrozenDecisionCorruptedError("campaign_id 不合法")
        if not isinstance(snapshot["committed_at"], str) or not is_canonical_utc_timestamp(
            snapshot["committed_at"]
        ):
            raise FrozenDecisionCorruptedError("committed_at 不合法")
        if not _THESIS_ID_RE.fullmatch(snapshot["thesis_id"]):
            raise FrozenDecisionCorruptedError("thesis_id 不合法")
        if (
            not isinstance(snapshot["thesis_revision"], int)
            or isinstance(snapshot["thesis_revision"], bool)
            or snapshot["thesis_revision"] < 1
        ):
            raise FrozenDecisionCorruptedError("thesis_revision 不合法")
        for view_key in ("asset_view", "trade_view", "portfolio_view"):
            if not isinstance(snapshot[view_key], dict):
                raise FrozenDecisionCorruptedError(f"{view_key} 必须是 JSON 对象")
        if snapshot["next_best_action"] not in NEXT_BEST_ACTIONS:
            raise FrozenDecisionCorruptedError("next_best_action 不合法")
        if not isinstance(snapshot["action_envelope"], dict):
            raise FrozenDecisionCorruptedError("action_envelope 必须是 JSON 对象")
        for cond_key in (
            "maintain_conditions",
            "upgrade_conditions",
            "downgrade_conditions",
            "invalidation_conditions",
            "key_assumptions",
            "event_invalidation_conditions",
        ):
            if not isinstance(snapshot[cond_key], list):
                raise FrozenDecisionCorruptedError(f"{cond_key} 必须是 JSON 数组")
        if not isinstance(snapshot["strategy_horizon"], (str, dict)) or (
            isinstance(snapshot["strategy_horizon"], str)
            and not snapshot["strategy_horizon"].strip()
        ):
            raise FrozenDecisionCorruptedError("strategy_horizon 不合法")
        if not isinstance(snapshot["review_by"], str) or not is_canonical_utc_timestamp(
            snapshot["review_by"]
        ):
            raise FrozenDecisionCorruptedError("review_by 不合法")
        if snapshot["validity_status_at_commit"] != VALIDITY_STATUS_AT_COMMIT:
            raise FrozenDecisionCorruptedError("validity_status_at_commit 不合法")
        for policy_key in (
            "risk_policy_version",
            "opportunity_policy_version",
            "decision_policy_version",
            "behavior_model_version",
        ):
            if (
                not isinstance(snapshot[policy_key], str)
                or not snapshot[policy_key].strip()
            ):
                raise FrozenDecisionCorruptedError(f"{policy_key} 必须是规范非空字符串")
        for refs_key in ("evidence_refs", "risk_refs", "source_refs"):
            if not isinstance(snapshot[refs_key], list) or not all(
                isinstance(ref, str) for ref in snapshot[refs_key]
            ):
                raise FrozenDecisionCorruptedError(f"{refs_key} 必须是字符串引用数组")
        for confidence_key in (
            "data_quality",
            "evidence_confidence",
            "inference_confidence",
            "decision_confidence",
        ):
            # 任意 canonical JSON 值（含 null / dict / 标量）；NaN 等非法值由
            # canonical 序列化在写前拒绝。
            snapshot[confidence_key]  # noqa: B018 — 键存在性检查
    except KeyError as exc:
        raise FrozenDecisionCorruptedError(f"snapshot 缺少字段：{exc.args[0]}") from exc


# ---------------------------------------------------------------------------
# 行组装与完整读验证
# ---------------------------------------------------------------------------

def _row_to_snapshot(row: sqlite3.Row) -> dict[str, Any]:
    try:
        snapshot = json.loads(row["snapshot_json"])
    except (ValueError, TypeError):
        raise FrozenDecisionCorruptedError("snapshot_json 无法解析") from None
    if not isinstance(snapshot, dict):
        raise FrozenDecisionCorruptedError("snapshot_json 顶层必须是 JSON 对象")
    missing = SNAPSHOT_KEYS - set(snapshot)
    if missing:
        raise FrozenDecisionCorruptedError(
            f"snapshot 缺少字段：{sorted(missing)}"
        )
    extra = set(snapshot) - SNAPSHOT_KEYS
    if extra:
        raise FrozenDecisionCorruptedError(f"snapshot 含未知字段：{sorted(extra)}")
    # 存储文本必须是 canonical：任何非规范表示（乱序键、空白、NaN 字面量等）
    # 都会导致文本比对失败，fail closed。
    try:
        canonical = canonical_json(snapshot)
    except (ValueError, TypeError):
        raise FrozenDecisionCorruptedError(
            "snapshot_json 含非法 JSON 值（NaN / Infinity / 非 JSON 结构）"
        ) from None
    if row["snapshot_json"] != canonical:
        raise FrozenDecisionCorruptedError("snapshot_json 不是 canonical 表示")
    # 独立列必须与 snapshot_json 内容逐字一致，防止半更新伪造。
    for key in _LEAF_KEYS:
        if row[key] != snapshot[key]:
            raise FrozenDecisionCorruptedError(f"列与 snapshot 不一致：{key}")
    # 哈希必须匹配重算值。
    if row["snapshot_hash"] != snapshot_hash(snapshot):
        raise FrozenDecisionCorruptedError("snapshot_hash 与内容不匹配")
    if not _SNAPSHOT_HASH_RE.fullmatch(row["snapshot_hash"]):
        raise FrozenDecisionCorruptedError("snapshot_hash 格式不合法")
    if row["user_confirmed"] != 1:
        raise FrozenDecisionCorruptedError("user_confirmed 必须为 True")
    if not is_canonical_utc_timestamp(row["created_at"]):
        raise FrozenDecisionCorruptedError("created_at 不是 canonical UTC 时间戳")
    _validate_snapshot_values(snapshot)
    return snapshot


def _row_to_frozen(row: sqlite3.Row, snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        **snapshot,
        "snapshot_json": row["snapshot_json"],
        "snapshot_hash": row["snapshot_hash"],
        "user_confirmed": True,
        "created_at": row["created_at"],
    }


def _verify_frozen(frozen: dict[str, Any]) -> dict[str, Any]:
    """写前防御校验：行 dict → snapshot 重建 → canonical 文本 → 哈希 → 值校验。"""
    try:
        missing = SNAPSHOT_KEYS - set(frozen)
        if missing:
            raise ValueError(f"缺少 snapshot 字段：{sorted(missing)}")
        extra = set(frozen) - SNAPSHOT_KEYS - {"snapshot_json", "snapshot_hash", "user_confirmed", "created_at"}
        if extra:
            raise ValueError(f"含未知字段：{sorted(extra)}")
        snapshot = {key: frozen[key] for key in SNAPSHOT_KEYS}
        _validate_snapshot_values(snapshot)
        if frozen["snapshot_json"] != canonical_json(snapshot):
            raise ValueError("snapshot_json 与 snapshot 字段不一致")
        if frozen["snapshot_hash"] != snapshot_hash(snapshot):
            raise ValueError("snapshot_hash 与 snapshot 字段不一致")
        if frozen["user_confirmed"] is not True:
            raise ValueError("user_confirmed 必须是严格 True")
        if not is_canonical_utc_timestamp(frozen["created_at"]):
            raise ValueError("created_at 必须是 canonical UTC 时间戳")
    except FrozenDecisionError:
        raise
    except Exception as exc:
        raise ValueError(f"拒绝写入非规范冻结记录：{exc}") from exc
    return frozen


# ---------------------------------------------------------------------------
# 写路径（append-only + 幂等重放 + 冲突 fail closed）
# ---------------------------------------------------------------------------

_FROZEN_COLUMNS = (
    "decision_id",
    "security_code",
    "strategy",
    "campaign_id",
    "committed_at",
    "snapshot_schema_version",
    "snapshot_hash",
    "thesis_id",
    "thesis_revision",
    "next_best_action",
    "review_by",
    "validity_status_at_commit",
    "risk_policy_version",
    "opportunity_policy_version",
    "decision_policy_version",
    "behavior_model_version",
    "user_confirmed",
    "snapshot_json",
    "created_at",
)


def _open_for_write(db_path: str | Path) -> sqlite3.Connection:
    """可写连接：只读预检（版本 + 结构断言）通过后才允许打开可写连接。

    结构损坏的 current-version 库在可写连接打开前即被拒绝（零突变）；
    全新库（文件不存在）允许创建精确 v0.1 schema。
    """
    path = _as_path(db_path)
    if path != ":memory:":
        if _db_file_exists(path):
            # 只读预检：任何 schema 不合法都在可写连接打开前拒绝
            conn_ro = _connect_readonly(path)
            try:
                _validate_and_prepare_schema(conn_ro, is_write=False)
            except FrozenDecisionError:
                raise
            except sqlite3.DatabaseError:
                raise FrozenDecisionCorruptedError()
            finally:
                conn_ro.close()
        _ensure_parent_dir(path)
    conn = _connect(path)
    try:
        with conn:
            _validate_and_prepare_schema(conn, is_write=True)
        row = conn.execute("PRAGMA integrity_check").fetchone()
        if row is None or row[0] != "ok":
            conn.close()
            raise FrozenDecisionCorruptedError()
    except sqlite3.DatabaseError:
        conn.close()
        raise FrozenDecisionCorruptedError()
    except (FrozenDecisionCorruptedError, FrozenDecisionSchemaVersionError):
        conn.close()
        raise
    return conn


class _Tx:
    """BEGIN IMMEDIATE 事务；异常自动 ROLLBACK。"""

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def __enter__(self) -> sqlite3.Connection:
        self._conn.execute("BEGIN IMMEDIATE")
        return self._conn

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:  # noqa: ANN001
        if exc_type is not None:
            self._conn.rollback()
        else:
            self._conn.commit()


def write_frozen_decision(db_path: str | Path, frozen: dict[str, Any]) -> dict[str, Any]:
    """写入一条冻结决策；同 decision_id 精确重放幂等返回，冲突 fail closed。

    无 UPDATE / DELETE / UPSERT / REPLACE：同 decision_id 只能存在一种内容。
    """
    _verify_frozen(frozen)
    with _LOCK:
        conn = _open_for_write(db_path)
        try:
            with _Tx(conn):
                existing = conn.execute(
                    "SELECT * FROM frozen_decisions WHERE decision_id = ?",
                    (frozen["decision_id"],),
                ).fetchone()
                if existing is None:
                    values = tuple(frozen.get(col) for col in _FROZEN_COLUMNS)
                    conn.execute(
                        f"INSERT INTO frozen_decisions ({', '.join(_FROZEN_COLUMNS)}) "
                        f"VALUES ({', '.join('?' for _ in _FROZEN_COLUMNS)})",
                        values,
                    )
                    conn.commit()  # 先落盘再返回，保证读回即可验证
                    row = conn.execute(
                        "SELECT * FROM frozen_decisions WHERE decision_id = ?",
                        (frozen["decision_id"],),
                    ).fetchone()
                    snapshot = _row_to_snapshot(row)
                    return _row_to_frozen(row, snapshot)
                # 幂等重放：全部受保护内容必须完全一致
                existing_frozen = {
                    key: existing[key] for key in _FROZEN_COLUMNS
                }
                incoming_frozen = {
                    key: frozen.get(key) for key in _FROZEN_COLUMNS
                }
                if existing_frozen != incoming_frozen:
                    raise FrozenDecisionConflictError(
                        f"decision_id {frozen['decision_id']} 已存在且内容不一致"
                    )
                snapshot = _row_to_snapshot(existing)
                return _row_to_frozen(existing, snapshot)
        except FrozenDecisionError:
            raise
        except sqlite3.DatabaseError:
            raise FrozenDecisionCorruptedError()
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# 读路径（零副作用 + fail closed）
# ---------------------------------------------------------------------------

def _open_readonly_if_exists(db_path: str | Path) -> sqlite3.Connection | None:
    """只读打开；文件缺失返回 None，绝不创建目录 / DB / -wal / -shm。"""
    if not _db_file_exists(db_path):
        return None
    return _connect_readonly(db_path)


def get_frozen_decision(
    db_path: str | Path, decision_id: str
) -> dict[str, Any] | None:
    """按 decision_id 读取；缺失返回 None；内容损坏 fail closed。"""
    conn = _open_readonly_if_exists(db_path)
    if conn is None:
        return None
    try:
        _validate_and_prepare_schema(conn, is_write=False)
        row = conn.execute(
            "SELECT * FROM frozen_decisions WHERE decision_id = ?",
            (decision_id,),
        ).fetchone()
        if row is None:
            return None
        snapshot = _row_to_snapshot(row)
        return _row_to_frozen(row, snapshot)
    except FrozenDecisionError:
        raise
    except sqlite3.DatabaseError:
        raise FrozenDecisionCorruptedError()
    finally:
        conn.close()


def list_frozen_decisions(
    db_path: str | Path,
    security_code: str | None = None,
    strategy: str | None = None,
    campaign_id: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """确定性列举：committed_at ASC，decision_id ASC。

    过滤器：security_code / strategy / campaign_id（精确匹配，无模糊查询）。
    任一记录损坏 → 整个列举 fail closed。
    """
    conn = _open_readonly_if_exists(db_path)
    if conn is None:
        return []
    try:
        _validate_and_prepare_schema(conn, is_write=False)
        if strategy is not None and strategy not in STRATEGIES:
            raise ValueError(f"strategy 过滤器不合法：{strategy}")
        where = "WHERE 1=1"
        params: list[Any] = []
        if security_code is not None:
            where += " AND security_code = ?"
            params.append(security_code)
        if strategy is not None:
            where += " AND strategy = ?"
            params.append(strategy)
        if campaign_id is not None:
            where += " AND campaign_id = ?"
            params.append(campaign_id)
        params.extend([limit, offset])
        rows = conn.execute(
            f"SELECT * FROM frozen_decisions {where} "
            "ORDER BY committed_at ASC, decision_id ASC LIMIT ? OFFSET ?",
            params,
        ).fetchall()
        results = []
        for row in rows:
            snapshot = _row_to_snapshot(row)
            results.append(_row_to_frozen(row, snapshot))
        return results
    except FrozenDecisionError:
        raise
    except sqlite3.DatabaseError:
        raise FrozenDecisionCorruptedError()
    finally:
        conn.close()
