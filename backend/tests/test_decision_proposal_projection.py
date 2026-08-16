"""Adversarial tests for the DC1 Formal Decision Proposal contract."""

from __future__ import annotations

import copy
import inspect
import json
from pathlib import Path

import pytest

from decision_evidence_delta_projection import (
    DecisionContext,
    NormalizedEvidenceItem,
    TIME_SEMANTICS_AUTHORITATIVE,
    project_decision_evidence_delta,
)
from decision_proposal_projection import (
    NEXT_BEST_ACTIONS,
    DecisionProposalValidationError,
    project_decision_proposal,
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
    return project_decision_evidence_delta(
        context=context,
        evidence_items=(
            NormalizedEvidenceItem(
                evidence_id="1" * 32,
                scope_kind="security",
                scope_id=SECURITY,
                effective_at=effective,
                retrieved_at="2026-08-16T00:00:00.000000Z",
                time_semantics=TIME_SEMANTICS_AUTHORITATIVE,
                authority_refs=("evidence:fixture",),
            ),
        ),
    )


def _thesis(
    state: str = "STABLE",
    *,
    campaign_id: str = CAMPAIGN,
    as_of: str = AS_OF,
) -> CurrentThesisAuthority:
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
            "campaign_id": campaign_id,
            "security_code": SECURITY,
            "strategy": STRATEGY,
            "as_of": as_of,
            "authority_refs": ["formal_current_thesis:fixture"],
            "projection": {
                "schema_version": "formal_current_thesis.projection.v0.1",
                "campaign_id": campaign_id,
                "thesis_id": THESIS_ID,
                "formal_status": "READY",
                "original": {"revision": 1, "snapshot": {"core": "fixture"}},
                "binding_audit": {},
                "strategy": STRATEGY,
                "expected_horizon": {"unit": "TRADING_DAY"},
                "effective_state": state,
                "latest_delta": latest,
                "terminal": state in {"DISPROVEN", "INVALIDATED"},
                "deltas": deltas,
            },
        }
    )


