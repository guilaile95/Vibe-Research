"""Sell Engine Projection Core v0.1 acceptance matrix (P0-SE1 / R1)."""

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

import sell_engine_projection as se


AS_OF = "2026-08-12T10:00:00Z"
SEC = "600519"
CAMP_SWING = "campaign_" + ("a" * 32)
CAMP_MEDIUM = "campaign_" + ("b" * 32)
CAMP_SHORT = "campaign_" + ("c" * 32)


def _dim(state: str, *refs: str) -> dict:
    return {"state": state, "authority_refs": list(refs)}


def _clean_dims(**overrides: dict) -> dict:
    base = {
        "thesis": _dim("STABLE", "thesis:1"),
        "risk_exit": _dim("NONE", "risk_exit:1"),
        "expectation_price_in": _dim("NONE", "exp:1"),
        "risk_reward": _dim("NONE", "rr:1"),
        "catalyst": _dim("NONE", "cat:1"),
        "portfolio_rebalance": _dim("NONE", "port:1"),
        "opportunity_cost": _dim("NONE", "opp:1"),
        "technical_execution": _dim("NONE", "tech:1"),
    }
    base.update(overrides)
    return base


def _project(
    *,
    strategy: str = "SWING",
    campaign_id: str = CAMP_SWING,
    security_code: str = SEC,
    as_of: str = AS_OF,
    **dims,
):
    payload = _clean_dims(**dims)
    return se.project_sell_engine(
        security_code=security_code,
        strategy=strategy,
        campaign_id=campaign_id,
        as_of=as_of,
        **payload,
    )


# ---------------------------------------------------------------------------
# A. THESIS INVALIDATION
# ---------------------------------------------------------------------------


def test_a_thesis_invalidated_maps_to_thesis_invalidated_state():
    out = _project(thesis=_dim("INVALIDATED", "thesis:inv"))
    assert out["sell_state"] == "THESIS_INVALIDATED"
    assert out["primary_reason"] == "THESIS_INVALIDATION"
    assert "THESIS_INVALIDATED" in out["reason_codes"]
    assert out["sell_evaluation"] == "EVALUATED"
    assert out["hold_positive_proof"] is False


def test_a_thesis_disproven_maps_to_thesis_invalidated():
    out = _project(thesis=_dim("DISPROVEN", "thesis:dis"))
    assert out["sell_state"] == "THESIS_INVALIDATED"
    assert out["primary_reason"] == "THESIS_INVALIDATION"
    assert "THESIS_DISPROVEN" in out["reason_codes"]


def test_a_weakened_not_thesis_invalidation_no_auto_watch():
    out = _project(thesis=_dim("WEAKENED", "thesis:w"))
    assert out["sell_state"] is None
    assert out["primary_reason"] is None
    assert out["hold_positive_proof"] is False
    assert "THESIS_WEAKENED" in out["reason_codes"]
    assert "THESIS_INVALIDATION" not in out["supporting_reasons"]
    assert out["sell_state"] != "WATCH_TO_REDUCE"
    assert out["sell_state"] != "THESIS_INVALIDATED"


def test_a_loss_alone_not_accepted_as_input():
    with pytest.raises(se.SellEngineValidationError, match="unsupported keys"):
        _project(thesis={"state": "STABLE", "authority_refs": ["t"], "pnl": -0.2})


# ---------------------------------------------------------------------------
# B. RISK EXIT (normalized pressure, not raw hard risk)
# ---------------------------------------------------------------------------


def test_b_normalized_risk_exit_exit_pressure():
    out = _project(risk_exit=_dim("EXIT", "risk_exit:env"))
    assert out["sell_state"] == "EXIT"
    assert out["primary_reason"] == "RISK_EXIT"
    assert "RISK_EXIT_EXIT" in out["reason_codes"]


def test_b_risk_exit_none_no_pressure():
    out = _project()
    assert out["sell_state"] == "HOLD"
    assert "RISK_EXIT_NONE" in out["reason_codes"]


