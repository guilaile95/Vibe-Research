"""Decision Challenge Coverage projection tests (P0-DC1)."""

from __future__ import annotations

import ast
import copy
import importlib
import inspect
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import decision_challenge_projection as dc


AS_OF = "2026-08-13T12:00:00Z"
FIRST_AT = "2026-08-13T10:00:00Z"
SECOND_AT = "2026-08-13T11:00:00Z"
SEC = "600519"
CAMP_A = "campaign_" + ("a" * 32)
CAMP_B = "campaign_" + ("b" * 32)
DEC_A = "decision_" + ("c" * 32)
DEC_B = "decision_" + ("d" * 32)
POLICY = dc.POLICY_VERSION_V01


def _dim(evaluation: str, refs: list[str] | None = None) -> dict:
    payload = {"evaluation": evaluation}
    if refs is not None:
        payload["authority_refs"] = refs
    elif evaluation in {"EVALUATED", "UNKNOWN"}:
        payload["authority_refs"] = [f"dim:{evaluation.lower()}"]
    return payload


def _all_evaluated() -> dict:
    return {
        dim: _dim("EVALUATED", [f"ref:{dim}"])
        for dim in dc.REQUIRED_DIMENSIONS
    }


def _project(**overrides):
    base = {
        "security_code": SEC,
        "strategy": "SWING",
        "campaign_id": CAMP_A,
        "decision_id": DEC_A,
        "as_of": AS_OF,
        "policy_version": POLICY,
        "challenge_requirement": "REQUIRED",
        "challenge_requirement_authority_refs": ["req:importance:1"],
        "dimension_results": _all_evaluated(),
        "first_pass_ref": "review:first:1",
        "first_pass_at": FIRST_AT,
        "second_pass_ref": "review:second:1",
        "second_pass_at": SECOND_AT,
    }
    base.update(overrides)
    return dc.project_decision_challenge(**base)


def test_a_required_all_evaluated_two_pass_complete():
    out = _project()
    assert out["challenge_packet_state"] == "COMPLETE"
    assert out["challenge_evaluation"] == "EVALUATED"
    assert out["two_pass_state"] == "VALID"
    assert out["covered_dimensions"] == list(dc.REQUIRED_DIMENSIONS)
    assert out["unknown_dimensions"] == []
    assert "CHALLENGE_PACKET_COMPLETE" in out["reason_codes"]


def test_b_one_dimension_unknown_complete_unknown():
    dims = _all_evaluated()
    dims["STRONGEST_OPPOSING_EVIDENCE"] = _dim("UNKNOWN", ["opp:unknown"])
    out = _project(dimension_results=dims)
    assert out["challenge_packet_state"] == "COMPLETE"
    assert out["challenge_evaluation"] == "UNKNOWN"
    assert "STRONGEST_OPPOSING_EVIDENCE" in out["unknown_dimensions"]
    assert "STRONGEST_OPPOSING_EVIDENCE" in out["covered_dimensions"]


def test_c_unknown_dimension_explicitly_surfaced():
    dims = _all_evaluated()
    dims["PRE_MORTEM"] = _dim("UNKNOWN", ["pm:unknown"])
    out = _project(dimension_results=dims)
    assert out["unknown_dimensions"] == ["PRE_MORTEM"]
    assert "UNKNOWN_EQUALS_POSITIVE_EVIDENCE=NO" in out["explainability"]["note"]


def test_d_unknown_not_equal_not_evaluated():
    dims_u = _all_evaluated()
    dims_u["INVALIDATION_FACTS"] = _dim("UNKNOWN", ["inv:u"])
    dims_n = _all_evaluated()
    dims_n["INVALIDATION_FACTS"] = _dim("NOT_EVALUATED")
    u = _project(dimension_results=dims_u)
    n = _project(dimension_results=dims_n)
    assert u["challenge_packet_state"] == "COMPLETE"
    assert n["challenge_packet_state"] == "INCOMPLETE"
    assert u["challenge_evaluation"] != n["challenge_evaluation"]


