"""Adversarial tests for the DC1 Material Change authority."""

from __future__ import annotations

import copy
import inspect

import pytest

from decision_evidence_delta_projection import (
    DecisionContext,
    NormalizedEvidenceItem,
    TIME_SEMANTICS_AUTHORITATIVE,
    TIME_SEMANTICS_UNKNOWN,
    project_decision_evidence_delta,
)
from hard_risk_contract import HardRiskEvaluation
from material_change_projection import (
    AUTHORITY_REF,
    CurrentThesisAuthority,
    MaterialChangeValidationError,
    current_thesis_authority_from_mapping,
    project_material_change,
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
    if kind == "new":
        items = (
            NormalizedEvidenceItem(
                evidence_id="1" * 32,
                scope_kind="security",
                scope_id=SECURITY,
                effective_at="2026-08-11T00:00:00.000000Z",
                retrieved_at="2026-08-16T00:00:00.000000Z",
                time_semantics=TIME_SEMANTICS_AUTHORITATIVE,
                authority_refs=("evidence:source",),
            ),
        )
    elif kind == "unknown":
        items = (
            NormalizedEvidenceItem(
                evidence_id="2" * 32,
                scope_kind="security",
                scope_id=SECURITY,
                effective_at=None,
                retrieved_at="2026-08-16T00:00:00.000000Z",
                time_semantics=TIME_SEMANTICS_UNKNOWN,
                authority_refs=("evidence:source",),
            ),
        )
    elif kind == "out_of_scope":
        items = (
            NormalizedEvidenceItem(
                evidence_id="3" * 32,
                scope_kind="security",
                scope_id="000001",
                effective_at="2026-08-11T00:00:00.000000Z",
                retrieved_at=None,
                time_semantics=TIME_SEMANTICS_AUTHORITATIVE,
                authority_refs=("evidence:source",),
            ),
        )
    else:
        items = (
            NormalizedEvidenceItem(
                evidence_id="4" * 32,
                scope_kind="security",
                scope_id=SECURITY,
                effective_at="2026-08-09T00:00:00.000000Z",
                retrieved_at="2026-08-16T00:00:00.000000Z",
                time_semantics=TIME_SEMANTICS_AUTHORITATIVE,
                authority_refs=("evidence:source",),
            ),
        )
    return project_decision_evidence_delta(context=context, evidence_items=items)


def _thesis(
    state: str = "STABLE",
    *,
    confirmed_at: str | None = "2026-08-12T00:00:00Z",
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
            "confirmed_at": confirmed_at,
            "evidence_snapshots": [],
        }
        deltas = [latest]
    projection = {
        "schema_version": "formal_current_thesis.projection.v0.1",
        "campaign_id": CAMPAIGN,
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
    }
    return current_thesis_authority_from_mapping(
        {
            "campaign_id": CAMPAIGN,
            "security_code": SECURITY,
            "strategy": STRATEGY,
            "as_of": as_of,
            "authority_refs": ["formal_current_thesis:fixture"],
            "projection": projection,
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


def _project(
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


def test_new_evidence_alone_is_not_material_change():
    result = _project(evidence="new")

    assert result.material_change_state == "UNKNOWN"
    assert result.material_change_evaluation == "UNKNOWN"
    assert result.evidence_relation == "NEW_AFTER_DECISION"
    assert "NEW_EVIDENCE_WITHOUT_MATERIALITY_AUTHORITY" in result.reason_codes


def test_preexisting_evidence_with_clean_named_authorities_is_none():
    result = _project()

    assert result.material_change_state == "NONE"
    assert result.material_change_evaluation == "EVALUATED"
    assert result.evidence_relation == "PREEXISTING_AT_DECISION"


@pytest.mark.parametrize("state", ["DISPROVEN", "INVALIDATED"])
def test_terminal_thesis_is_one_confirmed_material_change_not_a_double_count(state):
    result = _project(evidence="new", thesis=_thesis(state))

    assert result.material_change_state == "CONFIRMED"
    assert result.material_change_evaluation == "EVALUATED"
    assert result.materiality_basis == "THESIS_TERMINAL"
    assert result.reason_codes == (f"THESIS_{state}_AFTER_DECISION",)


def test_weakened_thesis_is_confirmed_review_change_but_not_sell_action():
    result = _project(evidence="new", thesis=_thesis("WEAKENED"))

    assert result.material_change_state == "CONFIRMED"
    assert result.materiality_basis == "THESIS_WEAKENED"
    assert "REDUCE" not in result.reason_codes
    assert "EXIT" not in result.reason_codes


def test_preexisting_evidence_cannot_become_decision_after_material_change():
    result = _project(thesis=_thesis("WEAKENED"))

    assert result.evidence_relation == "PREEXISTING_AT_DECISION"
    assert result.material_change_state == "UNKNOWN"
    assert result.material_change_evaluation == "UNKNOWN"
    assert result.material_change_state != "CONFIRMED"


def test_stable_delta_does_not_become_material():
    result = _project(evidence="preexisting", thesis=_thesis("STRENGTHENED"))

    assert result.material_change_state == "NONE"
    assert result.material_change_evaluation == "EVALUATED"


def test_unknown_temporal_relation_fails_closed():
    result = _project(evidence="unknown")

    assert result.material_change_state == "UNKNOWN"
    assert result.material_change_evaluation == "UNKNOWN"
    assert result.evidence_relation == "UNKNOWN_TEMPORAL_RELATION"
    assert result.materiality_basis == "EC1_TEMPORAL_RELATION_UNKNOWN"


def test_hard_risk_confirmed_alone_is_not_a_material_change_fact():
    result = _project(hard=_hard("CONFIRMED"))

    assert result.material_change_state == "UNKNOWN"
    assert result.material_change_evaluation == "UNKNOWN"
    assert result.materiality_basis == "HARD_RISK_CONFIRMED_WITHOUT_AFTER_DECISION_PROOF"
    assert result.reason_codes == ("HARD_RISK_CONFIRMED_WITHOUT_AFTER_DECISION_PROOF",)


def test_hard_risk_confirmed_with_preexisting_evidence_is_not_material():
    result = _project(evidence="preexisting", hard=_hard("CONFIRMED"))

    assert result.evidence_relation == "PREEXISTING_AT_DECISION"
    assert result.material_change_state != "CONFIRMED"
    assert result.material_change_state == "UNKNOWN"


def test_hard_risk_confirmed_without_temporal_proof_is_not_material():
    result = _project(evidence="unknown", hard=_hard("CONFIRMED"))

    assert result.evidence_relation == "UNKNOWN_TEMPORAL_RELATION"
    assert result.material_change_state != "CONFIRMED"
    assert result.material_change_evaluation == "UNKNOWN"


def test_weakened_thesis_after_decision_with_ec1_support_is_material():
    result = _project(evidence="new", thesis=_thesis("WEAKENED"), hard=_hard("CONFIRMED"))

    assert result.material_change_state == "CONFIRMED"
    assert result.material_change_evaluation == "EVALUATED"


def test_terminal_thesis_requires_after_decision_support():
    result = _project(evidence="preexisting", thesis=_thesis("INVALIDATED"), hard=_hard("CONFIRMED"))

    assert result.material_change_state != "CONFIRMED"
    assert result.material_change_state == "UNKNOWN"


def test_hard_risk_error_is_not_downgraded_to_unknown_evaluation():
    result = _project(hard=_hard("UNKNOWN", "ERROR"))

    assert result.material_change_state == "UNKNOWN"
    assert result.material_change_evaluation == "ERROR"


def test_hard_risk_error_stays_error_even_when_ec1_time_is_unknown():
    result = _project(evidence="unknown", hard=_hard("UNKNOWN", "ERROR"))

    assert result.material_change_state == "UNKNOWN"
    assert result.material_change_evaluation == "ERROR"


def test_missing_named_authorities_are_not_evaluated():
    result = project_material_change(
        security_code=SECURITY,
        strategy=STRATEGY,
        campaign_id=CAMPAIGN,
        as_of=AS_OF,
        decision_evidence_delta=_delta("preexisting"),
        current_thesis_authority=None,
        hard_risk_evaluation=None,
    )

    assert result.material_change_state == "NOT_EVALUATED"
    assert result.material_change_evaluation == "NOT_EVALUATED"


def test_identity_and_literal_as_of_mismatch_fail_closed():
    with pytest.raises(MaterialChangeValidationError):
        project_material_change(
            security_code="000001",
            strategy=STRATEGY,
            campaign_id=CAMPAIGN,
            as_of=AS_OF,
            decision_evidence_delta=_delta(),
            current_thesis_authority=_thesis(),
            hard_risk_evaluation=_hard(),
        )
    with pytest.raises(MaterialChangeValidationError):
        project_material_change(
            security_code=SECURITY,
            strategy=STRATEGY,
            campaign_id=CAMPAIGN,
            as_of="2026-08-16T00:00:00.000000Z",
            decision_evidence_delta=_delta(),
            current_thesis_authority=_thesis(),
            hard_risk_evaluation=_hard(),
        )


def test_generic_material_conclusion_is_not_an_input_path():
    parameters = inspect.signature(project_material_change).parameters
    assert "material_change_state" not in parameters
    assert "severity" not in parameters
    with pytest.raises(TypeError):
        project_material_change(  # type: ignore[call-arg]
            security_code=SECURITY,
            strategy=STRATEGY,
            campaign_id=CAMPAIGN,
            as_of=AS_OF,
            decision_evidence_delta=_delta(),
            current_thesis_authority=_thesis(),
            hard_risk_evaluation=_hard(),
            material_change_state="CONFIRMED",
        )


def test_input_is_not_mutated_and_repeated_projection_is_deterministic():
    thesis = _thesis("WEAKENED")
    before = copy.deepcopy(thesis.to_dict())
    first = _project(thesis=thesis).to_dict()
    second = _project(thesis=thesis).to_dict()

    assert first == second
    assert thesis.to_dict() == before
    assert AUTHORITY_REF in first["authority_refs"]


def test_module_has_no_runtime_or_ai_boundary_imports():
    source = inspect.getsource(project_material_change)
    assert "datetime.now" not in source
    module_source = inspect.getsource(__import__("material_change_projection"))
    assert "sqlite" not in module_source.lower()
    assert "requests" not in module_source.lower()
    assert "open(" not in module_source
