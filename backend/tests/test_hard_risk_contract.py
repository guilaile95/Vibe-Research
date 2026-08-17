from __future__ import annotations

import pytest

from hard_risk_contract import (
    HardRiskContractError,
    HardRiskEvaluation,
    hard_risk_evaluation_from_mapping,
)


BASE = {
    "security_code": "600519",
    "strategy": "SWING",
    "campaign_id": "campaign_0123456789abcdef0123456789abcdef",
    "as_of": "2026-08-16T00:00:00Z",
}


def make(**overrides):
    payload = {
        **BASE,
        "hard_risk_state": "CLEAR",
        "hard_risk_evaluation": "EVALUATED",
        "reason_codes": [],
        "authority_refs": ["hard-risk:test-authority"],
        **overrides,
    }
    return HardRiskEvaluation(**payload)


def test_legal_state_evaluation_pairs_round_trip():
    cases = [
        ("CLEAR", "EVALUATED", [], ["authority:clear"]),
        ("CONFIRMED", "EVALUATED", ["HARD_RISK_CONFIRMED"], ["authority:confirmed"]),
        ("UNKNOWN", "UNKNOWN", ["HARD_RISK_INPUT_UNKNOWN"], []),
        ("UNKNOWN", "ERROR", ["HARD_RISK_EVALUATION_ERROR"], []),
        ("NOT_EVALUATED", "NOT_EVALUATED", ["HARD_RISK_NOT_EVALUATED"], []),
    ]
    for state, evaluation, reasons, refs in cases:
        result = make(
            hard_risk_state=state,
            hard_risk_evaluation=evaluation,
            reason_codes=reasons,
            authority_refs=refs,
        )
        assert hard_risk_evaluation_from_mapping(result.to_dict()) == result


def test_illegal_pairs_fail_closed():
    for state, evaluation in [
        ("CLEAR", "UNKNOWN"),
        ("CLEAR", "NOT_EVALUATED"),
        ("CONFIRMED", "ERROR"),
        ("NOT_EVALUATED", "EVALUATED"),
    ]:
        with pytest.raises(HardRiskContractError):
            make(
                hard_risk_state=state,
                hard_risk_evaluation=evaluation,
                reason_codes=["INVALID_PAIR"],
            )


def test_positive_proof_states_require_authority_refs():
    for state in ("CLEAR", "CONFIRMED"):
        with pytest.raises(HardRiskContractError):
            make(
                hard_risk_state=state,
                hard_risk_evaluation="EVALUATED",
                reason_codes=[] if state == "CLEAR" else ["CONFIRMED"],
                authority_refs=[],
            )


def test_non_clear_results_require_reason_codes():
    for state, evaluation in [
        ("CONFIRMED", "EVALUATED"),
        ("UNKNOWN", "UNKNOWN"),
        ("UNKNOWN", "ERROR"),
        ("NOT_EVALUATED", "NOT_EVALUATED"),
    ]:
        with pytest.raises(HardRiskContractError):
            make(
                hard_risk_state=state,
                hard_risk_evaluation=evaluation,
                reason_codes=[],
            )


def test_identity_and_as_of_fail_closed():
    bad = [
        {"security_code": "60051"},
        {"strategy": "LONG"},
        {"campaign_id": "campaign_bad"},
        {"as_of": "2026-08-16T08:00:00+08:00"},
        {"as_of": "2026-08-16T00:00:00"},
    ]
    for patch in bad:
        with pytest.raises(HardRiskContractError):
            make(**patch)


def test_exact_shape_and_duplicate_provenance_fail_closed():
    result = make()
    extra = {**result.to_dict(), "unexpected": True}
    with pytest.raises(HardRiskContractError):
        hard_risk_evaluation_from_mapping(extra)
    with pytest.raises(HardRiskContractError):
        make(authority_refs=["a", "a"])