def test_e_opposing_not_evaluated_incomplete():
    dims = _all_evaluated()
    dims["STRONGEST_OPPOSING_EVIDENCE"] = _dim("NOT_EVALUATED")
    out = _project(dimension_results=dims)
    assert out["challenge_packet_state"] == "INCOMPLETE"
    assert out["challenge_evaluation"] == "NOT_EVALUATED"
    assert "OPPOSING_EVIDENCE_NOT_EVALUATED" in out["reason_codes"]


def test_f_pre_mortem_error_incomplete_error():
    dims = _all_evaluated()
    dims["PRE_MORTEM"] = _dim("ERROR")
    out = _project(dimension_results=dims)
    assert out["challenge_packet_state"] == "INCOMPLETE"
    assert out["challenge_evaluation"] == "ERROR"
    assert "PRE_MORTEM_ERROR" in out["reason_codes"]


def test_g_multiple_incomplete_reasons_cumulative():
    dims = _all_evaluated()
    dims["STRONGEST_OPPOSING_EVIDENCE"] = _dim("NOT_EVALUATED")
    dims["PRE_MORTEM"] = _dim("ERROR")
    out = _project(
        dimension_results=dims,
        first_pass_ref=None,
        first_pass_at=None,
        second_pass_ref=None,
        second_pass_at=None,
    )
    assert "OPPOSING_EVIDENCE_NOT_EVALUATED" in out["reason_codes"]
    assert "PRE_MORTEM_ERROR" in out["reason_codes"]
    assert "TWO_PASS_INCOMPLETE" in out["reason_codes"]
    assert out["challenge_evaluation"] == "ERROR"


def test_h_not_required_not_applicable():
    out = _project(
        challenge_requirement="NOT_REQUIRED",
        dimension_results=None,
        first_pass_ref=None,
        first_pass_at=None,
        second_pass_ref=None,
        second_pass_at=None,
    )
    assert out["challenge_packet_state"] == "NOT_APPLICABLE"
    assert out["challenge_evaluation"] == "EVALUATED"
    assert out["two_pass_state"] == "NOT_APPLICABLE"
    assert "CHALLENGE_NOT_REQUIRED" in out["reason_codes"]


def test_i_not_required_requires_authority_witness():
    with pytest.raises(
        dc.DecisionChallengeValidationError,
        match="challenge_requirement_authority_refs",
    ):
        _project(
            challenge_requirement="NOT_REQUIRED",
            challenge_requirement_authority_refs=[],
            dimension_results=None,
            first_pass_ref=None,
            first_pass_at=None,
            second_pass_ref=None,
            second_pass_at=None,
        )


def test_j_requirement_unknown_not_not_applicable():
    out = _project(
        challenge_requirement="UNKNOWN",
        dimension_results=None,
        first_pass_ref=None,
        first_pass_at=None,
        second_pass_ref=None,
        second_pass_at=None,
    )
    assert out["challenge_packet_state"] != "NOT_APPLICABLE"
    assert out["challenge_packet_state"] == "INCOMPLETE"
    assert out["challenge_evaluation"] == "UNKNOWN"
    assert "CHALLENGE_REQUIREMENT_UNKNOWN" in out["reason_codes"]


def test_k_requirement_not_evaluated_not_not_applicable():
    out = _project(
        challenge_requirement="NOT_EVALUATED",
        dimension_results=None,
        first_pass_ref=None,
        first_pass_at=None,
        second_pass_ref=None,
        second_pass_at=None,
    )
    assert out["challenge_packet_state"] != "NOT_APPLICABLE"
    assert out["challenge_evaluation"] == "NOT_EVALUATED"
    assert "CHALLENGE_REQUIREMENT_NOT_EVALUATED" in out["reason_codes"]


