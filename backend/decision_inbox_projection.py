"""持仓 Decision Inbox 纯域投影核心（P0-DI1）。

第一版只回答一个问题：

    给定一个确定的 ``Security + Strategy + Campaign`` 及其已规范化的
    Thesis / Decision / Risk / Data 状态，这个 Campaign 当前是否需要
    用户处理？为什么？

架构边界（HARD）：

- 纯 campaign 级 read-model projection；Decision Unit = Security + Strategy + Campaign
- 零 I/O：无 SQLite / 文件系统 / 环境 / 网络 / FastAPI / AI / 墙钟 / 持久化
- 零 BUY/SELL 生成、零数值优先级分数（不实现 0-100 / 四因子乘积）
- ``as_of`` 必须显式传入；禁止内部 ``now()``
- 只消费上游已归一化的 facts，不负责查询任何 authority；
  不 import ``top_risk_*`` / ``decision_cockpit_*`` / ``portfolio_advice_*``
  （它们不是本模块的 Semantic Authority）

可见状态（唯一权威，每 item 恰好一个）：

    NO_ACTION_REQUIRED / REVIEW_REQUIRED / BLOCKED_BY_DATA / SETUP_REQUIRED

确定性优先级（单一 precedence authority）：

    1. CONFIRMED HARD RISK 或 TERMINAL THESIS  → REVIEW_REQUIRED
    2. CRITICAL DATA BLOCK                     → BLOCKED_BY_DATA
    3. STRUCTURAL SETUP GAP                    → SETUP_REQUIRED
    4. WEAKENED / MATERIAL CHANGE / REVIEW_BY  → REVIEW_REQUIRED
    5. PROVEN CLEAN STATE                      → NO_ACTION_REQUIRED

原则：

- UNKNOWN != healthy：任何必要 authority 为 UNKNOWN / NOT_EVALUATED /
  NOT_AVAILABLE 时不得默认成 CLEAR
- terminal thesis / confirmed hard risk 不能被数据问题隐藏
- review_by 只允许 ``as_of >= review_by → REVIEW_REQUIRED``；
  本模块不生成 AGING / STALE / EXPIRED / INVALIDATED（Validity Projection
  不是 runtime authority）
- 历史 Frozen Decision 永远命名为 LAST_FROZEN_DECISION，绝不当成
  CURRENT_RECOMMENDATION
- campaign_capital_relevance 恒为 UNKNOWN（无 shares→campaign 分配权威，
  禁止把整只证券仓位复制到每个 Campaign，禁止 double count）
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Iterable, Mapping

SCHEMA_VERSION = "decision_inbox_projection.v0.1"

# ---------------------------------------------------------------------------
# 枚举（本模块的语义权威）
# ---------------------------------------------------------------------------

VISIBLE_STATES = (
    "NO_ACTION_REQUIRED",
    "REVIEW_REQUIRED",
    "BLOCKED_BY_DATA",
    "SETUP_REQUIRED",
)

# 归一化输入枚举
THESIS_STATES = ("STABLE", "WEAKENED", "DISPROVEN", "INVALIDATED", "UNKNOWN")
THESIS_STRUCTURAL_STATES = ("MISSING", "NOT_READY", "NOT_FROZEN", "READY")
TERMINAL_THESIS_STATES = ("DISPROVEN", "INVALIDATED")
CAMPAIGN_STATUSES = (
    "DRAFT", "RESEARCHING", "PRE-ENTRY", "ACTIVE", "REDUCING",
    "CLOSED", "REJECTED", "EXPIRED",
)
# P0 持仓 Decision Inbox 的正式 Campaign 范围
CAMPAIGN_STATUSES_IN_SCOPE = ("ACTIVE", "REDUCING")
STRATEGIES = ("SHORT", "SWING", "MEDIUM")
HARD_RISK_STATES = ("CLEAR", "CONFIRMED", "UNKNOWN")
MATERIAL_CHANGE_STATES = ("NONE", "MATERIAL", "CRITICAL", "UNKNOWN")
CRITICAL_DATA_STATES = ("USABLE", "BLOCKED", "UNKNOWN", "STALE")
CONFIDENCE_LEVELS = ("HIGH", "MEDIUM", "LOW", "UNKNOWN")

# 工作流动作（非投资 BUY/SELL 动作）
WORKFLOW_ACTIONS = (
    "REVIEW_THESIS",
    "CREATE_FORMAL_DECISION",
    "REVIEW_FORMAL_DECISION",
    "REPAIR_DATA",
    "RESEARCH_EVIDENCE",
    "NONE",
)

# 原因码（可多值；visible state 唯一）
REASON_CAMPAIGN_NOT_IN_SCOPE = "CAMPAIGN_NOT_IN_SCOPE"
REASON_UNASSIGNED_HOLDING = "UNASSIGNED_HOLDING"
REASON_THESIS_MISSING = "THESIS_MISSING"
REASON_THESIS_NOT_READY = "THESIS_NOT_READY"
REASON_THESIS_NOT_FROZEN = "THESIS_NOT_FROZEN"
REASON_THESIS_WEAKENED = "THESIS_WEAKENED"
REASON_THESIS_DISPROVEN = "THESIS_DISPROVEN"
REASON_THESIS_INVALIDATED = "THESIS_INVALIDATED"
REASON_THESIS_UNKNOWN = "THESIS_UNKNOWN"
REASON_FORMAL_DECISION_MISSING = "FORMAL_DECISION_MISSING"
REASON_REVIEW_BY_REACHED = "REVIEW_BY_REACHED"
REASON_HARD_RISK_CONFIRMED = "HARD_RISK_CONFIRMED"
REASON_HARD_RISK_UNKNOWN = "HARD_RISK_UNKNOWN"
REASON_CRITICAL_DATA_BLOCKED = "CRITICAL_DATA_BLOCKED"
REASON_CRITICAL_DATA_UNKNOWN = "CRITICAL_DATA_UNKNOWN"
REASON_CRITICAL_DATA_STALE = "CRITICAL_DATA_STALE"
REASON_COVERAGE_INCOMPLETE = "COVERAGE_INCOMPLETE"
REASON_MATERIAL_CHANGE_MATERIAL = "MATERIAL_CHANGE_MATERIAL"
REASON_MATERIAL_CHANGE_CRITICAL = "MATERIAL_CHANGE_CRITICAL"
REASON_MATERIAL_CHANGE_UNKNOWN = "MATERIAL_CHANGE_UNKNOWN"
REASON_LOW_CONFIDENCE = "LOW_CONFIDENCE"
REASON_CLEAN = "CLEAN"

REASON_CODES = (
    REASON_CAMPAIGN_NOT_IN_SCOPE,
    REASON_UNASSIGNED_HOLDING,
    REASON_THESIS_MISSING,
    REASON_THESIS_NOT_READY,
    REASON_THESIS_NOT_FROZEN,
    REASON_THESIS_WEAKENED,
    REASON_THESIS_DISPROVEN,
    REASON_THESIS_INVALIDATED,
    REASON_THESIS_UNKNOWN,
    REASON_FORMAL_DECISION_MISSING,
    REASON_REVIEW_BY_REACHED,
    REASON_HARD_RISK_CONFIRMED,
    REASON_HARD_RISK_UNKNOWN,
    REASON_CRITICAL_DATA_BLOCKED,
    REASON_CRITICAL_DATA_UNKNOWN,
    REASON_CRITICAL_DATA_STALE,
    REASON_COVERAGE_INCOMPLETE,
    REASON_MATERIAL_CHANGE_MATERIAL,
    REASON_MATERIAL_CHANGE_CRITICAL,
    REASON_MATERIAL_CHANGE_UNKNOWN,
    REASON_LOW_CONFIDENCE,
    REASON_CLEAN,
)

_SECURITY_CODE_RE = re.compile(r"^\d{6}$")
_CAMPAIGN_ID_RE = re.compile(r"^campaign_[0-9a-f]{32}$")
_DECISION_ID_RE = re.compile(r"^decision_[0-9a-f]{32}$")


class DecisionInboxValidationError(ValueError):
    """归一化输入不合法（fail closed）：拒绝任何非规范化 fact。"""


# ---------------------------------------------------------------------------
# 深度冻结 / 解冻（与仓库 O1 同模式；本模块自包含实现，零跨域耦合）
# ---------------------------------------------------------------------------

def _deep_freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {key: _deep_freeze(item) for key, item in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_deep_freeze(item) for item in value)
    return value


def _deep_unfreeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _deep_unfreeze(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_deep_unfreeze(item) for item in value]
    return value


# ---------------------------------------------------------------------------
# 时间（纯解析；无墙钟）
# ---------------------------------------------------------------------------

def _parse_utc_instant(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise DecisionInboxValidationError(f"{field}：必须是 UTC 时间戳")
    try:
        dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        raise DecisionInboxValidationError(
            f"{field}：无法解析的时间戳"
        ) from None
    if dt.tzinfo is None:
        raise DecisionInboxValidationError(f"{field}：缺少时区信息")
    if dt.utcoffset().total_seconds() != 0:
        raise DecisionInboxValidationError(
            f"{field}：仅接受零偏移 UTC（Z 或 +00:00），不做时区换算"
        )
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# 归一化输入契约
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CampaignFacts:
    """给定 Campaign 的已归一化事实（由上游 adapter 提供，本模块不查询）。

    - ``campaign_id`` 为 None 时表达 ``UNASSIGNED_HOLDING``（无 Campaign 的
      真实持仓；本模块不伪造 campaign_id）
    - ``latest_frozen_decision`` 为 None 或含
      decision_id / committed_at / review_by / previous_next_best_action
    - ``authority_refs`` 只承载上游给出的引用（如 thesis_id），不伪造
    """

    security_code: str
    strategy: str
    campaign_id: str | None
    campaign_status: str
    thesis_state: str
    current_thesis: str
    latest_frozen_decision: Mapping[str, Any] | None
    hard_risk_state: str
    material_change_state: str
    critical_data_state: str
    decision_confidence: str
    coverage_complete: bool
    as_of: str
    authority_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        # 严格枚举/格式校验（fail closed），随后深度冻结全部嵌套
        if not isinstance(self.security_code, str) or not _SECURITY_CODE_RE.fullmatch(
            self.security_code
        ):
            raise DecisionInboxValidationError("security_code：必须是 6 位数字")
        if self.strategy not in STRATEGIES:
            raise DecisionInboxValidationError(
                f"strategy：必须是 {STRATEGIES} 之一"
            )
        if self.campaign_id is not None and (
            not isinstance(self.campaign_id, str)
            or not _CAMPAIGN_ID_RE.fullmatch(self.campaign_id)
        ):
            raise DecisionInboxValidationError(
                "campaign_id：必须是 campaign_ + 32 位小写 hex，或 None（未分配持仓）"
            )
        if self.campaign_status not in CAMPAIGN_STATUSES:
            raise DecisionInboxValidationError(
                f"campaign_status：必须是 {CAMPAIGN_STATUSES} 之一"
            )
        if self.thesis_state not in THESIS_STRUCTURAL_STATES:
            raise DecisionInboxValidationError(
                f"thesis_state：必须是 {THESIS_STRUCTURAL_STATES} 之一"
            )
        if self.current_thesis not in THESIS_STATES:
            raise DecisionInboxValidationError(
                f"current_thesis：必须是 {THESIS_STATES} 之一"
            )
        decision = self.latest_frozen_decision
        if decision is not None:
            if not isinstance(decision, Mapping):
                raise DecisionInboxValidationError(
                    "latest_frozen_decision：必须是 Mapping 或 None"
                )
            required = {
                "decision_id", "committed_at", "review_by", "previous_next_best_action",
            }
            if set(decision) != required:
                raise DecisionInboxValidationError(
                    f"latest_frozen_decision：字段集必须精确为 {sorted(required)}"
                )
            if not isinstance(decision["decision_id"], str) or not _DECISION_ID_RE.fullmatch(
                decision["decision_id"]
            ):
                raise DecisionInboxValidationError(
                    "latest_frozen_decision.decision_id 格式不合法"
                )
            _parse_utc_instant(decision["committed_at"], "latest_frozen_decision.committed_at")
            _parse_utc_instant(decision["review_by"], "latest_frozen_decision.review_by")
            if not isinstance(decision["previous_next_best_action"], str):
                raise DecisionInboxValidationError(
                    "latest_frozen_decision.previous_next_best_action 必须是非空字符串"
                )
        if self.hard_risk_state not in HARD_RISK_STATES:
            raise DecisionInboxValidationError(
                f"hard_risk_state：必须是 {HARD_RISK_STATES} 之一"
            )
        if self.material_change_state not in MATERIAL_CHANGE_STATES:
            raise DecisionInboxValidationError(
                f"material_change_state：必须是 {MATERIAL_CHANGE_STATES} 之一"
            )
        if self.critical_data_state not in CRITICAL_DATA_STATES:
            raise DecisionInboxValidationError(
                f"critical_data_state：必须是 {CRITICAL_DATA_STATES} 之一"
            )
        if self.decision_confidence not in CONFIDENCE_LEVELS:
            raise DecisionInboxValidationError(
                f"decision_confidence：必须是 {CONFIDENCE_LEVELS} 之一"
            )
        if not isinstance(self.coverage_complete, bool):
            raise DecisionInboxValidationError("coverage_complete：必须是严格 bool")
        _parse_utc_instant(self.as_of, "as_of")
        if not isinstance(self.authority_refs, (list, tuple)) or not all(
            isinstance(ref, str) for ref in self.authority_refs
        ):
            raise DecisionInboxValidationError("authority_refs：必须是字符串列表")
        object.__setattr__(
            self,
            "latest_frozen_decision",
            _deep_freeze(decision) if decision is not None else None,
        )
        object.__setattr__(self, "authority_refs", tuple(self.authority_refs))

    def to_dict(self) -> dict[str, Any]:
        return {
            "security_code": self.security_code,
            "strategy": self.strategy,
            "campaign_id": self.campaign_id,
            "campaign_status": self.campaign_status,
            "thesis_state": self.thesis_state,
            "current_thesis": self.current_thesis,
            "latest_frozen_decision": (
                _deep_unfreeze(self.latest_frozen_decision)
                if self.latest_frozen_decision is not None
                else None
            ),
            "hard_risk_state": self.hard_risk_state,
            "material_change_state": self.material_change_state,
            "critical_data_state": self.critical_data_state,
            "decision_confidence": self.decision_confidence,
            "coverage_complete": self.coverage_complete,
            "as_of": self.as_of,
            "authority_refs": list(self.authority_refs),
        }


def campaign_facts_from_mapping(record: Mapping[str, Any]) -> CampaignFacts:
    """严格反序列化归一化输入；字段集/类型/枚举任何不符 fail closed。"""
    if not isinstance(record, Mapping):
        raise DecisionInboxValidationError("record：必须是 Mapping")
    keys = set(record)
    expected = set(CampaignFacts.__dataclass_fields__)
    if keys != expected:
        raise DecisionInboxValidationError(
            f"record：字段集必须精确为 {sorted(expected)}"
        )
    return CampaignFacts(**record)


# ---------------------------------------------------------------------------
# 输出：Inbox Item（唯一可见状态 + 多原因码 + 可解释性）
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class InboxItem:
    """单个 Campaign 的收件箱条目（纯投影输出，深度不可变）。

    - ``visible_state``：恰好一个
    - ``reason_codes``：可多个（按确定性顺序）
    - ``last_frozen_decision``：历史冻结决策（绝不命名为 current recommendation）
    - ``campaign_capital_relevance``：恒为 UNKNOWN
    - ``ai_review_recommended``：decision_confidence == LOW 时为 True（无 AI 调用）
    """

    schema_version: str = SCHEMA_VERSION
    visible_state: str = ""
    reason_codes: tuple[str, ...] = ()
    security_code: str = ""
    strategy: str = ""
    campaign_id: str | None = None
    campaign_status: str = ""
    campaign_capital_relevance: str = "UNKNOWN"
    current_thesis: Mapping[str, Any] = field(default_factory=dict)
    last_frozen_decision: Mapping[str, Any] | None = None
    hard_risk_state: str = ""
    material_change_state: str = ""
    critical_data_state: str = ""
    decision_confidence: str = ""
    coverage_complete: bool = False
    ai_review_recommended: bool = False
    explainability: Mapping[str, Any] = field(default_factory=dict)
    as_of: str = ""

    def __post_init__(self) -> None:
        if self.visible_state not in VISIBLE_STATES:
            raise DecisionInboxValidationError(
                f"visible_state：必须是 {VISIBLE_STATES} 之一"
            )
        if self.campaign_capital_relevance != "UNKNOWN":
            raise DecisionInboxValidationError(
                "campaign_capital_relevance：必须为 UNKNOWN（无分配权威）"
            )
        for field_name in (
            "current_thesis",
            "last_frozen_decision",
            "explainability",
        ):
            object.__setattr__(
                self, field_name, _deep_freeze(getattr(self, field_name))
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "visible_state": self.visible_state,
            "reason_codes": list(self.reason_codes),
            "security_code": self.security_code,
            "strategy": self.strategy,
            "campaign_id": self.campaign_id,
            "campaign_status": self.campaign_status,
            "campaign_capital_relevance": self.campaign_capital_relevance,
            "current_thesis": _deep_unfreeze(self.current_thesis),
            "last_frozen_decision": (
                _deep_unfreeze(self.last_frozen_decision)
                if self.last_frozen_decision is not None
                else None
            ),
            "hard_risk_state": self.hard_risk_state,
            "material_change_state": self.material_change_state,
            "critical_data_state": self.critical_data_state,
            "decision_confidence": self.decision_confidence,
            "coverage_complete": self.coverage_complete,
            "ai_review_recommended": self.ai_review_recommended,
            "explainability": _deep_unfreeze(self.explainability),
            "as_of": self.as_of,
        }


# ---------------------------------------------------------------------------
# 可解释性构造（确定性；全部由 facts 派生，无自由文本生成）
# ---------------------------------------------------------------------------

_WORKFLOW_BY_REASON: dict[str, str] = {
    REASON_CAMPAIGN_NOT_IN_SCOPE: "NONE",
    REASON_UNASSIGNED_HOLDING: "NONE",
    REASON_THESIS_MISSING: "REVIEW_THESIS",
    REASON_THESIS_NOT_READY: "REVIEW_THESIS",
    REASON_THESIS_NOT_FROZEN: "REVIEW_THESIS",
    REASON_THESIS_WEAKENED: "REVIEW_THESIS",
    REASON_THESIS_DISPROVEN: "REVIEW_THESIS",
    REASON_THESIS_INVALIDATED: "REVIEW_THESIS",
    REASON_THESIS_UNKNOWN: "RESEARCH_EVIDENCE",
    REASON_FORMAL_DECISION_MISSING: "CREATE_FORMAL_DECISION",
    REASON_REVIEW_BY_REACHED: "REVIEW_FORMAL_DECISION",
    REASON_HARD_RISK_CONFIRMED: "REVIEW_FORMAL_DECISION",
    REASON_HARD_RISK_UNKNOWN: "REPAIR_DATA",
    REASON_CRITICAL_DATA_BLOCKED: "REPAIR_DATA",
    REASON_CRITICAL_DATA_UNKNOWN: "REPAIR_DATA",
    REASON_CRITICAL_DATA_STALE: "REPAIR_DATA",
    REASON_COVERAGE_INCOMPLETE: "REPAIR_DATA",
    REASON_MATERIAL_CHANGE_MATERIAL: "REVIEW_THESIS",
    REASON_MATERIAL_CHANGE_CRITICAL: "REVIEW_THESIS",
    REASON_MATERIAL_CHANGE_UNKNOWN: "REPAIR_DATA",
    REASON_LOW_CONFIDENCE: "NONE",
    REASON_CLEAN: "NONE",
}


def _build_explainability(facts: CampaignFacts, reasons: list[str]) -> dict[str, Any]:
    """确定性可解释性：WHAT / WHY_NOW / WHAT_CHANGED / WHICH_CAMPAIGN /
    AUTHORITY_REFS / UNCERTAINTIES / CLEAR_CONDITIONS / NEXT_WORKFLOW_ACTION。"""
    campaign_label = facts.campaign_id or "UNASSIGNED_HOLDING"

    what = (
        f"{facts.security_code} / {facts.strategy} / {campaign_label}："
        f"{'、'.join(reasons) if reasons else '无需处理'}"
    )
    why_now = (
        "需要在下个可交易时点前重新评估" if reasons and reasons[0] != REASON_CLEAN
        else "当前无处理事项"
    )
    if facts.current_thesis == "WEAKENED":
        changed = "THESIS_WEAKENED"
    elif facts.current_thesis in ("DISPROVEN", "INVALIDATED"):
        changed = f"THESIS_{facts.current_thesis}"
    elif facts.material_change_state in ("MATERIAL", "CRITICAL"):
        changed = f"MATERIAL_CHANGE_{facts.material_change_state}"
    elif facts.hard_risk_state == "CONFIRMED":
        changed = "HARD_RISK_CONFIRMED"
    else:
        changed = "NO_CHANGE_EVIDENCE"

    uncertainties: list[str] = []
    if facts.hard_risk_state == "UNKNOWN":
        uncertainties.append("hard_risk_state=UNKNOWN")
    if facts.material_change_state == "UNKNOWN":
        uncertainties.append("material_change_state=UNKNOWN")
    if facts.critical_data_state in ("UNKNOWN", "STALE"):
        uncertainties.append(f"critical_data_state={facts.critical_data_state}")
    if facts.decision_confidence == "UNKNOWN":
        uncertainties.append("decision_confidence=UNKNOWN")
    if not facts.coverage_complete:
        uncertainties.append("coverage_complete=false")

    clear_conditions = [
        "campaign_status ∈ {ACTIVE, REDUCING}",
        "thesis_state == READY",
        "current_thesis == STABLE",
        "latest_frozen_decision 存在",
        "as_of < review_by",
        "hard_risk_state == CLEAR",
        "material_change_state == NONE",
        "critical_data_state == USABLE",
        "coverage_complete == true",
    ]

    return {
        "what": what,
        "why_now": why_now,
        "what_changed": changed,
        "which_campaign": campaign_label,
        "authority_refs": list(facts.authority_refs),
        "uncertainties": uncertainties,
        "clear_conditions": clear_conditions,
        "next_workflow_action": _WORKFLOW_BY_REASON.get(
            reasons[0] if reasons else REASON_CLEAN, "NONE"
        ),
    }


# ---------------------------------------------------------------------------
# 投影权威（单一确定性 precedence）
# ---------------------------------------------------------------------------

def _project(facts: CampaignFacts) -> InboxItem:
    reasons: list[str] = []
    visible_state = ""

    # 1) CONFIRMED HARD RISK 或 TERMINAL THESIS → REVIEW_REQUIRED
    if facts.hard_risk_state == "CONFIRMED":
        reasons.append(REASON_HARD_RISK_CONFIRMED)
    if facts.thesis_state == "READY" and facts.current_thesis == "DISPROVEN":
        reasons.append(REASON_THESIS_DISPROVEN)
    if facts.thesis_state == "READY" and facts.current_thesis == "INVALIDATED":
        reasons.append(REASON_THESIS_INVALIDATED)
    if reasons:
        visible_state = "REVIEW_REQUIRED"

    # 2) CRITICAL DATA BLOCK → BLOCKED_BY_DATA（terminal / hard risk 不被隐藏）
    if not visible_state:
        data_reasons: list[str] = []
        if facts.critical_data_state == "BLOCKED":
            data_reasons.append(REASON_CRITICAL_DATA_BLOCKED)
        elif facts.critical_data_state == "UNKNOWN":
            data_reasons.append(REASON_CRITICAL_DATA_UNKNOWN)
        elif facts.critical_data_state == "STALE":
            data_reasons.append(REASON_CRITICAL_DATA_STALE)
        if not facts.coverage_complete:
            data_reasons.append(REASON_COVERAGE_INCOMPLETE)
        if facts.hard_risk_state == "UNKNOWN":
            data_reasons.append(REASON_HARD_RISK_UNKNOWN)
        if facts.material_change_state == "UNKNOWN":
            data_reasons.append(REASON_MATERIAL_CHANGE_UNKNOWN)
        if data_reasons:
            reasons = data_reasons
            visible_state = "BLOCKED_BY_DATA"

    # 3) STRUCTURAL SETUP GAP → SETUP_REQUIRED
    if not visible_state:
        setup_reasons: list[str] = []
        if facts.campaign_status not in CAMPAIGN_STATUSES_IN_SCOPE:
            setup_reasons.append(REASON_CAMPAIGN_NOT_IN_SCOPE)
        elif facts.campaign_id is None:
            setup_reasons.append(REASON_UNASSIGNED_HOLDING)
        if facts.thesis_state == "MISSING":
            setup_reasons.append(REASON_THESIS_MISSING)
        elif facts.thesis_state == "NOT_READY":
            setup_reasons.append(REASON_THESIS_NOT_READY)
        elif facts.thesis_state == "NOT_FROZEN":
            setup_reasons.append(REASON_THESIS_NOT_FROZEN)
        if facts.thesis_state == "READY" and facts.latest_frozen_decision is None:
            setup_reasons.append(REASON_FORMAL_DECISION_MISSING)
        if setup_reasons:
            reasons = setup_reasons
            visible_state = "SETUP_REQUIRED"

    # 4) WEAKENED / MATERIAL CHANGE / REVIEW_BY / UNKNOWN THESIS → REVIEW_REQUIRED
    if not visible_state:
        review_reasons: list[str] = []
        if facts.current_thesis == "WEAKENED":
            review_reasons.append(REASON_THESIS_WEAKENED)
        elif facts.current_thesis == "UNKNOWN":
            review_reasons.append(REASON_THESIS_UNKNOWN)
        if facts.material_change_state == "MATERIAL":
            review_reasons.append(REASON_MATERIAL_CHANGE_MATERIAL)
        elif facts.material_change_state == "CRITICAL":
            review_reasons.append(REASON_MATERIAL_CHANGE_CRITICAL)
        if facts.latest_frozen_decision is not None:
            review_by = facts.latest_frozen_decision["review_by"]
            if _parse_utc_instant(facts.as_of, "as_of") >= _parse_utc_instant(
                review_by, "latest_frozen_decision.review_by"
            ):
                review_reasons.append(REASON_REVIEW_BY_REACHED)
        if review_reasons:
            reasons = review_reasons
            visible_state = "REVIEW_REQUIRED"

    # 5) PROVEN CLEAN STATE → NO_ACTION_REQUIRED
    if not visible_state:
        reasons = [REASON_CLEAN]
        visible_state = "NO_ACTION_REQUIRED"

    # LOW confidence：附注 + AI_REVIEW_RECOMMENDED（不改 visible state）
    if facts.decision_confidence == "LOW":
        reasons.append(REASON_LOW_CONFIDENCE)
        ai_review = True
    else:
        ai_review = False

    current_thesis_payload = {
        "thesis_state": facts.thesis_state,
        "current_thesis": facts.current_thesis,
    }
    return InboxItem(
        visible_state=visible_state,
        reason_codes=tuple(reasons),
        security_code=facts.security_code,
        strategy=facts.strategy,
        campaign_id=facts.campaign_id,
        campaign_status=facts.campaign_status,
        current_thesis=current_thesis_payload,
        last_frozen_decision=facts.latest_frozen_decision,
        hard_risk_state=facts.hard_risk_state,
        material_change_state=facts.material_change_state,
        critical_data_state=facts.critical_data_state,
        decision_confidence=facts.decision_confidence,
        coverage_complete=facts.coverage_complete,
        ai_review_recommended=ai_review,
        explainability=_build_explainability(facts, reasons),
        as_of=facts.as_of,
    )


def project_campaign(facts: CampaignFacts | Mapping[str, Any]) -> InboxItem:
    """投影单个 Campaign → InboxItem（确定性 precedence 权威）。

    输入为 ``CampaignFacts`` 或严格形状的 Mapping（``campaign_facts_from_mapping``）。
    """
    normalized = (
        facts if isinstance(facts, CampaignFacts) else campaign_facts_from_mapping(facts)
    )
    return _project(normalized)


def project_campaigns(items: Iterable[CampaignFacts | Mapping[str, Any]]) -> list[InboxItem]:
    """投影多个 Campaign；输出按技术 key 稳定排序。

    排序 key（security_code, strategy, campaign_id）仅为确定性技术 key，
    不是投资优先级。
    """
    results = [project_campaign(item) for item in items]
    return sorted(
        results,
        key=lambda r: (r.security_code, r.strategy, r.campaign_id or ""),
    )
