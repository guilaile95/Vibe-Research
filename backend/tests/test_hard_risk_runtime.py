"""Focused HR1 Formal Hard Risk pure-authority tests."""

from __future__ import annotations

import ast
import copy
from pathlib import Path

import pytest

from hard_risk_contract import hard_risk_evaluation_from_mapping
from hard_risk_runtime import (
    ALL_IMPLEMENTED_HARD_RISK_CHECKS,
    HardRiskRuntimeError,
    evaluate_hard_risk,
)


BACKEND = Path(__file__).resolve().parents[1]
MODULE_PATH = BACKEND / "hard_risk_runtime.py"
AS_OF = "2026-08-16T00:00:00Z"
CAMPAIGN_A = "campaign_0123456789abcdef0123456789abcdef"
CAMPAIGN_B = "campaign_fedcba9876543210fedcba9876543210"


def _campaign(
    *, campaign_id: str = CAMPAIGN_A, security_code: str = "600519", strategy: str = "SWING"
) -> dict:
    return {
        "campaign_id": campaign_id,
        "security_code": security_code,
        "strategy": strategy,
        "status": "ACTIVE",
    }


def _proof(
    *,
    campaign_id: str = CAMPAIGN_A,
    security_code: str = "600519",
    strategy: str = "SWING",
    as_of: str = AS_OF,
    check_id: str = "trading_eligibility",
    risk_type: str = "TRADING_ELIGIBILITY",
    state: str = "CONFIRMED",
    evaluation: str = "EVALUATED",
    severity: str | None = "HIGH",
    positive_proof: bool = True,
    refs: list[str] | None = None,
    reasons: list[str] | None = None,
    coverage: list[str] | None = None,
    fact_time: str | None = None,
) -> dict:
    record = {
        "campaign_id": campaign_id,
        "security_code": security_code,
        "strategy": strategy,
        "as_of": as_of,
        "check_id": check_id,
        "risk_type": risk_type,
        "hard_risk_state": state,
        "hard_risk_evaluation": evaluation,
        "positive_proof": positive_proof,
        "authority_refs": refs if refs is not None else [f"authority:{check_id}:v1"],
        "reason_codes": reasons if reasons is not None else [f"{check_id}:proof"],
        "coverage": coverage if coverage is not None else [],
    }
    if severity is not None:
        record["severity"] = severity
    if fact_time is not None:
        record["fact_time"] = fact_time
    return record


def _thesis_envelope(
    *,
    campaign_id: str = CAMPAIGN_A,
    security_code: str = "600519",
    strategy: str = "SWING",
    as_of: str = AS_OF,
    effective_state: str = "DISPROVEN",
    terminal: bool = True,
    refs: list[str] | None = None,
    confirmed_at: str | None = "2026-08-15T00:00:00Z",
) -> dict:
    latest_delta = {
        "delta_state": effective_state,
        "confirmed_at": confirmed_at,
    }
    return {
        "campaign_id": campaign_id,
        "security_code": security_code,
        "strategy": strategy,
        "as_of": as_of,
        "authority_refs": refs or ["formal_current_thesis.projection:v0.1"],
        "projection": {
            "schema_version": "formal_current_thesis.projection.v0.1",
            "campaign_id": campaign_id,
            "strategy": strategy,
            "formal_status": "READY",
            "effective_state": effective_state,
            "terminal": terminal,
            "latest_delta": latest_delta,
            "deltas": [latest_delta],
        },
    }


def _evaluate(facts: dict, *, campaign: dict | None = None, as_of: str = AS_OF):
    current_campaign = campaign if campaign is not None else _campaign()
    return evaluate_hard_risk(
        campaign_id=current_campaign["campaign_id"],
        campaign=current_campaign,
        as_of=as_of,
        authoritative_facts=facts,
    )


