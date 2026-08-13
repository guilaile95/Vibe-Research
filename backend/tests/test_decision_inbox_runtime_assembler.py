"""P0-DI2 — current-only Decision Inbox runtime assembler domain tests.

全部使用注入式只读 ports；不访问真实数据库、不产生写入。
DDA / CCD / RA / DI1 使用真实 pure cores，仅 thesis / frozen / price / lake
端口注入，以证明组合链语义而不是 mock 掉权威。
"""

from __future__ import annotations

from copy import deepcopy

import pytest

import campaign_service
import critical_data_dependency_policy as dda
import critical_data_price_reference_adapter as price_adapter
import decision_inbox_projection as di
import decision_inbox_runtime_assembler as runtime
import formal_thesis_projection as thesis_projection


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


def _ports(
    *,
    composition_reader=None,
    thesis_reader=None,
    frozen_reader=None,
    price_evaluator=_price_usable,
    lake_provider=lambda: _FAKE_LAKE,
):
    calls = {"thesis": [], "frozen": [], "lake": [], "price": []}

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

    ports = runtime.RuntimePorts(
        composition_reader=composition_reader or (lambda: _composition()),
        dependency_resolver=dda.resolve_strategy_dependencies,
        price_evaluator=_price,
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
        assert calls == {"thesis": [], "frozen": [], "lake": [], "price": []}

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
        assert calls == {"thesis": [], "frozen": [], "lake": [], "price": []}


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
        # price USABLE 但 market_sector/disclosures 缺 adapter → 诚实 UNKNOWN
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
        ports, _calls = _ports(
            composition_reader=lambda: _composition(
                [_composition_item(campaigns=[campaign_m])]
            )
        )
        item = _assemble(ports)["campaign_items"][0]
        assert item["strategy"] == STRATEGY_MEDIUM
        assert item["critical_data_evaluation"] == "NOT_EVALUATED"
        assert item["visible_state"] == "BLOCKED_BY_DATA"

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
