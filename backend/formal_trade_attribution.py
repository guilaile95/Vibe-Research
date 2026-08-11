"""正式决策 ↔ 手动交易归属领域核心（P0-TB1，纯逻辑，零 I/O）。

定义跨域语义契约：

    Frozen Decision  ←attributed→  Manual Trade

"归属"（attribution）的含义是：

    "这条已记录的手动交易，是在这个用户确认的正式冻结决策的背景下发生的。"

它**不是**合规性判断：不要求交易操作服从 next_best_action，
也不对任何投资质量做出判断（WAIT→buy、EXIT→add 均可正式归属）。

本模块是纯领域逻辑：

- 无 SQLite / 文件系统 / 网络 / 环境变量 / 时钟读 / AI / HTTP
- 函数接收已加载的 Mapping / 值对象
- 不修改 Trade Ledger（不改 trade_records、不填充空字段、不改写操作/状态/时间戳）
- 不新增持久化（本切片的归属记录是领域契约，持久化属后续单独授权的切片）

正式决策见证验证复用已接受的 P0-FD1 公开确定性原语
（frozen_decision_store.SNAPSHOT_KEYS / canonical_json / snapshot_hash /
STRATEGIES / NEXT_BEST_ACTIONS / is_canonical_utc_timestamp）。
"""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from frozen_decision_store import (
    NEXT_BEST_ACTIONS,
    SNAPSHOT_KEYS,
    STRATEGIES,
    SCHEMA_VERSION as FROZEN_DECISION_SCHEMA_VERSION,
    canonical_json,
    is_canonical_utc_timestamp,
    snapshot_hash,
)

SCHEMA_VERSION = "formal_trade_attribution.v0.1"

# ---------------------------------------------------------------------------
# 权威枚举与格式（来源：已接受 P0-FD1 + 现行 Trade Ledger 权威）
# ---------------------------------------------------------------------------

# Trade Ledger 权威：operation / execution_status / trade_id 格式
TRADE_OPERATIONS = ("buy", "add", "reduce", "sell")
TRADE_EXECUTION_STATUSES = ("full", "partial", "not_executed")

_ATTRIBUTION_ID_RE = re.compile(r"^trade_attribution_[0-9a-f]{32}$")
_TRADE_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_DECISION_ID_RE = re.compile(r"^decision_[0-9a-f]{32}$")
_SECURITY_CODE_RE = re.compile(r"^\d{6}$")
_CAMPAIGN_ID_RE = re.compile(r"^campaign_[0-9a-f]{32}$")
_THESIS_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_SNAPSHOT_HASH_RE = re.compile(r"^[0-9a-f]{64}$")

# ---------------------------------------------------------------------------
# 错误模型
# ---------------------------------------------------------------------------


class FormalTradeAttributionError(RuntimeError):
    """正式交易归属领域基础异常。"""


class AttributionValidationError(FormalTradeAttributionError):
    """输入验证失败：见证伪造 / 格式非法 / 时间反转 / 状态矛盾等。"""


class AttributionConflictError(FormalTradeAttributionError):
    """归属集合冲突：同 id 内容冲突、同一交易归属多个决策等。"""


class AttributionSchemaVersionError(FormalTradeAttributionError):
    """归属记录 schema 版本不兼容。"""


# ---------------------------------------------------------------------------
# 时间工具（纯解析，无时钟读；不做时区猜测）
# ---------------------------------------------------------------------------


def parse_utc_instant(value: Any, field: str) -> datetime:
    """解析零偏移 UTC 时间戳为 aware datetime。

    接受 ``Z`` 或 ``+00:00`` 后缀（微秒 0-6 位）。缺失时区 / 非零偏移
    一律拒绝（不猜测、不换算）。用于跨格式（FD1 的 Z 与 Trade Ledger
    的 +00:00）的一致性比较与规范化。
    """
    if not isinstance(value, str) or not value.strip():
        raise AttributionValidationError(f"{field}：必须是带时区的 UTC 时间戳")
    text = value.strip()
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        raise AttributionValidationError(f"{field}：无法解析的时间戳") from None
    if dt.tzinfo is None:
        raise AttributionValidationError(f"{field}：缺少时区信息")
    if dt.utcoffset().total_seconds() != 0:
        raise AttributionValidationError(
            f"{field}：仅接受零偏移 UTC（Z 或 +00:00），不做时区换算"
        )
    return dt.astimezone(timezone.utc)