def test_l_requirement_error_preserved():
    out = _project(
        challenge_requirement="ERROR",
        dimension_results=None,
        first_pass_ref=None,
        first_pass_at=None,
        second_pass_ref=None,
        second_pass_at=None,
    )
    assert out["challenge_packet_state"] != "NOT_APPLICABLE"
    assert out["challenge_evaluation"] == "ERROR"
    assert "CHALLENGE_REQUIREMENT_ERROR" in out["reason_codes"]


def test_m_missing_dimension_authority_refs_fail_closed():
    dims = _all_evaluated()
    dims["STRONGEST_SUPPORTING_EVIDENCE"] = {
        "evaluation": "EVALUATED",
        "authority_refs": [],
    }
    with pytest.raises(dc.DecisionChallengeValidationError, match="authority_refs"):
        _project(dimension_results=dims)


def test_n_empty_requirement_refs_fail_closed():
    with pytest.raises(
        dc.DecisionChallengeValidationError,
        match="challenge_requirement_authority_refs",
    ):
        _project(challenge_requirement_authority_refs=[])


def test_o_same_pass_refs_fail_closed():
    with pytest.raises(dc.DecisionChallengeValidationError, match="first_pass_ref"):
        _project(first_pass_ref="review:same", second_pass_ref="review:same")


def test_p_second_pass_before_first_fail_closed():
    with pytest.raises(dc.DecisionChallengeValidationError, match="second_pass_at"):
        _project(first_pass_at=SECOND_AT, second_pass_at=FIRST_AT)


def test_q_second_pass_after_as_of_fail_closed():
    with pytest.raises(dc.DecisionChallengeValidationError, match="as_of"):
        _project(second_pass_at="2026-08-13T13:00:00Z")


def test_r_strict_utc_timestamp_validation():
    with pytest.raises(dc.DecisionChallengeValidationError, match="as_of"):
        _project(as_of="2026-08-13")
    with pytest.raises(dc.DecisionChallengeValidationError, match="as_of"):
        _project(as_of="2026-08-13T12:00:00+08:00")
    out = _project(as_of="2026-08-13T12:00:00+00:00")
    assert out["as_of"] == "2026-08-13T12:00:00+00:00"


def test_s_unknown_policy_not_evaluated():
    out = _project(policy_version="dc.decision_challenge.v9.9")
    assert out["challenge_evaluation"] == "NOT_EVALUATED"
    assert out["challenge_packet_state"] == "INCOMPLETE"
    assert "POLICY_VERSION_NOT_AVAILABLE" in out["reason_codes"]
    assert out["policy_authority_ref"] is None


def test_t_no_latest_policy_fallback():
    out = _project(policy_version="dc.unknown")
    assert out["policy_version"] == "dc.unknown"
    assert out["challenge_packet_state"] != "COMPLETE"


def test_u_as_of_does_not_select_policy():
    a = _project(as_of="2020-01-01T00:00:00Z", second_pass_at="2020-01-01T00:00:00Z", first_pass_at="2019-12-31T00:00:00Z")
    b = _project(as_of="2030-01-01T00:00:00Z")
    assert a["policy_version"] == b["policy_version"] == POLICY
    u = _project(
        as_of="2030-01-01T00:00:00Z",
        policy_version="dc.unknown",
    )
    assert u["challenge_evaluation"] == "NOT_EVALUATED"


def test_v_decision_identity_isolation():
    out = _project()
    assert out["security_code"] == SEC
    assert out["campaign_id"] == CAMP_A
    assert out["decision_id"] == DEC_A
    assert CAMP_B not in str(out)
    assert DEC_B not in str(out)


def test_w_same_security_different_campaign_isolated():
    a = _project(campaign_id=CAMP_A, decision_id=DEC_A)
    b = _project(campaign_id=CAMP_B, decision_id=DEC_B)
    assert a["campaign_id"] != b["campaign_id"]
    assert a["decision_id"] != b["decision_id"]
    assert a["security_code"] == b["security_code"]
    assert CAMP_B not in str(a)
    assert CAMP_A not in str(b)