def test_confirmed_requires_high_severity_positive_proof_and_retains_refs():
    result = _evaluate(
        {
            "hard_risk_proofs": [
                _proof(
                    refs=["z:source", "a:source"],
                    reasons=["Z_REASON", "A_REASON"],
                )
            ]
        }
    )

    assert result.hard_risk_state == "CONFIRMED"
    assert result.hard_risk_evaluation == "EVALUATED"
    assert result.authority_refs == ("a:source", "z:source")
    assert "HARD_RISK_CONFIRMED" in result.reason_codes
    assert result.to_dict()["authority_refs"] == ["a:source", "z:source"]
    assert hard_risk_evaluation_from_mapping(result.to_dict()) == result


def test_clear_requires_explicit_positive_proof_covering_all_implemented_checks():
    result = _evaluate(
        {
            "hard_risk_proofs": [
                _proof(
                    check_id="hard_risk.aggregate",
                    risk_type="HARD_RISK_AGGREGATE",
                    state="CLEAR",
                    severity=None,
                    refs=["hard-risk-authority:v0.1"],
                    reasons=[],
                    coverage=[ALL_IMPLEMENTED_HARD_RISK_CHECKS],
                )
            ]
        }
    )

    assert result.hard_risk_state == "CLEAR"
    assert result.hard_risk_evaluation == "EVALUATED"
    assert result.reason_codes == ("CLEAR_POSITIVE_PROOF",)
    assert result.authority_refs == ("hard-risk-authority:v0.1",)


def test_missing_required_authority_is_not_evaluated_not_clear():
    result = _evaluate({})

    assert result.hard_risk_state == "NOT_EVALUATED"
    assert result.hard_risk_evaluation == "NOT_EVALUATED"
    assert result.authority_refs == ()
    assert "NO_HARD_RISK_AUTHORITY" in result.reason_codes


def test_ambiguous_authority_is_unknown():
    result = _evaluate(
        {
            "hard_risk_proofs": [
                _proof(
                    state="UNKNOWN",
                    evaluation="UNKNOWN",
                    severity=None,
                    positive_proof=False,
                    refs=["provider:ambiguous:v1"],
                    reasons=["FACT_CONFLICT"],
                )
            ]
        }
    )

    assert result.hard_risk_state == "UNKNOWN"
    assert result.hard_risk_evaluation == "UNKNOWN"
    assert "FACT_CONFLICT" in result.reason_codes
    assert result.authority_refs == ("provider:ambiguous:v1",)


def test_authority_error_remains_unknown_with_error_evaluation_axis():
    result = _evaluate(
        {
            "hard_risk_proofs": [
                _proof(
                    state="UNKNOWN",
                    evaluation="ERROR",
                    severity=None,
                    positive_proof=False,
                    refs=["provider:error:v1"],
                    reasons=["PROVIDER_ERROR"],
                )
            ]
        }
    )
    assert result.hard_risk_state == "UNKNOWN"
    assert result.hard_risk_evaluation == "ERROR"


def test_low_severity_confirmed_claim_is_downgraded_to_unknown():
    result = _evaluate(
        {
            "hard_risk_proofs": [
                _proof(severity="MATERIAL", positive_proof=True)
            ]
        }
    )

    assert result.hard_risk_state == "UNKNOWN"
    assert result.hard_risk_evaluation == "UNKNOWN"
    assert "AUTHORITY_PROOF_AMBIGUOUS" in result.reason_codes
    assert result.hard_risk_state != "CONFIRMED"


def test_formal_thesis_terminal_projection_is_a_confirmed_hard_risk_proof():
    result = _evaluate(
        {"formal_thesis_projection": _thesis_envelope(effective_state="DISPROVEN")}
    )

    assert result.hard_risk_state == "CONFIRMED"
    assert result.hard_risk_evaluation == "EVALUATED"
    assert "THESIS_CORE_FACT_DISPROVEN" in result.reason_codes
    assert result.authority_refs == ("formal_current_thesis.projection:v0.1",)


@pytest.mark.parametrize("state,reason", [("DISPROVEN", "THESIS_CORE_FACT_DISPROVEN"), ("INVALIDATED", "THESIS_CORE_FACT_INVALIDATED")])
def test_formal_thesis_terminal_states_are_both_deterministic(state, reason):
    result = _evaluate(
        {"formal_thesis_projection": _thesis_envelope(effective_state=state)}
    )
    assert result.hard_risk_state == "CONFIRMED"
    assert reason in result.reason_codes