def to_canonical_utc(value: Any, field: str) -> str:
    """解析并规范化为 canonical UTC：``YYYY-MM-DDTHH:MM:SS.ffffffZ``。"""
    return parse_utc_instant(value, field).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


# ---------------------------------------------------------------------------
# 输入 A — 正式冻结决策见证独立验证
# ---------------------------------------------------------------------------


def verify_frozen_decision_witness(decision: Mapping[str, Any]) -> dict[str, Any]:
    """独立验证正式冻结决策见证，防止绑定明显伪造的 mapping。

    验证：
    1. 从 SNAPSHOT_KEYS 重建受保护 snapshot，要求
       canonical_json(snapshot) == snapshot_json（逐字）
    2. snapshot_hash(snapshot) == 持久化 snapshot_hash
    3. user_confirmed 严格 True
    4. 身份/枚举/时间戳显式格式验证（decision_id、schema 版本、
       security_code、strategy、campaign_id、thesis_id、thesis_revision、
       committed_at、review_by、next_best_action）

    返回规范化后的决策锚字段（供归属构造使用）。
    """
    if not isinstance(decision, Mapping):
        raise AttributionValidationError("decision：必须是 Mapping")

    missing = SNAPSHOT_KEYS - set(decision)
    if missing:
        raise AttributionValidationError(
            f"decision：缺少受保护快照字段 {sorted(missing)}"
        )
    for key in ("snapshot_json", "snapshot_hash", "user_confirmed"):
        if key not in decision:
            raise AttributionValidationError(f"decision：缺少 {key}")
    snapshot = {key: decision[key] for key in SNAPSHOT_KEYS}

    # 防伪造核心：canonical 文本逐字一致 + 哈希一致
    try:
        expected_text = canonical_json(snapshot)
    except (ValueError, TypeError):
        raise AttributionValidationError(
            "decision：快照含非法 JSON 值（NaN / Infinity / 非 JSON 结构）"
        ) from None
    if decision["snapshot_json"] != expected_text:
        raise AttributionValidationError(
            "decision：snapshot_json 与受保护字段不一致（见证被篡改）"
        )
    if decision["snapshot_hash"] != snapshot_hash(snapshot):
        raise AttributionValidationError(
            "decision：snapshot_hash 与受保护内容不匹配（见证被篡改）"
        )

    # 显式身份 / 枚举 / 时间戳格式验证
    if decision["snapshot_schema_version"] != FROZEN_DECISION_SCHEMA_VERSION:
        raise AttributionValidationError(
            f"decision：snapshot_schema_version 必须为 {FROZEN_DECISION_SCHEMA_VERSION}"
        )
    if decision["user_confirmed"] is not True:
        raise AttributionValidationError("decision：user_confirmed 必须是严格 True")
    if not isinstance(decision["decision_id"], str) or not _DECISION_ID_RE.fullmatch(
        decision["decision_id"]
    ):
        raise AttributionValidationError("decision：decision_id 格式不合法")
    if not isinstance(decision["security_code"], str) or not _SECURITY_CODE_RE.fullmatch(
        decision["security_code"]
    ):
        raise AttributionValidationError("decision：security_code 必须是 6 位数字")
    if decision["strategy"] not in STRATEGIES:
        raise AttributionValidationError("decision：strategy 不合法")
    if not isinstance(decision["campaign_id"], str) or not _CAMPAIGN_ID_RE.fullmatch(
        decision["campaign_id"]
    ):
        raise AttributionValidationError("decision：campaign_id 格式不合法")
    if not isinstance(decision["thesis_id"], str) or not _THESIS_ID_RE.fullmatch(
        decision["thesis_id"]
    ):
        raise AttributionValidationError("decision：thesis_id 格式不合法")
    if (
        not isinstance(decision["thesis_revision"], int)
        or isinstance(decision["thesis_revision"], bool)
        or decision["thesis_revision"] < 1
    ):
        raise AttributionValidationError("decision：thesis_revision 必须为正整数")
    if not is_canonical_utc_timestamp(decision["committed_at"]):
        raise AttributionValidationError("decision：committed_at 不是 canonical UTC")
    if not is_canonical_utc_timestamp(decision["review_by"]):
        raise AttributionValidationError("decision：review_by 不是 canonical UTC")
    if decision["next_best_action"] not in NEXT_BEST_ACTIONS:
        raise AttributionValidationError("decision：next_best_action 不合法")

    return {
        "decision_id": decision["decision_id"],
        "decision_snapshot_hash": decision["snapshot_hash"],
        "security_code": decision["security_code"],
        "strategy": decision["strategy"],
        "campaign_id": decision["campaign_id"],
        "thesis_id": decision["thesis_id"],
        "thesis_revision": decision["thesis_revision"],
        "decision_committed_at": decision["committed_at"],
        "decision_review_by": decision["review_by"],
        "decision_next_best_action": decision["next_best_action"],
    }


