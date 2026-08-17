"""P0-DI2 — current-only Decision Inbox runtime assembler domain tests.

全部使用注入式只读 ports；不访问真实数据库、不产生写入、不发网络请求。
DDA / CCD / RA / DI1 使用真实 pure cores，仅 thesis / frozen / price /
market_sector / disclosures / financials / lake 端口注入，以证明组合链语义
而不是 mock 掉权威。三个 capability evaluator 默认注入确定性 fake
（NOT_EVALUATED），真实 evaluator 语义由其各自专项测试覆盖。
"""

from __future__ import annotations

from copy import deepcopy

import pytest

import campaign_service
import campaign_critical_data_runtime as critical_data_runtime
import critical_data_dependency_policy as dda
import critical_data_disclosures_adapter as disclosures_adapter
import critical_data_financials_adapter as financials_adapter
import critical_data_market_sector_adapter as market_sector_adapter
import critical_data_price_reference_adapter as price_adapter
import decision_inbox_projection as di
import decision_inbox_runtime_assembler as runtime
import formal_thesis_projection as thesis_projection
import hard_risk_contract as hr


AS_OF = "2026-08-13T04:00:00.000000Z"
SECURITY = "600519"
SECURITY_B = "000001"
STRATEGY = "SWING"
STRATEGY_MEDIUM = "MEDIUM"
CAMPAIGN_A = "campaign_" + "a" * 32
CAMPAIGN_B = "campaign_" + "b" * 32
THESIS_A = "t" * 32
DECISION_A = "decision_" + "f" * 32
_FAKE_LAKE = object()


def _campaign(
    campaign_id: str = CAMPAIGN_A,
    security_code: str = SECURITY,
    strategy: str = STRATEGY,
    status: str = "ACTIVE",
) -> dict:
    return {
        "campaign_id": campaign_id,
        "security_code": security_code,
        "strategy": strategy,
        "status": status,
        "created_at": "2026-08-01T00:00:00.000000Z",
        "thesis_binding_status": "BOUND",
        "thesis_binding": {
            "thesis_id": THESIS_A,
            "thesis_revision_at_bind": 1,
            "campaign_strategy_at_bind": strategy,
            "bound_at": "2026-08-01T00:00:00.000000Z",
        },
    }


def _composition_item(
    security_code: str = SECURITY,
    security_name: str = "贵州茅台",
    campaigns: list | None = None,
) -> dict:
    campaigns = campaigns or []
    return {
        "item_kind": "HOLDING_COMPOSITION",
        "security_code": security_code,
        "security_name": security_name,
        "holding": {
            "status": "OPEN",
            "shares": 100,
            "cost_basis": 150000.0,
            "avg_cost": 1500.0,
            "cost_known": True,
            "origin": "PRE_VIBE",
        },
        "composition_status": (
            "ASSIGNED_HOLDING" if campaigns else "UNASSIGNED_HOLDING"
        ),
        "campaigns": campaigns,
        "allocation_status": (
            "NOT_APPLICABLE" if not campaigns else "UNKNOWN"
        ),
    }


def _composition(items: list | None = None, evaluated: bool = True) -> dict:
    items = items or []
    return {
        "schema_version": "holdings-campaign-composition.v0.1",
        "evaluation_status": "EVALUATED" if evaluated else "NOT_EVALUATED",
        "canonical": evaluated,
        "reason_codes": [] if evaluated else ["POSITION_LEDGER_NOT_BOOTSTRAPPED"],
        "items": items,
        "total_holdings": len(items),
    }



def _missing_thesis(campaign_id: str) -> dict:
    """模拟未绑定 Current Thesis（无 binding → thesis_reader 抛错）。"""
    raise campaign_service.ThesisBindingNotFoundError("no thesis binding")


def _thesis_ready(effective_state: str = "STABLE") -> dict:
    return {
        "campaign_id": CAMPAIGN_A,
        "thesis_id": THESIS_A,
        "binding": {
            "thesis_revision_at_bind": 1,
            "campaign_strategy_at_bind": STRATEGY,
            "bound_at": "2026-08-01T00:00:00.000000Z",
        },
        "frozen_revision": 1,
        "original_snapshot": {},
        "deltas": [],
        "effective_state": effective_state,
        "ready": True,
        "formal_status": "READY",
    }


def _thesis_not_frozen() -> dict:
    return {
        "campaign_id": CAMPAIGN_A,
        "thesis_id": THESIS_A,
        "binding": {
            "thesis_revision_at_bind": 1,
            "campaign_strategy_at_bind": STRATEGY,
            "bound_at": "2026-08-01T00:00:00.000000Z",
        },
        "formal_state": "draft",
        "frozen_revision": None,
        "ready": False,
        "formal_status": "NOT_READY",
        "reason": "NOT_FROZEN",
    }


def _frozen(
    decision_id: str = DECISION_A,
    committed_at: str = "2026-08-02T00:00:00.000000Z",
    review_by: str = "2026-08-20T00:00:00.000000Z",
    next_best_action: str = "HOLD",
    decision_confidence: str = "HIGH",
) -> dict:
    return {
        "decision_id": decision_id,
        "committed_at": committed_at,
        "review_by": review_by,
        "next_best_action": next_best_action,
        "decision_confidence": decision_confidence,
    }


def _price_usable(_lake, definition: dict) -> dict:
    return {
        "dependency_id": price_adapter.DEPENDENCY_ID,
        "state": "USABLE",
        "as_of": definition["as_of"],
        "authority_refs": [price_adapter.ADAPTER_AUTHORITY_REF],
    }


def _market_sector_not_evaluated(_lake, definition: dict) -> dict:
    return {
        "dependency_id": market_sector_adapter.DEPENDENCY_ID,
        "state": "NOT_EVALUATED",
        "as_of": definition["as_of"],
        "authority_refs": [market_sector_adapter.ADAPTER_AUTHORITY_REF],
    }


def _disclosures_not_evaluated(_lake, definition: dict) -> dict:
    return {
        "dependency_id": disclosures_adapter.DEPENDENCY_ID,
        "state": "NOT_EVALUATED",
        "as_of": definition["as_of"],
        "authority_refs": [disclosures_adapter.ADAPTER_AUTHORITY_REF],
    }


def _financials_not_evaluated(_lake, definition: dict) -> dict:
    return {
        "dependency_id": financials_adapter.DEPENDENCY_ID,
        "state": "NOT_EVALUATED",
        "as_of": definition["as_of"],
        "authority_refs": [
            financials_adapter.ADAPTER_AUTHORITY_REF,
            financials_adapter.REPORT_PERIOD_BLOCKER_REF,
        ],
    }