def test_x_input_immutability():
    req_refs = ["req:1"]
    dims = _all_evaluated()
    snap = copy.deepcopy({"req": req_refs, "dims": dims})
    dc.project_decision_challenge(
        security_code=SEC,
        strategy="SWING",
        campaign_id=CAMP_A,
        decision_id=DEC_A,
        as_of=AS_OF,
        policy_version=POLICY,
        challenge_requirement="REQUIRED",
        challenge_requirement_authority_refs=req_refs,
        dimension_results=dims,
        first_pass_ref="review:first:1",
        first_pass_at=FIRST_AT,
        second_pass_ref="review:second:1",
        second_pass_at=SECOND_AT,
    )
    assert req_refs == snap["req"]
    assert dims == snap["dims"]


def test_y_deterministic_repeated_output():
    assert _project() == _project()


def test_z_no_buy_sell_authority():
    out = _project()
    for token in ("BUY NOW", "EXIT", "REDUCE", "HOLD", "AVOID"):
        assert token not in out["reason_codes"]
        assert out.get("recommended_action") is None
    assert "BUY_SELL" not in out
    assert out["challenge_requirement"] == "REQUIRED"


def test_aa_no_action_envelope():
    out = _project()
    assert "action_envelope" not in out
    assert out.get("next_best_action") is None


def test_ab_no_evidence_arbitration():
    out = _project()
    assert out.get("evidence_conflict") is None
    assert out.get("materiality") is None
    assert "FACT" not in out["reason_codes"]


def test_ac_no_evidence_strength_scoring():
    out = _project()
    assert out.get("evidence_strength_score") is None
    assert out.get("decision_confidence") is None
    assert "STRONGEST_EVIDENCE_SELECTION_OWNED_BY_DC1=NO" in out["explainability"]["note"]


