"""P0-DI2 — current-only Decision Inbox runtime assembler.

组合已冻结 authorities，不重新读取持仓/Campaign membership：

    #118 holdings_campaign_composition snapshot
      → 每个真实 ACTIVE / REDUCING Campaign
      → DDA1 resolve_strategy_dependencies
      → per-capability real evaluators（P0-DS1）
           ├─ cap.security.price_reference → #116 adapter（readonly lake）
           ├─ cap.context.market_sector → 真实市场广度读取路径
           ├─ cap.security.disclosures → 真实公告读取路径（EMPTY_BUT_VALID 区分）
           └─ cap.security.financials → 真实财务读取路径
              （report-period applicability 未解决 → NOT_EVALUATED + 显式 blocker）
      → CCD1 project_campaign_critical_data
      → RA1 project_decision_assurance
      → DI1 CampaignFacts → project_campaign

本 Slice 明确不产生 false clean：
- Hard Risk 走 P0-HR1 port：identity exact + literal same-as-of 校验后透传给
  RA1 / DI1；C 的 production evaluator 未完成时，production 默认端口显式返回
  NOT_EVALUATED（无 authority 不声称已评估），integration 阶段注入 fake port
  证明全链语义。
- Material Change 在 DC1 production path 由 approved C projection 评估；
  没有历史 Frozen Decision boundary 时保持 NOT_EVALUATED。
- Formal Thesis / Frozen Decision 在 DC1 production path 使用 same-as-of
  适用性评估；读取过记录 ≠ 完成评估。旧的注入式 current-only fixture
  没有 Formal Original snapshot 时保持 NOT_EVALUATED。
- capability NOT_EVALUATED 仍是合法结果（数据缺失 / applicability 未解决 /
  未到评估时点），绝不为了灯变绿强制 USABLE。

只读、零写入、fail closed。所有生产端口均基于既有只读 authorities；
本模块不 import router / app / frontend。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import copy
from typing import Any, Callable, Mapping

import campaign_service
import campaign_critical_data_runtime as cdr
import decision_assurance_projection as ra
import decision_commit_runtime as dc_runtime
import decision_inbox_projection as di
import formal_thesis_projection as thesis_projection
import frozen_decision_service as frozen_service
import hard_risk_contract as hr
import hard_risk_current_thesis_adapter as thesis_hr_adapter
import hard_risk_runtime as hr_runtime
import holdings_campaign_composition as composition
from fact_lake_store import FactLake


SCHEMA_VERSION = "decision_inbox_runtime.v0.1"
DDA_POLICY_VERSION = cdr.DDA_POLICY_VERSION

_FACT_LAKE_ROOT_ENV = "VR_FACT_LAKE_ROOT"
_FACT_LAKE_CONTROL_FILE = "fact_lake_control.sqlite3"


class DecisionInboxRuntimeError(RuntimeError):
    """Decision Inbox runtime 基础错误（fail closed → HTTP 500）。"""


class DecisionInboxRuntimeIntegrityError(DecisionInboxRuntimeError):
    """组合链中任一 authority 返回内部不一致契约。"""


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(
        timespec="microseconds"
    ).replace("+00:00", "Z")


def _parse_utc_instant(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise DecisionInboxRuntimeIntegrityError(
            f"{field} 不是合法 UTC 时间戳"
        ) from exc
    if parsed.tzinfo is None:
        raise DecisionInboxRuntimeIntegrityError(
            f"{field} 缺少时区信息"
        )
    return parsed.astimezone(timezone.utc)


_production_lake_provider = cdr.production_lake_provider
_production_price_evaluator = cdr.production_price_evaluator
_record_observation_event = cdr.record_observation_event
_production_market_sector_evaluator = cdr.production_market_sector_evaluator
_production_disclosures_evaluator = cdr.production_disclosures_evaluator
_production_financials_evaluator = cdr.production_financials_evaluator


def _production_frozen_decisions_reader(
    campaign_id: str,
) -> list[Mapping[str, Any]]:
    """确定性读取 campaign 全部冻结决策（committed_at ASC）；缺库返回空。"""
    results: list[Mapping[str, Any]] = []
    offset = 0
    while True:
        page = frozen_service.list_decisions(
            campaign_id=campaign_id, limit=100, offset=offset
        )
        results.extend(page)
        if len(page) < 100:
            return results
        offset += 100
        if offset > 10000:
            raise DecisionInboxRuntimeError(
                "frozen decision scan exceeded safety bound"
            )


def _production_hard_risk_evaluator(
    definition: Mapping[str, Any],
    campaign: Mapping[str, Any],
    current_thesis_projection: Mapping[str, Any] | None,
) -> Mapping[str, Any]:
    """P0-HR1 production Hard Risk 端口：Current Thesis authority → C runtime。

    - Current Thesis 已在 assembler 内 single-read，本端口不再自行读取。
    - 只经 thesis_hr_adapter 做 shape adaptation（补 schema_version /
      strategy / terminal），最终 state 由 hard_risk_runtime 决定。
    - 未绑定（projection=None）→ C 返回 NOT_EVALUATED（fail closed）。
    - v0.1 无 CLEAR authority：C 永不输出 CLEAR。
    """
    envelope = thesis_hr_adapter.build_current_thesis_envelope(
        campaign=campaign,
        as_of=definition["as_of"],
        current_thesis_projection=current_thesis_projection,
    )
    return hr_runtime.evaluate_hard_risk_mapping(
        campaign_id=campaign["campaign_id"],
        campaign=campaign,
        as_of=definition["as_of"],
        formal_thesis_projection=envelope,
    )


CapabilityEvaluator = cdr.CapabilityEvaluator

HardRiskEvaluator = Callable[
    [Mapping[str, Any], Mapping[str, Any], Mapping[str, Any] | None],
    Mapping[str, Any],
]


@dataclass(frozen=True)
class RuntimePorts:
    """runtime 全部 I/O 端口；测试注入，生产默认绑定既有只读 authorities。

    四个 critical-data capability 各有真实 evaluator（P0-DS1）：
    price_reference 读 Fact Lake；market_sector / disclosures / financials
    走既有真实业务读取路径。NOT_EVALUATED 仍是合法结果（数据缺失 /
    applicability 未解决 / 未到评估时点），绝不强制 USABLE。

    hard_risk_evaluator（P0-HR1）接收 definition（DDA 展开的 Campaign 上下文）、
    真实 Campaign record、以及同一 snapshot 内 single-read 的 Current Thesis
    projection，返回 hard_risk_contract 契约结果；production 默认经 Current
    Thesis adapter 绑定 hard_risk_runtime（C core），未绑定时 NOT_EVALUATED。
    """

    composition_reader: Callable[[], Mapping[str, Any]]
    dependency_resolver: Callable[..., Mapping[str, Any]]
    price_evaluator: CapabilityEvaluator = _production_price_evaluator
    market_sector_evaluator: CapabilityEvaluator = (
        _production_market_sector_evaluator
    )
    disclosures_evaluator: CapabilityEvaluator = (
        _production_disclosures_evaluator
    )
    financials_evaluator: CapabilityEvaluator = (
        _production_financials_evaluator
    )
    hard_risk_evaluator: HardRiskEvaluator = _production_hard_risk_evaluator
    thesis_reader: Callable[[str], Mapping[str, Any]] = (
        thesis_projection.project_current_thesis
    )
    frozen_decisions_reader: Callable[
        [str], list[Mapping[str, Any]]
    ] = _production_frozen_decisions_reader
    lake_provider: Callable[[], FactLake | None] = _production_lake_provider


PRODUCTION_PORTS = RuntimePorts(
    composition_reader=composition.assemble_holdings_campaign_composition,
    dependency_resolver=cdr.PRODUCTION_PORTS.dependency_resolver,
)


# ---------------------------------------------------------------------------
# 组合校验 helpers
# ---------------------------------------------------------------------------

def _require_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise DecisionInboxRuntimeIntegrityError(f"{label} 必须是 Mapping")
    return value


def _assert_same_identity(
    left: Mapping[str, Any], right: Mapping[str, Any], *, label: str
) -> None:
    for key in ("security_code", "strategy", "campaign_id"):
        if left.get(key) != right.get(key):
            raise DecisionInboxRuntimeIntegrityError(
                f"{label} identity mismatch on {key}"
            )


def _assert_literal_as_of(left: str, right: str, *, label: str) -> None:
    if left != right:
        raise DecisionInboxRuntimeIntegrityError(
            f"{label} as_of 不一致（必须逐字相等）"
        )


def _validate_capability_result(
    result: Mapping[str, Any],
    *,
    dependency_id: str,
    as_of: str,
) -> Mapping[str, Any]:
    result = _require_mapping(result, "capability result")
    if result.get("dependency_id") != dependency_id:
        raise DecisionInboxRuntimeIntegrityError(
            "capability result dependency_id 不匹配"
        )
    _assert_literal_as_of(
        str(result.get("as_of", "")), as_of, label="capability result"
    )
    return result


def _evaluate_hard_risk(
    ports: RuntimePorts,
    definition: Mapping[str, Any],
    campaign: Mapping[str, Any],
    current_thesis_projection: Mapping[str, Any] | None,
) -> hr.HardRiskEvaluation:
    """调用 HR1 port 并执行 identity / as_of / contract 三闸校验（fail closed）。

    - evaluator 自身异常（IO / 网络 / 编程错误）→ 整体 fail closed（500）。
      ERROR 状态的契约表达由 evaluator 显式返回 UNKNOWN/ERROR 结果承担，
      组装层不猜 C 的异常类型（唯一共享界面是 hard_risk_contract）。
    - 返回结果违反 shared contract（非法 state/evaluation pair、缺 authority
      refs、非法 identity 格式、额外字段等）→ integrity 错误（500）。
    - security_code / strategy / campaign_id 与调用方不逐字一致，或 as_of 非
      literal 相同 → integrity 错误（与 DDA/CCD/RA 同款校验，防跨 Campaign
      串结果与跨时点复用）。
    """
    try:
        raw = ports.hard_risk_evaluator(
            definition, campaign, current_thesis_projection
        )
    except Exception as exc:
        raise DecisionInboxRuntimeError(
            f"Hard Risk evaluator 失败（campaign {definition['campaign_id']}）"
        ) from exc
    try:
        normalized = hr.hard_risk_evaluation_from_mapping(raw)
    except hr.HardRiskContractError as exc:
        raise DecisionInboxRuntimeIntegrityError(
            f"Hard Risk 结果违反 shared contract: {exc}"
        ) from exc
    _assert_same_identity(
        normalized.to_dict(), definition, label="Hard Risk"
    )
    _assert_literal_as_of(
        normalized.as_of, definition["as_of"], label="Hard Risk"
    )
    return normalized


# ---------------------------------------------------------------------------
# Thesis / Frozen Decision 归一化（current-only 结构事实）
# ---------------------------------------------------------------------------

def _thesis_normalized(
    thesis_reader: Callable[[str], Mapping[str, Any]],
    campaign_id: str,
) -> tuple[str, str, Mapping[str, Any] | None]:
    """返回 (thesis_state, current_thesis, projection)。

    Current Thesis projection 在本函数内 single-read 一次：同一 immutable
    result 同时用于 DI1 归一化与 Hard Risk 生产评估，杜绝 snapshot race
    （HR 读版本 A、DI1 读版本 B）。

    - 未绑定 → (MISSING, UNKNOWN, None)
    - 未冻结 → (NOT_FROZEN, UNKNOWN, projection)
    - 其他 NOT_READY → (NOT_READY, UNKNOWN, projection)
    - READY → (READY, effective_state, projection)
    """
    try:
        projection = thesis_reader(campaign_id)
    except campaign_service.ThesisBindingNotFoundError:
        return "MISSING", "UNKNOWN", None
    except (
        thesis_projection.CurrentThesisProjectionError,
        campaign_service.CampaignThesisStrategyConflictError,
    ) as exc:
        raise DecisionInboxRuntimeIntegrityError(
            "current thesis projection 失败"
        ) from exc
    projection = _require_mapping(projection, "thesis projection")
    if projection.get("formal_status") != "READY":
        reason = projection.get("reason")
        if reason == "NOT_FROZEN":
            return "NOT_FROZEN", "UNKNOWN", projection
        return "NOT_READY", "UNKNOWN", projection
    effective = projection.get("effective_state")
    if not isinstance(effective, str) or effective not in di.THESIS_STATES:
        raise DecisionInboxRuntimeIntegrityError(
            "thesis effective_state 不是合法 DI1 枚举"
        )
    return "READY", effective, projection


def _latest_frozen_decision(
    frozen_decisions_reader: Callable[[str], list[Mapping[str, Any]]],
    campaign_id: str,
    as_of: str,
) -> Mapping[str, Any] | None:
    """committed_at <= as_of 的最新冻结决策 → DI1 形状；无则 None。"""
    decisions = frozen_decisions_reader(campaign_id)
    if not isinstance(decisions, list):
        raise DecisionInboxRuntimeIntegrityError(
            "frozen decision reader 必须返回 list"
        )
    cutoff = _parse_utc_instant(as_of, "as_of")
    latest: Mapping[str, Any] | None = None
    latest_ts: datetime | None = None
    for decision in decisions:
        decision = _require_mapping(decision, "frozen decision")
        committed_at = decision.get("committed_at")
        if not isinstance(committed_at, str):
            raise DecisionInboxRuntimeIntegrityError(
                "frozen decision committed_at 缺失"
            )
        committed_ts = _parse_utc_instant(
            committed_at, "frozen decision committed_at"
        )
        if committed_ts > cutoff:
            continue
        if latest_ts is None or committed_ts > latest_ts:
            latest = decision
            latest_ts = committed_ts
    if latest is None:
        return None
    required = {
        "decision_id", "committed_at", "review_by", "next_best_action",
    }
    if set(latest) < required:
        raise DecisionInboxRuntimeIntegrityError(
            "frozen decision 缺少必要字段"
        )
    return {
        "decision_id": latest["decision_id"],
        "committed_at": latest["committed_at"],
        "review_by": latest["review_by"],
        "previous_next_best_action": latest["next_best_action"],
    }


def _decision_confidence(
    frozen: Mapping[str, Any] | None, frozen_raw: Mapping[str, Any] | None
) -> str:
    """透传 latest frozen 的合法置信度；否则 UNKNOWN（不伪造）。"""
    if frozen is None or frozen_raw is None:
        return "UNKNOWN"
    raw = frozen_raw.get("decision_confidence")
    if raw in di.CONFIDENCE_LEVELS:
        return raw
    return "UNKNOWN"


# ---------------------------------------------------------------------------
# Campaign 组合（DDA → capabilities → CCD → RA → DI1）
# ---------------------------------------------------------------------------

def _capability_results(
    definition: Mapping[str, Any],
    *,
    lake: FactLake | None,
    ports: RuntimePorts,
) -> list[Mapping[str, Any]]:
    """Compatibility wrapper for the shared Critical Data runtime."""

    shared_ports = cdr.critical_data_ports_from(ports)
    return list(cdr._capability_results(definition, lake=lake, ports=shared_ports))


def _project_campaign_item(
    campaign: Mapping[str, Any],
    *,
    as_of: str,
    lake: FactLake | None,
    ports: RuntimePorts,
) -> Mapping[str, Any]:
    definition = _require_mapping(
        ports.dependency_resolver(
            security_code=campaign["security_code"],
            strategy=campaign["strategy"],
            campaign_id=campaign["campaign_id"],
            as_of=as_of,
            policy_version=DDA_POLICY_VERSION,
        ),
        "DDA definition",
    )
    _assert_same_identity(definition, campaign, label="DDA")
    _assert_literal_as_of(definition["as_of"], as_of, label="DDA")

    try:
        ccd = _require_mapping(
            cdr.project_campaign_critical_data(
                campaign=campaign,
                as_of=as_of,
                ports=cdr.critical_data_ports_from(ports),
                lake=lake,
            ),
            "CCD projection",
        )
    except cdr.CriticalDataRuntimeIntegrityError as exc:
        raise DecisionInboxRuntimeIntegrityError(str(exc)) from exc
    _assert_same_identity(ccd, definition, label="CCD")
    _assert_literal_as_of(ccd["as_of"], as_of, label="CCD")

    # Current Thesis 只读一次：同一 immutable projection 同时供 Hard Risk
    # 生产评估与 DI1 归一化，杜绝 snapshot race（HR 读版本 A、DI1 读版本 B）。
    thesis_state, current_thesis, thesis_projection = _thesis_normalized(
        ports.thesis_reader, campaign["campaign_id"]
    )
    hard_risk = _evaluate_hard_risk(
        ports, definition, campaign, thesis_projection
    )

    decisions = ports.frozen_decisions_reader(campaign["campaign_id"])
    # DC1 consumes the same single-read Current Thesis projection already used
    # by HR1.  Production READY data always takes the strict DC1 path, so a
    # malformed/missing Formal Original snapshot fails closed.  A custom
    # injected fixture may intentionally use the pre-DC1 transport shape
    # (empty Original snapshot); preserve its current-only compatibility path.
    original_snapshot = (
        thesis_projection.get("original_snapshot")
        if isinstance(thesis_projection, Mapping)
        else None
    )
    dc1_ready_shape = (
        isinstance(thesis_projection, Mapping)
        and thesis_projection.get("formal_status") == "READY"
        and (
            ports is PRODUCTION_PORTS
            or (
                isinstance(original_snapshot, Mapping)
                and bool(original_snapshot)
                and (
                    isinstance(original_snapshot.get("thesis"), Mapping)
                    or "subject_type" in original_snapshot
                )
            )
        )
    )
    dc1_authorities = None
    if dc1_ready_shape:
        try:
            dc1_authorities = dc_runtime.evaluate_authorities(
                campaign=campaign,
                as_of=as_of,
                current_thesis_projection=thesis_projection,
                frozen_decisions=decisions,
                critical_data=ccd,
                evidence_reader=dc_runtime.PRODUCTION_PORTS.evidence_reader,
                hard_risk=hard_risk,
            )
        except dc_runtime.DecisionCommitRuntimeError as exc:
            raise DecisionInboxRuntimeIntegrityError(
                "DC1 authority evaluation failed"
            ) from exc

    if dc1_authorities is None:
        assurance = _require_mapping(
            ra.project_decision_assurance(
                security_code=ccd["security_code"],
                strategy=ccd["strategy"],
                campaign_id=ccd["campaign_id"],
                # current-only / legacy injected shape：无 same-as-of 适用性
                # authority，不得声称 Formal Thesis / Decision 已评估。
                formal_thesis_evaluation="NOT_EVALUATED",
                formal_decision_evaluation="NOT_EVALUATED",
                hard_risk_evaluation=hard_risk.hard_risk_evaluation,
                material_change_evaluation="NOT_EVALUATED",
                critical_data_evaluation=ccd["critical_data_evaluation"],
                as_of=ccd["as_of"],
            ),
            "RA projection",
        )
        _assert_same_identity(assurance, ccd, label="RA")
        _assert_literal_as_of(assurance["as_of"], as_of, label="RA")
        latest_frozen = _latest_frozen_decision(
            lambda _campaign_id: decisions, campaign["campaign_id"], as_of
        )
        material_state = "NOT_EVALUATED"
        material_evaluation = "NOT_EVALUATED"
        material_reason_codes: list[str] = []
        formal_thesis_evaluation = "NOT_EVALUATED"
        formal_decision_evaluation = "NOT_EVALUATED"
        sell_engine_payload = None
    else:
        assurance = _require_mapping(
            dc1_authorities.decision_assurance, "RA projection"
        )
        _assert_same_identity(assurance, ccd, label="RA")
        _assert_literal_as_of(assurance["as_of"], as_of, label="RA")
        latest_frozen = dc1_authorities.latest_frozen
        material_state = (
            dc1_authorities.material_change.material_change_state
            if dc1_authorities.material_change is not None
            else "NOT_EVALUATED"
        )
        material_evaluation = dc1_authorities.material_change_evaluation
        material_reason_codes = list(dc1_authorities.material_change_reason_codes)
        formal_thesis_evaluation = dc1_authorities.formal_thesis_evaluation
        formal_decision_evaluation = dc1_authorities.formal_decision["evaluation"]
        sell_engine_payload = dc1_authorities.sell_engine.to_dict()

    latest_raw = None
    if latest_frozen is not None and dc1_authorities is None:
        for decision in decisions:
            if decision.get("decision_id") == latest_frozen["decision_id"]:
                latest_raw = decision
                break
    elif dc1_authorities is not None:
        latest_raw = dc1_authorities.latest_frozen_raw
    confidence = _decision_confidence(latest_frozen, latest_raw)

    authority_refs = list(ccd.get("authority_refs", []))
    authority_refs.extend(hard_risk.authority_refs)
    facts = di.CampaignFacts(
        security_code=campaign["security_code"],
        strategy=campaign["strategy"],
        campaign_id=campaign["campaign_id"],
        campaign_status=campaign["status"],
        thesis_state=thesis_state,
        current_thesis=current_thesis,
        latest_frozen_decision=latest_frozen,
        hard_risk_state=hard_risk.hard_risk_state,
        material_change_state=material_state,
        critical_data_state=ccd["critical_data_state"],
        critical_data_evaluation=ccd["critical_data_evaluation"],
        decision_confidence=confidence,
        coverage_complete=bool(assurance["coverage_complete"]),
        as_of=as_of,
        authority_refs=authority_refs,
    )
    projected = di.project_campaign(facts).to_dict()

    # P0-HR1 O lane：product composition 层暴露 Hard Risk 专属 provenance。
    # 四个专属字段直接来自已通过 contract validation 的 HardRiskEvaluation；
    # DI1 的 reason_codes / explainability.authority_refs 是 Campaign-level
    # generic explainability（含 Critical Data / Thesis / Decision 等多 authority），
    # 禁止充当 Hard Risk 专属 provenance。DI1 输出的 hard_risk_state 必须与
    # HardRiskEvaluation 完全一致，否则 fail closed。
    if projected.get("hard_risk_state") != hard_risk.hard_risk_state:
        raise DecisionInboxRuntimeIntegrityError(
            "DI1 hard_risk_state 与 HardRiskEvaluation 不一致"
        )
    projected["hard_risk_evaluation"] = hard_risk.hard_risk_evaluation
    projected["hard_risk_reason_codes"] = list(hard_risk.reason_codes)
    projected["hard_risk_authority_refs"] = list(hard_risk.authority_refs)
    # DC1 fields are additive to the frozen DI1 payload.  DI1's existing
    # visible-state projection remains the authority for inbox state; these
    # fields expose the real RA1 / Formal Decision / Material / Sell results
    # without changing the legacy CampaignFacts contract.
    projected["formal_thesis_evaluation"] = formal_thesis_evaluation
    projected["formal_decision_evaluation"] = formal_decision_evaluation
    projected["material_change_evaluation"] = material_evaluation
    projected["material_change_reason_codes"] = material_reason_codes
    projected["critical_data"] = copy.deepcopy(dict(ccd))
    projected["decision_assurance"] = copy.deepcopy(dict(assurance))
    if sell_engine_payload is not None:
        projected["sell_engine"] = sell_engine_payload
    return projected


def _holding_setup_item(
    item: Mapping[str, Any], *, as_of: str
) -> Mapping[str, Any]:
    return {
        "item_kind": "UNASSIGNED_HOLDING",
        "security_code": item["security_code"],
        "security_name": item["security_name"],
        "holding": item["holding"],
        "reason_codes": ["UNASSIGNED_HOLDING"],
        "next_workflow_action": "CREATE_CAMPAIGN",
        "as_of": as_of,
    }


# ---------------------------------------------------------------------------
# 公共 API
# ---------------------------------------------------------------------------

def assemble_current_decision_inbox(
    *,
    as_of: str | None = None,
    ports: RuntimePorts = PRODUCTION_PORTS,
) -> dict[str, Any]:
    """生成 current-only Decision Inbox snapshot（只读、零写入、fail closed）。"""
    snapshot_as_of = _utc_now_iso() if as_of is None else as_of
    _parse_utc_instant(snapshot_as_of, "as_of")

    derived = _require_mapping(
        ports.composition_reader(), "holdings composition"
    )
    if derived.get("evaluation_status") != "EVALUATED":
        return {
            "schema_version": SCHEMA_VERSION,
            "as_of": snapshot_as_of,
            "evaluation_status": "NOT_EVALUATED",
            "canonical": False,
            "reason_codes": list(derived.get("reason_codes", [])),
            "holding_setup_items": [],
            "campaign_items": [],
            "total_holdings": 0,
            "total_campaign_items": 0,
        }

    has_campaigns = any(
        _require_mapping(item, "composition item").get("campaigns")
        for item in derived.get("items", [])
    )
    lake = ports.lake_provider() if has_campaigns else None
    holding_setup_items: list[Mapping[str, Any]] = []
    campaign_items: list[Mapping[str, Any]] = []
    for item in derived.get("items", []):
        item = _require_mapping(item, "composition item")
        campaigns = item.get("campaigns", [])
        if not campaigns:
            holding_setup_items.append(
                _holding_setup_item(item, as_of=snapshot_as_of)
            )
            continue
        for campaign in campaigns:
            campaign = _require_mapping(campaign, "composition campaign")
            campaign_items.append(
                _project_campaign_item(
                    campaign,
                    as_of=snapshot_as_of,
                    lake=lake,
                    ports=ports,
                )
            )

    campaign_items.sort(
        key=lambda entry: (
            entry["security_code"],
            entry["strategy"],
            entry["campaign_id"],
        )
    )
    holding_setup_items.sort(key=lambda entry: entry["security_code"])
    return {
        "schema_version": SCHEMA_VERSION,
        "as_of": snapshot_as_of,
        "evaluation_status": "EVALUATED",
        "canonical": True,
        "reason_codes": list(derived.get("reason_codes", [])),
        "holding_setup_items": holding_setup_items,
        "campaign_items": campaign_items,
        "total_holdings": int(derived.get("total_holdings", 0)),
        "total_campaign_items": len(campaign_items),
    }


__all__ = [
    "DDA_POLICY_VERSION",
    "DecisionInboxRuntimeError",
    "DecisionInboxRuntimeIntegrityError",
    "PRODUCTION_PORTS",
    "RuntimePorts",
    "SCHEMA_VERSION",
    "assemble_current_decision_inbox",
]