def test_b_hard_risk_confirmed_raw_state_not_accepted():
    # Raw hard-risk vocabulary is not a sell-engine input.
    with pytest.raises(se.SellEngineValidationError, match="risk_exit.state"):
        _project(risk_exit=_dim("CONFIRMED", "hr:1"))


def test_b_hard_risk_confirmed_alone_does_not_auto_exit():
    # Even if caller tries legacy field name — only risk_exit pressure exists.
    # Confirmed: no automatic EXIT without normalized EXIT pressure.
    out = _project(risk_exit=_dim("NONE", "risk_exit:clear"))
    assert out["sell_state"] == "HOLD"
    assert out["sell_state"] != "EXIT"


# ---------------------------------------------------------------------------
# C. EXPECTATION / PRICE-IN
# ---------------------------------------------------------------------------


def test_c_expectation_reduce_pressure():
    out = _project(expectation_price_in=_dim("REDUCE", "exp:r"))
    assert out["sell_state"] == "REDUCE"
    assert out["primary_reason"] == "EXPECTATION_PRICE_IN"
    assert "EXPECTATION_PRICE_IN_REDUCE" in out["reason_codes"]


def test_c_expectation_exit_pass_through_no_silent_downgrade():
    out = _project(expectation_price_in=_dim("EXIT", "exp:e"))
    assert out["sell_state"] == "EXIT"
    assert out["primary_reason"] == "EXPECTATION_PRICE_IN"
    assert "EXPECTATION_PRICE_IN_EXIT" in out["reason_codes"]


# ---------------------------------------------------------------------------
# D. R/R DETERIORATION — no silent downgrade
# ---------------------------------------------------------------------------


def test_d_rr_exit_not_silently_downgraded():
    out = _project(risk_reward=_dim("EXIT", "rr:e"))
    assert out["sell_state"] == "EXIT"
    assert out["primary_reason"] == "RISK_REWARD_DETERIORATION"
    assert "RISK_REWARD_EXIT" in out["reason_codes"]
    assert "CAPPED" not in "".join(out["reason_codes"])


def test_d_rr_watch_maps_to_watch_to_reduce():
    out = _project(risk_reward=_dim("WATCH", "rr:w"))
    assert out["sell_state"] == "WATCH_TO_REDUCE"


# ---------------------------------------------------------------------------
# E. CATALYST — normalized pressure; applicability upstream-owned
# ---------------------------------------------------------------------------


def test_e_catalyst_exit_pass_through():
    out = _project(
        strategy="SHORT",
        campaign_id=CAMP_SHORT,
        catalyst=_dim("EXIT", "cat:e"),
    )
    assert out["sell_state"] == "EXIT"
    assert out["primary_reason"] == "CATALYST_FAILURE"


def test_e_catalyst_reduce_pass_through():
    out = _project(catalyst=_dim("REDUCE", "cat:r"))
    assert out["sell_state"] == "REDUCE"
    assert out["primary_reason"] == "CATALYST_FAILURE"


def test_e_catalyst_not_yet_is_not_failure():
    out = _project(catalyst=_dim("NOT_YET", "cat:ny"))
    assert out["sell_state"] == "HOLD"
    assert out["primary_reason"] is None
    assert "CATALYST_NOT_YET" in out["reason_codes"]


def test_e_medium_catalyst_not_applicable_ok():
    out = _project(
        strategy="MEDIUM",
        campaign_id=CAMP_MEDIUM,
        catalyst=_dim("NOT_APPLICABLE", "cat:na"),
    )
    assert out["sell_state"] == "HOLD"
    assert "CATALYST_NOT_APPLICABLE" in out["reason_codes"]


def test_e_short_catalyst_authoritative_not_applicable_allowed():
    out = _project(
        strategy="SHORT",
        campaign_id=CAMP_SHORT,
        catalyst=_dim("NOT_APPLICABLE", "cat:na-short"),
    )
    assert out["sell_state"] == "HOLD"
    assert out["dimensions"]["catalyst"]["applicable"] is False


# ---------------------------------------------------------------------------
# F. PORTFOLIO REBALANCE
# ---------------------------------------------------------------------------


