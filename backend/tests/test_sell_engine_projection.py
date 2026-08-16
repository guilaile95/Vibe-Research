"""Adversarial tests for the DC1 Sell Engine vNext composition."""

from __future__ import annotations

import copy
import inspect

import pytest

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
from sell_engine_projection import (
    CatalystAuthority,
    ExpectationPriceInAuthority,
    OpportunityCostAuthority,
    PortfolioRebalanceAuthority,
    RiskExitAuthority,
    RiskRewardAuthority,
    SellEngineValidationError,
    TechnicalExecutionAuthority,
    project_sell_engine,
)


SECURITY = "600519"
STRATEGY = "SWING"
CAMPAIGN = "campaign_" + "a" * 32
DECISION_ID = "decision_" + "d" * 32
THESIS_ID = "e" * 32
BOUNDARY = "2026-08-10T00:00:00.000000Z"
AS_OF = "2026-08-16T00:00:00Z"


def _delta(kind: str = "preexisting"):
    context = DecisionContext(
        security_code=SECURITY,
        strategy=STRATEGY,
        campaign_id=CAMPAIGN,
        decision_id=DECISION_ID,
        decision_boundary_at=BOUNDARY,
    )
    effective = "2026-08-11T00:00:00.000000Z" if kind == "new" else "2026-08-09T00:00:00.000000Z"
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


def _clean_dimensions() -> dict:
    return {
        "risk_exit": RiskExitAuthority("NONE", authority_refs=("risk:fixture",)),
        "expectation_price_in": ExpectationPriceInAuthority("NONE", authority_refs=("expectation:fixture",)),
        "risk_reward": RiskRewardAuthority("NONE", authority_refs=("rr:fixture",)),
        "catalyst": CatalystAuthority("NONE", authority_refs=("catalyst:fixture",)),
        "portfolio_rebalance": PortfolioRebalanceAuthority("NONE", authority_refs=("portfolio:fixture",)),
        "opportunity_cost": OpportunityCostAuthority("NONE", authority_refs=("opportunity:fixture",)),
        "technical_execution": TechnicalExecutionAuthority("NONE", authority_refs=("technical:fixture",)),
    }


def _project(
    *,
    thesis: CurrentThesisAuthority | None = None,
    hard: HardRiskEvaluation | None = None,
    material=None,
    **overrides,
):
    dimensions = _clean_dimensions()
    dimensions.update(overrides)
    return project_sell_engine(
        security_code=SECURITY,
        strategy=STRATEGY,
        campaign_id=CAMPAIGN,
        as_of=AS_OF,
        current_thesis_authority=_thesis() if thesis is None else thesis,
        hard_risk_evaluation=_hard() if hard is None else hard,
        material_change=_material() if material is None else material,
        **dimensions,
    )


def test_hold_requires_positive_proof_from_all_named_dimensions():
    result = _project()

    assert result.sell_state == "HOLD"
    assert result.hold_positive_proof is True
    assert result.sell_evaluation == "EVALUATED"


def test_named_expectation_adapter_can_produce_reduce():
    result = _project(
        expectation_price_in=ExpectationPriceInAuthority(
            "REDUCE", authority_refs=("expectation:fixture",)
        )
    )

    assert result.sell_state == "REDUCE"
    assert result.primary_reason == "EXPECTATION_PRICE_IN"


def test_named_expectation_adapter_can_produce_exit_without_silent_downgrade():
    result = _project(
        expectation_price_in=ExpectationPriceInAuthority(
            "EXIT", authority_refs=("expectation:fixture",)
        )
    )

    assert result.sell_state == "EXIT"
    assert result.primary_reason == "EXPECTATION_PRICE_IN"


def test_hard_risk_confirmed_is_review_pressure_not_automatic_exit():
    hard = _hard("CONFIRMED")
    result = _project(hard=hard, material=_material(hard=hard))

    assert result.sell_state == "WATCH_TO_REDUCE"
    assert result.primary_reason == "RISK_EXIT"
    assert result.review_pressure is True
    assert result.sell_state != "EXIT"


@pytest.mark.parametrize("state", ["DISPROVEN", "INVALIDATED"])
def test_terminal_thesis_maps_to_thesis_invalidated(state):
    thesis = _thesis(state)
    hard = _hard("CONFIRMED")
    result = _project(thesis=thesis, hard=hard, material=_material(thesis=thesis, hard=hard))

    assert result.sell_state == "THESIS_INVALIDATED"
    assert result.primary_reason == "THESIS_INVALIDATION"


