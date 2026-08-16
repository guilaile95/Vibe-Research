"""Adversarial tests for the DC1 uncommitted Proposal boundary."""

from __future__ import annotations

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
    decision_proposal_from_mapping,
    project_decision_proposal,
)
from hard_risk_contract import HardRiskEvaluation
from material_change_projection import (
    CurrentThesisAuthority,
    current_thesis_authority_from_mapping,
    project_material_change,
)
from sell_engine_projection import project_sell_engine


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
    effective = (
        "2026-08-11T00:00:00.000000Z"
        if kind == "new"
        else "2026-08-09T00:00:00.000000Z"
    )
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


def _sell(
    *,
    thesis: CurrentThesisAuthority | None = None,
    hard: HardRiskEvaluation | None = None,
    material=None,
):
    current = _thesis() if thesis is None else thesis
    risk = _hard() if hard is None else hard
    change = _material(thesis=current, hard=risk) if material is None else material
    return project_sell_engine(
        security_code=SECURITY,
        strategy=STRATEGY,
        campaign_id=CAMPAIGN,
        as_of=AS_OF,
        current_thesis_authority=current,
        hard_risk_evaluation=risk,
        material_change=change,
    )


def _proposal(
    *,
    thesis: CurrentThesisAuthority | None = None,
    hard: HardRiskEvaluation | None = None,
    material=None,
    sell=None,
    asset_view: dict | None = None,
    trade_view: dict | None = None,
    portfolio_view: dict | None = None,
):
    current = _thesis() if thesis is None else thesis
    risk = _hard() if hard is None else hard
    change = _material(thesis=current, hard=risk) if material is None else material
    engine = _sell(thesis=current, hard=risk, material=change) if sell is None else sell
    return project_decision_proposal(
        security_code=SECURITY,
        strategy=STRATEGY,
        campaign_id=CAMPAIGN,
        thesis_id=THESIS_ID,
        thesis_revision=1,
        as_of=AS_OF,
        asset_view=asset_view or {"view": "ASSET", "stance": "positive", "source": "asset:fixture"},
        trade_view=trade_view or {"view": "TRADE", "horizon": "SWING", "source": "trade:fixture"},
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


def test_proposal_is_uncommitted_and_preserves_three_proposed_views():
    result = _proposal()
    payload = result.to_dict()

    assert result.proposal_status == "UNCOMMITTED"
    assert result.constraint_evaluation == "NOT_EVALUATED"
    assert "proposal_evaluation" not in payload
    assert "formal_decision_evaluation" not in payload
    assert payload["asset_view"]["view"] == "ASSET"
    assert payload["trade_view"]["view"] == "TRADE"
    assert payload["portfolio_view"]["view"] == "PORTFOLIO"
    assert payload["view_provenance"] == {
        "asset_view": {"view_origin": "USER_DRAFT", "provenance_refs": []},
        "trade_view": {"view_origin": "USER_DRAFT", "provenance_refs": []},
        "portfolio_view": {"view_origin": "USER_DRAFT", "provenance_refs": []},
    }
    assert not {
        "decision_id",
        "committed_at",
        "snapshot_hash",
        "broker",
        "order",
    } & set(_all_strings(payload))


def test_hard_risk_confirmed_is_watch_review_pressure_not_exit():
    hard = _hard("CONFIRMED")
    result = _proposal(hard=hard, material=_material(hard=hard))

    assert result.next_best_action == "WATCH TO REDUCE"
    assert result.next_best_action != "EXIT"
    assert result.constraint_evaluation == "NOT_EVALUATED"
    assert {"BUY NOW", "BUY SMALL", "SCALE IN"}.issubset(
        set(result.action_envelope["blocked_actions"])
    )
    assert "EXIT" in result.action_envelope["allowed_actions"]


def test_terminal_thesis_is_exit_candidate_but_not_formal_decision():
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
    assert "formal_decision_evaluation" not in result.to_dict()


def test_material_unknown_and_unimplemented_sell_side_narrow_to_research():
    material_unknown = _material(evidence="new")
    result = _proposal(
        material=material_unknown,
        sell=_sell(material=material_unknown),
    )

    assert result.authority_facts["material_change"]["state"] == "UNKNOWN"
    assert result.constraint_evaluation == "NOT_EVALUATED"
    assert result.next_best_action == "RESEARCH MORE"
    assert set(result.action_envelope["allowed_actions"]) == {"WAIT", "RESEARCH MORE"}
    assert "HOLD" in result.action_envelope["blocked_actions"]


def test_not_evaluated_is_distinct_from_unknown_in_authority_facts():
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
        sell_engine=None,
    )

    assert result.constraint_evaluation == "NOT_EVALUATED"
    assert result.authority_facts["hard_risk"]["evaluation"] == "NOT_EVALUATED"
    assert result.authority_facts["material_change"]["evaluation"] == "NOT_EVALUATED"
    assert result.next_best_action == "RESEARCH MORE"