def test_f_portfolio_rebalance_reduce_preserves_reason():
    out = _project(portfolio_rebalance=_dim("REDUCE", "port:r"))
    assert out["sell_state"] == "REDUCE"
    assert out["primary_reason"] == "PORTFOLIO_REBALANCE"
    assert "PORTFOLIO_REBALANCE" in out["supporting_reasons"]
    assert "asset_view" not in out


# ---------------------------------------------------------------------------
# G. OPPORTUNITY COST — no silent EXIT→REDUCE
# ---------------------------------------------------------------------------


def test_g_opportunity_cost_exit_not_silently_downgraded():
    out = _project(opportunity_cost=_dim("EXIT", "opp:e"))
    assert out["sell_state"] == "EXIT"
    assert out["primary_reason"] == "OPPORTUNITY_COST"
    assert "OPPORTUNITY_COST_EXIT" in out["reason_codes"]
    assert "CAPPED" not in "".join(out["reason_codes"])


def test_g_opportunity_cost_not_evaluated_blocks_hold():
    out = _project(opportunity_cost=_dim("NOT_EVALUATED"))
    assert out["sell_state"] is None
    assert out["hold_positive_proof"] is False
    assert out["sell_evaluation"] == "NOT_EVALUATED"
    assert "OPPORTUNITY_COST_NOT_EVALUATED" in out["uncertainties"]


# ---------------------------------------------------------------------------
# H. TECHNICAL EXECUTION — pass through normalized pressure
# ---------------------------------------------------------------------------


def test_h_medium_technical_exit_fail_closed():
    with pytest.raises(se.SellEngineValidationError, match="MEDIUM"):
        _project(
            strategy="MEDIUM",
            campaign_id=CAMP_MEDIUM,
            catalyst=_dim("NOT_APPLICABLE", "cat:na"),
            technical_execution=_dim("EXIT", "tech:e"),
        )


def test_h_medium_technical_watch_allowed():
    out = _project(
        strategy="MEDIUM",
        campaign_id=CAMP_MEDIUM,
        catalyst=_dim("NOT_APPLICABLE", "cat:na"),
        technical_execution=_dim("WATCH", "tech:w"),
    )
    assert out["sell_state"] == "WATCH_TO_REDUCE"
    assert out["primary_reason"] == "TECHNICAL_EXECUTION"


def test_h_medium_technical_reduce_allowed():
    out = _project(
        strategy="MEDIUM",
        campaign_id=CAMP_MEDIUM,
        catalyst=_dim("NOT_APPLICABLE", "cat:na"),
        technical_execution=_dim("REDUCE", "tech:r"),
    )
    assert out["sell_state"] == "REDUCE"
    assert out["primary_reason"] == "TECHNICAL_EXECUTION"


def test_h_medium_technical_not_applicable_allowed():
    out = _project(
        strategy="MEDIUM",
        campaign_id=CAMP_MEDIUM,
        catalyst=_dim("NOT_APPLICABLE", "cat:na"),
        technical_execution=_dim("NOT_APPLICABLE", "tech:na"),
    )
    assert out["sell_state"] == "HOLD"
    assert out["hold_positive_proof"] is True


def test_h_short_technical_exit_still_allowed():
    out = _project(
        strategy="SHORT",
        campaign_id=CAMP_SHORT,
        technical_execution=_dim("EXIT", "tech:e"),
    )
    assert out["sell_state"] == "EXIT"
    assert out["primary_reason"] == "TECHNICAL_EXECUTION"


def test_h_technical_watch():
    out = _project(technical_execution=_dim("WATCH", "tech:w"))
    assert out["sell_state"] == "WATCH_TO_REDUCE"


# ---------------------------------------------------------------------------
# I. multiple reasons cumulative
# ---------------------------------------------------------------------------


def test_i_multiple_reasons_cumulative_not_collapsed():
    out = _project(
        risk_reward=_dim("REDUCE", "rr:r"),
        portfolio_rebalance=_dim("WATCH", "port:w"),
        technical_execution=_dim("WATCH", "tech:w"),
    )
    assert out["sell_state"] == "REDUCE"
    assert "RISK_REWARD_DETERIORATION" in out["supporting_reasons"]
    assert "PORTFOLIO_REBALANCE" in out["supporting_reasons"]
    assert "TECHNICAL_EXECUTION" in out["supporting_reasons"]
    assert out["primary_reason"] in out["supporting_reasons"]
    assert out["primary_reason"] == "RISK_REWARD_DETERIORATION"
    assert len(out["supporting_reasons"]) >= 3