def _capability_result(dependency_id: str, state: str, as_of: str) -> dict:
    return {
        "dependency_id": dependency_id,
        "state": state,
        "as_of": as_of,
        "authority_refs": [f"test:{dependency_id}"],
    }


def _hr_result(
    definition: dict,
    *,
    state: str,
    evaluation: str,
    reasons: list[str],
    refs: list[str],
) -> dict:
    """构造契约合法 HardRiskEvaluation 形状（identity/as_of 取自 definition）。"""
    return {
        "schema_version": hr.SCHEMA_VERSION,
        "policy_version": hr.POLICY_VERSION_V01,
        "security_code": definition["security_code"],
        "strategy": definition["strategy"],
        "campaign_id": definition["campaign_id"],
        "as_of": definition["as_of"],
        "hard_risk_state": state,
        "hard_risk_evaluation": evaluation,
        "reason_codes": reasons,
        "authority_refs": refs,
    }


def _hr_clear(definition: dict, campaign: dict | None = None, thesis_projection: dict | None = None) -> dict:
    return _hr_result(
        definition, state="CLEAR", evaluation="EVALUATED",
        reasons=[], refs=["hard-risk:fake-clear"],
    )


def _hr_confirmed(definition: dict, campaign: dict | None = None, thesis_projection: dict | None = None) -> dict:
    return _hr_result(
        definition, state="CONFIRMED", evaluation="EVALUATED",
        reasons=["HARD_RISK_CONFIRMED"], refs=["hard-risk:fake-confirmed"],
    )


def _hr_unknown(definition: dict, campaign: dict | None = None, thesis_projection: dict | None = None) -> dict:
    return _hr_result(
        definition, state="UNKNOWN", evaluation="UNKNOWN",
        reasons=["HARD_RISK_INPUT_UNKNOWN"], refs=[],
    )


def _hr_not_evaluated(definition: dict, campaign: dict | None = None, thesis_projection: dict | None = None) -> dict:
    return _hr_result(
        definition, state="NOT_EVALUATED", evaluation="NOT_EVALUATED",
        reasons=["HARD_RISK_NOT_EVALUATED"], refs=[],
    )


def _hr_error(definition: dict, campaign: dict | None = None, thesis_projection: dict | None = None) -> dict:
    return _hr_result(
        definition, state="UNKNOWN", evaluation="ERROR",
        reasons=["HARD_RISK_EVALUATION_ERROR"], refs=[],
    )


def _market_usable(_lake, definition: dict) -> dict:
    return _capability_result(
        market_sector_adapter.DEPENDENCY_ID, "USABLE", definition["as_of"]
    )


def _disclosures_usable(_lake, definition: dict) -> dict:
    return _capability_result(
        disclosures_adapter.DEPENDENCY_ID, "USABLE", definition["as_of"]
    )


def _ports(
    *,
    composition_reader=None,
    thesis_reader=None,
    frozen_reader=None,
    price_evaluator=_price_usable,
    market_sector_evaluator=_market_sector_not_evaluated,
    disclosures_evaluator=_disclosures_not_evaluated,
    financials_evaluator=_financials_not_evaluated,
    hard_risk_evaluator=_hr_not_evaluated,
    lake_provider=lambda: _FAKE_LAKE,
):
    calls = {"thesis": [], "frozen": [], "lake": [], "price": [],
             "market": [], "disclosures": [], "financials": []}

    def _thesis(campaign_id):
        calls["thesis"].append(campaign_id)
        if thesis_reader is None:
            return _thesis_ready()
        if isinstance(thesis_reader, dict):
            return deepcopy(thesis_reader)
        return thesis_reader(campaign_id)

    def _frozen_port(campaign_id):
        calls["frozen"].append(campaign_id)
        if frozen_reader is None:
            return [_frozen()]
        if isinstance(frozen_reader, list):
            return deepcopy(frozen_reader)
        return frozen_reader(campaign_id)

    def _lake():
        calls["lake"].append(True)
        return lake_provider()

    def _price(lake, definition):
        calls["price"].append(True)
        if price_evaluator is None:
            return None
        return price_evaluator(lake, definition)

    def _market(lake, definition):
        calls["market"].append(True)
        return market_sector_evaluator(lake, definition)

    def _disclosures(lake, definition):
        calls["disclosures"].append(True)
        return disclosures_evaluator(lake, definition)

    def _financials(lake, definition):
        calls["financials"].append(True)
        return financials_evaluator(lake, definition)

    def _hard_risk(definition, campaign, thesis_projection):
        return hard_risk_evaluator(definition)

    ports = runtime.RuntimePorts(
        composition_reader=composition_reader or (lambda: _composition()),
        dependency_resolver=dda.resolve_strategy_dependencies,
        price_evaluator=_price,
        market_sector_evaluator=_market,
        disclosures_evaluator=_disclosures,
        financials_evaluator=_financials,
        hard_risk_evaluator=_hard_risk,
        thesis_reader=_thesis,
        frozen_decisions_reader=_frozen_port,
        lake_provider=_lake,
    )
    return ports, calls


def _assemble(ports):
    return runtime.assemble_current_decision_inbox(as_of=AS_OF, ports=ports)


class TestCompositionGate:
    def test_not_evaluated_composition_short_circuits_without_fake_items(self):
        ports, calls = _ports(
            composition_reader=lambda: _composition(evaluated=False)
        )
        result = _assemble(ports)
        assert result["evaluation_status"] == "NOT_EVALUATED"
        assert result["canonical"] is False
        assert result["reason_codes"] == ["POSITION_LEDGER_NOT_BOOTSTRAPPED"]
        assert result["holding_setup_items"] == []
        assert result["campaign_items"] == []
        assert result["total_holdings"] == 0
        assert calls == {"thesis": [], "frozen": [], "lake": [], "price": [], "market": [], "disclosures": [], "financials": []}

    def test_unassigned_holding_is_setup_item_not_campaign_facts(self):
        ports, calls = _ports(
            composition_reader=lambda: _composition(
                [_composition_item(campaigns=[])]
            )
        )
        result = _assemble(ports)
        assert result["evaluation_status"] == "EVALUATED"
        assert len(result["holding_setup_items"]) == 1
        setup = result["holding_setup_items"][0]
        assert setup["item_kind"] == "UNASSIGNED_HOLDING"
        assert setup["security_code"] == SECURITY
        assert setup["reason_codes"] == ["UNASSIGNED_HOLDING"]
        assert setup["next_workflow_action"] == "CREATE_CAMPAIGN"
        assert setup["as_of"] == AS_OF
        assert "campaign_id" not in setup
        assert "strategy" not in setup
        assert result["campaign_items"] == []
        assert calls == {"thesis": [], "frozen": [], "lake": [], "price": [], "market": [], "disclosures": [], "financials": []}

