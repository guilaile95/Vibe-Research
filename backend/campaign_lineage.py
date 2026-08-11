"""Campaign Re-entry Lineage Domain Core v0.1 —— 纯确定性 domain contract。

为 ``Campaign → RE_ENTRY → Campaign`` 建立不可变、可验证、可投影的 lineage
契约，**不修改任何现有 Campaign 持久化/服务/路由**（campaign_store /
campaign_service / campaign_router 保持原样）。

P0-CL1 冻结的语义（§4 North Star 规则）：
- Full Exit 后旧 Campaign 永久 CLOSED，重新进入必须创建新 Campaign；
- RE_ENTRY 是历史/溯源关联，不是 Campaign identity 复用；
- 旧 Campaign 的 Strategy 永不因 re-entry 而改变（SHORT→MEDIUM 只能建模为
  新 Campaign + 可选 lineage，绝不是父 Campaign 的更新）。

本模块特性：
- 纯函数、零 I/O（不读 SQLite / 文件 / env / 时钟 / 网络 / AI）；
- 不 import campaign_store/service/router（本地持有冻结枚举作为契约复制）；
- 所有时间都是显式输入，纯校验不做当前时间推断；
- 记录不可变（frozen dataclass，无 setter）；修正=未来独立策略下的新记录；
- lineage_id 由显式创建 helper 生成（可注入），validation/projection 保持
  确定性；lineage_hash 绑定全部受保护语义字段。

FUTURE / NOT AUTHORIZED（本 slice 不实现）：持久化表、API 路由、Campaign
DB schema 变更（可能需 v0.2）、自动创建子 Campaign、自动关闭父 Campaign。
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping

SCHEMA_VERSION = "campaign_lineage.v0.1"

# ---- 冻结枚举（契约复制自 campaign_store，纯模块不依赖 store）----
STRATEGIES = ("SHORT", "SWING", "MEDIUM")
STATUSES = (
    "DRAFT", "RESEARCHING", "PRE-ENTRY", "ACTIVE", "REDUCING",
    "CLOSED", "REJECTED", "EXPIRED",
)
# v0.1 唯一 relation type（不预建 MERGE/SPLIT/ROLL_OVER/CLONE/STRATEGY_CHANGE）
RELATION_RE_ENTRY = "RE_ENTRY"
RELATION_TYPES = (RELATION_RE_ENTRY,)

# 父 Campaign 允许的终态（RE_ENTRY = 已完成仓位退出的新 Campaign）
PARENT_ALLOWED_STATUSES = ("CLOSED",)
# 子 Campaign 允许的早阶段（lineage 建立时）
CHILD_ALLOWED_STATUSES = ("DRAFT", "RESEARCHING", "PRE-ENTRY")

_CAMPAIGN_ID_RE = re.compile(r"^campaign_[0-9a-f]{32}$")
_SECURITY_CODE_RE = re.compile(r"^\d{6}$")
_LINEAGE_ID_RE = re.compile(r"^lineage_[0-9a-f]{32}$")
_TRANSITION_ID_RE = re.compile(r"^campaign_transition_[0-9a-f]{32}$")
_REASON_MAX_LEN = 200

# Campaign 生命周期 transition graph（契约复制自 campaign_store 冻结 graph；
# 纯模块不依赖 store；parity 测试对照权威源检测漂移）
TRANSITION_GRAPH: dict[str, tuple[str, ...]] = {
    "DRAFT": ("RESEARCHING", "REJECTED", "EXPIRED"),
    "RESEARCHING": ("PRE-ENTRY", "REJECTED", "EXPIRED"),
    "PRE-ENTRY": ("ACTIVE", "REJECTED", "EXPIRED"),
    "ACTIVE": ("REDUCING", "CLOSED"),
    "REDUCING": ("CLOSED",),
    "CLOSED": (),
    "REJECTED": (),
    "EXPIRED": (),
}

# 受保护语义字段：任一改变 → lineage_hash 必须改变。
# lineage_id / created_at 有意排除在 hash 之外（审计/记录元数据，非语义）。
_HASH_FIELDS = (
    "relation_type",
    "parent_campaign_id",
    "child_campaign_id",
    "security_code",
    "parent_strategy",
    "child_strategy",
    "parent_closed_at",
    "child_created_at",
    "reason",
    "schema_version",
)

_UTC_ISO_FORMATS = ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z")


class CampaignLineageError(Exception):
    """Campaign Re-entry Lineage 领域异常基类。"""


class LineageValidationError(CampaignLineageError):
    """输入非法 / 契约违反（fail closed）。"""


class LineageIntegrityError(CampaignLineageError):
    """链/记录之间的一致性违反（环、多父、hash 漂移等）。"""


# ---------------------------------------------------------------------------
# 时间：canonical UTC，显式输入
# ---------------------------------------------------------------------------

def _parse_utc(value: str) -> datetime:
    """解析 canonical UTC ISO 8601（必须带时区；归一化为 UTC）。不可解析 → fail closed。"""
    if not isinstance(value, str) or not value.strip():
        raise LineageValidationError(f"时间必须是带时区的 ISO 8601 字符串，got {value!r}")
    text = value.strip()
    for fmt in _UTC_ISO_FORMATS:
        try:
            dt = datetime.strptime(text, fmt)
            break
        except ValueError:
            continue
    else:
        raise LineageValidationError(f"非法 UTC 时间戳: {text!r}")
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise LineageValidationError(f"时间戳必须带时区（不允许 naive）: {text!r}")
    return dt.astimezone(timezone.utc)


def _canonical_utc(value: str) -> str:
    """归一化为 canonical UTC 微秒形式（`YYYY-MM-DDTHH:MM:SS.ffffffZ`）。

    对齐 Campaign Core 的 ``_TIMESTAMP_RE``（``\\.[0-9]{6}Z``）：保留源 instant
    的微秒精度，不截断到毫秒。
    """
    return _parse_utc(value).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"


def _is_canonical_utc(value: str) -> bool:
    """value 是否已是 canonical UTC 微秒表示（拒绝非 canonical 文本后静默归一化）。"""
    if not isinstance(value, str):
        return False
    try:
        return _canonical_utc(value) == value
    except LineageValidationError:
        return False


# ---------------------------------------------------------------------------
# Campaign 快照输入校验（minimal Mapping，不定义竞争 Campaign 类）
# ---------------------------------------------------------------------------

def validate_campaign_snapshot(campaign: Mapping[str, Any]) -> None:
    """校验 lineage 所需的 Campaign 快照字段（不复制 Campaign domain）。

    要求字段：campaign_id / security_code / strategy / status / created_at。
    """
    if not isinstance(campaign, Mapping):
        raise LineageValidationError("campaign 必须是 Mapping")
    campaign_id = campaign.get("campaign_id")
    security_code = campaign.get("security_code")
    strategy = campaign.get("strategy")
    status = campaign.get("status")
    created_at = campaign.get("created_at")
    if not isinstance(campaign_id, str) or not _CAMPAIGN_ID_RE.fullmatch(campaign_id):
        raise LineageValidationError(f"非法 campaign_id: {campaign_id!r}")
    if not isinstance(security_code, str) or not _SECURITY_CODE_RE.fullmatch(security_code):
        raise LineageValidationError(f"非法 security_code（需 6 位数字）: {security_code!r}")
    if strategy not in STRATEGIES:
        raise LineageValidationError(f"strategy 必须是 {STRATEGIES} 之一，got {strategy!r}")
    if status not in STATUSES:
        raise LineageValidationError(f"status 必须是 {STATUSES} 之一，got {status!r}")
    _canonical_utc(created_at)


def _validate_campaign_id(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not _CAMPAIGN_ID_RE.fullmatch(value):
        raise LineageValidationError(f"{field_name} 必须是 campaign_<32hex>，got {value!r}")
    return value


def _validate_strategy(value: Any, field_name: str) -> str:
    if value not in STRATEGIES:
        raise LineageValidationError(f"{field_name} 必须是 {STRATEGIES} 之一，got {value!r}")
    return value


def _validate_reason(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LineageValidationError("reason 必须是非空字符串（无 AI 默认、无 silent 'reentry' fallback）")
    reason = value.strip()
    if len(reason) > _REASON_MAX_LEN:
        raise LineageValidationError(f"reason 长度超过 {_REASON_MAX_LEN}")
    return reason


# ---------------------------------------------------------------------------
# Lineage 记录（不可变 value object）
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CampaignLineageRecord:
    """不可变 canonical lineage 记录。

    lineage_hash 绑定全部受保护语义字段（_HASH_FIELDS）；lineage_id / created_at
    不参与 hash。任何语义字段改变 → hash 漂移 → 校验失败（fail closed）。
    """

    lineage_id: str
    relation_type: str
    parent_campaign_id: str
    child_campaign_id: str
    security_code: str
    parent_strategy: str
    child_strategy: str
    parent_closed_at: str
    child_created_at: str
    reason: str
    created_at: str
    schema_version: str = SCHEMA_VERSION
    lineage_hash: str = field(default="", compare=True)

    # ---- to/from dict ----

    def to_dict(self) -> dict:
        return {
            "lineage_id": self.lineage_id,
            "relation_type": self.relation_type,
            "parent_campaign_id": self.parent_campaign_id,
            "child_campaign_id": self.child_campaign_id,
            "security_code": self.security_code,
            "parent_strategy": self.parent_strategy,
            "child_strategy": self.child_strategy,
            "parent_closed_at": self.parent_closed_at,
            "child_created_at": self.child_created_at,
            "reason": self.reason,
            "created_at": self.created_at,
            "schema_version": self.schema_version,
            "lineage_hash": self.lineage_hash,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CampaignLineageRecord":
        """反序列化（严格）：未知/缺字段、schema 漂移、类型不符、非 canonical
        时间、hash 漂移 → fail closed。不做任何 silent 类型归一化。"""
        if not isinstance(data, Mapping):
            raise LineageValidationError("lineage 记录必须是 Mapping")
        allowed = _RECORD_FIELDS
        unknown = set(data) - allowed
        if unknown:
            raise LineageValidationError(f"lineage 记录含未知字段: {sorted(unknown)}")
        missing = allowed - set(data)
        if missing:
            raise LineageValidationError(f"lineage 记录缺字段: {sorted(missing)}")
        if data.get("schema_version") != SCHEMA_VERSION:
            raise LineageValidationError(
                f"schema_version 漂移: got {data.get('schema_version')!r}, expect {SCHEMA_VERSION}"
            )
        # P1-D：先要求精确类型（全部文本字段必须已是 str），再要求 canonical UTC 时间
        for field_name in _TEXT_FIELDS:
            value = data[field_name]
            if not isinstance(value, str):
                raise LineageValidationError(
                    f"lineage 记录 {field_name} 必须是 str，got {type(value).__name__}（拒绝类型归一化）"
                )
        for field_name in _CANONICAL_UTC_FIELDS:
            if not _is_canonical_utc(data[field_name]):
                raise LineageValidationError(
                    f"lineage 记录 {field_name} 必须是 canonical UTC 微秒形式（拒绝非 canonical 文本）"
                )
        record = cls(
            lineage_id=data["lineage_id"],
            relation_type=data["relation_type"],
            parent_campaign_id=data["parent_campaign_id"],
            child_campaign_id=data["child_campaign_id"],
            security_code=data["security_code"],
            parent_strategy=data["parent_strategy"],
            child_strategy=data["child_strategy"],
            parent_closed_at=data["parent_closed_at"],
            child_created_at=data["child_created_at"],
            reason=data["reason"],
            created_at=data["created_at"],
            schema_version=data["schema_version"],
            lineage_hash=data["lineage_hash"],
        )
        # 先验证语义合法性，再验证 hash（防漂移）
        _validate_record_semantics(record)
        expected = compute_lineage_hash(
            relation_type=record.relation_type,
            parent_campaign_id=record.parent_campaign_id,
            child_campaign_id=record.child_campaign_id,
            security_code=record.security_code,
            parent_strategy=record.parent_strategy,
            child_strategy=record.child_strategy,
            parent_closed_at=record.parent_closed_at,
            child_created_at=record.child_created_at,
            reason=record.reason,
            schema_version=record.schema_version,
        )
        if expected != record.lineage_hash:
            raise LineageIntegrityError("lineage_hash 漂移（受保护语义字段与 hash 不一致）")
        return record


_RECORD_FIELDS = frozenset(CampaignLineageRecord.__dataclass_fields__)

# P1-D：from_dict 严格解码所需的文本字段 / canonical UTC 时间字段
_TEXT_FIELDS = (
    "lineage_id", "relation_type", "parent_campaign_id", "child_campaign_id",
    "security_code", "parent_strategy", "child_strategy", "parent_closed_at",
    "child_created_at", "reason", "created_at", "schema_version", "lineage_hash",
)
_CANONICAL_UTC_FIELDS = ("parent_closed_at", "child_created_at", "created_at")


# ---------------------------------------------------------------------------
# Hash（确定性 SHA-256 over protected semantics）
# ---------------------------------------------------------------------------

def compute_lineage_hash(
    *,
    relation_type: str,
    parent_campaign_id: str,
    child_campaign_id: str,
    security_code: str,
    parent_strategy: str,
    child_strategy: str,
    parent_closed_at: str,
    child_created_at: str,
    reason: str,
    schema_version: str,
) -> str:
    """确定性 canonical SHA-256（bind 全部受保护语义字段）。

    文档：lineage_id 与 created_at **不**参与 hash（审计元数据）；任何受保护
    语义字段改变都会改变 hash。
    """
    canonical = json.dumps(
        {
            "relation_type": relation_type,
            "parent_campaign_id": parent_campaign_id,
            "child_campaign_id": child_campaign_id,
            "security_code": security_code,
            "parent_strategy": parent_strategy,
            "child_strategy": child_strategy,
            "parent_closed_at": _canonical_utc(parent_closed_at),
            "child_created_at": _canonical_utc(child_created_at),
            "reason": reason,
            "schema_version": schema_version,
        },
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# 语义校验（纯函数，确定性）
# ---------------------------------------------------------------------------

def _validate_record_semantics(record: CampaignLineageRecord) -> None:
    if record.relation_type not in RELATION_TYPES:
        raise LineageValidationError(
            f"v0.1 仅支持 relation {RELATION_TYPES}，got {record.relation_type!r}"
        )
    _validate_campaign_id(record.parent_campaign_id, "parent_campaign_id")
    _validate_campaign_id(record.child_campaign_id, "child_campaign_id")
    if record.parent_campaign_id == record.child_campaign_id:
        raise LineageValidationError("parent 与 child 必须是不同 Campaign（禁止身份复用）")
    if not isinstance(record.security_code, str) or not _SECURITY_CODE_RE.fullmatch(record.security_code):
        raise LineageValidationError(f"非法 security_code: {record.security_code!r}")
    _validate_strategy(record.parent_strategy, "parent_strategy")
    _validate_strategy(record.child_strategy, "child_strategy")
    _validate_reason(record.reason)
    _canonical_utc(record.created_at)  # created_at 仅需合法 UTC（不在 hash 内）
    parent_close = _parse_utc(record.parent_closed_at)
    child_create = _parse_utc(record.child_created_at)
    # 严格时间序：parent_closed_at < child_created_at
    if parent_close >= child_create:
        raise LineageValidationError("parent_closed_at 必须早于 child_created_at（时间倒转）")
    if not _LINEAGE_ID_RE.fullmatch(record.lineage_id):
        raise LineageValidationError(f"非法 lineage_id: {record.lineage_id!r}")


# ---------------------------------------------------------------------------
# 创建 helper（唯一允许生成 UUID 的入口；其余路径保持确定性）
# ---------------------------------------------------------------------------

def new_lineage_id() -> str:
    """生成 lineage_<uuid4hex>（仅在显式创建时调用）。"""
    return f"lineage_{uuid.uuid4().hex}"


def build_lineage_record(
    *,
    parent_campaign: Mapping[str, Any],
    child_campaign: Mapping[str, Any],
    parent_closed_at: str,
    reason: str,
    created_at: str,
    relation_type: str = RELATION_RE_ENTRY,
    lineage_id: str | None = None,
    parent_transitions: list[Mapping[str, Any]] | None = None,
) -> CampaignLineageRecord:
    """构建一个 immutable lineage 记录（纯函数；id/时间显式传入或注入）。

    - 校验 parent：status 必须 CLOSED；
    - 校验 child：status 必须 ∈ {DRAFT, RESEARCHING, PRE-ENTRY}；
    - security_code 三方（parent/child/record）精确 6 位一致；
    - 时间序 parent_closed_at < child_created_at（严格）；
    - Strategy 各自独立存储，互不修改（父策略永不因 re-entry 改变）。

    ``parent_closed_at`` 两种来源（二选一，均显式）：
    1. 提供 ``parent_transitions``（父 Campaign 的完整 transition 历史）→ close
       锚点必须由 ``derive_parent_closed_at`` 推导并与之相等，绝不信任任意调用方
       提供的 close 时间戳；
    2. 不提供 ``parent_transitions`` → 使用显式 ``parent_closed_at``（调用方无
       历史可用时的最小路径；文档已标注该区分）。
    """
    validate_campaign_snapshot(parent_campaign)
    validate_campaign_snapshot(child_campaign)
    if relation_type not in RELATION_TYPES:
        raise LineageValidationError(f"v0.1 仅支持 relation {RELATION_TYPES}，got {relation_type!r}")
    parent_id = _validate_campaign_id(parent_campaign["campaign_id"], "parent_campaign_id")
    child_id = _validate_campaign_id(child_campaign["campaign_id"], "child_campaign_id")
    if parent_id == child_id:
        raise LineageValidationError("parent 与 child 必须是不同 Campaign（禁止身份复用）")
    if parent_campaign["status"] not in PARENT_ALLOWED_STATUSES:
        raise LineageValidationError(
            f"RE_ENTRY 要求 parent CLOSED，got {parent_campaign['status']!r}"
        )
    if child_campaign["status"] not in CHILD_ALLOWED_STATUSES:
        raise LineageValidationError(
            f"v0.1 child 仅允许早阶段 {CHILD_ALLOWED_STATUSES}，got {child_campaign['status']!r}"
        )
    security = parent_campaign["security_code"]
    if child_campaign["security_code"] != security:
        raise LineageValidationError(
            f"RE_ENTRY 要求同 security（精确 6 位）：parent={security} vs child={child_campaign['security_code']}"
        )
    parent_strategy = _validate_strategy(parent_campaign["strategy"], "parent_strategy")
    child_strategy = _validate_strategy(child_campaign["strategy"], "child_strategy")
    reason_ok = _validate_reason(reason)
    # close 时间：提供完整 transition 历史时必须由历史推导（绑定 parent 身份），
    # 且与调用方提供的 close 时间戳必须一致（不信任未经验证的时间）。
    if parent_transitions is not None:
        derived_close = derive_parent_closed_at(parent_id, parent_transitions)
        if derived_close is None:
            raise LineageValidationError(
                "parent transition 历史无法推导合法 CLOSED 锚点（fail closed）"
            )
        if _canonical_utc(parent_closed_at) != derived_close:
            raise LineageValidationError(
                "parent_closed_at 与 transition 历史推导的 CLOSED 锚点不一致（拒绝未验证时间）"
            )
        parent_close = derived_close
    else:
        parent_close = _canonical_utc(parent_closed_at)
    child_create = _canonical_utc(child_campaign["created_at"])
    if _parse_utc(parent_close) >= _parse_utc(child_create):
        raise LineageValidationError("parent_closed_at 必须早于 child_created_at（时间倒转）")
    created_ok = _canonical_utc(created_at)
    lineage_id_ok = lineage_id if lineage_id is not None else new_lineage_id()
    if not _LINEAGE_ID_RE.fullmatch(lineage_id_ok):
        raise LineageValidationError(f"非法 lineage_id: {lineage_id_ok!r}")
    record_hash = compute_lineage_hash(
        relation_type=relation_type,
        parent_campaign_id=parent_id,
        child_campaign_id=child_id,
        security_code=security,
        parent_strategy=parent_strategy,
        child_strategy=child_strategy,
        parent_closed_at=parent_close,
        child_created_at=child_create,
        reason=reason_ok,
        schema_version=SCHEMA_VERSION,
    )
    return CampaignLineageRecord(
        lineage_id=lineage_id_ok,
        relation_type=relation_type,
        parent_campaign_id=parent_id,
        child_campaign_id=child_id,
        security_code=security,
        parent_strategy=parent_strategy,
        child_strategy=child_strategy,
        parent_closed_at=parent_close,
        child_created_at=child_create,
        reason=reason_ok,
        created_at=created_ok,
        schema_version=SCHEMA_VERSION,
        lineage_hash=record_hash,
    )


# ---------------------------------------------------------------------------
# 父 CLOSED 时间推导（来自 transition 历史，纯函数）
# ---------------------------------------------------------------------------

def derive_parent_closed_at(
    parent_campaign_id: str,
    transitions: list[Mapping[str, Any]],
) -> str | None:
    """从给定 Campaign 自身的 transition 历史推导 CLOSED 时间锚点（显式绑定身份）。

    - 每条 transition 必须：``campaign_id == parent_campaign_id``（不接受其它
      Campaign 的历史）、``transition_id`` 为 canonical 形状且集合内唯一；
    - 排序确定性：``(transitioned_at, transition_id)`` 升序，**不依赖输入列表顺序**；
    - 返回使状态最终到达 CLOSED 的最后一条 transition 的 transitioned_at
      （canonical UTC 微秒）；
    - 任何 transition 非法 / 不是合法推进 / 最终态不是 CLOSED → None（fail
      closed：不信任任意调用方提供的 closed 时间戳）；
    - 不修改输入 transition 列表。
    """
    _validate_campaign_id(parent_campaign_id, "parent_campaign_id")
    if not isinstance(transitions, list):
        return None
    entries: list[tuple[datetime, str, str, str, str]] = []  # (time, tid, from, to, at)
    seen_ids: set[str] = set()
    for t in transitions:
        if not isinstance(t, Mapping):
            return None
        try:
            tid = t["transition_id"]
            cid = t["campaign_id"]
            from_status = t["from_status"]
            to_status = t["to_status"]
            transitioned = t["transitioned_at"]
        except (KeyError, TypeError):
            return None
        if not isinstance(tid, str) or not _TRANSITION_ID_RE.fullmatch(tid):
            return None
        if tid in seen_ids:
            return None  # transition_id 重复 → 历史不合法
        seen_ids.add(tid)
        if cid != parent_campaign_id:
            return None  # 不是本 Campaign 的 transition
        if from_status not in STATUSES or to_status not in STATUSES:
            return None
        try:
            at = _canonical_utc(transitioned)
        except (TypeError, LineageValidationError):
            return None
        entries.append((_parse_utc(at), tid, from_status, to_status, at))
    if not entries:
        return None
    entries.sort(key=lambda pair: (pair[0], pair[1]))  # (transitioned_at, transition_id)
    current: str | None = None
    final_at: str | None = None
    for _, _tid, from_status, to_status, at in entries:
        if current is None:
            current = from_status
        if from_status != current:
            return None  # 非连续推进 → 历史不合法
        if to_status not in TRANSITION_GRAPH.get(current, ()):
            return None  # graph 不允许的边
        current = to_status
        if current == "CLOSED":
            final_at = at
    if current != "CLOSED" or final_at is None:
        return None
    return final_at


# ---------------------------------------------------------------------------
# 链校验 / 投影（全部确定性，输入顺序无关）
# ---------------------------------------------------------------------------

def validate_lineage_set(records: list[CampaignLineageRecord]) -> list[CampaignLineageRecord]:
    """校验一个 lineage 记录集合（纯函数，不修改输入）。

    拒绝：自环、重复冲突边、环、child 多父、security 跨链不一致、strategy 跨链
    不一致、campaign 创建/关闭时间冲突（R2-A/B）、campaign 创建前已关闭
    （R2-C，跨边生命周期倒转）、时间倒转、非法 ID、非法 Strategy、未知
    relation、hash 漂移。
    返回原顺序列表（验证通过时）；异常一律 LineageIntegrityError / LineageValidationError。
    """
    if not isinstance(records, list):
        raise LineageValidationError("records 必须是列表")
    # 1. 每条记录语义 + hash（from_dict 已覆盖，此处双保险）
    by_parent_child: dict[tuple[str, str], CampaignLineageRecord] = {}
    security_by_campaign: dict[str, str] = {}
    strategy_by_campaign: dict[str, str] = {}  # P1-A：一个 campaign_id 只能映射一个 Strategy
    created_at_by_campaign: dict[str, str] = {}  # R2-A：一个 campaign 只能有一个 child_created_at
    closed_at_by_campaign: dict[str, str] = {}   # R2-B：一个 campaign 的所有出边只能有一个 parent_closed_at
    for record in records:
        if not isinstance(record, CampaignLineageRecord):
            raise LineageValidationError("records 元素必须是 CampaignLineageRecord")
        _validate_record_semantics(record)
        expected = compute_lineage_hash(
            relation_type=record.relation_type,
            parent_campaign_id=record.parent_campaign_id,
            child_campaign_id=record.child_campaign_id,
            security_code=record.security_code,
            parent_strategy=record.parent_strategy,
            child_strategy=record.child_strategy,
            parent_closed_at=record.parent_closed_at,
            child_created_at=record.child_created_at,
            reason=record.reason,
            schema_version=record.schema_version,
        )
        if expected != record.lineage_hash:
            raise LineageIntegrityError(f"hash 漂移: {record.lineage_id}")
        if record.parent_campaign_id == record.child_campaign_id:
            raise LineageIntegrityError(f"自环: {record.lineage_id}")
        key = (record.parent_campaign_id, record.child_campaign_id)
        if key in by_parent_child:
            raise LineageIntegrityError(f"重复冲突边: {key}")
        by_parent_child[key] = record
        # security 跨链一致
        for cid, code in ((record.parent_campaign_id, record.security_code),
                          (record.child_campaign_id, record.security_code)):
            if cid in security_by_campaign and security_by_campaign[cid] != code:
                raise LineageIntegrityError(f"跨链 security 不一致: {cid}")
            security_by_campaign[cid] = code
        # P1-A：strategy 跨链一致（同一 campaign_id 在整条链中只能有一个 Strategy）
        for cid, strat in ((record.parent_campaign_id, record.parent_strategy),
                           (record.child_campaign_id, record.child_strategy)):
            if cid in strategy_by_campaign and strategy_by_campaign[cid] != strat:
                raise LineageIntegrityError(
                    f"跨链 strategy 不一致（campaign 只能有一个 Strategy）: {cid} "
                    f"{strategy_by_campaign[cid]} vs {strat}"
                )
            strategy_by_campaign[cid] = strat
        # R2-A：同一 campaign 作为 child 只能有一个创建时间（canonical 字符串精确比较，不降精度）
        if record.child_campaign_id in created_at_by_campaign and \
                created_at_by_campaign[record.child_campaign_id] != record.child_created_at:
            raise LineageIntegrityError(
                f"campaign {record.child_campaign_id} 创建时间冲突: "
                f"{created_at_by_campaign[record.child_campaign_id]} vs {record.child_created_at}"
            )
        created_at_by_campaign[record.child_campaign_id] = record.child_created_at
        # R2-B：同一 campaign 作为 parent 的所有出边只能有一个 CLOSED 锚点
        if record.parent_campaign_id in closed_at_by_campaign and \
                closed_at_by_campaign[record.parent_campaign_id] != record.parent_closed_at:
            raise LineageIntegrityError(
                f"campaign {record.parent_campaign_id} 多个 CLOSED 时间: "
                f"{closed_at_by_campaign[record.parent_campaign_id]} vs {record.parent_closed_at}"
            )
        closed_at_by_campaign[record.parent_campaign_id] = record.parent_closed_at
    # 2. child 单父（至多一个直接 RE_ENTRY parent）
    child_parents: dict[str, str] = {}
    for record in records:
        cid = record.child_campaign_id
        if cid in child_parents and child_parents[cid] != record.parent_campaign_id:
            raise LineageIntegrityError(f"child 多父（v0.1 至多一个 RE_ENTRY parent）: {cid}")
        child_parents[cid] = record.parent_campaign_id
    # 3. R2-C：同一 campaign 既作 child 又作 parent → 自身生命周期必须严格有序
    #    （campaign.created_at < campaign.closed_at）；否则就是「创建前已关闭」的
    #    不可能历史（例如 B created T3 却 closed T2）。
    for cid in created_at_by_campaign:
        if cid in closed_at_by_campaign:
            created = _parse_utc(created_at_by_campaign[cid])
            closed = _parse_utc(closed_at_by_campaign[cid])
            if created >= closed:
                raise LineageIntegrityError(
                    f"campaign {cid} 在创建前已关闭（created {created_at_by_campaign[cid]}"
                    f" >= closed {closed_at_by_campaign[cid]}）"
                )
    # 4. 时间序（每条 parent_close < child_create 已校验；链级时间倒转 = 成环）
    _assert_acyclic(records)
    return records


def _assert_acyclic(records: list[CampaignLineageRecord]) -> None:
    """确定性环检测（拓扑序；不依赖输入顺序）。"""
    children_of: dict[str, list[str]] = {}
    for record in records:
        children_of.setdefault(record.parent_campaign_id, []).append(record.child_campaign_id)
    visited: set[str] = set()
    stack: set[str] = set()

    def visit(node: str) -> None:
        if node in stack:
            raise LineageIntegrityError(f"环检测失败: {node}")
        if node in visited:
            return
        stack.add(node)
        for child in children_of.get(node, ()):
            visit(child)
        stack.discard(node)
        visited.add(node)

    for node in list(children_of):
        visit(node)


def ancestors(campaign_id: str, records: list[CampaignLineageRecord]) -> list[CampaignLineageRecord]:
    """确定性祖先投影：从给定 campaign 沿 RE_ENTRY 父链回溯，按时间序（旧→新）返回。

    P1-B：投影入口先 ``validate_lineage_set(records)`` —— 不投影未校验的 lineage
    （不依赖调用方记得先校验）。"""
    _validate_campaign_id(campaign_id, "campaign_id")
    validate_lineage_set(records)  # 入口预校验：multi-parent / hash 漂移 / 环 / 跨链不一致 → fail closed
    parent_of: dict[str, str] = {}
    for record in records:
        parent_of[record.child_campaign_id] = record.parent_campaign_id
    by_id: dict[str, CampaignLineageRecord] = {r.child_campaign_id: r for r in records}
    chain: list[CampaignLineageRecord] = []
    current = campaign_id
    seen: set[str] = set()
    while current in parent_of:
        if current in seen:
            raise LineageIntegrityError(f"祖先投影遇到环: {current}")
        seen.add(current)
        parent = parent_of[current]
        record = by_id.get(current)
        if record is None:
            break
        chain.append(record)
        current = parent
    # 拓扑：祖先链天然按 child 出现顺序；按 parent_closed_at 升序（旧→新）确定性排序
    chain.sort(key=lambda r: (_parse_utc(r.parent_closed_at), r.lineage_id))
    return chain


def descendants(campaign_id: str, records: list[CampaignLineageRecord]) -> list[CampaignLineageRecord]:
    """确定性后代投影：从给定 campaign 沿 RE_ENTRY 子链下行（无自动创建/无 transition）。

    P1-B：投影入口先 ``validate_lineage_set(records)`` —— 不投影未校验的 lineage。"""
    _validate_campaign_id(campaign_id, "campaign_id")
    validate_lineage_set(records)  # 入口预校验
    children_of: dict[str, list[CampaignLineageRecord]] = {}
    for record in records:
        children_of.setdefault(record.parent_campaign_id, []).append(record)
    out: list[CampaignLineageRecord] = []
    seen: set[str] = set()

    def walk(node: str) -> None:
        for record in children_of.get(node, ()):
            if record.child_campaign_id in seen:
                raise LineageIntegrityError(f"后代投影遇到环: {record.child_campaign_id}")
            seen.add(record.child_campaign_id)
            out.append(record)
            walk(record.child_campaign_id)

    walk(campaign_id)
    out.sort(key=lambda r: (_parse_utc(r.child_created_at), r.lineage_id))
    return out