# ---------------------------------------------------------------------------
# 输入 B — 现行 Trade Ledger 记录验证
# ---------------------------------------------------------------------------


def verify_trade_record(trade: Mapping[str, Any]) -> dict[str, Any]:
    """验证现行 Trade Ledger 记录形状（不定义竞争 Trade 类，不修改记录）。

    验证：trade_id（32 hex 无前缀）、code（6 位）、operation /
    execution_status 枚举、executed_at 与状态一致性、created_at、
    voided_at（新归属要求 None）、既有 thesis 引用（全空或完全匹配）。

    返回规范化后的交易锚字段。
    """
    if not isinstance(trade, Mapping):
        raise AttributionValidationError("trade：必须是 Mapping")

    trade_id = trade.get("trade_id")
    if not isinstance(trade_id, str) or not _TRADE_ID_RE.fullmatch(trade_id):
        raise AttributionValidationError("trade：trade_id 必须是 32 位小写 hex（无前缀）")
    code = trade.get("code")
    if not isinstance(code, str) or not _SECURITY_CODE_RE.fullmatch(code):
        raise AttributionValidationError("trade：code 必须是 6 位数字")
    operation = trade.get("operation")
    if operation not in TRADE_OPERATIONS:
        raise AttributionValidationError(
            f"trade：operation 必须是 {TRADE_OPERATIONS} 之一"
        )
    status = trade.get("execution_status")
    if status not in TRADE_EXECUTION_STATUSES:
        raise AttributionValidationError(
            f"trade：execution_status 必须是 {TRADE_EXECUTION_STATUSES} 之一"
        )

    # 作废策略：已作废记录不是当前执行权威，拒绝新归属
    if trade.get("voided_at") is not None:
        raise AttributionValidationError("trade：已作废交易不得创建新归属")

    # executed_at 与状态一致性（保留实际状态，不捏造执行）
    executed_at = trade.get("executed_at")
    if status in ("full", "partial"):
        if executed_at is None:
            raise AttributionValidationError(
                "trade：full/partial 状态要求 executed_at 必填"
            )
        normalized_executed_at = to_canonical_utc(executed_at, "trade.executed_at")
    else:  # not_executed
        if executed_at is not None:
            raise AttributionValidationError(
                "trade：not_executed 状态要求 executed_at 为 None"
            )
        normalized_executed_at = None

    created_at = trade.get("created_at")
    if created_at is None:
        raise AttributionValidationError("trade：created_at 必填")
    normalized_created_at = to_canonical_utc(created_at, "trade.created_at")

    # 既有 thesis 引用交叉检查：全空或完全匹配，禁止半空 / 冲突
    trade_thesis_id = trade.get("thesis_id")
    trade_thesis_revision = trade.get("thesis_revision")
    if trade_thesis_id is None and trade_thesis_revision is None:
        pass  # 允许：Frozen Decision 成为正式归属锚
    else:
        if not isinstance(trade_thesis_id, str) or not _THESIS_ID_RE.fullmatch(
            trade_thesis_id
        ):
            raise AttributionValidationError(
                "trade：thesis_id / thesis_revision 必须同时提供且格式合法"
            )
        if (
            not isinstance(trade_thesis_revision, int)
            or isinstance(trade_thesis_revision, bool)
            or trade_thesis_revision < 1
        ):
            raise AttributionValidationError(
                "trade：thesis_id / thesis_revision 必须同时提供且格式合法"
            )

    return {
        "trade_id": trade_id,
        "trade_operation": operation,
        "trade_execution_status": status,
        "trade_executed_at": normalized_executed_at,
        "trade_created_at": normalized_created_at,
        "thesis_id": trade_thesis_id,
        "thesis_revision": trade_thesis_revision,
    }


