"""Sell Engine Projection Core v0.1 acceptance matrix (P0-SE1)."""

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
        "hard_risk": _dim("CLEAR", "hard_risk:1"),
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


def test_a_thesis_weakened_is_watch_not_exit():
    out = _project(thesis=_dim("WEAKENED", "thesis:w"))
    assert out["sell_state"] == "WATCH_TO_REDUCE"
    assert out["primary_reason"] == "THESIS_INVALIDATION"
    assert "THESIS_WEAKENED" in out["reason_codes"]


def test_a_loss_alone_not_accepted_as_input():
    with pytest.raises(se.SellEngineValidationError, match="unsupported keys"):
        _project(thesis={"state": "STABLE", "authority_refs": [], "pnl": -0.2})


# ---------------------------------------------------------------------------
# B. RISK EXIT
# ---------------------------------------------------------------------------


def test_b_hard_risk_confirmed_is_exit_risk_exit():
    out = _project(hard_risk=_dim("CONFIRMED", "hr:1"))
    assert out["sell_state"] == "EXIT"
    assert out["primary_reason"] == "RISK_EXIT"
    assert "HARD_RISK_CONFIRMED" in out["reason_codes"]


def test_b_hard_risk_clear_no_pressure():
    out = _project()
    assert out["sell_state"] == "HOLD"
    assert "HARD_RISK_CLEAR" in out["reason_codes"]


# ---------------------------------------------------------------------------
# C. EXPECTATION / PRICE-IN
# ---------------------------------------------------------------------------


def test_c_expectation_reduce_pressure():
    out = _project(expectation_price_in=_dim("REDUCE", "exp:r"))
    assert out["sell_state"] == "REDUCE"
    assert out["primary_reason"] == "EXPECTATION_PRICE_IN"
    assert "EXPECTATION_PRICE_IN_REDUCE" in out["reason_codes"]


def test_c_expectation_exit_allowed_when_normalized_upstream():
    out = _project(expectation_price_in=_dim("EXIT", "exp:e"))
    assert out["sell_state"] == "EXIT"
    assert out["primary_reason"] == "EXPECTATION_PRICE_IN"


# ---------------------------------------------------------------------------
# D. R/R DETERIORATION
# ---------------------------------------------------------------------------


def test_d_rr_deterioration_not_mechanical_exit():
    out = _project(risk_reward=_dim("EXIT", "rr:e"))
    # EXIT input is capped to REDUCE for R/R.
    assert out["sell_state"] == "REDUCE"
    assert out["primary_reason"] == "RISK_REWARD_DETERIORATION"
    assert "RISK_REWARD_EXIT_CAPPED_TO_REDUCE" in out["reason_codes"]


def test_d_rr_watch_maps_to_watch_to_reduce():
    out = _project(risk_reward=_dim("WATCH", "rr:w"))
    assert out["sell_state"] == "WATCH_TO_REDUCE"


# ---------------------------------------------------------------------------
# E. CATALYST FAILURE
# ---------------------------------------------------------------------------


def test_e_catalyst_failed_short_exit():
    out = _project(
        strategy="SHORT",
        campaign_id=CAMP_SHORT,
        catalyst=_dim("FAILED", "cat:f"),
    )
    assert out["sell_state"] == "EXIT"
    assert out["primary_reason"] == "CATALYST_FAILURE"
    assert "CATALYST_FAILED" in out["reason_codes"]


def test_e_catalyst_failed_swing_reduce_not_exit():
    out = _project(catalyst=_dim("FAILED", "cat:f"))
    assert out["sell_state"] == "REDUCE"
    assert out["primary_reason"] == "CATALYST_FAILURE"


def test_e_catalyst_not_yet_is_not_failure():
    out = _project(catalyst=_dim("NOT_YET", "cat:ny"))
    assert out["sell_state"] == "HOLD"
    assert out["primary_reason"] is None
    assert "CATALYST_NOT_YET" in out["reason_codes"]