def test_inbox_critical_data_is_the_shared_runtime_projection():
    campaign = _campaign()
    ports, _calls = _ports(
        composition_reader=lambda: _composition(
            [_composition_item(campaigns=[campaign])]
        )
    )

    result = _assemble(ports)
    expected = critical_data_runtime.project_campaign_critical_data(
        campaign=campaign,
        as_of=AS_OF,
        ports=critical_data_runtime.critical_data_ports_from(ports),
        lake=_FAKE_LAKE,
    )
    item = result["campaign_items"][0]

    assert item["critical_data"]["campaign_id"] == expected["campaign_id"]
    assert item["critical_data"]["security_code"] == expected["security_code"]
    assert item["critical_data"]["strategy"] == expected["strategy"]
    assert item["critical_data"]["as_of"] == expected["as_of"]
    assert item["critical_data"]["critical_data_state"] == expected["critical_data_state"]
    assert item["critical_data"]["critical_data_evaluation"] == expected["critical_data_evaluation"]


@pytest.mark.parametrize("critical_state", ["USABLE", "BLOCKED", "UNKNOWN", "STALE"])
def test_inbox_shared_ccd_preserves_all_canonical_domain_states(critical_state):
    campaign = _campaign()

    def result_for(dependency_id):
        def evaluator(_lake, definition):
            return _capability_result(
                dependency_id, critical_state, definition["as_of"]
            )

        return evaluator

    ports, _calls = _ports(
        composition_reader=lambda: _composition(
            [_composition_item(campaigns=[campaign])]
        ),
        price_evaluator=result_for(price_adapter.DEPENDENCY_ID),
        market_sector_evaluator=result_for(market_sector_adapter.DEPENDENCY_ID),
        disclosures_evaluator=result_for(disclosures_adapter.DEPENDENCY_ID),
    )

    result = _assemble(ports)
    expected = critical_data_runtime.project_campaign_critical_data(
        campaign=campaign,
        as_of=AS_OF,
        ports=critical_data_runtime.critical_data_ports_from(ports),
        lake=_FAKE_LAKE,
    )
    item = result["campaign_items"][0]

    assert item["critical_data"]["critical_data_state"] == critical_state
    assert item["critical_data"]["critical_data_evaluation"] == (
        "EVALUATED" if critical_state != "UNKNOWN" else "UNKNOWN"
    )
    for key in ("security_code", "strategy", "campaign_id", "as_of"):
        assert item["critical_data"][key] == expected[key]
    assert item["critical_data"]["critical_data_state"] == expected["critical_data_state"]
    assert item["critical_data"]["critical_data_evaluation"] == expected["critical_data_evaluation"]


class TestFullChain:
    def test_single_assigned_campaign_full_chain_honest_blocked(self):
        ports, _calls = _ports(
            composition_reader=lambda: _composition(
                [_composition_item(campaigns=[_campaign()])]
            )
        )
        result = _assemble(ports)
        assert result["total_campaign_items"] == 1
        item = result["campaign_items"][0]
        assert item["security_code"] == SECURITY
        assert item["strategy"] == STRATEGY
        assert item["campaign_id"] == CAMPAIGN_A
        assert item["campaign_status"] == "ACTIVE"
        assert item["current_thesis"]["thesis_state"] == "READY"
        assert item["current_thesis"]["current_thesis"] == "STABLE"
        assert item["last_frozen_decision"] == {
            "decision_id": DECISION_A,
            "committed_at": "2026-08-02T00:00:00.000000Z",
            "review_by": "2026-08-20T00:00:00.000000Z",
            "previous_next_best_action": "HOLD",
        }
        assert item["hard_risk_state"] == "NOT_EVALUATED"
        assert item["material_change_state"] == "NOT_EVALUATED"
        # price USABLE 但 market_sector/disclosures 未评估（fake NOT_EVALUATED）
        # → 诚实 UNKNOWN / NOT_EVALUATED，绝无 false clean
        assert item["critical_data_state"] == "UNKNOWN"
        assert item["critical_data_evaluation"] == "NOT_EVALUATED"
        assert item["decision_confidence"] == "HIGH"
        assert item["coverage_complete"] is False
        assert item["visible_state"] == "BLOCKED_BY_DATA"
        for code in (
            di.REASON_HARD_RISK_NOT_EVALUATED,
            di.REASON_MATERIAL_CHANGE_NOT_EVALUATED,
            di.REASON_CRITICAL_DATA_NOT_EVALUATED,
            di.REASON_COVERAGE_INCOMPLETE,
        ):
            assert code in item["reason_codes"]
        assert item["as_of"] == AS_OF
        # 全部权威链都在同一 as_of 上（explainability authority_refs 来自 CCD）
        assert price_adapter.ADAPTER_AUTHORITY_REF in item["explainability"][
            "authority_refs"
        ]

    def test_missing_thesis_is_setup_required(self):
        def reader(_campaign_id):
            raise campaign_service.ThesisBindingNotFoundError("missing")

        ports, _calls = _ports(
            composition_reader=lambda: _composition(
                [_composition_item(campaigns=[_campaign()])]
            ),
            thesis_reader=reader,
        )
        item = _assemble(ports)["campaign_items"][0]
        assert item["current_thesis"]["thesis_state"] == "MISSING"
        assert item["current_thesis"]["current_thesis"] == "UNKNOWN"
        assert item["visible_state"] == "SETUP_REQUIRED"
        assert di.REASON_THESIS_MISSING in item["reason_codes"]

    def test_not_frozen_thesis(self):
        ports, _calls = _ports(
            composition_reader=lambda: _composition(
                [_composition_item(campaigns=[_campaign()])]
            ),
            thesis_reader=_thesis_not_frozen(),
        )
        item = _assemble(ports)["campaign_items"][0]
        assert item["current_thesis"]["thesis_state"] == "NOT_FROZEN"
        assert item["visible_state"] == "SETUP_REQUIRED"
        assert di.REASON_THESIS_NOT_FROZEN in item["reason_codes"]

    def test_ready_without_frozen_decision_is_formal_decision_missing(self):
        ports, _calls = _ports(
            composition_reader=lambda: _composition(
                [_composition_item(campaigns=[_campaign()])]
            ),
            frozen_reader=[],
        )
        item = _assemble(ports)["campaign_items"][0]
        assert item["last_frozen_decision"] is None
        assert di.REASON_FORMAL_DECISION_MISSING in item["reason_codes"]
        assert item["visible_state"] == "SETUP_REQUIRED"
        assert item["decision_confidence"] == "UNKNOWN"

    def test_review_by_reached_is_review_required(self):
        ports, _calls = _ports(
            composition_reader=lambda: _composition(
                [_composition_item(campaigns=[_campaign()])]
            ),
            frozen_reader=[_frozen(review_by="2026-08-10T00:00:00.000000Z")],
        )
        item = _assemble(ports)["campaign_items"][0]
        assert di.REASON_REVIEW_BY_REACHED in item["reason_codes"]
        assert item["visible_state"] == "REVIEW_REQUIRED"

    def test_future_frozen_decision_is_not_selected(self):
        ports, _calls = _ports(
            composition_reader=lambda: _composition(
                [_composition_item(campaigns=[_campaign()])]
            ),
            frozen_reader=[
                _frozen(committed_at="2026-08-14T00:00:00.000000Z")
            ],
        )
        item = _assemble(ports)["campaign_items"][0]
        assert item["last_frozen_decision"] is None
        assert di.REASON_FORMAL_DECISION_MISSING in item["reason_codes"]