def test_weakened_thesis_does_not_auto_reduce_or_exit():
    thesis = _thesis("WEAKENED")
    result = _project(
        thesis=thesis,
        material=_material(evidence="new", thesis=thesis),
    )

    assert result.sell_state is None
    assert result.sell_state not in {"REDUCE", "EXIT", "THESIS_INVALIDATED"}
    assert result.hold_positive_proof is False
    assert result.review_pressure is True


def test_unknown_and_not_evaluated_do_not_become_hold():
    unknown_hard = _hard("UNKNOWN", "UNKNOWN")
    unknown = _project(hard=unknown_hard, material=_material(hard=unknown_hard, evidence="new"))
    assert unknown.sell_evaluation == "UNKNOWN"
    assert unknown.sell_state != "HOLD"
    assert unknown.hold_positive_proof is False

    not_evaluated = project_sell_engine(
        security_code=SECURITY,
        strategy=STRATEGY,
        campaign_id=CAMPAIGN,
        as_of=AS_OF,
        current_thesis_authority=_thesis(),
        hard_risk_evaluation=None,
        material_change=None,
        **_clean_dimensions(),
    )
    assert not_evaluated.sell_evaluation == "NOT_EVALUATED"
    assert not_evaluated.sell_state != "HOLD"


def test_error_is_not_downgraded_to_unknown():
    error_hard = _hard("UNKNOWN", "ERROR")
    result = _project(hard=error_hard, material=_material(hard=error_hard))

    assert result.sell_evaluation == "ERROR"
    assert result.sell_state != "HOLD"


def test_generic_mapping_pressure_and_raw_hard_risk_labels_are_rejected():
    with pytest.raises(SellEngineValidationError, match="named"):
        _project(risk_exit={"state": "EXIT", "authority_refs": ["caller"]})
    with pytest.raises(SellEngineValidationError):
        _project(risk_exit={"state": "CONFIRMED", "authority_refs": ["caller"]})


def test_loss_profit_and_technical_signal_are_not_thesis_authority():
    with pytest.raises(TypeError):
        _project(pnl=-0.2)  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        _project(profit=0.4)  # type: ignore[call-arg]

    technical = _project(
        technical_execution=TechnicalExecutionAuthority(
            "REDUCE", authority_refs=("technical:fixture",)
        )
    )
    assert technical.sell_state == "REDUCE"
    assert technical.sell_state != "THESIS_INVALIDATED"


def test_medium_technical_exit_is_not_an_independent_long_horizon_exit():
    with pytest.raises(SellEngineValidationError, match="MEDIUM"):
        project_sell_engine(
            security_code=SECURITY,
            strategy="MEDIUM",
            campaign_id=CAMPAIGN,
            as_of=AS_OF,
            current_thesis_authority=_thesis(strategy="MEDIUM"),
            hard_risk_evaluation=None,
            material_change=None,
            technical_execution=TechnicalExecutionAuthority(
                "EXIT", authority_refs=("technical:fixture",)
            ),
            **{
                key: value
                for key, value in _clean_dimensions().items()
                if key != "technical_execution"
            },
        )


def test_identity_as_of_and_input_mutation_are_fail_closed_or_detached():
    with pytest.raises(SellEngineValidationError):
        project_sell_engine(
            security_code=SECURITY,
            strategy=STRATEGY,
            campaign_id=CAMPAIGN,
            as_of=AS_OF,
            current_thesis_authority=_thesis(),
            hard_risk_evaluation=_hard("CLEAR", security_code="000001"),
            material_change=_material(),
            expectation_price_in=ExpectationPriceInAuthority(
                "REDUCE", authority_refs=("expectation:fixture",)
            ),
            **{
                key: value
                for key, value in _clean_dimensions().items()
                if key != "expectation_price_in"
            },
        )

    result = _project()
    detached = result.to_dict()
    detached["dimensions"]["thesis"]["reason_codes"].append("mutated")
    assert "mutated" not in result.to_dict()["dimensions"]["thesis"]["reason_codes"]


def test_signature_has_no_generic_pressure_or_action_input():
    parameters = inspect.signature(project_sell_engine).parameters
    assert "pressure" not in parameters
    assert "action" not in parameters
    assert "material_change_state" not in parameters
    assert "pnl" not in parameters