# ---------------------------------------------------------------------------
# J. primary reason must drive final sell_state
# ---------------------------------------------------------------------------


def test_j_primary_must_drive_final_state_expectation_over_catalyst():
    # Blocking counterexample from R1: Catalyst REDUCE + Expectation EXIT
    # must not pick CATALYST_FAILURE as primary for EXIT.
    out = _project(
        catalyst=_dim("REDUCE", "c"),
        expectation_price_in=_dim("EXIT", "e"),
    )
    assert out["sell_state"] == "EXIT"
    assert out["primary_reason"] == "EXPECTATION_PRICE_IN"
    assert out["primary_reason"] != "CATALYST_FAILURE"
    assert "CATALYST_FAILURE" in out["supporting_reasons"]
    assert out["primary_reason"] in out["co_driving_reasons"]
    # Only EXIT drivers are co-driving for EXIT.
    assert "CATALYST_FAILURE" not in out["co_driving_reasons"]


def test_j_thesis_terminal_primary_for_thesis_invalidated():
    out = _project(
        thesis=_dim("INVALIDATED", "t"),
        risk_exit=_dim("EXIT", "h"),
        risk_reward=_dim("REDUCE", "r"),
    )
    assert out["sell_state"] == "THESIS_INVALIDATED"
    assert out["primary_reason"] == "THESIS_INVALIDATION"
    assert "RISK_EXIT" in out["supporting_reasons"]


def test_j_co_drivers_display_tie_break_not_semantic():
    out = _project(
        risk_exit=_dim("EXIT", "r"),
        expectation_price_in=_dim("EXIT", "e"),
    )
    assert out["sell_state"] == "EXIT"
    assert set(out["co_driving_reasons"]) == {
        "RISK_EXIT",
        "EXPECTATION_PRICE_IN",
    }
    assert out["primary_reason"] in out["co_driving_reasons"]
    assert out["primary_reason_selection"] == (
        "DISPLAY_TIE_BREAK_NOT_SEMANTIC_PRIORITY"
    )


# ---------------------------------------------------------------------------
# K. Campaign isolation
# ---------------------------------------------------------------------------


def test_k_campaign_isolation_same_security_different_results():
    swing = _project(
        strategy="SWING",
        campaign_id=CAMP_SWING,
        catalyst=_dim("REDUCE", "c1"),
    )
    medium = _project(
        strategy="MEDIUM",
        campaign_id=CAMP_MEDIUM,
        catalyst=_dim("NOT_APPLICABLE", "c2"),
        technical_execution=_dim("WATCH", "t2"),
    )
    assert swing["campaign_id"] != medium["campaign_id"]
    assert swing["security_code"] == medium["security_code"]
    assert swing["sell_state"] == "REDUCE"
    assert medium["sell_state"] == "WATCH_TO_REDUCE"
    assert swing["primary_reason"] != medium["primary_reason"]


def test_k_no_sibling_state_leak_in_output():
    out = _project(campaign_id=CAMP_SWING)
    assert out["campaign_id"] == CAMP_SWING
    assert CAMP_MEDIUM not in str(out)
    assert CAMP_SHORT not in str(out)


# ---------------------------------------------------------------------------
# L. strategy does not invent catalyst applicability
# ---------------------------------------------------------------------------


def test_l_strategy_does_not_block_short_not_applicable():
    out = _project(
        strategy="SHORT",
        campaign_id=CAMP_SHORT,
        catalyst=_dim("NOT_APPLICABLE", "cat:na"),
    )
    assert out["sell_state"] == "HOLD"
    assert out["hold_positive_proof"] is True


# ---------------------------------------------------------------------------
# M/N/O. UNKNOWN / NOT_EVALUATED / ERROR
# ---------------------------------------------------------------------------