class TestCapabilityDispatch:
    def test_price_usable_never_cleans_whole_campaign(self):
        ports, _calls = _ports(
            composition_reader=lambda: _composition(
                [_composition_item(campaigns=[_campaign()])]
            )
        )
        item = _assemble(ports)["campaign_items"][0]
        assert item["critical_data_state"] == "UNKNOWN"
        assert item["critical_data_evaluation"] == "NOT_EVALUATED"
        assert item["visible_state"] != "NO_ACTION_REQUIRED"

    def test_price_not_evaluated_when_lake_missing(self):
        ports, calls = _ports(
            composition_reader=lambda: _composition(
                [_composition_item(campaigns=[_campaign()])]
            ),
            lake_provider=lambda: None,
        )
        _assemble(ports)
        assert calls["lake"] == [True]
        assert calls["price"] == []

    def test_price_error_maps_to_critical_data_error(self):
        def broken(_lake, _definition):
            raise price_adapter.PriceReferenceCapabilityError("broken")

        ports, _calls = _ports(
            composition_reader=lambda: _composition(
                [_composition_item(campaigns=[_campaign()])]
            ),
            price_evaluator=broken,
        )
        item = _assemble(ports)["campaign_items"][0]
        assert item["critical_data_evaluation"] == "ERROR"
        assert di.REASON_CRITICAL_DATA_ERROR in item["reason_codes"]

    def test_medium_strategy_dispatch_without_market_sector(self):
        campaign_m = _campaign(
            campaign_id=CAMPAIGN_B,
            strategy=STRATEGY_MEDIUM,
        )
        ports, calls = _ports(
            composition_reader=lambda: _composition(
                [_composition_item(campaigns=[campaign_m])]
            )
        )
        item = _assemble(ports)["campaign_items"][0]
        assert item["strategy"] == STRATEGY_MEDIUM
        assert item["critical_data_evaluation"] == "NOT_EVALUATED"
        assert item["visible_state"] == "BLOCKED_BY_DATA"
        # MEDIUM required = price + disclosures + financials（DDA1 冻结），
        # market_sector 不参与
        assert calls["market"] == []
        assert calls["disclosures"] == [True]
        assert calls["financials"] == [True]

    def test_all_capabilities_usable_maps_through_ccd(self):
        """§11-A：真实 capability USABLE 时 CCD 能消费。"""

        def market_usable(_lake, definition):
            return _capability_result(
                market_sector_adapter.DEPENDENCY_ID, "USABLE",
                definition["as_of"],
            )

        def disclosures_usable(_lake, definition):
            return _capability_result(
                disclosures_adapter.DEPENDENCY_ID, "USABLE",
                definition["as_of"],
            )

        ports, _calls = _ports(
            composition_reader=lambda: _composition(
                [_composition_item(campaigns=[_campaign()])]
            ),
            market_sector_evaluator=market_usable,
            disclosures_evaluator=disclosures_usable,
        )
        item = _assemble(ports)["campaign_items"][0]
        # price + market_sector + disclosures 全 USABLE（SWING 依赖集）
        assert item["critical_data_state"] == "USABLE"
        assert item["critical_data_evaluation"] == "EVALUATED"
        # 但仍不得 false clean：thesis/frozen 之外 hard risk 等仍 NOT_EVALUATED
        assert item["visible_state"] != "NO_ACTION_REQUIRED"

    def test_market_sector_usable_alone_keeps_unknown_for_swing(self):
        """市场 USABLE 但 disclosures 未评估 → critical_data 仍非 USABLE。"""

        def market_usable(_lake, definition):
            return _capability_result(
                market_sector_adapter.DEPENDENCY_ID, "USABLE",
                definition["as_of"],
            )

        ports, _calls = _ports(
            composition_reader=lambda: _composition(
                [_composition_item(campaigns=[_campaign()])]
            ),
            market_sector_evaluator=market_usable,
        )
        item = _assemble(ports)["campaign_items"][0]
        assert item["critical_data_state"] == "UNKNOWN"
        assert item["critical_data_evaluation"] == "NOT_EVALUATED"

    def test_market_sector_error_maps_to_critical_data_error(self):
        def broken(_lake, _definition):
            raise market_sector_adapter.MarketSectorCapabilityError("broken")

        ports, _calls = _ports(
            composition_reader=lambda: _composition(
                [_composition_item(campaigns=[_campaign()])]
            ),
            market_sector_evaluator=broken,
        )
        item = _assemble(ports)["campaign_items"][0]
        assert item["critical_data_evaluation"] == "ERROR"
        assert di.REASON_CRITICAL_DATA_ERROR in item["reason_codes"]

    def test_financials_blocker_ref_flows_into_explainability(self):
        """§11-F：financials applicability 未解决 → NOT_EVALUATED + 显式 blocker。"""

        def financials_blocked(_lake, definition):
            return _financials_not_evaluated(_lake, definition)

        campaign_m = _campaign(
            campaign_id=CAMPAIGN_B,
            strategy=STRATEGY_MEDIUM,
        )
        ports, _calls = _ports(
            composition_reader=lambda: _composition(
                [_composition_item(campaigns=[campaign_m])]
            ),
            financials_evaluator=financials_blocked,
        )
        item = _assemble(ports)["campaign_items"][0]
        assert item["critical_data_evaluation"] == "NOT_EVALUATED"
        assert item["visible_state"] != "NO_ACTION_REQUIRED"
        # blocker 经 authority_refs 显式可见（CCD exact-shape contract 无法
        # 扩字段，故 blocker 以稳定 ref 字符串承载）
        assert financials_adapter.REPORT_PERIOD_BLOCKER_REF in item[
            "explainability"]["authority_refs"
        ]

    def test_multi_campaign_keeps_independent_identity(self):
        ports, _calls = _ports(
            composition_reader=lambda: _composition(
                [
                    _composition_item(
                        campaigns=[
                            _campaign(campaign_id=CAMPAIGN_A, status="ACTIVE"),
                            _campaign(
                                campaign_id=CAMPAIGN_B,
                                status="REDUCING",
                            ),
                        ]
                    )
                ]
            )
        )
        items = _assemble(ports)["campaign_items"]
        assert [i["campaign_id"] for i in items] == [CAMPAIGN_A, CAMPAIGN_B]
        assert [i["campaign_status"] for i in items] == ["ACTIVE", "REDUCING"]