def test_stable_thesis_is_not_a_clear_proof():
    result = _evaluate(
        {"formal_thesis_projection": _thesis_envelope(effective_state="STABLE", terminal=False)}
    )
    assert result.hard_risk_state == "UNKNOWN"
    assert result.hard_risk_evaluation == "UNKNOWN"
    assert "NO_POSITIVE_HARD_RISK_PROOF" in result.reason_codes


def test_confirmed_and_clear_proofs_conflict_to_unknown():
    result = _evaluate(
        {
            "hard_risk_proofs": [
                _proof(check_id="confirmed.check"),
                _proof(
                    check_id="clear.check",
                    risk_type="HARD_RISK_AGGREGATE",
                    state="CLEAR",
                    severity=None,
                    refs=["clear:v1"],
                    reasons=[],
                    coverage=[ALL_IMPLEMENTED_HARD_RISK_CHECKS],
                ),
            ]
        }
    )
    assert result.hard_risk_state == "UNKNOWN"
    assert result.hard_risk_evaluation == "UNKNOWN"
    assert "HARD_RISK_PROOF_CONFLICT" in result.reason_codes


def test_malformed_campaign_identity_fails_closed():
    with pytest.raises(HardRiskRuntimeError):
        _evaluate({}, campaign=_campaign(security_code="60051"))


def test_campaign_locator_must_match_true_backend_campaign():
    with pytest.raises(HardRiskRuntimeError, match="CAMPAIGN_LOCATOR_MISMATCH"):
        evaluate_hard_risk(
            campaign_id=CAMPAIGN_B,
            campaign=_campaign(campaign_id=CAMPAIGN_A),
            as_of=AS_OF,
            authoritative_facts={},
        )


def test_sibling_campaign_fact_cannot_leak_into_target():
    result = _evaluate(
        {"hard_risk_proofs": [_proof(campaign_id=CAMPAIGN_B)]}
    )
    assert result.hard_risk_state == "NOT_EVALUATED"
    assert result.hard_risk_evaluation == "NOT_EVALUATED"
    assert "AUTHORITY_IDENTITY_MISMATCH" in result.reason_codes
    assert "HARD_RISK_CONFIRMED" not in result.reason_codes


def test_backend_campaign_security_and_strategy_are_authority():
    result = _evaluate(
        {
            "hard_risk_proofs": [
                _proof(security_code="000001", strategy="SHORT")
            ]
        }
    )
    assert result.security_code == "600519"
    assert result.strategy == "SWING"
    assert result.hard_risk_state == "NOT_EVALUATED"
    assert "AUTHORITY_IDENTITY_MISMATCH" in result.reason_codes


def test_same_security_sibling_campaign_is_still_isolated():
    sibling = _campaign(campaign_id=CAMPAIGN_B, strategy="SWING")
    result = evaluate_hard_risk(
        campaign_id=CAMPAIGN_A,
        campaign=_campaign(campaign_id=CAMPAIGN_A),
        as_of=AS_OF,
        authoritative_facts={
            "hard_risk_proofs": [
                _proof(campaign_id=sibling["campaign_id"]),
            ]
        },
    )
    assert result.campaign_id == CAMPAIGN_A
    assert result.hard_risk_state == "NOT_EVALUATED"


def test_as_of_is_explicit_and_authority_mismatch_fails_closed():
    result = _evaluate(
        {"hard_risk_proofs": [_proof(as_of="2026-08-15T00:00:00Z")]}
    )
    assert result.as_of == AS_OF
    assert result.hard_risk_state == "NOT_EVALUATED"
    assert "AUTHORITY_AS_OF_MISMATCH" in result.reason_codes


def test_fact_lookahead_fails_closed():
    result = _evaluate(
        {
            "hard_risk_proofs": [
                _proof(fact_time="2026-08-17T00:00:00Z")
            ]
        }
    )
    assert result.hard_risk_state == "NOT_EVALUATED"
    assert "AUTHORITY_LOOKAHEAD" in result.reason_codes