def test_m_unknown_dimension_blocks_hold():
    out = _project(risk_exit=_dim("UNKNOWN"))
    assert out["sell_state"] is None
    assert out["hold_positive_proof"] is False
    assert out["sell_evaluation"] == "UNKNOWN"
    assert "RISK_EXIT_UNKNOWN" in out["uncertainties"]


def test_n_not_evaluated_blocks_hold():
    out = _project(risk_reward=_dim("NOT_EVALUATED"))
    assert out["sell_state"] is None
    assert out["hold_positive_proof"] is False
    assert out["sell_evaluation"] == "NOT_EVALUATED"


def test_o_error_is_highest_evaluation_severity():
    out = _project(
        risk_exit=_dim("UNKNOWN"),
        risk_reward=_dim("NOT_EVALUATED"),
        catalyst=_dim("ERROR"),
    )
    assert out["sell_evaluation"] == "ERROR"
    assert out["sell_state"] is None
    assert out["hold_positive_proof"] is False


def test_o_error_with_confirmed_exit_keeps_exit_and_error_eval():
    out = _project(
        risk_exit=_dim("EXIT", "risk:1"),
        opportunity_cost=_dim("ERROR"),
    )
    assert out["sell_state"] == "EXIT"
    assert out["primary_reason"] == "RISK_EXIT"
    assert out["sell_evaluation"] == "ERROR"


# ---------------------------------------------------------------------------
# P. no false HOLD
# ---------------------------------------------------------------------------


def test_p_no_false_hold_when_any_applicable_not_evaluated():
    out = _project(expectation_price_in=_dim("NOT_EVALUATED"))
    assert out["sell_state"] != "HOLD"
    assert out["hold_positive_proof"] is False


def test_p_hold_requires_positive_proof_all_clear():
    out = _project()
    assert out["sell_state"] == "HOLD"
    assert out["hold_positive_proof"] is True
    assert "HOLD_POSITIVE_PROOF" in out["reason_codes"]
    assert out["primary_reason"] is None


def test_p_not_applicable_optional_does_not_block_hold():
    out = _project(
        technical_execution=_dim("NOT_APPLICABLE", "tech:na"),
        catalyst=_dim("NOT_APPLICABLE", "cat:na"),
    )
    assert out["sell_state"] == "HOLD"
    assert out["hold_positive_proof"] is True


# ---------------------------------------------------------------------------
# P1 provenance closure
# ---------------------------------------------------------------------------


def test_p1_empty_refs_cannot_create_hold():
    with pytest.raises(se.SellEngineValidationError, match="authority_refs"):
        _project(thesis=_dim("STABLE"))  # missing refs on clean


def test_p1_all_clean_empty_refs_rejected():
    with pytest.raises(se.SellEngineValidationError, match="authority_refs"):
        se.project_sell_engine(
            security_code=SEC,
            strategy="SWING",
            campaign_id=CAMP_SWING,
            as_of=AS_OF,
            thesis={"state": "STABLE", "authority_refs": []},
            risk_exit={"state": "NONE", "authority_refs": []},
            expectation_price_in={"state": "NONE", "authority_refs": []},
            risk_reward={"state": "NONE", "authority_refs": []},
            catalyst={"state": "NONE", "authority_refs": []},
            portfolio_rebalance={"state": "NONE", "authority_refs": []},
            opportunity_cost={"state": "NONE", "authority_refs": []},
            technical_execution={"state": "NONE", "authority_refs": []},
        )


def test_p1_empty_refs_cannot_create_exit():
    with pytest.raises(se.SellEngineValidationError, match="authority_refs"):
        _project(expectation_price_in=_dim("EXIT"))


def test_p1_thesis_invalidated_empty_refs_rejected():
    with pytest.raises(se.SellEngineValidationError, match="authority_refs"):
        _project(thesis=_dim("INVALIDATED"))


def test_p1_not_applicable_empty_refs_rejected():
    with pytest.raises(se.SellEngineValidationError, match="authority_refs"):
        _project(catalyst=_dim("NOT_APPLICABLE"))