def test_e_medium_no_catalyst_not_applicable_ok():
    out = _project(
        strategy="MEDIUM",
        campaign_id=CAMP_MEDIUM,
        catalyst=_dim("NOT_APPLICABLE", "cat:na"),
    )
    assert out["sell_state"] == "HOLD"
    assert "CATALYST_NOT_APPLICABLE" in out["reason_codes"]


def test_e_short_not_applicable_forbidden():
    with pytest.raises(se.SellEngineValidationError, match="MEDIUM"):
        _project(
            strategy="SHORT",
            campaign_id=CAMP_SHORT,
            catalyst=_dim("NOT_APPLICABLE"),
        )


# ---------------------------------------------------------------------------
# F. PORTFOLIO REBALANCE
# ---------------------------------------------------------------------------


def test_f_portfolio_rebalance_reduce_preserves_reason():
    out = _project(portfolio_rebalance=_dim("REDUCE", "port:r"))
    assert out["sell_state"] == "REDUCE"
    assert out["primary_reason"] == "PORTFOLIO_REBALANCE"
    assert "PORTFOLIO_REBALANCE" in out["supporting_reasons"]
    # Asset view not rewritten — engine only emits sell state/reasons.
    assert "asset_view" not in out


# ---------------------------------------------------------------------------
# G. OPPORTUNITY COST
# ---------------------------------------------------------------------------


def test_g_opportunity_cost_cannot_alone_exit():
    out = _project(opportunity_cost=_dim("EXIT", "opp:e"))
    assert out["sell_state"] == "REDUCE"
    assert out["primary_reason"] == "OPPORTUNITY_COST"
    assert "OPPORTUNITY_COST_EXIT_CAPPED_TO_REDUCE" in out["reason_codes"]


def test_g_opportunity_cost_not_evaluated_blocks_hold():
    out = _project(opportunity_cost=_dim("NOT_EVALUATED"))
    assert out["sell_state"] is None
    assert out["hold_positive_proof"] is False
    assert out["sell_evaluation"] == "NOT_EVALUATED"
    assert "OPPORTUNITY_COST_NOT_EVALUATED" in out["uncertainties"]


# ---------------------------------------------------------------------------
# H. TECHNICAL EXECUTION
# ---------------------------------------------------------------------------


def test_h_technical_only_medium_cannot_invalidate_or_exit():
    out = _project(
        strategy="MEDIUM",
        campaign_id=CAMP_MEDIUM,
        catalyst=_dim("NOT_APPLICABLE"),
        technical_execution=_dim("EXIT", "tech:e"),
    )
    assert out["sell_state"] == "WATCH_TO_REDUCE"
    assert out["primary_reason"] == "TECHNICAL_EXECUTION"
    assert out["sell_state"] != "THESIS_INVALIDATED"
    assert out["sell_state"] != "EXIT"
    assert "TECHNICAL_EXIT_CAPPED_MEDIUM_WATCH" in out["reason_codes"]


def test_h_technical_short_exit_capped_to_reduce():
    out = _project(
        strategy="SHORT",
        campaign_id=CAMP_SHORT,
        technical_execution=_dim("EXIT", "tech:e"),
    )
    assert out["sell_state"] == "REDUCE"
    assert "TECHNICAL_EXIT_CAPPED_SHORT_REDUCE" in out["reason_codes"]


def test_h_technical_swing_watch():
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
    # primary is one of them; others remain
    assert out["primary_reason"] in out["supporting_reasons"]
    assert len(out["supporting_reasons"]) >= 3


# ---------------------------------------------------------------------------
# J. primary reason precedence
# ---------------------------------------------------------------------------


def test_j_thesis_invalidation_outranks_risk_exit():
    out = _project(
        thesis=_dim("INVALIDATED", "t"),
        hard_risk=_dim("CONFIRMED", "h"),
        risk_reward=_dim("REDUCE", "r"),
    )
    assert out["sell_state"] == "THESIS_INVALIDATED"
    assert out["primary_reason"] == "THESIS_INVALIDATION"
    assert "RISK_EXIT" in out["supporting_reasons"]
    assert "RISK_REWARD_DETERIORATION" in out["supporting_reasons"]