def test_error_propagates_without_downgrade():
    error_hard = _hard("UNKNOWN", "ERROR")
    material = _material(hard=error_hard)
    result = _proposal(hard=error_hard, material=material, sell=_sell(hard=error_hard, material=material))

    assert result.constraint_evaluation == "ERROR"
    assert result.next_best_action == "RESEARCH MORE"


def test_opaque_view_json_cannot_become_formal_decision_evaluation():
    result = _proposal(
        asset_view={"formal_decision_evaluation": "EVALUATED", "opaque": {"x": 1}},
        trade_view={"formal_decision_evaluation": "EVALUATED"},
        portfolio_view={"formal_decision_evaluation": "EVALUATED"},
    )
    payload = result.to_dict()

    assert result.constraint_evaluation == "NOT_EVALUATED"
    assert "formal_decision_evaluation" not in payload
    assert "formal_decision_evaluation" not in result.authority_facts
    assert payload["asset_view"]["formal_decision_evaluation"] == "EVALUATED"


def test_portfolio_view_cannot_rewrite_asset_view():
    portfolio = {
        "view": "PORTFOLIO",
        "constraint": "concentration_high",
        "asset_view": "must_not_copy",
    }
    result = _proposal(portfolio_view=portfolio)

    assert result.asset_view == {
        "view": "ASSET",
        "stance": "positive",
        "source": "asset:fixture",
    }
    assert result.portfolio_view["constraint"] == "concentration_high"
    assert "asset_view" in result.portfolio_view


def test_identity_thesis_revision_and_literal_as_of_mismatches_fail_closed():
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
            current_thesis_authority=_thesis(campaign_id="campaign_" + "b" * 32),
            hard_risk_evaluation=None,
            material_change=None,
            sell_engine=None,
        )

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
    assert "formal_decision_evaluation" not in parameters
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


def test_action_envelope_partitions_frozen_vocabulary():
    result = _proposal()
    allowed = set(result.action_envelope["allowed_actions"])
    blocked = set(result.action_envelope["blocked_actions"])

    assert allowed | blocked == set(NEXT_BEST_ACTIONS)
    assert not allowed & blocked
    assert allowed == {"WAIT", "RESEARCH MORE"}


def test_mapping_round_trip_requires_constraint_evaluation_and_provenance():
    payload = _proposal().to_dict()
    assert decision_proposal_from_mapping(payload).to_dict() == payload

    old_payload = dict(payload)
    old_payload["proposal_evaluation"] = old_payload.pop("constraint_evaluation")
    with pytest.raises(DecisionProposalValidationError):
        decision_proposal_from_mapping(old_payload)


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
    assert "\\nfrom frozen_decision_service" not in source
    assert "freeze_decision" not in source
    assert "datetime.now" not in source
    assert "sqlite" not in source.lower()
    assert "requests" not in source.lower()


def test_stable_fixtures_explicitly_separate_production_and_future_contracts():
    fixture_path = (
        Path(__file__).resolve().parent
        / "fixtures"
        / "decision_domain"
        / "decision_proposal_fixtures.json"
    )
    fixtures = json.loads(fixture_path.read_text(encoding="utf-8"))
    by_id = {item["fixture_id"]: item for item in fixtures}
    assert set(by_id) == {
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
    future = {"A_HOLD_CANDIDATE", "C_REDUCE_CANDIDATE", "D_EXIT_CANDIDATE"}
    production = set(by_id) - future
    for fixture_id, fixture in by_id.items():
        assert fixture["fixture_scope"] == (
            "FUTURE_CONTRACT_ONLY" if fixture_id in future else "PRODUCTION_SUPPORTED"
        )
        assert fixture["proposal_status"] == "UNCOMMITTED"
        assert fixture["constraint_evaluation"] in {
            "EVALUATED",
            "UNKNOWN",
            "NOT_EVALUATED",
            "ERROR",
        }
        assert "proposal_evaluation" not in fixture
        assert "formal_decision_evaluation" not in fixture
        assert set(fixture["view_provenance"]) == {
            "asset_view",
            "trade_view",
            "portfolio_view",
        }
        assert fixture["next_best_action"] in NEXT_BEST_ACTIONS
        allowed = set(fixture["action_envelope"]["allowed_actions"])
        blocked = set(fixture["action_envelope"]["blocked_actions"])
        assert allowed | blocked == set(NEXT_BEST_ACTIONS)
        assert not allowed & blocked

    assert by_id["A_HOLD_CANDIDATE"]["next_best_action"] == "HOLD"
    assert by_id["C_REDUCE_CANDIDATE"]["next_best_action"] == "REDUCE"
    assert by_id["D_EXIT_CANDIDATE"]["next_best_action"] == "EXIT"
    assert all(by_id[item]["fixture_scope"] == "PRODUCTION_SUPPORTED" for item in production)