def test_p1_incomplete_may_omit_refs():
    out = _project(risk_reward=_dim("NOT_EVALUATED"))
    assert out["sell_evaluation"] == "NOT_EVALUATED"
    out2 = _project(risk_exit=_dim("UNKNOWN"))
    assert out2["sell_evaluation"] == "UNKNOWN"
    out3 = _project(catalyst=_dim("ERROR"))
    assert out3["sell_evaluation"] == "ERROR"


# ---------------------------------------------------------------------------
# Q/R. loss != sell, profit != hold
# ---------------------------------------------------------------------------


def test_q_loss_field_rejected():
    with pytest.raises(se.SellEngineValidationError):
        _project(
            risk_exit={
                "state": "NONE",
                "authority_refs": ["r"],
                "unrealized_loss": 0.3,
            }
        )


def test_r_profit_field_rejected():
    with pytest.raises(se.SellEngineValidationError):
        _project(
            thesis={
                "state": "STABLE",
                "authority_refs": ["t"],
                "profit": 0.5,
            }
        )


# ---------------------------------------------------------------------------
# S. technical pressure is composition only (no invented thesis invalidate)
# ---------------------------------------------------------------------------


def test_s_technical_only_not_thesis_invalidated():
    out = _project(
        strategy="MEDIUM",
        campaign_id=CAMP_MEDIUM,
        catalyst=_dim("NOT_APPLICABLE", "c"),
        technical_execution=_dim("REDUCE", "t"),
    )
    assert out["sell_state"] != "THESIS_INVALIDATED"
    assert out["primary_reason"] == "TECHNICAL_EXECUTION"
    assert out["sell_state"] == "REDUCE"


# ---------------------------------------------------------------------------
# T/U/V. deterministic / zero mutation / detached
# ---------------------------------------------------------------------------


def test_t_same_input_deterministic_output():
    kwargs = _clean_dims(risk_reward=_dim("REDUCE", "rr:1"))
    a = se.project_sell_engine(
        security_code=SEC,
        strategy="SWING",
        campaign_id=CAMP_SWING,
        as_of=AS_OF,
        **kwargs,
    )
    b = se.project_sell_engine(
        security_code=SEC,
        strategy="SWING",
        campaign_id=CAMP_SWING,
        as_of=AS_OF,
        **kwargs,
    )
    assert a == b


def test_u_input_zero_mutation():
    thesis = _dim("WEAKENED", "t1")
    risk = _dim("NONE", "h1")
    exp = _dim("NONE", "e1")
    rr = _dim("NONE", "r1")
    cat = _dim("NONE", "c1")
    port = _dim("NONE", "p1")
    opp = _dim("NONE", "o1")
    tech = _dim("WATCH", "x1")
    snap = copy.deepcopy(
        {
            "thesis": thesis,
            "risk_exit": risk,
            "expectation_price_in": exp,
            "risk_reward": rr,
            "catalyst": cat,
            "portfolio_rebalance": port,
            "opportunity_cost": opp,
            "technical_execution": tech,
        }
    )
    se.project_sell_engine(
        security_code=SEC,
        strategy="SWING",
        campaign_id=CAMP_SWING,
        as_of=AS_OF,
        thesis=thesis,
        risk_exit=risk,
        expectation_price_in=exp,
        risk_reward=rr,
        catalyst=cat,
        portfolio_rebalance=port,
        opportunity_cost=opp,
        technical_execution=tech,
    )
    assert thesis == snap["thesis"]
    assert risk == snap["risk_exit"]
    assert exp == snap["expectation_price_in"]
    assert rr == snap["risk_reward"]
    assert cat == snap["catalyst"]
    assert port == snap["portfolio_rebalance"]
    assert opp == snap["opportunity_cost"]
    assert tech == snap["technical_execution"]


