"""Adversarial tests for the DC1 production Sell Engine boundary."""

from __future__ import annotations

import inspect

import pytest

import sell_engine_projection as sell_module
from decision_evidence_delta_projection import (
    DecisionContext,
    NormalizedEvidenceItem,
    TIME_SEMANTICS_AUTHORITATIVE,
    project_decision_evidence_delta,
)
from hard_risk_contract import HardRiskEvaluation
from material_change_projection import (
    CurrentThesisAuthority,
    current_thesis_authority_from_mapping,
    project_material_change,
)
from sell_engine_projection import SellEngineValidationError, project_sell_engine


SECURITY = "600519"
STRATEGY = "SWING"
CAMPAIGN = "campaign_" + "a" * 32
DECISION_ID = "decision_" + "d" * 32
THESIS_ID = "e" * 32
BOUNDARY = "2026-08-10T00:00:00.000000Z"
AS_OF = "2026-08-16T00:00:00Z"

UNIMPLEMENTED = (
    "risk_exit",
    "expectation_price_in",
    "risk_reward",
    "catalyst",
    "portfolio_rebalance",
    "opportunity_cost",
    "technical_execution",
)


def _delta(kind: str = "preexisting"):
    context = DecisionContext(
        security_code=SECURITY,
        strategy=STRATEGY,
        campaign_id=CAMPAIGN,
        decision_id=DECISION_ID,
        decision_boundary_at=BOUNDARY,
    )
    effective = (
        "2026-08-11T00:00:00.000000Z"
        if kind == "new"
        else "2026-08-09T00:00:00.000000Z"
    )
    item = NormalizedEvidenceItem(
        evidence_id="1" * 32,
        scope_kind="security",
        scope_id=SECURITY,
        effective_at=effective,
        retrieved_at="2026-08-16T00:00:00.000000Z",
        time_semantics=TIME_SEMANTICS_AUTHORITATIVE,
        authority_refs=("evidence:fixture",),
    )
    return project_decision_evidence_delta(context=context, evidence_items=(item,))


def _thesis(state: str = "STABLE", *, strategy: str = STRATEGY) -> CurrentThesisAuthority:
    latest = None
    deltas: list[dict] = []
    if state != "STABLE":
        latest = {
            "delta_id": "f" * 32,
            "delta_sequence": 1,
            "delta_state": state,
            "reason": "fixture",
            "confirmed_at": "2026-08-12T00:00:00Z",
            "evidence_snapshots": [],
        }
        deltas = [latest]
    return current_thesis_authority_from_mapping(
        {
            "campaign_id": CAMPAIGN,
            "security_code": SECURITY,
            "strategy": strategy,
            "as_of": AS_OF,
            "authority_refs": ["formal_current_thesis:fixture"],
            "projection": {
                "schema_version": "formal_current_thesis.projection.v0.1",
                "campaign_id": CAMPAIGN,
                "thesis_id": THESIS_ID,
                "formal_status": "READY",
                "original": {"revision": 1, "snapshot": {"core": "fixture"}},
                "binding_audit": {},
                "strategy": strategy,
                "expected_horizon": {"unit": "TRADING_DAY"},
                "effective_state": state,
                "latest_delta": latest,
                "terminal": state in {"DISPROVEN", "INVALIDATED"},
                "deltas": deltas,
            },
        }
    )


def _hard(
    state: str = "CLEAR",
    evaluation: str = "EVALUATED",
    *,
    security_code: str = SECURITY,
    strategy: str = STRATEGY,
) -> HardRiskEvaluation:
    return HardRiskEvaluation(
        security_code=security_code,
        strategy=strategy,
        campaign_id=CAMPAIGN,
        as_of=AS_OF,
        hard_risk_state=state,
        hard_risk_evaluation=evaluation,
        reason_codes=() if state == "CLEAR" else (f"HARD_RISK_{state}",),
        authority_refs=("hard_risk:fixture",),
    )


def _material(
    *,
    evidence: str = "preexisting",
    thesis: CurrentThesisAuthority | None = None,
    hard: HardRiskEvaluation | None = None,
):
    return project_material_change(
        security_code=SECURITY,
        strategy=STRATEGY,
        campaign_id=CAMPAIGN,
        as_of=AS_OF,
        decision_evidence_delta=_delta(evidence),
        current_thesis_authority=_thesis() if thesis is None else thesis,
        hard_risk_evaluation=_hard() if hard is None else hard,
    )


def _project(
    *,
    thesis: CurrentThesisAuthority | None = None,
    hard: HardRiskEvaluation | None = None,
    material=None,
):
    return project_sell_engine(
        security_code=SECURITY,
        strategy=STRATEGY,
        campaign_id=CAMPAIGN,
        as_of=AS_OF,
        current_thesis_authority=_thesis() if thesis is None else thesis,
        hard_risk_evaluation=_hard() if hard is None else hard,
        material_change=_material() if material is None else material,
    )


def test_production_signature_has_no_caller_declared_pressure_ports():
    parameters = inspect.signature(project_sell_engine).parameters
    assert {
        "risk_exit",
        "expectation_price_in",
        "risk_reward",
        "catalyst",
        "portfolio_rebalance",
        "opportunity_cost",
        "technical_execution",
    }.isdisjoint(parameters)
    assert "pnl" not in parameters
    assert "action" not in parameters
    assert "material_change_state" not in parameters


