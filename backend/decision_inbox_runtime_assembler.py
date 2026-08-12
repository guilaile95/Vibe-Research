"""P0-DI2 — current-only Decision Inbox runtime assembler.

组合已冻结 authorities，不重新读取持仓/Campaign membership：

    #118 holdings_campaign_composition snapshot
      → 每个真实 ACTIVE / REDUCING Campaign
      → DDA1 resolve_strategy_dependencies
      → per-capability results
           ├─ cap.security.price_reference → #116 adapter（readonly lake）
           └─ market_sector / disclosures / financials → NOT_EVALUATED（无 adapter）
      → CCD1 project_campaign_critical_data
      → RA1 project_decision_assurance
      → DI1 CampaignFacts → project_campaign

本 Slice 明确不产生 false clean：
- Hard Risk / Material Change 无授权 authority → 恒 NOT_EVALUATED。
- Formal Thesis / Frozen Decision 仅以 current-only 结构事实读取；
  RA1 的 FORMAL_THESIS / FORMAL_DECISION 维度无 same-as-of 适用性 authority，
  因此保持 NOT_EVALUATED（读取过记录 ≠ 完成评估）。
- 未接 adapter 的 capability 必须 NOT_EVALUATED，绝不因价格可用而整体 USABLE。

只读、零写入、fail closed。所有生产端口均基于既有只读 authorities；
本模块不 import router / app / frontend。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import os
from pathlib import Path
from typing import Any, Callable, Mapping

import campaign_service
import critical_data_dependency_policy as dda
import critical_data_price_reference_adapter as price_adapter
import decision_assurance_projection as ra
import decision_inbox_projection as di
import formal_thesis_projection as thesis_projection
import frozen_decision_service as frozen_service
import holdings_campaign_composition as composition
from campaign_critical_data_projection import project_campaign_critical_data
from fact_lake_store import FactLake, open_existing_fact_lake
from security_exchange_policy import POLICY_VERSION_V01 as SER_POLICY_VERSION


SCHEMA_VERSION = "decision_inbox_runtime.v0.1"
DDA_POLICY_VERSION = dda.POLICY_VERSION_V01

_CAPABILITY_NOT_EVALUATED = frozenset(
    {
        dda.CAP_CONTEXT_MARKET_SECTOR,
        dda.CAP_SECURITY_DISCLOSURES,
        dda.CAP_SECURITY_FINANCIALS,
    }
)

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


def _not_evaluated_result(dependency_id: str, as_of: str) -> dict[str, Any]:
    return {
        "dependency_id": dependency_id,
        "state": "NOT_EVALUATED",
        "as_of": as_of,
        "authority_refs": [],
    }


def _error_result(dependency_id: str, as_of: str) -> dict[str, Any]:
    return {
        "dependency_id": dependency_id,
        "state": "ERROR",
        "as_of": as_of,
        "authority_refs": [],
    }


# ---------------------------------------------------------------------------
# 生产默认 ports（全部只读）
# ---------------------------------------------------------------------------

def _production_lake_provider() -> FactLake | None:
    """返回 readonly Fact Lake；根未配置或不存在 → None（价格未评估）。"""
    raw = os.environ.get(_FACT_LAKE_ROOT_ENV, "").strip()
    if not raw:
        return None
    root = Path(raw)
    if not (root / _FACT_LAKE_CONTROL_FILE).exists():
        return None
    return open_existing_fact_lake(root, readonly=True)


def _production_price_evaluator(
    lake: FactLake, definition: Mapping[str, Any]
) -> dict[str, Any]:
    return price_adapter.evaluate_price_reference_capability(
        lake=lake,
        security_code=definition["security_code"],
        campaign_id=definition["campaign_id"],
        as_of=definition["as_of"],
        security_exchange_policy_version=SER_POLICY_VERSION,
    )


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


@dataclass(frozen=True)
class RuntimePorts:
    """runtime 全部 I/O 端口；测试注入，生产默认绑定既有只读 authorities。"""

    composition_reader: Callable[[], Mapping[str, Any]]
    dependency_resolver: Callable[..., Mapping[str, Any]]
    price_evaluator: Callable[[Any, Mapping[str, Any]], Mapping[str, Any]]
    thesis_reader: Callable[[str], Mapping[str, Any]]
    frozen_decisions_reader: Callable[[str], list[Mapping[str, Any]]]
    lake_provider: Callable[[], FactLake | None]


PRODUCTION_PORTS = RuntimePorts(
    composition_reader=composition.assemble_holdings_campaign_composition,
    dependency_resolver=dda.resolve_strategy_dependencies,
    price_evaluator=_production_price_evaluator,
    thesis_reader=thesis_projection.project_current_thesis,
    frozen_decisions_reader=_production_frozen_decisions_reader,
    lake_provider=_production_lake_provider,
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


# ---------------------------------------------------------------------------
# Thesis / Frozen Decision 归一化（current-only 结构事实）
# ---------------------------------------------------------------------------

def _thesis_normalized(
    thesis_reader: Callable[[str], Mapping[str, Any]],
    campaign_id: str,
) -> tuple[str, str]:
    """返回 (thesis_state, current_thesis)。

    - 未绑定 → (MISSING, UNKNOWN)
    - 未冻结 → (NOT_FROZEN, UNKNOWN)
    - 其他 NOT_READY → (NOT_READY, UNKNOWN)
    - READY → (READY, effective_state)
    """
    try:
        projection = thesis_reader(campaign_id)
    except campaign_service.ThesisBindingNotFoundError:
        return "MISSING", "UNKNOWN"
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
            return "NOT_FROZEN", "UNKNOWN"
        return "NOT_READY", "UNKNOWN"
    effective = projection.get("effective_state")
    if not isinstance(effective, str) or effective not in di.THESIS_STATES:
        raise DecisionInboxRuntimeIntegrityError(
            "thesis effective_state 不是合法 DI1 枚举"
        )
    return "READY", effective


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
    results: list[Mapping[str, Any]] = []
    for dependency_id in definition.get("required_dependency_ids", []):
        if not isinstance(dependency_id, str) or not dependency_id:
            raise DecisionInboxRuntimeIntegrityError(
                "required_dependency_ids 含非法元素"
            )
        if dependency_id == price_adapter.DEPENDENCY_ID:
            if lake is None:
                result = _not_evaluated_result(
                    dependency_id, definition["as_of"]
                )
            else:
                try:
                    result = ports.price_evaluator(lake, definition)
                except price_adapter.PriceReferenceCapabilityError:
                    result = _error_result(
                        dependency_id, definition["as_of"]
                    )
            results.append(
                _validate_capability_result(
                    result,
                    dependency_id=dependency_id,
                    as_of=definition["as_of"],
                )
            )
        elif dependency_id in _CAPABILITY_NOT_EVALUATED:
            results.append(
                _not_evaluated_result(dependency_id, definition["as_of"])
            )
        else:
            raise DecisionInboxRuntimeIntegrityError(
                f"未知 capability: {dependency_id}"
            )
    return results


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

    results = _capability_results(definition, lake=lake, ports=ports)
    ccd = _require_mapping(
        project_campaign_critical_data(
            security_code=definition["security_code"],
            strategy=definition["strategy"],
            campaign_id=definition["campaign_id"],
            as_of=definition["as_of"],
            dependency_set_state=definition["dependency_set_state"],
            dependency_set_authority_refs=definition[
                "dependency_set_authority_refs"
            ],
            required_dependency_ids=definition["required_dependency_ids"],
            dependency_results=results,
        ),
        "CCD projection",
    )
    _assert_same_identity(ccd, definition, label="CCD")
    _assert_literal_as_of(ccd["as_of"], as_of, label="CCD")

    assurance = _require_mapping(
        ra.project_decision_assurance(
            security_code=ccd["security_code"],
            strategy=ccd["strategy"],
            campaign_id=ccd["campaign_id"],
            # current-only：无 same-as-of 适用性 authority，不得声称已评估
            formal_thesis_evaluation="NOT_EVALUATED",
            formal_decision_evaluation="NOT_EVALUATED",
            hard_risk_evaluation="NOT_EVALUATED",
            material_change_evaluation="NOT_EVALUATED",
            critical_data_evaluation=ccd["critical_data_evaluation"],
            as_of=ccd["as_of"],
        ),
        "RA projection",
    )
    _assert_same_identity(assurance, ccd, label="RA")
    _assert_literal_as_of(assurance["as_of"], as_of, label="RA")

    thesis_state, current_thesis = _thesis_normalized(
        ports.thesis_reader, campaign["campaign_id"]
    )
    decisions = ports.frozen_decisions_reader(campaign["campaign_id"])
    latest_frozen = _latest_frozen_decision(
        lambda _campaign_id: decisions, campaign["campaign_id"], as_of
    )
    latest_raw = None
    if latest_frozen is not None:
        for decision in decisions:
            if decision.get("decision_id") == latest_frozen["decision_id"]:
                latest_raw = decision
                break
    confidence = _decision_confidence(latest_frozen, latest_raw)

    authority_refs = list(ccd.get("authority_refs", []))
    facts = di.CampaignFacts(
        security_code=campaign["security_code"],
        strategy=campaign["strategy"],
        campaign_id=campaign["campaign_id"],
        campaign_status=campaign["status"],
        thesis_state=thesis_state,
        current_thesis=current_thesis,
        latest_frozen_decision=latest_frozen,
        hard_risk_state="NOT_EVALUATED",
        material_change_state="NOT_EVALUATED",
        critical_data_state=ccd["critical_data_state"],
        critical_data_evaluation=ccd["critical_data_evaluation"],
        decision_confidence=confidence,
        coverage_complete=bool(assurance["coverage_complete"]),
        as_of=as_of,
        authority_refs=authority_refs,
    )
    return di.project_campaign(facts).to_dict()


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