def test_v_detached_output_immutability_from_inputs():
    refs = ["shared-ref"]
    thesis = {"state": "STABLE", "authority_refs": refs}
    out = se.project_sell_engine(
        security_code=SEC,
        strategy="SWING",
        campaign_id=CAMP_SWING,
        as_of=AS_OF,
        thesis=thesis,
        risk_exit=_dim("NONE", "r"),
        expectation_price_in=_dim("NONE", "e"),
        risk_reward=_dim("NONE", "rr"),
        catalyst=_dim("NONE", "c"),
        portfolio_rebalance=_dim("NONE", "p"),
        opportunity_cost=_dim("NONE", "o"),
        technical_execution=_dim("NONE", "t"),
    )
    out["authority_refs"].append("mutated")
    out["reason_codes"].append("MUT")
    assert "mutated" not in thesis["authority_refs"]
    assert refs == ["shared-ref"]


# ---------------------------------------------------------------------------
# W/X/Y. no I/O / no AI / no wall clock
# ---------------------------------------------------------------------------


def test_w_no_io_imports():
    src = Path(se.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    forbidden = {
        "sqlite3",
        "pathlib",
        "os",
        "sys",
        "subprocess",
        "socket",
        "http",
        "urllib",
        "requests",
        "fastapi",
        "aiohttp",
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                assert root not in forbidden
        if isinstance(node, ast.ImportFrom) and node.module:
            root = node.module.split(".")[0]
            assert root not in forbidden
    assert "sqlite3" not in src
    assert "open(" not in src


def test_x_no_ai_imports_or_tokens():
    src = Path(se.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    forbidden_modules = {"openai", "anthropic", "langchain", "llama_index"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] not in forbidden_modules
        if isinstance(node, ast.ImportFrom) and node.module:
            assert node.module.split(".")[0] not in forbidden_modules
    for token in ("openai", "anthropic", "chat_completion", "ChatOpenAI"):
        assert token not in src


def test_y_no_wall_clock():
    src = Path(se.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr in {
                "now",
                "utcnow",
                "today",
            }:
                pytest.fail(f"wall clock call forbidden: {func.attr}")
    assert "datetime.now" not in src
    assert "datetime.utcnow" not in src
    assert "time.time" not in src


def test_as_of_required_and_validated():
    with pytest.raises(se.SellEngineValidationError, match="as_of"):
        se.project_sell_engine(
            security_code=SEC,
            strategy="SWING",
            campaign_id=CAMP_SWING,
            as_of="2026-08-12",
            **_clean_dims(),
        )


def test_invalid_campaign_id_rejected():
    with pytest.raises(se.SellEngineValidationError, match="campaign_id"):
        _project(campaign_id="camp-1")


def test_invalid_strategy_rejected():
    with pytest.raises(se.SellEngineValidationError, match="strategy"):
        _project(strategy="LONG")


def test_strengthened_thesis_is_hold_ok():
    out = _project(thesis=_dim("STRENGTHENED", "t"))
    assert out["sell_state"] == "HOLD"
    assert out["hold_positive_proof"] is True
    assert "THESIS_STRENGTHENED" in out["opposing_reasons"]


def test_thesis_not_ready_is_not_evaluated_path():
    out = _project(thesis=_dim("NOT_READY"))
    assert out["sell_state"] is None
    assert out["sell_evaluation"] == "NOT_EVALUATED"
    assert "THESIS_NOT_EVALUATED" in out["uncertainties"]


def test_module_exports_expected_public_api():
    assert hasattr(se, "project_sell_engine")
    assert se.SCHEMA_VERSION == "sell_engine.projection.v0.1"
    assert "HOLD" in se.SELL_STATES
    assert "THESIS_INVALIDATED" in se.SELL_STATES
    assert "THESIS_INVALIDATION" in se.REASON_CATEGORIES
    sig = inspect.signature(se.project_sell_engine)
    assert all(
        p.kind == inspect.Parameter.KEYWORD_ONLY
        for p in sig.parameters.values()
    )
    assert "risk_exit" in sig.parameters
    assert "hard_risk" not in sig.parameters


def test_no_full_semantic_precedence_ladder_in_source():
    src = Path(se.__file__).read_text(encoding="utf-8")
    assert "_PRIMARY_PRECEDENCE" not in src
    assert "DISPLAY_TIE_BREAK_NOT_SEMANTIC_PRIORITY" in src


def test_reload_module_is_pure():
    importlib.reload(se)
    out = _project()
    assert out["schema_version"] == se.SCHEMA_VERSION