def test_top_risk_score_is_not_hard_risk_authority():
    result = _evaluate(
        {
            "top_risk": {
                "risk_score": 999,
                "status": "critical",
                "crowding": 1.0,
                "runup": 1.0,
            }
        }
    )
    assert result.hard_risk_state == "NOT_EVALUATED"
    assert result.hard_risk_evaluation == "NOT_EVALUATED"


def test_critical_data_and_data_health_do_not_become_confirmed_hard_risk():
    result = _evaluate(
        {
            "critical_data_projection": {
                "critical_data_state": "BLOCKED",
                "critical_data_evaluation": "ERROR",
            },
            "data_health": {"status": "unavailable"},
            "disclosures": {"state": "ERROR"},
            "financials": {"state": "NOT_EVALUATED"},
            "trading_eligibility": {"status": "DELISTED"},
        }
    )
    assert result.hard_risk_state == "NOT_EVALUATED"
    assert result.hard_risk_state != "CONFIRMED"


def test_authority_refs_and_reason_codes_are_deterministic_under_input_reordering():
    first = _evaluate(
        {
            "hard_risk_proofs": [
                _proof(
                    check_id="z.check",
                    refs=["z-ref"],
                    reasons=["Z_REASON"],
                ),
                _proof(
                    check_id="a.check",
                    refs=["a-ref"],
                    reasons=["A_REASON"],
                ),
            ]
        }
    )
    second = _evaluate(
        {
            "hard_risk_proofs": [
                _proof(
                    check_id="a.check",
                    refs=["a-ref"],
                    reasons=["A_REASON"],
                ),
                _proof(
                    check_id="z.check",
                    refs=["z-ref"],
                    reasons=["Z_REASON"],
                ),
            ]
        }
    )
    assert first == second
    assert first.authority_refs == ("a-ref", "z-ref")
    assert first.reason_codes == tuple(sorted(first.reason_codes, key=lambda code: (code not in {"HARD_RISK_CONFIRMED"}, code)))


def test_input_and_output_are_detached():
    facts = {"hard_risk_proofs": [_proof(refs=["authority:v1"], reasons=["R1"])]}
    original = copy.deepcopy(facts)
    result = _evaluate(facts)
    assert facts == original
    payload = result.to_dict()
    payload["authority_refs"].append("caller:mutation")
    payload["reason_codes"].append("caller:mutation")
    assert result.authority_refs == ("authority:v1",)
    assert result.reason_codes == ("HARD_RISK_CONFIRMED", "R1")


def test_repeated_evaluation_is_deterministic():
    facts = {"formal_thesis_projection": _thesis_envelope()}
    expected = _evaluate(facts)
    for _ in range(25):
        assert _evaluate(copy.deepcopy(facts)) == expected


def test_result_never_emits_action_fields():
    result = _evaluate({"formal_thesis_projection": _thesis_envelope()})
    payload = result.to_dict()
    assert "EXIT" not in payload
    assert "SELL" not in payload
    assert "action" not in payload


def test_unknown_inputs_fail_closed_instead_of_becoming_new_authority():
    result = _evaluate({"invented_risk_engine": {"state": "CONFIRMED"}})
    assert result.hard_risk_state == "NOT_EVALUATED"
    assert result.hard_risk_evaluation == "NOT_EVALUATED"
    assert "AUTHORITY_PAYLOAD_INVALID" in result.reason_codes


def test_static_module_has_no_io_ai_or_wall_clock_dependency():
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    imported: set[str] = set()
    call_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                call_names.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                call_names.add(node.func.attr)
    assert imported.isdisjoint(
        {
            "os",
            "pathlib",
            "random",
            "requests",
            "httpx",
            "sqlite3",
            "duckdb",
            "openai",
            "anthropic",
            "ai",
        }
    )
    assert call_names.isdisjoint({"open", "connect", "request", "post", "now", "utcnow", "today", "time"})
