"""Decision Evidence Delta Projection Core v0.1（P0-EC1）。

回答 Frozen Decision 之后的第一个确定性事实问题：

> 系统到底获得了哪些"真正新的"证据？

本 core 只建立一个新的 deterministic authority——**Decision Evidence Temporal
Delta**——它区分：

    NEW_AFTER_DECISION / PREEXISTING_AT_DECISION / UNKNOWN_TEMPORAL_RELATION / OUT_OF_SCOPE

**核心铁律**（修复真实错误）：

    RETRIEVAL TIME != FACT / EVENT TIME

今天抓到两个月前已发生的公告，不能因为 ``retrieved_at = today`` 就被当成
decision 之后的新证据。只有 ``effective_at``（证据所描述事实在市场/业务语义上
何时成立/发生/生效）可以参与"是否发生在 decision boundary 之后"的判断。

- **纯 domain core，零 I/O**：无 DB / SQLite / filesystem / network / FastAPI /
  AI / scheduler / wall clock / provider / new persistence / new dataset。
- **不判断投资意义**：严格禁止输出 MATERIAL / CRITICAL / material_change_state /
  REVIEW_REQUIRED / BUY / SELL —— NEW EVIDENCE != MATERIAL EVIDENCE。
- **不读 Current Thesis / Thesis Delta / Frozen Decision DB**：``decision_boundary_at``
  由上游显式传入；WEAKENED/DISPROVEN/INVALIDATED 的解释属 Thesis authority。
- **不判断 Hard Risk / Data Health**：即使 evidence 内容看似严重，EC1 只判断
  时间与 identity 关系；provider outage / data stale 不是 NEW_AFTER_DECISION
  evidence（除非调用方传入具有明确 effective_at 的业务事实）。
- **Campaign 隔离**：v0.1 只支持 security / campaign 两种 scope；campaign-scoped
  evidence 严禁跨 Campaign 传播（即使 security_code 与 strategy 相同）。
- 复用仓库既有权威 idiom：canonical UTC（``YYYY-MM-DDTHH:MM:SS.ffffffZ``，
  6 位微秒 + Z）、STRATEGIES = (SHORT, SWING, MEDIUM)、campaign_id =
  ``campaign_<32 小写 hex>``、security_code = 6 位数字。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

SCHEMA_VERSION = "decision_evidence_delta.v0.1"

# ---- 时间关系分类（本 core 唯一 authority 输出）----
NEW_AFTER_DECISION = "NEW_AFTER_DECISION"
PREEXISTING_AT_DECISION = "PREEXISTING_AT_DECISION"
UNKNOWN_TEMPORAL_RELATION = "UNKNOWN_TEMPORAL_RELATION"
OUT_OF_SCOPE = "OUT_OF_SCOPE"

# scope kinds（v0.1 仅两种）
SCOPE_SECURITY = "security"
SCOPE_CAMPAIGN = "campaign"

# time semantics（最小区分，不建复杂 ontology）
TIME_SEMANTICS_AUTHORITATIVE = "AUTHORITATIVE_EFFECTIVE_TIME"
TIME_SEMANTICS_UNKNOWN = "UNKNOWN"

_CANONICAL_UTC_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$")
_CAMPAIGN_ID_RE = re.compile(r"^campaign_[0-9a-f]{32}$")
_SECURITY_CODE_RE = re.compile(r"^\d{6}$")
_STRATEGIES = ("SHORT", "SWING", "MEDIUM")
_EVIDENCE_ID_RE = re.compile(r"^[0-9a-f]{32}$")


class DecisionEvidenceDeltaError(Exception):
    """EC1 领域异常基类（fail closed）。"""


class EvidenceDeltaInputError(DecisionEvidenceDeltaError):
    """输入契约违反（schema corruption / malformed input，fail closed）。"""


def _require_nonempty_text(value: Any, field: str) -> str:
    if type(value) is not str or not value.strip() or value != value.strip():
        raise EvidenceDeltaInputError(f"{field} 必须是非空规范文本")
    return value


def _parse_utc(value: Any, field: str) -> datetime:
    """严格 canonical UTC（6 位微秒 + Z）；malformed → fail closed（非 UNKNOWN）。"""
    if type(value) is not str or _CANONICAL_UTC_RE.fullmatch(value) is None:
        raise EvidenceDeltaInputError(f"{field} 必须是 canonical UTC 时间戳")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise EvidenceDeltaInputError(
            f"{field} 不是真实 UTC 时间（如 2 月 30 日）") from exc


# ---------------------------------------------------------------------------
# 输入值对象（frozen；调用方显式传入，core 不读取任何 store）
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DecisionContext:
    """目标决策上下文（Security + Strategy + Campaign 决策单元）。"""

    security_code: str
    strategy: str
    campaign_id: str
    decision_id: str
    decision_boundary_at: str

    def __post_init__(self) -> None:
        _require_nonempty_text(self.security_code, "security_code")
        if _SECURITY_CODE_RE.fullmatch(self.security_code) is None:
            raise EvidenceDeltaInputError("security_code 必须是 6 位数字")
        if self.strategy not in _STRATEGIES:
            raise EvidenceDeltaInputError(
                f"strategy 必须是 {_STRATEGIES} 之一，got {self.strategy!r}")
        if _CAMPAIGN_ID_RE.fullmatch(self.campaign_id) is None:
            raise EvidenceDeltaInputError("campaign_id 必须是 campaign_<32 位小写 hex>")
        _require_nonempty_text(self.decision_id, "decision_id")
        # boundary 是 canonical UTC；malformed → fail closed
        _parse_utc(self.decision_boundary_at, "decision_boundary_at")


@dataclass(frozen=True)
class NormalizedEvidenceItem:
    """一条已规范化的证据（时间语义分离：effective_at 参与判断，retrieved_at 仅记录）。"""

    evidence_id: str
    scope_kind: str
    scope_id: str
    effective_at: str | None
    retrieved_at: str | None
    time_semantics: str
    authority_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        if _EVIDENCE_ID_RE.fullmatch(self.evidence_id) is None:
            raise EvidenceDeltaInputError("evidence_id 必须是 32 位小写 hex")
        if self.scope_kind not in (SCOPE_SECURITY, SCOPE_CAMPAIGN):
            raise EvidenceDeltaInputError(
                f"scope_kind 必须是 {SCOPE_SECURITY}/{SCOPE_CAMPAIGN}，got {self.scope_kind!r}")
        _require_nonempty_text(self.scope_id, "scope_id")
        if self.time_semantics not in (
                TIME_SEMANTICS_AUTHORITATIVE, TIME_SEMANTICS_UNKNOWN):
            raise EvidenceDeltaInputError(
                f"time_semantics 必须是 AUTHORITATIVE/UNKNOWN，got {self.time_semantics!r}")
        if self.time_semantics is TIME_SEMANTICS_AUTHORITATIVE:
            if self.effective_at is None:
                raise EvidenceDeltaInputError(
                    "AUTHORITATIVE_EFFECTIVE_TIME 必须提供 effective_at（fail closed，"
                    "不静默降级为 UNKNOWN）")
            _parse_utc(self.effective_at, "effective_at")
        else:  # UNKNOWN 语义
            if self.effective_at is not None:
                raise EvidenceDeltaInputError(
                    "UNKNOWN time_semantics 不得携带 effective_at")
        if self.retrieved_at is not None:
            _parse_utc(self.retrieved_at, "retrieved_at")
        if type(self.authority_refs) is not tuple or \
                any(type(r) is not str or not r.strip() for r in self.authority_refs):
            raise EvidenceDeltaInputError("authority_refs 必须是非空字符串元组")


# ---------------------------------------------------------------------------
# 输出值对象（frozen；deep isolated）
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DecisionEvidenceDelta:
    """Frozen Decision 之后的 evidence temporal delta（不含投资意义判断）。"""

    schema_version: str
    security_code: str
    strategy: str
    campaign_id: str
    decision_id: str
    decision_boundary_at: str
    new_evidence: tuple[str, ...]
    preexisting_evidence: tuple[str, ...]
    unknown_temporal_evidence: tuple[str, ...]
    out_of_scope_evidence: tuple[str, ...]
    has_new_evidence: bool
    temporal_coverage_complete: bool

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "security_code": self.security_code,
            "strategy": self.strategy,
            "campaign_id": self.campaign_id,
            "decision_id": self.decision_id,
            "decision_boundary_at": self.decision_boundary_at,
            "new_evidence": list(self.new_evidence),
            "preexisting_evidence": list(self.preexisting_evidence),
            "unknown_temporal_evidence": list(self.unknown_temporal_evidence),
            "out_of_scope_evidence": list(self.out_of_scope_evidence),
            "has_new_evidence": self.has_new_evidence,
            "temporal_coverage_complete": self.temporal_coverage_complete,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "DecisionEvidenceDelta":
        """严格反序列化（exact field set / exact types / 无未知字段）。"""
        if not isinstance(data, Mapping):
            raise EvidenceDeltaInputError("delta 必须是 Mapping")
        expected = set(cls.__dataclass_fields__)
        if set(data) != expected:
            missing = sorted(expected - set(data))
            extra = sorted(set(data) - expected)
            raise EvidenceDeltaInputError(
                f"delta 字段不匹配: missing={missing}, extra={extra}")
        if data["schema_version"] != SCHEMA_VERSION:
            raise EvidenceDeltaInputError(
                f"schema_version 漂移: {data['schema_version']!r}")
        for name in ("new_evidence", "preexisting_evidence",
                     "unknown_temporal_evidence", "out_of_scope_evidence"):
            values = data[name]
            if not isinstance(values, list) or \
                    any(type(v) is not str for v in values):
                raise EvidenceDeltaInputError(f"{name} 必须是字符串列表")
            if len(values) != len(set(values)):
                raise EvidenceDeltaInputError(f"{name} 不得重复")
        for name in ("has_new_evidence", "temporal_coverage_complete"):
            if type(data[name]) is not bool:
                raise EvidenceDeltaInputError(f"{name} 必须是 bool")
        return cls(
            schema_version=data["schema_version"],
            security_code=data["security_code"],
            strategy=data["strategy"],
            campaign_id=data["campaign_id"],
            decision_id=data["decision_id"],
            decision_boundary_at=data["decision_boundary_at"],
            new_evidence=tuple(data["new_evidence"]),
            preexisting_evidence=tuple(data["preexisting_evidence"]),
            unknown_temporal_evidence=tuple(data["unknown_temporal_evidence"]),
            out_of_scope_evidence=tuple(data["out_of_scope_evidence"]),
            has_new_evidence=data["has_new_evidence"],
            temporal_coverage_complete=data["temporal_coverage_complete"],
        )


# ---------------------------------------------------------------------------
# 核心评估（纯函数；确定性）
# ---------------------------------------------------------------------------

def _is_scope_valid(item: NormalizedEvidenceItem, ctx: DecisionContext) -> bool:
    """v0.1 scope 规则：security 匹配 security_code；campaign 匹配 campaign_id。"""
    if item.scope_kind is SCOPE_SECURITY:
        return item.scope_id == ctx.security_code
    if item.scope_kind is SCOPE_CAMPAIGN:
        return item.scope_id == ctx.campaign_id
    return False  # 未知 scope_kind 已在 __post_init__ 拒绝；防御


def classify_evidence_item(
    ctx: DecisionContext,
    item: NormalizedEvidenceItem,
) -> str:
    """单条证据的时间关系分类（纯函数）。

    只允许 effective_at 参与"是否发生在 decision boundary 之后"的判断；
    严禁 retrieved_at > boundary → NEW_AFTER_DECISION 自动成立。
    """
    if not _is_scope_valid(item, ctx):
        return OUT_OF_SCOPE
    if item.time_semantics is TIME_SEMANTICS_UNKNOWN:
        # 无有效 effective_at → 不用 retrieved_at 猜（UNKNOWN 是合法业务状态）
        return UNKNOWN_TEMPORAL_RELATION
    effective = _parse_utc(item.effective_at, "effective_at")
    boundary = _parse_utc(ctx.decision_boundary_at, "decision_boundary_at")
    return NEW_AFTER_DECISION if effective > boundary else PREEXISTING_AT_DECISION


def project_decision_evidence_delta(
    *,
    context: DecisionContext,
    evidence_items: tuple[NormalizedEvidenceItem, ...],
) -> DecisionEvidenceDelta:
    """对一份决策上下文的所有 scope-valid candidate evidence 生成 temporal delta。

    - 输入顺序不影响语义（确定性稳定排序：evidence_id）。
    - 输入零突变；输出 deep isolated（全部新 tuple/dict）。
    - duplicate evidence_id → fail closed。
    - temporal_coverage_complete = 所有 scope-valid candidate 都有可靠 effective_at
      可裁决；存在 UNKNOWN_TEMPORAL_RELATION → false（即使已发现 new evidence）。
    - has_new_evidence 只表示"至少存在一条 effective_at 晚于 boundary 的
      scope-valid evidence"，绝不是 material_change。
    """
    if not isinstance(context, DecisionContext):
        raise EvidenceDeltaInputError("context 必须是 DecisionContext")
    if type(evidence_items) is not tuple:
        raise EvidenceDeltaInputError("evidence_items 必须是元组")
    seen: set[str] = set()
    for item in evidence_items:
        if not isinstance(item, NormalizedEvidenceItem):
            raise EvidenceDeltaInputError(
                "evidence_items 元素必须是 NormalizedEvidenceItem")
        if item.evidence_id in seen:
            raise EvidenceDeltaInputError(
                f"duplicate evidence_id: {item.evidence_id!r}")
        seen.add(item.evidence_id)

    new_ids: list[str] = []
    preexisting_ids: list[str] = []
    unknown_ids: list[str] = []
    out_of_scope_ids: list[str] = []
    scope_valid_count = 0
    unknown_scope_valid = 0

    for item in evidence_items:
        classification = classify_evidence_item(context, item)
        if classification is OUT_OF_SCOPE:
            out_of_scope_ids.append(item.evidence_id)
            continue
        scope_valid_count += 1
        if classification is NEW_AFTER_DECISION:
            new_ids.append(item.evidence_id)
        elif classification is PREEXISTING_AT_DECISION:
            preexisting_ids.append(item.evidence_id)
        else:  # UNKNOWN_TEMPORAL_RELATION
            unknown_ids.append(item.evidence_id)
            unknown_scope_valid += 1

    # deterministic stable ordering（不赋予投资优先级）
    new_ids.sort()
    preexisting_ids.sort()
    unknown_ids.sort()
    out_of_scope_ids.sort()

    temporal_coverage_complete = unknown_scope_valid == 0

    return DecisionEvidenceDelta(
        schema_version=SCHEMA_VERSION,
        security_code=context.security_code,
        strategy=context.strategy,
        campaign_id=context.campaign_id,
        decision_id=context.decision_id,
        decision_boundary_at=context.decision_boundary_at,
        new_evidence=tuple(new_ids),
        preexisting_evidence=tuple(preexisting_ids),
        unknown_temporal_evidence=tuple(unknown_ids),
        out_of_scope_evidence=tuple(out_of_scope_ids),
        has_new_evidence=bool(new_ids),
        temporal_coverage_complete=temporal_coverage_complete,
    )