def test_j_risk_exit_outranks_portfolio_and_technical():
    out = _project(
        hard_risk=_dim("CONFIRMED", "h"),
        portfolio_rebalance=_dim("EXIT", "p"),
        technical_execution=_dim("REDUCE", "t"),
    )
    assert out["sell_state"] == "EXIT"
    assert out["primary_reason"] == "RISK_EXIT"
    assert "PORTFOLIO_REBALANCE" in out["supporting_reasons"]
    assert "TECHNICAL_EXECUTION" in out["supporting_reasons"]


def test_j_catalyst_outranks_expectation_and_opportunity():
    out = _project(
        catalyst=_dim("FAILED", "c"),
        expectation_price_in=_dim("REDUCE", "e"),
        opportunity_cost=_dim("REDUCE", "o"),
    )
    assert out["primary_reason"] == "CATALYST_FAILURE"
    assert "EXPECTATION_PRICE_IN" in out["supporting_reasons"]
    assert "OPPORTUNITY_COST" in out["supporting_reasons"]


# ---------------------------------------------------------------------------
# K. Campaign isolation
# ---------------------------------------------------------------------------


def test_k_campaign_isolation_same_security_different_results():
    swing = _project(
        strategy="SWING",
        campaign_id=CAMP_SWING,
        catalyst=_dim("FAILED"),
    )
    medium = _project(
        strategy="MEDIUM",
        campaign_id=CAMP_MEDIUM,
        catalyst=_dim("NOT_APPLICABLE"),
        technical_execution=_dim("EXIT"),
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
# L. SHORT / SWING / MEDIUM semantic differences
# ---------------------------------------------------------------------------


def test_l_strategy_differences_catalyst_and_technical():
    short = _project(
        strategy="SHORT",
        campaign_id=CAMP_SHORT,
        catalyst=_dim("FAILED"),
    )
    swing = _project(
        strategy="SWING",
        campaign_id=CAMP_SWING,
        catalyst=_dim("FAILED"),
    )
    medium = _project(
        strategy="MEDIUM",
        campaign_id=CAMP_MEDIUM,
        catalyst=_dim("FAILED"),
    )
    assert short["sell_state"] == "EXIT"
    assert swing["sell_state"] == "REDUCE"
    assert medium["sell_state"] == "REDUCE"


# ---------------------------------------------------------------------------
# M/N/O. UNKNOWN / NOT_EVALUATED / ERROR
# ---------------------------------------------------------------------------


def test_m_unknown_dimension_blocks_hold():
    out = _project(hard_risk=_dim("UNKNOWN"))
    assert out["sell_state"] is None
    assert out["hold_positive_proof"] is False
    assert out["sell_evaluation"] == "UNKNOWN"
    assert "HARD_RISK_UNKNOWN" in out["uncertainties"]


def test_n_not_evaluated_blocks_hold():
    out = _project(risk_reward=_dim("NOT_EVALUATED"))
    assert out["sell_state"] is None
    assert out["hold_positive_proof"] is False
    assert out["sell_evaluation"] == "NOT_EVALUATED"


def test_o_error_is_highest_evaluation_severity():
    out = _project(
        hard_risk=_dim("UNKNOWN"),
        risk_reward=_dim("NOT_EVALUATED"),
        catalyst=_dim("ERROR"),
    )
    assert out["sell_evaluation"] == "ERROR"
    assert out["sell_state"] is None
    assert out["hold_positive_proof"] is False


def test_o_error_with_confirmed_exit_keeps_exit_and_error_eval():
    out = _project(
        hard_risk=_dim("CONFIRMED"),
        opportunity_cost=_dim("ERROR"),
    )
    assert out["sell_state"] == "EXIT"
    assert out["primary_reason"] == "RISK_EXIT"
    assert out["sell_evaluation"] == "ERROR"


# ---------------------------------------------------------------------------
# P. no false HOLD
# ---------------------------------------------------------------------------


def test_p_no_false_hold_when_any_required_not_evaluated():
    out = _project(expectation_price_in=_dim("NOT_EVALUATED"))
    assert out["sell_state"] != "HOLD"
    assert out["hold_positive_proof"] is False


def test_p_hold_requires_positive_proof_all_clear():
    out = _project()
    assert out["sell_state"] == "HOLD"
    assert out["hold_positive_proof"] is True
    assert "HOLD_POSITIVE_PROOF" in out["reason_codes"]
    assert out["primary_reason"] is None


# ---------------------------------------------------------------------------
# Q/R. loss != sell, profit != hold
# ---------------------------------------------------------------------------


def test_q_loss_field_rejected():
    with pytest.raises(se.SellEngineValidationError):
        _project(
            hard_risk={
                "state": "CLEAR",
                "authority_refs": [],
                "unrealized_loss": 0.3,
            }
        )


def test_r_profit_field_rejected():
    with pytest.raises(se.SellEngineValidationError):
        _project(
            thesis={
                "state": "STABLE",
                "authority_refs": [],
                "profit": 0.5,
            }
        )


# ---------------------------------------------------------------------------
# S. technical-only MEDIUM cannot invalidate thesis
# ---------------------------------------------------------------------------


def test_s_technical_only_medium_not_thesis_invalidated():
    out = _project(
        strategy="MEDIUM",
        campaign_id=CAMP_MEDIUM,
        catalyst=_dim("NOT_APPLICABLE"),
        technical_execution=_dim("EXIT"),
    )
    assert out["sell_state"] != "THESIS_INVALIDATED"
    assert out["primary_reason"] == "TECHNICAL_EXECUTION"


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
    hard = _dim("CLEAR", "h1")
    exp = _dim("NONE", "e1")
    rr = _dim("NONE", "r1")
    cat = _dim("NONE", "c1")
    port = _dim("NONE", "p1")
    opp = _dim("NONE", "o1")
    tech = _dim("WATCH", "x1")
    snap = copy.deepcopy(
        {
            "thesis": thesis,
            "hard_risk": hard,
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
        hard_risk=hard,
        expectation_price_in=exp,
        risk_reward=rr,
        catalyst=cat,
        portfolio_rebalance=port,
        opportunity_cost=opp,
        technical_execution=tech,
    )
    assert thesis == snap["thesis"]
    assert hard == snap["hard_risk"]
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
        hard_risk=_dim("CLEAR"),
        expectation_price_in=_dim("NONE"),
        risk_reward=_dim("NONE"),
        catalyst=_dim("NONE"),
        portfolio_rebalance=_dim("NONE"),
        opportunity_cost=_dim("NONE"),
        technical_execution=_dim("NONE"),
    )
    out["authority_refs"].append("mutated")
    out["reason_codes"].append("MUT")
    assert "mutated" not in thesis["authority_refs"]
    # Mutating output list must not alias input refs list
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
    # No open / connect calls
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
        if isinstance(node, ast.Attribute) and node.attr in {
            "now",
            "utcnow",
            "today",
            "time",
        }:
            # allow datetime.timezone only
            if isinstance(node.value, ast.Name) and node.value.id in {
                "datetime",
                "date",
                "time",
            }:
                assert node.attr not in {"now", "utcnow", "today"}
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
            as_of="2026-08-12",  # missing time/tz
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
    # pure function signature uses keyword-only dimensions
    sig = inspect.signature(se.project_sell_engine)
    assert all(
        p.kind == inspect.Parameter.KEYWORD_ONLY
        for p in sig.parameters.values()
    )


def test_reload_module_is_pure():
    importlib.reload(se)
    out = _project()
    assert out["schema_version"] == se.SCHEMA_VERSION