def test_ad_no_ai_imports():
    src = Path(dc.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    forbidden = {
        "openai",
        "anthropic",
        "sqlite3",
        "pathlib",
        "os",
        "sys",
        "subprocess",
        "socket",
        "requests",
        "fastapi",
        "frozen_decision_store",
        "frozen_decision_service",
        "decision_assurance_projection",
        "decision_evidence_delta_projection",
        "account_drawdown_projection",
        "risk_budget_projection",
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] not in forbidden
        if isinstance(node, ast.ImportFrom) and node.module:
            assert node.module.split(".")[0] not in forbidden
    assert "open(" not in src


def test_ae_no_io():
    src = Path(dc.__file__).read_text(encoding="utf-8")
    assert "sqlite3" not in src
    assert "Path(" not in src


def test_af_no_wall_clock():
    src = Path(dc.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in {"now", "utcnow", "today"}:
                pytest.fail(f"wall clock forbidden: {node.func.attr}")
    assert "datetime.now" not in src
    assert "time.time" not in src


def test_ag_keyword_only_public_api():
    sig = inspect.signature(dc.project_decision_challenge)
    assert all(
        p.kind == inspect.Parameter.KEYWORD_ONLY for p in sig.parameters.values()
    )
    assert dc.POLICY_VERSION_V01 == "dc.decision_challenge.v0.1"


def test_adversarial_complete_is_not_decision_correct_or_allowed():
    out = _project()
    assert out["challenge_packet_state"] == "COMPLETE"
    note = out["explainability"]["note"]
    assert "CHALLENGE_COVERAGE_NE_DECISION_CORRECTNESS" in note
    assert "CHALLENGE_COVERAGE_NE_DECISION_APPROVAL" in note
    assert out.get("buy_allowed") is None
    assert out.get("sell_allowed") is None
    assert out.get("decision_correct") is None


def test_adversarial_unknown_opposing_is_not_no_opposing():
    dims = _all_evaluated()
    dims["STRONGEST_OPPOSING_EVIDENCE"] = _dim("UNKNOWN", ["opp:unknown"])
    out = _project(dimension_results=dims)
    assert "NO_OPPOSING_EVIDENCE" not in out["reason_codes"]
    assert "STRONGEST_OPPOSING_EVIDENCE" in out["unknown_dimensions"]
    assert out["dimension_results"]["STRONGEST_OPPOSING_EVIDENCE"]["evaluation"] == (
        "UNKNOWN"
    )


def test_adversarial_not_required_comes_from_upstream():
    out = _project(
        challenge_requirement="NOT_REQUIRED",
        challenge_requirement_authority_refs=["req:upstream:1"],
        dimension_results=None,
        first_pass_ref=None,
        first_pass_at=None,
        second_pass_ref=None,
        second_pass_at=None,
    )
    assert out["challenge_requirement_authority_refs"] == ["req:upstream:1"]
    assert "DC1_DECIDES_IMPORTANCE=NO" in out["explainability"]["note"]


def test_adversarial_two_pass_structure_not_semantic_independence():
    out = _project()
    assert out["two_pass_state"] == "VALID"
    assert "TWO_PASS_SEMANTIC_INDEPENDENCE_VERIFIED=NO" in out["explainability"]["note"]


def test_adversarial_dc1_does_not_select_strongest_evidence():
    src = Path(dc.__file__).read_text(encoding="utf-8")
    assert "max(" not in src
    assert "strongest =" not in src.lower()
    out = _project()
    assert out.get("selected_supporting_evidence") is None
    assert out.get("selected_opposing_evidence") is None


def test_malformed_identity_reject():
    with pytest.raises(dc.DecisionChallengeValidationError, match="security_code"):
        _project(security_code="60051")
    with pytest.raises(dc.DecisionChallengeValidationError, match="campaign_id"):
        _project(campaign_id="camp-1")
    with pytest.raises(dc.DecisionChallengeValidationError, match="decision_id"):
        _project(decision_id="dec-1")
    with pytest.raises(dc.DecisionChallengeValidationError, match="strategy"):
        _project(strategy="LONG")


def test_policy_version_required():
    with pytest.raises(TypeError):
        dc.project_decision_challenge(
            security_code=SEC,
            strategy="SWING",
            campaign_id=CAMP_A,
            decision_id=DEC_A,
            as_of=AS_OF,
            challenge_requirement="NOT_REQUIRED",
            challenge_requirement_authority_refs=["r"],
        )


def test_missing_two_pass_when_required_incomplete():
    out = _project(
        first_pass_ref=None,
        first_pass_at=None,
        second_pass_ref=None,
        second_pass_at=None,
    )
    assert out["challenge_packet_state"] == "INCOMPLETE"
    assert out["two_pass_state"] == "INCOMPLETE"
    assert "TWO_PASS_INCOMPLETE" in out["reason_codes"]


def test_reload_pure():
    importlib.reload(dc)
    out = _project()
    assert out["schema_version"] == dc.SCHEMA_VERSION
    assert out["challenge_packet_state"] == "COMPLETE"


# ---------------------------------------------------------------------------
# R1: unknown policy must not apply v0.1 packet semantics
# ---------------------------------------------------------------------------


def test_r1_a_unknown_policy_required_no_packet_not_evaluated():
    out = _project(
        policy_version="dc.decision_challenge.v9.9",
        challenge_requirement="REQUIRED",
        dimension_results=None,
        first_pass_ref=None,
        first_pass_at=None,
        second_pass_ref=None,
        second_pass_at=None,
    )
    assert out["challenge_evaluation"] == "NOT_EVALUATED"
    assert out["challenge_packet_state"] == "INCOMPLETE"
    assert "POLICY_VERSION_NOT_AVAILABLE" in out["reason_codes"]
    assert "TWO_PASS_INCOMPLETE" not in out["reason_codes"]
    assert "CHALLENGE_PACKET_COMPLETE" not in out["reason_codes"]


def test_r1_b_unknown_policy_complete_looking_packet_still_not_evaluated():
    out = _project(policy_version="dc.unknown")
    assert out["challenge_evaluation"] == "NOT_EVALUATED"
    assert out["challenge_packet_state"] == "INCOMPLETE"
    assert out["challenge_packet_state"] != "COMPLETE"
    assert "CHALLENGE_PACKET_COMPLETE" not in out["reason_codes"]
    assert "CHALLENGE_PACKET_COVERED_WITH_UNKNOWN" not in out["reason_codes"]


def test_r1_c_unknown_policy_unknown_requirement_cumulative():
    out = _project(
        policy_version="dc.unknown",
        challenge_requirement="UNKNOWN",
        dimension_results=None,
        first_pass_ref=None,
        first_pass_at=None,
        second_pass_ref=None,
        second_pass_at=None,
    )
    assert out["challenge_evaluation"] == "NOT_EVALUATED"
    assert out["reason_codes"] == [
        "POLICY_VERSION_NOT_AVAILABLE",
        "CHALLENGE_REQUIREMENT_UNKNOWN",
    ]
    assert out["challenge_requirement"] == "UNKNOWN"


def test_r1_d_unknown_policy_not_evaluated_requirement_cumulative():
    out = _project(
        policy_version="dc.unknown",
        challenge_requirement="NOT_EVALUATED",
        dimension_results=None,
        first_pass_ref=None,
        first_pass_at=None,
        second_pass_ref=None,
        second_pass_at=None,
    )
    assert out["challenge_evaluation"] == "NOT_EVALUATED"
    assert out["reason_codes"] == [
        "POLICY_VERSION_NOT_AVAILABLE",
        "CHALLENGE_REQUIREMENT_NOT_EVALUATED",
    ]


def test_r1_e_unknown_policy_error_requirement_preserves_error_reason():
    out = _project(
        policy_version="dc.unknown",
        challenge_requirement="ERROR",
        dimension_results=None,
        first_pass_ref=None,
        first_pass_at=None,
        second_pass_ref=None,
        second_pass_at=None,
    )
    assert out["challenge_evaluation"] == "NOT_EVALUATED"
    assert out["reason_codes"] == [
        "POLICY_VERSION_NOT_AVAILABLE",
        "CHALLENGE_REQUIREMENT_ERROR",
    ]
    assert out["challenge_requirement"] == "ERROR"


def test_r1_f_unknown_policy_not_required_not_not_applicable():
    out = _project(
        policy_version="dc.unknown",
        challenge_requirement="NOT_REQUIRED",
        dimension_results=None,
        first_pass_ref=None,
        first_pass_at=None,
        second_pass_ref=None,
        second_pass_at=None,
    )
    assert out["challenge_evaluation"] == "NOT_EVALUATED"
    assert out["challenge_packet_state"] == "INCOMPLETE"
    assert out["challenge_packet_state"] != "NOT_APPLICABLE"
    assert out["challenge_requirement"] == "NOT_REQUIRED"
    assert "CHALLENGE_NOT_REQUIRED" not in out["reason_codes"]


def test_r1_g_unknown_policy_does_not_expose_v01_required_dimensions():
    out = _project(
        policy_version="dc.unknown",
        dimension_results=None,
        first_pass_ref=None,
        first_pass_at=None,
        second_pass_ref=None,
        second_pass_at=None,
    )
    assert out["explainability"]["required_dimensions"] == []
    assert "POLICY_SEMANTICS_APPLIED=NO" in out["explainability"]["note"]
    assert "NO_IMPLICIT_V01_PACKET" in out["explainability"]["note"]


def test_r1_h_unknown_policy_never_packet_complete():
    out = _project(policy_version="dc.unknown")
    assert "CHALLENGE_PACKET_COMPLETE" not in out["reason_codes"]
    assert out["challenge_packet_state"] != "COMPLETE"