class TestFailClosed:
    def test_dda_identity_mismatch_fails_closed(self):
        def bad_resolver(**kwargs):
            result = dda.resolve_strategy_dependencies(**kwargs)
            result["security_code"] = SECURITY_B
            return result

        ports, _calls = _ports(
            composition_reader=lambda: _composition(
                [_composition_item(campaigns=[_campaign()])]
            )
        )
        ports = runtime.RuntimePorts(
            composition_reader=ports.composition_reader,
            dependency_resolver=bad_resolver,
            price_evaluator=ports.price_evaluator,
            thesis_reader=ports.thesis_reader,
            frozen_decisions_reader=ports.frozen_decisions_reader,
            lake_provider=ports.lake_provider,
        )
        with pytest.raises(runtime.DecisionInboxRuntimeIntegrityError):
            _assemble(ports)

    def test_price_result_as_of_mismatch_fails_closed(self):
        def wrong_as_of(_lake, definition):
            result = _price_usable(_lake, definition)
            result["as_of"] = "2026-08-12T00:00:00.000000Z"
            return result

        ports, _calls = _ports(
            composition_reader=lambda: _composition(
                [_composition_item(campaigns=[_campaign()])]
            ),
            price_evaluator=wrong_as_of,
        )
        with pytest.raises(runtime.DecisionInboxRuntimeIntegrityError):
            _assemble(ports)

    def test_thesis_integrity_error_fails_closed(self):
        def broken(_campaign_id):
            raise thesis_projection.CurrentThesisProjectionError("broken")

        ports, _calls = _ports(
            composition_reader=lambda: _composition(
                [_composition_item(campaigns=[_campaign()])]
            ),
            thesis_reader=broken,
        )
        with pytest.raises(runtime.DecisionInboxRuntimeIntegrityError):
            _assemble(ports)

    def test_confidence_unknown_when_stored_value_invalid(self):
        ports, _calls = _ports(
            composition_reader=lambda: _composition(
                [_composition_item(campaigns=[_campaign()])]
            ),
            frozen_reader=[_frozen(decision_confidence="WEIRD")],
        )
        item = _assemble(ports)["campaign_items"][0]
        assert item["decision_confidence"] == "UNKNOWN"


class TestDeterminism:
    def test_repeated_calls_deep_equal_and_input_isolated(self):
        source = _composition([_composition_item(campaigns=[_campaign()])])
        ports, _calls = _ports(composition_reader=lambda: deepcopy(source))
        first = _assemble(ports)
        second = _assemble(ports)
        assert first == second
        assert source["items"][0]["campaigns"][0]["status"] == "ACTIVE"

    def test_all_authorities_share_literal_as_of(self):
        ports, calls = _ports(
            composition_reader=lambda: _composition(
                [_composition_item(campaigns=[_campaign()])]
            )
        )
        result = _assemble(ports)
        assert result["as_of"] == AS_OF
        item = result["campaign_items"][0]
        assert item["as_of"] == AS_OF


# ---------------------------------------------------------------------------
# P0-HR1 — Hard Risk → Decision Inbox runtime integration
# ---------------------------------------------------------------------------

def _capture_assurance(monkeypatch) -> dict:
    """包装 RA1，捕获 assembler 传入的维度状态（验证不复制/不降级）。"""
    captured: dict = {}
    real = runtime.ra.project_decision_assurance

    def spy(**kwargs):
        captured.update(kwargs)
        return real(**kwargs)

    monkeypatch.setattr(runtime.ra, "project_decision_assurance", spy)
    return captured


def _swing_item(ports):
    return _assemble(ports)["campaign_items"][0]