def _hard(state: str = "CLEAR", evaluation: str = "EVALUATED") -> HardRiskEvaluation:
    return HardRiskEvaluation(
        security_code=SECURITY,
        strategy=STRATEGY,
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
    current = _thesis() if thesis is None else thesis
    risk = _hard() if hard is None else hard
    return project_material_change(
        security_code=SECURITY,
        strategy=STRATEGY,
        campaign_id=CAMPAIGN,
        as_of=AS_OF,
        decision_evidence_delta=_delta(evidence),
        current_thesis_authority=current,
        hard_risk_evaluation=risk,
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


def _sell(
    *,
    thesis: CurrentThesisAuthority | None = None,
    hard: HardRiskEvaluation | None = None,
    material=None,
    **overrides,
):
    current = _thesis() if thesis is None else thesis
    risk = _hard() if hard is None else hard
    dimensions = _clean_dimensions()
    dimensions.update(overrides)
    return project_sell_engine(
        security_code=SECURITY,
        strategy=STRATEGY,
        campaign_id=CAMPAIGN,
        as_of=AS_OF,
        current_thesis_authority=current,
        hard_risk_evaluation=risk,
        material_change=_material() if material is None else material,
        **dimensions,
    )


def _proposal(
    *,
    thesis: CurrentThesisAuthority | None = None,
    hard: HardRiskEvaluation | None = None,
    material=None,
    sell=None,
    portfolio_view: dict | None = None,
    **overrides,
):
    current = _thesis() if thesis is None else thesis
    risk = _hard() if hard is None else hard
    change = _material(thesis=current, hard=risk) if material is None else material
    engine = _sell(thesis=current, hard=risk, material=change, **overrides) if sell is None else sell
    return project_decision_proposal(
        security_code=SECURITY,
        strategy=STRATEGY,
        campaign_id=CAMPAIGN,
        thesis_id=THESIS_ID,
        thesis_revision=1,
        as_of=AS_OF,
        asset_view={"view": "ASSET", "stance": "positive", "source": "asset:fixture"},
        trade_view={"view": "TRADE", "horizon": "SWING", "source": "trade:fixture"},
        portfolio_view=portfolio_view or {"view": "PORTFOLIO", "constraint": "none"},
        current_thesis_authority=current,
        hard_risk_evaluation=risk,
        material_change=change,
        sell_engine=engine,
    )


def _all_strings(value):
    if isinstance(value, dict):
        for key, nested in value.items():
            yield key
            yield from _all_strings(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _all_strings(nested)


def test_hold_candidate_preserves_three_views_and_is_uncommitted():
    result = _proposal()
    payload = result.to_dict()

    assert result.proposal_status == "UNCOMMITTED"
    assert result.proposal_evaluation == "EVALUATED"
    assert result.next_best_action == "HOLD"
    assert payload["asset_view"]["view"] == "ASSET"
    assert payload["trade_view"]["view"] == "TRADE"
    assert payload["portfolio_view"]["view"] == "PORTFOLIO"
    assert "BUY NOW" in payload["action_envelope"]["blocked_actions"]
    assert "HOLD" in payload["action_envelope"]["allowed_actions"]
    assert not {
        "decision_id",
        "committed_at",
        "snapshot_hash",
        "broker",
        "order",
    } & set(_all_strings(payload))


def test_watch_reduce_candidate_from_hard_risk_is_not_exit():
    hard = _hard("CONFIRMED")
    result = _proposal(hard=hard, material=_material(hard=hard))

    assert result.next_best_action == "WATCH TO REDUCE"
    assert result.next_best_action != "EXIT"
    assert result.proposal_evaluation == "EVALUATED"
    assert {"BUY NOW", "BUY SMALL", "SCALE IN"}.issubset(
        set(result.action_envelope["blocked_actions"])
    )
    assert "EXIT" in result.action_envelope["allowed_actions"]


def test_reduce_and_exit_candidates_use_named_sell_authority():
    reduce_result = _proposal(
        sell=None,
        expectation_price_in=ExpectationPriceInAuthority(
            "REDUCE", authority_refs=("expectation:fixture",)
        ),
    )
    assert reduce_result.next_best_action == "REDUCE"

    exit_result = _proposal(
        sell=None,
        expectation_price_in=ExpectationPriceInAuthority(
            "EXIT", authority_refs=("expectation:fixture",)
        ),
    )
    assert exit_result.next_best_action == "EXIT"


def test_thesis_invalidated_is_explicit_and_not_a_committed_decision():
    thesis = _thesis("INVALIDATED")
    hard = _hard("CONFIRMED")
    result = _proposal(
        thesis=thesis,
        hard=hard,
        material=_material(evidence="new", thesis=thesis, hard=hard),
    )

    assert result.authority_facts["current_thesis"]["state"] == "INVALIDATED"
    assert result.next_best_action == "EXIT"
    assert result.proposal_status == "UNCOMMITTED"


def test_unknown_material_case_narrows_to_research_and_not_hold():
    unknown_material = _material(evidence="new")
    result = _proposal(material=unknown_material, sell=_sell(material=unknown_material))

    assert result.proposal_evaluation == "UNKNOWN"
    assert result.next_best_action == "RESEARCH MORE"
    assert set(result.action_envelope["allowed_actions"]) == {"WAIT", "RESEARCH MORE"}
    assert "HOLD" in result.action_envelope["blocked_actions"]


def test_not_evaluated_case_is_distinct_from_unknown():
    sell = _sell(hard=None, material=None)
    result = project_decision_proposal(
        security_code=SECURITY,
        strategy=STRATEGY,
        campaign_id=CAMPAIGN,
        thesis_id=THESIS_ID,
        thesis_revision=1,
        as_of=AS_OF,
        asset_view={"view": "ASSET"},
        trade_view={"view": "TRADE"},
        portfolio_view={"view": "PORTFOLIO"},
        current_thesis_authority=_thesis(),
        hard_risk_evaluation=None,
        material_change=None,
        sell_engine=sell,
    )

    assert result.proposal_evaluation == "NOT_EVALUATED"
    assert result.next_best_action == "RESEARCH MORE"
    assert result.proposal_evaluation != "UNKNOWN"


def test_error_propagates_without_downgrade():
    error_hard = _hard("UNKNOWN", "ERROR")
    material = _material(hard=error_hard)
    sell = _sell(hard=error_hard, material=material)
    result = _proposal(hard=error_hard, material=material, sell=sell)

    assert result.proposal_evaluation == "ERROR"
    assert result.proposal_evaluation != "UNKNOWN"


def test_portfolio_constraint_cannot_rewrite_asset_view():
    portfolio = {"view": "PORTFOLIO", "constraint": "concentration_high", "asset_view": "must_not_copy"}
    result = _proposal(portfolio_view=portfolio)

    assert result.asset_view == {
        "view": "ASSET",
        "stance": "positive",
        "source": "asset:fixture",
    }
    assert result.portfolio_view["constraint"] == "concentration_high"
    assert "asset_view" in result.portfolio_view


def test_identity_thesis_and_literal_as_of_mismatches_fail_closed():
    with pytest.raises(DecisionProposalValidationError):
        project_decision_proposal(
            security_code=SECURITY,
            strategy=STRATEGY,
            campaign_id=CAMPAIGN,
            thesis_id=THESIS_ID,
            thesis_revision=1,
            as_of=AS_OF,
            asset_view={"view": "ASSET"},
            trade_view={"view": "TRADE"},
            portfolio_view={"view": "PORTFOLIO"},
            current_thesis_authority=_thesis(
                campaign_id="campaign_" + "b" * 32
            ),
            hard_risk_evaluation=None,
            material_change=None,
            sell_engine=None,
        )

    bad_hard = HardRiskEvaluation(
        security_code="000001",
        strategy=STRATEGY,
        campaign_id=CAMPAIGN,
        as_of=AS_OF,
        hard_risk_state="CLEAR",
        hard_risk_evaluation="EVALUATED",
        reason_codes=(),
        authority_refs=("hard_risk:fixture",),
    )
    with pytest.raises(DecisionProposalValidationError):
        _proposal(hard=bad_hard, material=_material(), sell=_sell())

    with pytest.raises(DecisionProposalValidationError):
        project_decision_proposal(
            security_code=SECURITY,
            strategy=STRATEGY,
            campaign_id=CAMPAIGN,
            thesis_id=THESIS_ID,
            thesis_revision=2,
            as_of=AS_OF,
            asset_view={"view": "ASSET"},
            trade_view={"view": "TRADE"},
            portfolio_view={"view": "PORTFOLIO"},
            current_thesis_authority=_thesis(),
            hard_risk_evaluation=_hard(),
            material_change=_material(),
            sell_engine=_sell(),
        )


def test_generic_action_or_material_mapping_is_not_an_input_path():
    parameters = inspect.signature(project_decision_proposal).parameters
    assert "next_best_action" not in parameters
    assert "material_change_state" not in parameters
    with pytest.raises(DecisionProposalValidationError):
        project_decision_proposal(
            security_code=SECURITY,
            strategy=STRATEGY,
            campaign_id=CAMPAIGN,
            thesis_id=THESIS_ID,
            thesis_revision=1,
            as_of=AS_OF,
            asset_view={"view": "ASSET"},
            trade_view={"view": "TRADE"},
            portfolio_view={"view": "PORTFOLIO"},
            current_thesis_authority=_thesis(),
            hard_risk_evaluation=_hard(),
            material_change={"material_change_state": "CONFIRMED"},  # type: ignore[arg-type]
            sell_engine=_sell(),
        )


def test_action_envelope_partitions_existing_frozen_vocabulary():
    result = _proposal()
    allowed = set(result.action_envelope["allowed_actions"])
    blocked = set(result.action_envelope["blocked_actions"])

    assert allowed | blocked == set(NEXT_BEST_ACTIONS)
    assert not allowed & blocked
    assert set(result.action_envelope["allowed_actions"]) == {"WAIT", "HOLD", "RESEARCH MORE"}


def test_input_is_detached_and_projection_is_deterministic():
    asset = {"view": "ASSET", "nested": {"x": 1}}
    kwargs = {
        "security_code": SECURITY,
        "strategy": STRATEGY,
        "campaign_id": CAMPAIGN,
        "thesis_id": THESIS_ID,
        "thesis_revision": 1,
        "as_of": AS_OF,
        "asset_view": asset,
        "trade_view": {"view": "TRADE"},
        "portfolio_view": {"view": "PORTFOLIO"},
        "current_thesis_authority": _thesis(),
        "hard_risk_evaluation": _hard(),
        "material_change": _material(),
        "sell_engine": _sell(),
    }
    first = project_decision_proposal(**kwargs).to_dict()
    second = project_decision_proposal(**kwargs).to_dict()
    asset["nested"]["x"] = 99

    assert first == second
    assert first["asset_view"]["nested"]["x"] == 1


def test_proposal_module_does_not_call_commit_or_use_wall_clock():
    source = inspect.getsource(__import__("decision_proposal_projection"))
    assert "\nfrom frozen_decision_service" not in source
    assert "freeze_decision" not in source
    assert "datetime.now" not in source
    assert "sqlite" not in source.lower()
    assert "requests" not in source.lower()


def test_stable_json_fixtures_cover_the_cross_lane_contract():
    fixture_path = (
        Path(__file__).resolve().parent
        / "fixtures"
        / "decision_domain"
        / "decision_proposal_fixtures.json"
    )
    fixtures = json.loads(fixture_path.read_text(encoding="utf-8"))
    assert {item["fixture_id"] for item in fixtures} == {
        "A_HOLD_CANDIDATE",
        "B_WATCH_TO_REDUCE_CANDIDATE",
        "C_REDUCE_CANDIDATE",
        "D_EXIT_CANDIDATE",
        "E_THESIS_INVALIDATED_CANDIDATE",
        "F_HARD_RISK_CONFIRMED_NOT_AUTO_EXIT",
        "G_UNKNOWN_BLOCKED",
        "H_NOT_EVALUATED",
        "I_MATERIAL_CONFIRMED_REVIEW",
        "J_MATERIAL_UNKNOWN",
    }
    for fixture in fixtures:
        identity = fixture["identity"]
        assert identity == {
            "security_code": "600519",
            "strategy": "SWING",
            "campaign_id": CAMPAIGN,
            "thesis_id": THESIS_ID,
            "thesis_revision": 1,
            "as_of": AS_OF,
        }
        assert fixture["proposal_status"] == "UNCOMMITTED"
        assert fixture["next_best_action"] in NEXT_BEST_ACTIONS
        envelope = fixture["action_envelope"]
        allowed = set(envelope["allowed_actions"])
        blocked = set(envelope["blocked_actions"])
        assert allowed | blocked == set(NEXT_BEST_ACTIONS)
        assert not allowed & blocked
        assert fixture["next_best_action"] in allowed
        assert set(fixture["authority_facts"]) == {
            "current_thesis",
            "hard_risk",
            "material_change",
            "sell_engine",
        }
        assert fixture["authority_refs"]
        for field in (
            "maintain_conditions",
            "upgrade_conditions",
            "downgrade_conditions",
            "invalidation_conditions",
        ):
            assert isinstance(envelope[field], list)
        assert {"view": "ASSET"}.items() <= fixture["asset_view"].items()
        assert {"view": "TRADE"}.items() <= fixture["trade_view"].items()
        assert {"view": "PORTFOLIO"}.items() <= fixture["portfolio_view"].items()

    hard = _hard("CONFIRMED")
    weakened = _thesis("WEAKENED")
    material_unknown = _material(evidence="new")
    material_confirmed = _material(evidence="new", thesis=weakened)
    generated = {
        "A_HOLD_CANDIDATE": _proposal(),
        "B_WATCH_TO_REDUCE_CANDIDATE": _proposal(
            hard=hard, material=_material(hard=hard)
        ),
        "C_REDUCE_CANDIDATE": _proposal(
            expectation_price_in=ExpectationPriceInAuthority(
                "REDUCE", authority_refs=("expectation:fixture",)
            )
        ),
        "D_EXIT_CANDIDATE": _proposal(
            expectation_price_in=ExpectationPriceInAuthority(
                "EXIT", authority_refs=("expectation:fixture",)
            )
        ),
        "E_THESIS_INVALIDATED_CANDIDATE": _proposal(
            thesis=_thesis("INVALIDATED"),
            hard=hard,
            material=_material(
                evidence="new",
                thesis=_thesis("INVALIDATED"),
                hard=hard,
            ),
        ),
        "F_HARD_RISK_CONFIRMED_NOT_AUTO_EXIT": _proposal(
            hard=hard, material=_material(hard=hard)
        ),
        "G_UNKNOWN_BLOCKED": _proposal(
            material=material_unknown,
            sell=_sell(material=material_unknown),
        ),
        "I_MATERIAL_CONFIRMED_REVIEW": _proposal(
            thesis=weakened,
            material=material_confirmed,
            sell=_sell(thesis=weakened, material=material_confirmed),
        ),
        "J_MATERIAL_UNKNOWN": _proposal(
            material=material_unknown,
            sell=_sell(material=material_unknown),
        ),
    }
    by_id = {item["fixture_id"]: item for item in fixtures}
    for fixture_id, proposal in generated.items():
        fixture = by_id[fixture_id]
        payload = proposal.to_dict()
        assert payload["proposal_evaluation"] == fixture["proposal_evaluation"]
        assert payload["next_best_action"] == fixture["next_best_action"]
        assert payload["action_envelope"] == fixture["action_envelope"]
        assert payload["asset_view"] == {
            **fixture["asset_view"],
            **{
                key: value
                for key, value in payload["asset_view"].items()
                if key not in fixture["asset_view"]
            },
        }
        for name, expected in fixture["authority_facts"].items():
            assert payload["authority_facts"][name]["state"] == expected["state"]
            assert payload["authority_facts"][name]["evaluation"] == expected["evaluation"]