# ---------------------------------------------------------------------------
# 归属记录（不可变 canonical 值对象）
# ---------------------------------------------------------------------------

_ATTRIBUTION_FIELDS = (
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

# 除 attribution_hash 自身外的全部语义/审计字段（含 id 与时间戳）参与哈希
_HASHED_FIELDS = tuple(f for f in _ATTRIBUTION_FIELDS if f != "attribution_hash")

# 完整决策锚：同 decision_id 的所有归属记录，这些决策派生字段必须完全一致
# （集合验证唯一权威，禁止维护手写子集）
DECISION_ANCHOR_FIELDS = (
    "decision_snapshot_hash",
    "security_code",
    "strategy",
    "campaign_id",
    "thesis_id",
    "thesis_revision",
    "decision_committed_at",
    "decision_review_by",
    "decision_next_best_action",
)


def _validate_record_semantics(record: Mapping[str, Any]) -> None:
    """单一记录语义权威（P1-A）：时域来源必须自洽。

    - decision_committed_at <= trade_created_at（一律）
    - 已执行交易（trade_executed_at 非 None）另需：
      decision_committed_at <= trade_executed_at

    使用解析后的 UTC instant 比较（跨 Z / +00:00 格式安全）。
    此权威由严格 from_dict 强制，杜绝序列化后篡改时间戳绕过创建路径
    的时域校验（拒绝事后归属伪造）。
    """
    committed_at_dt = parse_utc_instant(
        record["decision_committed_at"], "decision_committed_at"
    )
    created_at_dt = parse_utc_instant(
        record["trade_created_at"], "trade_created_at"
    )
    if committed_at_dt > created_at_dt:
        raise AttributionValidationError(
            "时域来源不合法：决策提交时刻不得晚于交易创建时刻（拒绝事后归属）"
        )
    if record["trade_executed_at"] is not None:
        executed_at_dt = parse_utc_instant(
            record["trade_executed_at"], "trade_executed_at"
        )
        if committed_at_dt > executed_at_dt:
            raise AttributionValidationError(
                "时域来源不合法：决策提交时刻不得晚于实际执行时刻（拒绝事后归属）"
            )


@dataclass(frozen=True)
class FormalTradeAttribution:
    """不可变正式交易归属记录（值对象，无方法之外的任何行为）。

    schema_version 固定为 ``formal_trade_attribution.v0.1``。
    """

    attribution_id: str
    trade_id: str
    decision_id: str
    decision_snapshot_hash: str
    security_code: str
    strategy: str
    campaign_id: str
    thesis_id: str
    thesis_revision: int
    decision_committed_at: str
    decision_review_by: str
    decision_next_best_action: str
    trade_operation: str
    trade_execution_status: str
    trade_executed_at: str | None
    trade_created_at: str
    created_at: str
    schema_version: str = SCHEMA_VERSION
    attribution_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        """严格规范表示：精确字段集、固定顺序、原值输出。"""
        return {field: getattr(self, field) for field in _ATTRIBUTION_FIELDS}


def compute_attribution_hash(record: Mapping[str, Any]) -> str:
    """确定性 SHA-256 over canonical JSON（全部受保护字段，含 attribution_id
    与 created_at——避免出现"合法时间戳但不受哈希保护"的审计缺口）。

    本项目确定性 canonical 契约（stdlib），不声明完整 RFC 8785 合规。
    """
    payload = {field: record[field] for field in _HASHED_FIELDS}
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def new_attribution_id() -> str:
    """生成新的归属 ID：``trade_attribution_<32 位小写 hex uuid4>``。"""
    return f"trade_attribution_{uuid.uuid4().hex}"


def create_attribution(
    decision: Mapping[str, Any],
    trade: Mapping[str, Any],
    *,
    attribution_id: str,
    created_at: str,
) -> FormalTradeAttribution:
    """构造一条正式归属（纯验证 + 构造，无任何持久化，确定性）。

    验证顺序：
    1. 决策见证独立验证（防伪造）
    2. 交易记录验证（形状 / 状态 / 作废 / 既有 thesis 引用）
    3. 证券身份严格绑定（trade.code == decision.security_code）
    4. 决策 thesis 引用与交易既有引用交叉检查
    5. 构造不可变记录并通过严格 from_dict（统一执行格式、哈希与时域语义
       验证——时域来源：决策提交必须不晚于交易创建 / 执行）

    ``attribution_id`` / ``created_at`` 必须显式提供（调用方如需 UUID，
    显式调用 ``new_attribution_id()``）。构造函数内部不读时钟、不生成
    身份，保证同输入 → 同记录 → 同哈希。
    """
    if not isinstance(attribution_id, str) or not _ATTRIBUTION_ID_RE.fullmatch(
        attribution_id
    ):
        raise AttributionValidationError("attribution_id：必填且格式必须为 trade_attribution_<32 hex>")
    if not is_canonical_utc_timestamp(created_at):
        raise AttributionValidationError("created_at：必填且必须是 canonical UTC 时间戳")

    decision_anchor = verify_frozen_decision_witness(decision)
    trade_anchor = verify_trade_record(trade)

    # 证券身份：严格精确匹配，无别名、无名称匹配
    if trade["code"] != decision["security_code"]:
        raise AttributionValidationError(
            "证券身份不一致：trade.code 与 decision.security_code 必须精确匹配"
        )

    # 决策 thesis 锚 与 交易既有 thesis 引用交叉检查
    if trade_anchor["thesis_id"] is not None:
        if (
            trade_anchor["thesis_id"] != decision_anchor["thesis_id"]
            or trade_anchor["thesis_revision"] != decision_anchor["thesis_revision"]
        ):
            raise AttributionValidationError(
                "thesis 引用冲突：交易既有 thesis 引用必须与决策完全一致"
            )

    # 时域来源统一由 from_dict 内的记录语义权威（_validate_record_semantics）
    # 强制执行（创建路径与序列化路径共用同一权威）。

    # review_by 仅保留为证据，不参与任何有效性/失效判断（非有效性引擎）
    record: dict[str, Any] = {
        "attribution_id": attribution_id or new_attribution_id(),
        "trade_id": trade_anchor["trade_id"],
        "decision_id": decision_anchor["decision_id"],
        "decision_snapshot_hash": decision_anchor["decision_snapshot_hash"],
        "security_code": decision_anchor["security_code"],
        "strategy": decision_anchor["strategy"],
        "campaign_id": decision_anchor["campaign_id"],
        "thesis_id": decision_anchor["thesis_id"],
        "thesis_revision": decision_anchor["thesis_revision"],
        "decision_committed_at": decision_anchor["decision_committed_at"],
        "decision_review_by": decision_anchor["decision_review_by"],
        "decision_next_best_action": decision_anchor["decision_next_best_action"],
        "trade_operation": trade_anchor["trade_operation"],
        "trade_execution_status": trade_anchor["trade_execution_status"],
        "trade_executed_at": trade_anchor["trade_executed_at"],
        "trade_created_at": trade_anchor["trade_created_at"],
        "created_at": created_at,
        "schema_version": SCHEMA_VERSION,
    }
    record["attribution_hash"] = compute_attribution_hash(record)
    return from_dict(record)


# ---------------------------------------------------------------------------
# 严格序列化
# ---------------------------------------------------------------------------


def from_dict(record: Mapping[str, Any]) -> FormalTradeAttribution:
    """严格反序列化：精确字段集、精确类型、canonical 时间戳、schema 版本、
    哈希匹配。任何不符 fail closed，不做静默归一化 / 转换 / 时区猜测。
    """
    if not isinstance(record, Mapping):
        raise AttributionValidationError("record：必须是 Mapping")
    keys = set(record)
    if keys != set(_ATTRIBUTION_FIELDS):
        raise AttributionValidationError(
            f"record：字段集必须精确为 {sorted(_ATTRIBUTION_FIELDS)}"
        )

    if record["schema_version"] != SCHEMA_VERSION:
        raise AttributionSchemaVersionError(
            f"record：schema_version 必须为 {SCHEMA_VERSION}"
        )

    if not isinstance(record["attribution_id"], str) or not _ATTRIBUTION_ID_RE.fullmatch(
        record["attribution_id"]
    ):
        raise AttributionValidationError("record：attribution_id 格式不合法")
    if not isinstance(record["trade_id"], str) or not _TRADE_ID_RE.fullmatch(
        record["trade_id"]
    ):
        raise AttributionValidationError("record：trade_id 格式不合法")
    if not isinstance(record["decision_id"], str) or not _DECISION_ID_RE.fullmatch(
        record["decision_id"]
    ):
        raise AttributionValidationError("record：decision_id 格式不合法")
    if not isinstance(record["decision_snapshot_hash"], str) or not _SNAPSHOT_HASH_RE.fullmatch(
        record["decision_snapshot_hash"]
    ):
        raise AttributionValidationError("record：decision_snapshot_hash 格式不合法")
    if not isinstance(record["security_code"], str) or not _SECURITY_CODE_RE.fullmatch(
        record["security_code"]
    ):
        raise AttributionValidationError("record：security_code 格式不合法")
    if record["strategy"] not in STRATEGIES:
        raise AttributionValidationError("record：strategy 不合法")
    if not isinstance(record["campaign_id"], str) or not _CAMPAIGN_ID_RE.fullmatch(
        record["campaign_id"]
    ):
        raise AttributionValidationError("record：campaign_id 格式不合法")
    if not isinstance(record["thesis_id"], str) or not _THESIS_ID_RE.fullmatch(
        record["thesis_id"]
    ):
        raise AttributionValidationError("record：thesis_id 格式不合法")
    if (
        not isinstance(record["thesis_revision"], int)
        or isinstance(record["thesis_revision"], bool)
        or record["thesis_revision"] < 1
    ):
        raise AttributionValidationError("record：thesis_revision 必须为正整数")

    for field in (
        "decision_committed_at",
        "decision_review_by",
        "trade_created_at",
        "created_at",
    ):
        if not is_canonical_utc_timestamp(record[field]):
            raise AttributionValidationError(
                f"record：{field} 必须是 canonical UTC 时间戳"
            )

    executed_at = record["trade_executed_at"]
    status = record["trade_execution_status"]
    if status not in TRADE_EXECUTION_STATUSES:
        raise AttributionValidationError("record：trade_execution_status 不合法")
    if status in ("full", "partial"):
        if not is_canonical_utc_timestamp(executed_at):
            raise AttributionValidationError(
                "record：full/partial 状态要求 trade_executed_at 为 canonical UTC"
            )
    elif executed_at is not None:
        raise AttributionValidationError(
            "record：not_executed 状态要求 trade_executed_at 为 None"
        )
    if record["trade_operation"] not in TRADE_OPERATIONS:
        raise AttributionValidationError("record：trade_operation 不合法")
    if record["decision_next_best_action"] not in NEXT_BEST_ACTIONS:
        raise AttributionValidationError("record：decision_next_best_action 不合法")

    if not isinstance(record["attribution_hash"], str) or not _SNAPSHOT_HASH_RE.fullmatch(
        record["attribution_hash"]
    ):
        raise AttributionValidationError("record：attribution_hash 格式不合法")
    if record["attribution_hash"] != compute_attribution_hash(record):
        raise AttributionValidationError("record：attribution_hash 与内容不匹配")

    # 记录语义权威：时域来源自洽（创建路径与序列化路径共用）
    _validate_record_semantics(record)

    return FormalTradeAttribution(**record)


# ---------------------------------------------------------------------------
# 集合验证与投影（纯函数，输入顺序不影响结果）
# ---------------------------------------------------------------------------


def _records_to_dicts(records: Iterable[Any]) -> list[dict[str, Any]]:
    dicts: list[dict[str, Any]] = []
    for record in records:
        if isinstance(record, FormalTradeAttribution):
            # 不信任 dataclass 类型本身：实例与 Mapping 走同一严格验证路径
            dicts.append(from_dict(record.to_dict()).to_dict())
        elif isinstance(record, Mapping):
            dicts.append(from_dict(record).to_dict())
        else:
            raise AttributionValidationError(
                "集合元素必须是 FormalTradeAttribution 或 Mapping"
            )
    return dicts


def validate_attribution_set(records: Iterable[Any]) -> list[dict[str, Any]]:
    """验证归属集合并返回确定性归一化集合（唯一、有序）。

    拒绝：
    - 任一条记录无效（from_dict 级严格验证失败，含时域语义与时序篡改）
    - 同 attribution_id 但内容冲突
    - 同 trade_id 存在多条不同归属（one trade → one decision）
    - 同 decision_id 的归属记录决策锚字段不一致（DECISION_ANCHOR_FIELDS 全量）

    完全一致的重复记录去重为一条逻辑归属。

    返回：唯一记录按 (created_at ASC, attribution_id ASC) 排序，
    与输入顺序和重复次数无关。
    """
    dicts = _records_to_dicts(records)

    by_id: dict[str, dict[str, Any]] = {}
    for record in dicts:
        attribution_id = record["attribution_id"]
        if attribution_id in by_id and by_id[attribution_id] != record:
            raise AttributionConflictError(
                f"attribution_id {attribution_id} 内容冲突"
            )
        by_id[attribution_id] = record

    by_trade: dict[str, dict[str, Any]] = {}
    for record in dicts:
        trade_id = record["trade_id"]
        if trade_id in by_trade and by_trade[trade_id] != record:
            raise AttributionConflictError(
                f"trade_id {trade_id} 不得归属多个正式决策"
            )
        by_trade[trade_id] = record

    by_decision: dict[str, dict[str, Any]] = {}
    for record in dicts:
        decision_id = record["decision_id"]
        if decision_id in by_decision:
            prev = by_decision[decision_id]
            for field in DECISION_ANCHOR_FIELDS:
                if prev[field] != record[field]:
                    raise AttributionConflictError(
                        f"decision_id {decision_id} 的归属记录决策锚字段不一致：{field}"
                    )
        by_decision[decision_id] = record

    # 确定性归一化集合：同 attribution_id 的完全一致重复 → 一条逻辑归属；
    # 输出按 (created_at ASC, attribution_id ASC) 排序，与输入顺序无关
    return _sorted_by_provenance(list(by_id.values()))


def _sorted_by_provenance(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(records, key=lambda r: (r["created_at"], r["attribution_id"]))


def attributions_for_decision(
    decision_id: str, records: Iterable[Any]
) -> list[dict[str, Any]]:
    """投影：某个正式决策的全部归属（one decision → many trades）。

    先做中央集合验证，再过滤；确定性排序（created_at ASC，attribution_id ASC）。
    """
    validated = validate_attribution_set(records)
    return _sorted_by_provenance(
        [r for r in validated if r["decision_id"] == decision_id]
    )


def attribution_for_trade(
    trade_id: str, records: Iterable[Any]
) -> list[dict[str, Any]]:
    """投影：某条交易的归属（v0.1 契约下至多一条）。

    先做中央集合验证，再过滤；确定性排序。
    """
    validated = validate_attribution_set(records)
    return _sorted_by_provenance([r for r in validated if r["trade_id"] == trade_id])