class TestHardRiskIntegration:
    """A/C：CLEAR + EVALUATED → RA EVALUATED → DI 收到 CLEAR。"""

    def test_clear_maps_evaluated_and_di_receives_clear(self, monkeypatch):
        captured = _capture_assurance(monkeypatch)
        ports, _calls = _ports(
            composition_reader=lambda: _composition(
                [_composition_item(campaigns=[_campaign()])]
            ),
            hard_risk_evaluator=_hr_clear,
        )
        item = _swing_item(ports)
        assert item["hard_risk_state"] == "CLEAR"
        assert captured["hard_risk_evaluation"] == "EVALUATED"
        # CLEAR 不产生任何 HARD_RISK reason；CLEAR 也不强制 NO_ACTION_REQUIRED
        # （critical data 仍 NOT_EVALUATED → BLOCKED_BY_DATA，DI1 自己决定）
        assert not any("HARD_RISK" in code for code in item["reason_codes"])
        assert item["visible_state"] == "BLOCKED_BY_DATA"
        # 正证明 refs 并入 explainability（不丢失 CLEAR 的依据）
        assert "hard-risk:fake-clear" in item["explainability"]["authority_refs"]

    def test_clear_is_never_in_uncertainties(self, monkeypatch):
        _capture_assurance(monkeypatch)
        ports, _calls = _ports(
            composition_reader=lambda: _composition(
                [_composition_item(campaigns=[_campaign()])]
            ),
            hard_risk_evaluator=_hr_clear,
        )
        item = _swing_item(ports)
        uncertainties = " ".join(item["explainability"]["uncertainties"])
        assert "hard_risk" not in uncertainties

    """B：CONFIRMED + EVALUATED → DI1 REVIEW_REQUIRED（既有 reason 语义）。"""

    def test_confirmed_maps_review_required_via_di1(self, monkeypatch):
        captured = _capture_assurance(monkeypatch)
        ports, _calls = _ports(
            composition_reader=lambda: _composition(
                [_composition_item(campaigns=[_campaign()])]
            ),
            hard_risk_evaluator=_hr_confirmed,
        )
        item = _swing_item(ports)
        assert item["hard_risk_state"] == "CONFIRMED"
        assert captured["hard_risk_evaluation"] == "EVALUATED"
        assert di.REASON_HARD_RISK_CONFIRMED in item["reason_codes"]
        assert item["visible_state"] == "REVIEW_REQUIRED"
        assert (
            item["explainability"]["next_workflow_action"]
            == "REVIEW_FORMAL_DECISION"
        )

    """C/D：UNKNOWN / NOT_EVALUATED 绝不映射 CLEAR，绝不 clean。"""

    def test_unknown_never_maps_clear(self, monkeypatch):
        captured = _capture_assurance(monkeypatch)
        ports, _calls = _ports(
            composition_reader=lambda: _composition(
                [_composition_item(campaigns=[_campaign()])]
            ),
            hard_risk_evaluator=_hr_unknown,
            market_sector_evaluator=_market_usable,
            disclosures_evaluator=_disclosures_usable,
        )
        item = _swing_item(ports)
        assert item["hard_risk_state"] == "UNKNOWN"
        assert captured["hard_risk_evaluation"] == "UNKNOWN"
        assert di.REASON_HARD_RISK_UNKNOWN in item["reason_codes"]
        assert item["visible_state"] != "NO_ACTION_REQUIRED"
        assert item["visible_state"] != "REVIEW_REQUIRED"
        assert item["hard_risk_state"] != "CLEAR"

    def test_not_evaluated_never_maps_clear_and_coverage_incomplete(
        self, monkeypatch
    ):
        captured = _capture_assurance(monkeypatch)
        ports, _calls = _ports(
            composition_reader=lambda: _composition(
                [_composition_item(campaigns=[_campaign()])]
            ),
            hard_risk_evaluator=_hr_not_evaluated,
            market_sector_evaluator=_market_usable,
            disclosures_evaluator=_disclosures_usable,
        )
        item = _swing_item(ports)
        assert item["hard_risk_state"] == "NOT_EVALUATED"
        assert captured["hard_risk_evaluation"] == "NOT_EVALUATED"
        assert di.REASON_HARD_RISK_NOT_EVALUATED in item["reason_codes"]
        assert item["coverage_complete"] is False
        assert item["visible_state"] != "NO_ACTION_REQUIRED"
        assert item["hard_risk_state"] != "CLEAR"

    """E：ERROR 保持 ERROR（RA1 维度不降级成 UNKNOWN/CLEAR）。"""

    def test_error_is_not_downgraded(self, monkeypatch):
        captured = _capture_assurance(monkeypatch)
        ports, _calls = _ports(
            composition_reader=lambda: _composition(
                [_composition_item(campaigns=[_campaign()])]
            ),
            hard_risk_evaluator=_hr_error,
            market_sector_evaluator=_market_usable,
            disclosures_evaluator=_disclosures_usable,
        )
        item = _swing_item(ports)
        # 契约 pair：UNKNOWN + ERROR
        assert item["hard_risk_state"] == "UNKNOWN"
        # RA1 收到的是 ERROR 原值（绝不降级成 UNKNOWN/CLEAR）
        assert captured["hard_risk_evaluation"] == "ERROR"
        assert item["coverage_complete"] is False
        assert di.REASON_COVERAGE_INCOMPLETE in item["reason_codes"]
        assert item["visible_state"] != "NO_ACTION_REQUIRED"

    """F：malformed contract → fail closed（integrity）。"""

    def test_extra_field_malformed_contract_fails_closed(self):
        def malformed(definition):
            return {**_hr_clear(definition), "unexpected": True}

        ports, _calls = _ports(
            composition_reader=lambda: _composition(
                [_composition_item(campaigns=[_campaign()])]
            ),
            hard_risk_evaluator=malformed,
        )
        with pytest.raises(runtime.DecisionInboxRuntimeIntegrityError):
            _assemble(ports)

    def test_illegal_state_evaluation_pair_fails_closed(self):
        def illegal(definition):
            return _hr_result(
                definition, state="CLEAR", evaluation="NOT_EVALUATED",
                reasons=["INVALID_PAIR"], refs=["hard-risk:fake"],
            )

        ports, _calls = _ports(
            composition_reader=lambda: _composition(
                [_composition_item(campaigns=[_campaign()])]
            ),
            hard_risk_evaluator=illegal,
        )
        with pytest.raises(runtime.DecisionInboxRuntimeIntegrityError):
            _assemble(ports)

    """G/H/I：identity 不逐字一致 → fail closed。"""

    @pytest.mark.parametrize(
        "patch",
        [
            {"security_code": "000001"},
            {"strategy": "SHORT"},
            {"campaign_id": "campaign_" + "b" * 32},
        ],
    )
    def test_identity_mismatch_fails_closed(self, patch):
        def wrong_identity(definition):
            result = _hr_clear(definition)
            result.update(patch)
            return result

        ports, _calls = _ports(
            composition_reader=lambda: _composition(
                [_composition_item(campaigns=[_campaign()])]
            ),
            hard_risk_evaluator=wrong_identity,
        )
        with pytest.raises(runtime.DecisionInboxRuntimeIntegrityError):
            _assemble(ports)

    """J：as_of 必须 literal 相同（同一时刻不同格式也拒绝）。"""

    def test_as_of_literal_mismatch_fails_closed(self):
        def wrong_as_of(definition):
            result = _hr_clear(definition)
            result["as_of"] = "2026-08-13T04:00:00Z"
            return result

        ports, _calls = _ports(
            composition_reader=lambda: _composition(
                [_composition_item(campaigns=[_campaign()])]
            ),
            hard_risk_evaluator=wrong_as_of,
        )
        with pytest.raises(runtime.DecisionInboxRuntimeIntegrityError):
            _assemble(ports)

    """K：同 security 兄弟 Campaign 各自独立评估（identity 不串）。"""

    def test_same_security_sibling_campaign_isolation(self):
        campaign_swing = _campaign(
            campaign_id=CAMPAIGN_A, strategy=STRATEGY
        )
        campaign_medium = _campaign(
            campaign_id=CAMPAIGN_B, strategy=STRATEGY_MEDIUM
        )
        seen: list[tuple[str, str, str]] = []
        states_by_campaign = {
            CAMPAIGN_A: ("CLEAR", "EVALUATED", [], ["hard-risk:a"]),
            CAMPAIGN_B: ("CONFIRMED", "EVALUATED", ["HARD_RISK_CONFIRMED"],
                         ["hard-risk:b"]),
        }

        def evaluator(definition):
            seen.append(
                (
                    definition["security_code"],
                    definition["strategy"],
                    definition["campaign_id"],
                )
            )
            state, evaluation, reasons, refs = states_by_campaign[
                definition["campaign_id"]
            ]
            return _hr_result(
                definition, state=state, evaluation=evaluation,
                reasons=reasons, refs=refs,
            )

        ports, _calls = _ports(
            composition_reader=lambda: _composition(
                [
                    _composition_item(
                        campaigns=[campaign_swing, campaign_medium]
                    )
                ]
            ),
            hard_risk_evaluator=evaluator,
        )
        items = _assemble(ports)["campaign_items"]
        by_id = {item["campaign_id"]: item for item in items}
        assert by_id[CAMPAIGN_A]["hard_risk_state"] == "CLEAR"
        assert by_id[CAMPAIGN_B]["hard_risk_state"] == "CONFIRMED"
        # 每个 evaluator 调用收到的 identity 与其 campaign 精确一致
        assert (SECURITY, STRATEGY, CAMPAIGN_A) in seen
        assert (SECURITY, STRATEGY_MEDIUM, CAMPAIGN_B) in seen

    """L：CONFIRMED + Critical Data blocker → 既有 DI1 precedence 保持。"""

    def test_confirmed_plus_critical_data_blocker_keeps_di1_precedence(self):
        def broken_price(_lake, _definition):
            raise price_adapter.PriceReferenceCapabilityError("broken")

        ports, _calls = _ports(
            composition_reader=lambda: _composition(
                [_composition_item(campaigns=[_campaign()])]
            ),
            price_evaluator=broken_price,
            hard_risk_evaluator=_hr_confirmed,
        )
        item = _swing_item(ports)
        assert item["hard_risk_state"] == "CONFIRMED"
        assert di.REASON_HARD_RISK_CONFIRMED in item["reason_codes"]
        assert di.REASON_CRITICAL_DATA_ERROR in item["reason_codes"]
        # DI1 PHASE B：CONFIRMED 先于 generic data 层 → REVIEW_REQUIRED
        assert item["visible_state"] == "REVIEW_REQUIRED"

    """M：CONFIRMED 不产生 EXIT/SELL（action envelope 不越权）。"""

    def test_confirmed_never_emits_exit_sell(self):
        ports, _calls = _ports(
            composition_reader=lambda: _composition(
                [_composition_item(campaigns=[_campaign()])]
            ),
            hard_risk_evaluator=_hr_confirmed,
        )
        item = _swing_item(ports)
        assert (
            item["explainability"]["next_workflow_action"]
            == "REVIEW_FORMAL_DECISION"
        )
        # 既有 frozen decision 的 next_best_action 不被覆盖
        assert (
            item["last_frozen_decision"]["previous_next_best_action"] == "HOLD"
        )
        serialized = str(item)
        assert "EXIT" not in serialized
        assert "SELL" not in serialized

    """production 默认端口（C 未接入）：显式 NOT_EVALUATED，绝不猜 CLEAR。"""

    def test_production_port_not_evaluated_when_thesis_missing(self):
        """production port 真实绑定 C：未绑定 Current Thesis → NOT_EVALUATED。"""
        base, _calls = _ports(
            composition_reader=lambda: _composition(
                [_composition_item(campaigns=[_campaign()])]
            )
        )
        ports = runtime.RuntimePorts(
            composition_reader=base.composition_reader,
            dependency_resolver=dda.resolve_strategy_dependencies,
            price_evaluator=base.price_evaluator,
            market_sector_evaluator=base.market_sector_evaluator,
            disclosures_evaluator=base.disclosures_evaluator,
            financials_evaluator=base.financials_evaluator,
            thesis_reader=_missing_thesis,
            frozen_decisions_reader=base.frozen_decisions_reader,
            lake_provider=base.lake_provider,
        )
        item = _swing_item(ports)
        assert item["hard_risk_state"] == "NOT_EVALUATED"
        assert item["hard_risk_evaluation"] == "NOT_EVALUATED"
        assert di.REASON_HARD_RISK_NOT_EVALUATED in item["reason_codes"]
        assert item["hard_risk_state"] != "CLEAR"

    def test_production_port_stable_thesis_never_clear(self):
        """production port：READY + STABLE（非 terminal）→ UNKNOWN，绝不 CLEAR。"""
        base, _calls = _ports(
            composition_reader=lambda: _composition(
                [_composition_item(campaigns=[_campaign()])]
            )
        )
        ports = runtime.RuntimePorts(
            composition_reader=base.composition_reader,
            dependency_resolver=dda.resolve_strategy_dependencies,
            price_evaluator=base.price_evaluator,
            market_sector_evaluator=base.market_sector_evaluator,
            disclosures_evaluator=base.disclosures_evaluator,
            financials_evaluator=base.financials_evaluator,
            thesis_reader=base.thesis_reader,
            frozen_decisions_reader=base.frozen_decisions_reader,
            lake_provider=base.lake_provider,
        )
        item = _swing_item(ports)
        assert item["hard_risk_state"] == "UNKNOWN"
        assert item["hard_risk_evaluation"] == "UNKNOWN"
        assert item["hard_risk_state"] != "CLEAR"
        assert item["hard_risk_authority_refs"] != []
        assert item["visible_state"] != "NO_ACTION_REQUIRED"

    """evaluator 自身异常 → 整体 fail closed（不猜 C 的异常类型）。"""

    def test_evaluator_exception_fails_closed(self):
        def broken(_definition):
            raise RuntimeError("hard risk source down")

        ports, _calls = _ports(
            composition_reader=lambda: _composition(
                [_composition_item(campaigns=[_campaign()])]
            ),
            hard_risk_evaluator=broken,
        )
        with pytest.raises(runtime.DecisionInboxRuntimeError):
            _assemble(ports)

    # ------------------------------------------------------------------
    # O lane：Campaign item 暴露 Hard Risk 专属 provenance（与 DI1 generic
    # explainability 严格隔离；专属字段直接来自 contract-validated 结果）
    # ------------------------------------------------------------------

    def test_confirmed_exposes_exact_hard_risk_fields(self):
        ports, _calls = _ports(
            composition_reader=lambda: _composition(
                [_composition_item(campaigns=[_campaign()])]
            ),
            hard_risk_evaluator=_hr_confirmed,
        )
        item = _swing_item(ports)
        assert item["hard_risk_state"] == "CONFIRMED"
        assert item["hard_risk_evaluation"] == "EVALUATED"
        assert item["hard_risk_reason_codes"] == ["HARD_RISK_CONFIRMED"]
        assert item["hard_risk_authority_refs"] == ["hard-risk:fake-confirmed"]

    def test_clear_exposes_exact_hard_risk_fields(self):
        ports, _calls = _ports(
            composition_reader=lambda: _composition(
                [_composition_item(campaigns=[_campaign()])]
            ),
            hard_risk_evaluator=_hr_clear,
        )
        item = _swing_item(ports)
        assert item["hard_risk_state"] == "CLEAR"
        assert item["hard_risk_evaluation"] == "EVALUATED"
        assert item["hard_risk_reason_codes"] == []
        assert item["hard_risk_authority_refs"] == ["hard-risk:fake-clear"]

    def test_error_keeps_evaluation_error_in_payload(self):
        ports, _calls = _ports(
            composition_reader=lambda: _composition(
                [_composition_item(campaigns=[_campaign()])]
            ),
            hard_risk_evaluator=_hr_error,
        )
        item = _swing_item(ports)
        assert item["hard_risk_state"] == "UNKNOWN"
        assert item["hard_risk_evaluation"] == "ERROR"
        assert item["hard_risk_reason_codes"] == ["HARD_RISK_EVALUATION_ERROR"]
        assert item["hard_risk_authority_refs"] == []

    def test_not_evaluated_keeps_own_reasons(self):
        ports, _calls = _ports(
            composition_reader=lambda: _composition(
                [_composition_item(campaigns=[_campaign()])]
            ),
            hard_risk_evaluator=_hr_not_evaluated,
        )
        item = _swing_item(ports)
        assert item["hard_risk_state"] == "NOT_EVALUATED"
        assert item["hard_risk_evaluation"] == "NOT_EVALUATED"
        assert item["hard_risk_reason_codes"] == ["HARD_RISK_NOT_EVALUATED"]
        assert item["hard_risk_authority_refs"] == []

    def test_provenance_isolation_from_critical_data(self):
        """E：Hard Risk refs 严格专属；generic explainability 允许两者。"""

        def hr_proof(definition):
            return _hr_result(
                definition, state="CONFIRMED", evaluation="EVALUATED",
                reasons=["HARD_RISK_CONFIRMED"], refs=["hard-risk:proof"],
            )

        def cd_proof(dependency_id):
            def evaluator(_lake, definition):
                return {
                    "dependency_id": dependency_id,
                    "state": "USABLE",
                    "as_of": definition["as_of"],
                    "authority_refs": ["critical-data:proof"],
                }

            return evaluator

        ports, _calls = _ports(
            composition_reader=lambda: _composition(
                [_composition_item(campaigns=[_campaign()])]
            ),
            hard_risk_evaluator=hr_proof,
            market_sector_evaluator=cd_proof(
                market_sector_adapter.DEPENDENCY_ID
            ),
            disclosures_evaluator=cd_proof(
                disclosures_adapter.DEPENDENCY_ID
            ),
        )
        item = _swing_item(ports)
        # 专属字段严格 == evaluator 原始 refs，绝不混入 critical-data:proof
        assert item["hard_risk_authority_refs"] == ["hard-risk:proof"]
        # generic explainability 允许同时包含两者
        generic = item["explainability"]["authority_refs"]
        assert "hard-risk:proof" in generic
        assert "critical-data:proof" in generic

    def test_reason_isolation_from_generic_reasons(self):
        """F：专属 reason_codes 只能是 evaluator 原始 reasons。"""

        ports, _calls = _ports(
            composition_reader=lambda: _composition(
                [_composition_item(campaigns=[_campaign()])]
            ),
            hard_risk_evaluator=_hr_confirmed,
        )
        item = _swing_item(ports)
        # 专属字段不含 generic reasons（CRITICAL_DATA_* / COVERAGE_*）
        assert item["hard_risk_reason_codes"] == ["HARD_RISK_CONFIRMED"]
        assert not any(
            code.startswith("CRITICAL_DATA_") or "COVERAGE" in code
            for code in item["hard_risk_reason_codes"]
        )
        # generic reason_codes 同时包含 HR + Critical Data + Coverage
        generic = item["reason_codes"]
        assert di.REASON_HARD_RISK_CONFIRMED in generic
        assert any(
            code.startswith("CRITICAL_DATA_") for code in generic
        )
        assert di.REASON_COVERAGE_INCOMPLETE in generic

    def test_di1_state_mismatch_fails_closed(self, monkeypatch):
        """DI1 输出的 hard_risk_state 与 HardRiskEvaluation 不一致 → 500。"""

        class _TamperedItem:
            def __init__(self, inner, replacement):
                self._inner = inner
                self._replacement = replacement

            def to_dict(self):
                result = self._inner.to_dict()
                result["hard_risk_state"] = self._replacement
                return result

        real = runtime.di.project_campaign

        def tampered(facts):
            inner = real(facts)
            replacement = (
                "CONFIRMED" if facts.hard_risk_state != "CONFIRMED"
                else "CLEAR"
            )
            return _TamperedItem(inner, replacement)

        monkeypatch.setattr(runtime.di, "project_campaign", tampered)
        ports, _calls = _ports(
            composition_reader=lambda: _composition(
                [_composition_item(campaigns=[_campaign()])]
            ),
            hard_risk_evaluator=_hr_confirmed,
        )
        with pytest.raises(runtime.DecisionInboxRuntimeIntegrityError):
            _assemble(ports)