def test_legacy_named_authority_classes_are_not_constructible_inputs():
    assert not hasattr(sell_module, "RiskExitAuthority")
    assert not hasattr(sell_module, "ExpectationPriceInAuthority")
    assert not hasattr(sell_module, "RiskRewardAuthority")
    assert not hasattr(sell_module, "CatalystAuthority")
    assert not hasattr(sell_module, "PortfolioRebalanceAuthority")
    assert not hasattr(sell_module, "OpportunityCostAuthority")
    assert not hasattr(sell_module, "TechnicalExecutionAuthority")

    kwargs = {
        "security_code": SECURITY,
        "strategy": STRATEGY,
        "campaign_id": CAMPAIGN,
        "as_of": AS_OF,
        "current_thesis_authority": _thesis(),
        "hard_risk_evaluation": _hard(),
        "material_change": _material(),
    }
    with pytest.raises(TypeError):
        project_sell_engine(**kwargs, expectation_price_in={"state": "EXIT"})  # type: ignore[call-arg]


def test_all_unimplemented_sell_dimensions_are_not_evaluated_and_block_hold():
    result = _project()

    assert result.sell_state is None
    assert result.sell_evaluation == "NOT_EVALUATED"
    assert result.hold_positive_proof is False
    for name in UNIMPLEMENTED:
        dimension = result.dimensions[name]
        assert dimension["source_contract"] == "NOT_IMPLEMENTED"
        assert dimension["input_state"] == "NOT_EVALUATED"
        assert dimension["pressure_state"] is None
        assert dimension["evaluation"] == "NOT_EVALUATED"
        assert dimension["hold_ok"] is False
        assert dimension["authority_refs"] == []


def test_hard_risk_confirmed_is_watch_review_pressure_not_automatic_exit():
    hard = _hard("CONFIRMED")
    result = _project(hard=hard, material=_material(hard=hard))

    assert result.sell_state == "WATCH_TO_REDUCE"
    assert result.primary_reason == "RISK_EXIT"
    assert result.review_pressure is True
    assert result.sell_state != "EXIT"
    assert result.sell_evaluation == "NOT_EVALUATED"
    assert result.dimensions["hard_risk"]["evaluation"] == "EVALUATED"
    assert result.dimensions["hard_risk"]["pressure_state"] == "WATCH_TO_REDUCE"


@pytest.mark.parametrize("state", ["DISPROVEN", "INVALIDATED"])
def test_terminal_thesis_has_precedence_and_maps_to_thesis_invalidated(state):
    thesis = _thesis(state)
    hard = _hard("CONFIRMED")
    result = _project(
        thesis=thesis,
        hard=hard,
        material=_material(evidence="new", thesis=thesis, hard=hard),
    )

    assert result.sell_state == "THESIS_INVALIDATED"
    assert result.primary_reason == "THESIS_INVALIDATION"
    assert result.sell_state != "EXIT"


def test_weakened_thesis_is_review_pressure_without_reduce_or_exit():
    thesis = _thesis("WEAKENED")
    material = _material(evidence="new", thesis=thesis)
    result = _project(thesis=thesis, material=material)

    assert material.material_change_state == "CONFIRMED"
    assert result.sell_state is None
    assert result.sell_state not in {"REDUCE", "EXIT", "THESIS_INVALIDATED"}
    assert result.hold_positive_proof is False
    assert result.review_pressure is True


def test_unknown_and_error_are_not_downgraded_to_hold():
    unknown_hard = _hard("UNKNOWN", "UNKNOWN")
    unknown = _project(
        hard=unknown_hard,
        material=_material(evidence="new", hard=unknown_hard),
    )
    assert unknown.sell_evaluation == "NOT_EVALUATED"
    assert unknown.dimensions["hard_risk"]["evaluation"] == "UNKNOWN"
    assert unknown.sell_state != "HOLD"
    assert unknown.hold_positive_proof is False

    error_hard = _hard("UNKNOWN", "ERROR")
    error = _project(hard=error_hard, material=_material(hard=error_hard))
    assert error.sell_evaluation == "ERROR"
    assert error.sell_state != "HOLD"


def test_missing_real_authority_results_are_not_evaluated():
    result = project_sell_engine(
        security_code=SECURITY,
        strategy=STRATEGY,
        campaign_id=CAMPAIGN,
        as_of=AS_OF,
        current_thesis_authority=None,
        hard_risk_evaluation=None,
        material_change=None,
    )

    assert result.sell_evaluation == "NOT_EVALUATED"
    assert result.sell_state is None
    assert result.hold_positive_proof is False


def test_identity_and_as_of_mismatches_fail_closed():
    with pytest.raises(SellEngineValidationError):
        _project(hard=_hard("CLEAR", security_code="000001"))
    with pytest.raises(SellEngineValidationError):
        project_sell_engine(
            security_code=SECURITY,
            strategy=STRATEGY,
            campaign_id=CAMPAIGN,
            as_of="2026-08-16T00:00:00.000000Z",
            current_thesis_authority=_thesis(),
            hard_risk_evaluation=_hard(),
            material_change=_material(),
        )


def test_projection_output_is_detached_and_deterministic():
    first = _project().to_dict()
    second = _project().to_dict()
    first["dimensions"]["thesis"]["reason_codes"].append("mutated")

    assert second == _project().to_dict()
    assert "mutated" not in _project().to_dict()["dimensions"]["thesis"]["reason_codes"]


def test_module_has_no_runtime_or_ai_boundary():
    source = inspect.getsource(sell_module)
    assert "datetime.now" not in source
    assert "sqlite" not in source.lower()
    assert "requests" not in source.lower()
