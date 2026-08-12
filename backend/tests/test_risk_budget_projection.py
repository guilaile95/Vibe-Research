"""Risk Budget & Risk Allowed Cap projection tests (P0-RB1)."""

from __future__ import annotations

import ast
import copy
import importlib
import inspect
import math
import sys
from decimal import ROUND_HALF_EVEN, Decimal, getcontext, localcontext
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import risk_budget_projection as rb


AS_OF = "2026-08-12T12:00:00Z"
SEC = "600519"
CAMP_SWING = "campaign_" + ("a" * 32)
CAMP_MEDIUM = "campaign_" + ("b" * 32)
CAMP_SHORT = "campaign_" + ("c" * 32)
POLICY = rb.POLICY_VERSION_V01


def _project(**overrides):
    base = {
        "security_code": SEC,
        "strategy": "SWING",
        "campaign_id": CAMP_SWING,
        "as_of": AS_OF,
        "policy_version": POLICY,
        "account_nav": "1000000",
        "nav_basis": "OFFICIAL_SETTLED",
        "nav_authority_refs": ["nav:settled:1"],
        "entry_to_invalidation_distance_ratio": "0.10",
        "invalidation_authority_refs": ["inv:thesis:1"],
    }
    base.update(overrides)
    return rb.project_risk_budget(**base)


def _frozen_cap_str(nav: str, budget: str, distance: str) -> str:
    """Expected cap string under the module-owned frozen v0.1 context."""
    with localcontext(rb.RISK_BUDGET_DECIMAL_CONTEXT.copy()):
        cap = Decimal(nav) * Decimal(budget) / Decimal(distance)
        s = format(cap, "f")
        if "." in s:
            s = s.rstrip("0").rstrip(".")
        return s if s else "0"


def _frozen_ratio_str(nav: str, budget: str, distance: str) -> str:
    with localcontext(rb.RISK_BUDGET_DECIMAL_CONTEXT.copy()):
        cap = Decimal(nav) * Decimal(budget) / Decimal(distance)
        ratio = cap / Decimal(nav)
        s = format(ratio, "f")
        if "." in s:
            s = s.rstrip("0").rstrip(".")
        return s if s else "0"


# ---------------------------------------------------------------------------
# A/B/C policy constants
# ---------------------------------------------------------------------------


def test_a_short_policy_ratios():
    out = _project(strategy="SHORT", campaign_id=CAMP_SHORT)
    assert out["risk_budget_ratio"] == "0.0075"
    assert out["policy_backstop_ratio"] == "0.07"
    assert out["cap_evaluation"] == "EVALUATED"


def test_b_swing_policy_ratios():
    out = _project(strategy="SWING")
    assert out["risk_budget_ratio"] == "0.01"
    assert out["policy_backstop_ratio"] == "0.12"


def test_c_medium_policy_ratios():
    out = _project(strategy="MEDIUM", campaign_id=CAMP_MEDIUM)
    assert out["risk_budget_ratio"] == "0.0125"
    assert out["policy_backstop_ratio"] == "0.2"


# ---------------------------------------------------------------------------
# D exact formula
# ---------------------------------------------------------------------------


def test_d_exact_formula_swing_example():
    # NAV=1_000_000, budget=1%, distance=10% → cap=100_000
    out = _project(
        account_nav="1000000",
        entry_to_invalidation_distance_ratio="0.10",
    )
    assert out["risk_allowed_cap_notional"] == "100000"
    assert out["risk_allowed_cap_nav_ratio"] == "0.1"
    assert "100000" in out["explainability"]["why_this_cap"]


def test_d_exact_formula_decimal_inputs():
    out = _project(
        account_nav=Decimal("1000000"),
        entry_to_invalidation_distance_ratio=Decimal("0.08"),
        strategy="SHORT",
        campaign_id=CAMP_SHORT,
    )
    # 1_000_000 * 0.0075 / 0.08 = 93_750
    assert out["risk_allowed_cap_notional"] == "93750"


# ---------------------------------------------------------------------------
# E/F/G policy version
# ---------------------------------------------------------------------------


def test_e_explicit_policy_version_required():
    with pytest.raises(TypeError):
        rb.project_risk_budget(
            security_code=SEC,
            strategy="SWING",
            campaign_id=CAMP_SWING,
            as_of=AS_OF,
            # policy_version missing
            account_nav="1000000",
            nav_basis="OFFICIAL_SETTLED",
            nav_authority_refs=["n"],
            entry_to_invalidation_distance_ratio="0.1",
            invalidation_authority_refs=["i"],
        )


def test_f_unknown_policy_version_not_latest():
    out = _project(policy_version="rb.risk_budget.v9.9")
    assert out["cap_evaluation"] == "NOT_EVALUATED"
    assert out["risk_allowed_cap_notional"] is None
    assert "POLICY_VERSION_NOT_AVAILABLE" in out["reason_codes"]
    assert out["risk_budget_ratio"] is None


def test_g_as_of_does_not_choose_version():
    out_a = _project(as_of="2020-01-01T00:00:00Z", policy_version=POLICY)
    out_b = _project(as_of="2030-01-01T00:00:00Z", policy_version=POLICY)
    assert out_a["risk_budget_ratio"] == out_b["risk_budget_ratio"]
    assert out_a["policy_version"] == out_b["policy_version"] == POLICY
    # Different as_of with unknown version still not latest
    out_u = _project(as_of="2030-01-01T00:00:00Z", policy_version="rb.unknown")
    assert out_u["cap_evaluation"] == "NOT_EVALUATED"


# ---------------------------------------------------------------------------
# H/I invalidation distance explicit; backstop not substitute
# ---------------------------------------------------------------------------


def test_h_invalidation_distance_explicit_required():
    with pytest.raises(TypeError):
        rb.project_risk_budget(
            security_code=SEC,
            strategy="SWING",
            campaign_id=CAMP_SWING,
            as_of=AS_OF,
            policy_version=POLICY,
            account_nav="1000000",
            nav_basis="OFFICIAL_SETTLED",
            nav_authority_refs=["n"],
            invalidation_authority_refs=["i"],
        )


def test_i_backstop_never_substitutes_invalidation():
    # SWING backstop=12%, supplied distance=6% → must use 6%
    out = _project(entry_to_invalidation_distance_ratio="0.06")
    # 1e6 * 0.01 / 0.06 = 166666.666...
    assert out["entry_to_invalidation_distance_ratio"] == "0.06"
    assert out["policy_backstop_ratio"] == "0.12"
    expected = _frozen_cap_str("1000000", "0.01", "0.06")
    assert out["risk_allowed_cap_notional"] == expected
    # Must NOT equal cap computed with backstop as distance
    wrong = _frozen_cap_str("1000000", "0.01", "0.12")
    assert out["risk_allowed_cap_notional"] != wrong


# ---------------------------------------------------------------------------
# J/K/L/M backstop comparison / no silent clamp
# ---------------------------------------------------------------------------


def test_j_distance_within_backstop():
    out = _project(entry_to_invalidation_distance_ratio="0.06")
    assert out["backstop_comparison"] == "WITHIN_BACKSTOP"


def test_k_distance_at_backstop():
    out = _project(entry_to_invalidation_distance_ratio="0.12")
    assert out["backstop_comparison"] == "AT_BACKSTOP"
    # 1e6 * 0.01 / 0.12
    assert out["risk_allowed_cap_notional"] == _frozen_cap_str(
        "1000000", "0.01", "0.12"
    )


def test_l_distance_beyond_backstop():
    out = _project(entry_to_invalidation_distance_ratio="0.15")
    assert out["backstop_comparison"] == "BEYOND_BACKSTOP"


def test_m_no_silent_backstop_clamp_when_beyond():
    out = _project(entry_to_invalidation_distance_ratio="0.15")
    # Must use 0.15, not clamp to 0.12
    expected = _frozen_cap_str("1000000", "0.01", "0.15")
    assert out["risk_allowed_cap_notional"] == expected
    assert out["entry_to_invalidation_distance_ratio"] == "0.15"
    # No sell/exit action from beyond backstop
    assert out.get("sell_state") is None
    blob = str(out)
    assert "EXIT" not in blob or "EXIT" not in out["reason_codes"]
    assert "REDUCE" not in out["reason_codes"]


# ---------------------------------------------------------------------------
# N risk cap > NAV not portfolio-capped
# ---------------------------------------------------------------------------


def test_n_risk_cap_greater_than_nav_not_clamped():
    # tiny distance → large cap
    out = _project(entry_to_invalidation_distance_ratio="0.005")
    # 1e6 * 0.01 / 0.005 = 2_000_000 > NAV
    assert out["risk_allowed_cap_notional"] == "2000000"
    assert Decimal(out["risk_allowed_cap_nav_ratio"]) == Decimal("2")
    assert Decimal(out["risk_allowed_cap_notional"]) > Decimal(out["account_nav"])


# ---------------------------------------------------------------------------
# O/P/Q/R/S rejects
# ---------------------------------------------------------------------------


def test_o_zero_nav_reject():
    with pytest.raises(rb.RiskBudgetValidationError, match="account_nav"):
        _project(account_nav="0")


def test_p_negative_nav_reject():
    with pytest.raises(rb.RiskBudgetValidationError, match="account_nav"):
        _project(account_nav="-100")


def test_q_zero_distance_reject():
    with pytest.raises(
        rb.RiskBudgetValidationError, match="entry_to_invalidation_distance_ratio"
    ):
        _project(entry_to_invalidation_distance_ratio="0")


def test_r_negative_distance_reject():
    with pytest.raises(
        rb.RiskBudgetValidationError, match="entry_to_invalidation_distance_ratio"
    ):
        _project(entry_to_invalidation_distance_ratio="-0.1")


def test_s_nan_infinity_reject():
    with pytest.raises(rb.RiskBudgetValidationError):
        _project(account_nav=float("nan"))
    with pytest.raises(rb.RiskBudgetValidationError):
        _project(account_nav=float("inf"))
    with pytest.raises(rb.RiskBudgetValidationError):
        _project(entry_to_invalidation_distance_ratio=float("nan"))
    with pytest.raises(rb.RiskBudgetValidationError):
        _project(entry_to_invalidation_distance_ratio=math.inf)


# ---------------------------------------------------------------------------
# T/U campaign isolation / strategy differences
# ---------------------------------------------------------------------------


def test_t_campaign_isolation():
    a = _project(
        strategy="SWING",
        campaign_id=CAMP_SWING,
        entry_to_invalidation_distance_ratio="0.08",
    )
    b = _project(
        strategy="MEDIUM",
        campaign_id=CAMP_MEDIUM,
        entry_to_invalidation_distance_ratio="0.15",
    )
    assert a["campaign_id"] != b["campaign_id"]
    assert a["security_code"] == b["security_code"]
    assert a["risk_allowed_cap_notional"] != b["risk_allowed_cap_notional"]
    assert CAMP_MEDIUM not in str(a)
    assert CAMP_SWING not in str(b)


def test_u_same_security_different_strategies():
    short = _project(
        strategy="SHORT",
        campaign_id=CAMP_SHORT,
        entry_to_invalidation_distance_ratio="0.10",
    )
    swing = _project(
        strategy="SWING",
        campaign_id=CAMP_SWING,
        entry_to_invalidation_distance_ratio="0.10",
    )
    assert short["risk_budget_ratio"] == "0.0075"
    assert swing["risk_budget_ratio"] == "0.01"
    assert short["risk_allowed_cap_notional"] != swing["risk_allowed_cap_notional"]


# ---------------------------------------------------------------------------
# V/W immutability / deterministic
# ---------------------------------------------------------------------------


def test_v_input_immutability():
    nav_refs = ["nav:1"]
    inv_refs = ["inv:1"]
    snap = copy.deepcopy({"nav": nav_refs, "inv": inv_refs})
    rb.project_risk_budget(
        security_code=SEC,
        strategy="SWING",
        campaign_id=CAMP_SWING,
        as_of=AS_OF,
        policy_version=POLICY,
        account_nav="1000000",
        nav_basis="OFFICIAL_SETTLED",
        nav_authority_refs=nav_refs,
        entry_to_invalidation_distance_ratio="0.1",
        invalidation_authority_refs=inv_refs,
    )
    assert nav_refs == snap["nav"]
    assert inv_refs == snap["inv"]


def test_w_deterministic_repeated_output():
    a = _project()
    b = _project()
    assert a == b


# ---------------------------------------------------------------------------
# X/Y purity
# ---------------------------------------------------------------------------


def test_x_no_wall_clock():
    src = Path(rb.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in {"now", "utcnow", "today"}:
                pytest.fail(f"wall clock forbidden: {node.func.attr}")
    assert "datetime.now" not in src
    assert "time.time" not in src


def test_y_no_io_or_ai():
    src = Path(rb.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    forbidden = {
        "sqlite3",
        "pathlib",
        "os",
        "sys",
        "subprocess",
        "socket",
        "requests",
        "fastapi",
        "openai",
        "anthropic",
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] not in forbidden
        if isinstance(node, ast.ImportFrom) and node.module:
            assert node.module.split(".")[0] not in forbidden
    assert "open(" not in src


# ---------------------------------------------------------------------------
# Z no BUY/SELL vocabulary
# ---------------------------------------------------------------------------


def test_z_no_buy_sell_action_vocabulary():
    out = _project(entry_to_invalidation_distance_ratio="0.15")
    forbidden = {
        "BUY NOW",
        "HOLD",
        "REDUCE",
        "EXIT",
        "WATCH_TO_REDUCE",
        "AVOID",
        "SCALE IN",
        "WAIT",
    }
    for key in (
        "reason_codes",
        "cap_evaluation",
        "backstop_comparison",
        "schema_version",
    ):
        val = out.get(key)
        if isinstance(val, list):
            for item in val:
                assert item not in forbidden
        else:
            assert val not in forbidden
    assert "sell_state" not in out
    assert "recommended_position" not in out
    assert "executable_quantity" not in out
    assert "asset_optimal_position" not in out
    assert "portfolio_adjusted_position" not in out


# ---------------------------------------------------------------------------
# Adversarial / provenance / nav basis
# ---------------------------------------------------------------------------


def test_adversarial_backstop_not_stop_loss_action():
    out = _project(entry_to_invalidation_distance_ratio="0.20")
    assert out["backstop_comparison"] == "BEYOND_BACKSTOP"
    assert "STOP" not in out["reason_codes"]
    assert out["explainability"]["backstop_role"].startswith("POLICY_COMPARISON")


def test_adversarial_cap_not_recommended_or_executable():
    out = _project()
    assert "RISK_CONSTRAINT" in out["explainability"]["cap_semantics"]
    assert "NE_RECOMMENDED_POSITION" in out["explainability"]["cap_semantics"]
    assert "NE_EXECUTABLE_QUANTITY" in out["explainability"]["cap_semantics"]


def test_naked_nav_refs_rejected():
    with pytest.raises(rb.RiskBudgetValidationError, match="nav_authority_refs"):
        _project(nav_authority_refs=[])


def test_naked_invalidation_refs_rejected():
    with pytest.raises(
        rb.RiskBudgetValidationError, match="invalidation_authority_refs"
    ):
        _project(invalidation_authority_refs=[])


def test_nav_basis_official_vs_estimated():
    a = _project(nav_basis="OFFICIAL_SETTLED")
    b = _project(nav_basis="ESTIMATED_INTRADAY")
    assert a["nav_basis"] == "OFFICIAL_SETTLED"
    assert a["cap_evaluation"] == "EVALUATED"
    assert a["risk_allowed_cap_notional"] is not None
    assert b["nav_basis"] == "ESTIMATED_INTRADAY"
    assert b["cap_evaluation"] == "NOT_EVALUATED"
    assert b["risk_allowed_cap_notional"] is None
    assert b["account_nav"] == a["account_nav"]
    assert "INTRADAY_NAV_QUALITY_NOT_PROVEN" in b["reason_codes"]
    with pytest.raises(rb.RiskBudgetValidationError, match="nav_basis"):
        _project(nav_basis="OFFICIAL")  # must not silently alias


def test_malformed_security_and_campaign_and_strategy():
    with pytest.raises(rb.RiskBudgetValidationError, match="security_code"):
        _project(security_code="60051")
    with pytest.raises(rb.RiskBudgetValidationError, match="campaign_id"):
        _project(campaign_id="camp-1")
    with pytest.raises(rb.RiskBudgetValidationError, match="strategy"):
        _project(strategy="LONG")


def test_malformed_as_of_reject():
    with pytest.raises(rb.RiskBudgetValidationError, match="as_of"):
        _project(as_of="2026-08-12")


def test_public_api_keyword_only():
    sig = inspect.signature(rb.project_risk_budget)
    assert all(
        p.kind == inspect.Parameter.KEYWORD_ONLY for p in sig.parameters.values()
    )
    assert rb.POLICY_VERSION_V01 == "rb.risk_budget.v0.1"
    assert rb.NUMERIC_CONTEXT_VERSION == "rb.numeric.v0.1"
    assert rb.NUMERIC_PRECISION == 50
    assert rb.NUMERIC_ROUNDING == ROUND_HALF_EVEN


def test_reload_pure():
    importlib.reload(rb)
    out = _project()
    assert out["schema_version"] == rb.SCHEMA_VERSION


# ---------------------------------------------------------------------------
# R1 P1-1: frozen numeric context (no global Decimal dependence)
# ---------------------------------------------------------------------------


def test_r1_global_decimal_prec_6_vs_50_same_output():
    original = getcontext().copy()
    try:
        getcontext().prec = 6
        out_a = _project(entry_to_invalidation_distance_ratio="0.06")
        getcontext().prec = 50
        out_b = _project(entry_to_invalidation_distance_ratio="0.06")
        assert out_a == out_b
        assert out_a["risk_allowed_cap_notional"] == out_b["risk_allowed_cap_notional"]
        assert out_a["risk_allowed_cap_nav_ratio"] == out_b["risk_allowed_cap_nav_ratio"]
        assert out_a["risk_allowed_cap_notional"] == _frozen_cap_str(
            "1000000", "0.01", "0.06"
        )
        assert out_a["risk_allowed_cap_nav_ratio"] == _frozen_ratio_str(
            "1000000", "0.01", "0.06"
        )
        # A poisoned global prec=6 must not collapse the repeating 6s.
        assert out_a["risk_allowed_cap_notional"] != "1.67E+5"
        assert "166666" in out_a["risk_allowed_cap_notional"]
    finally:
        getcontext().prec = original.prec
        getcontext().rounding = original.rounding


def test_r1_distance_006_deterministic_repeated():
    original = getcontext().copy()
    try:
        getcontext().prec = 6
        outputs = [
            _project(entry_to_invalidation_distance_ratio="0.06") for _ in range(5)
        ]
        assert all(item == outputs[0] for item in outputs)
        assert outputs[0]["risk_allowed_cap_notional"] == _frozen_cap_str(
            "1000000", "0.01", "0.06"
        )
        assert outputs[0]["risk_allowed_cap_nav_ratio"] == _frozen_ratio_str(
            "1000000", "0.01", "0.06"
        )
    finally:
        getcontext().prec = original.prec
        getcontext().rounding = original.rounding


def test_r1_numeric_context_is_frozen_v01():
    assert rb.RISK_BUDGET_DECIMAL_CONTEXT.prec == 50
    assert str(rb.RISK_BUDGET_DECIMAL_CONTEXT.rounding) == "ROUND_HALF_EVEN"
    src = Path(rb.__file__).read_text(encoding="utf-8")
    assert "getcontext(" not in src
    assert ".quantize(" not in src
    assert "round(" not in src
    assert "ROUND_HALF_EVEN" in src


# ---------------------------------------------------------------------------
# R1 P1-2 / P2: NAV eligibility and incomplete reasons
# ---------------------------------------------------------------------------


def test_r1_official_settled_known_policy_evaluated():
    out = _project(nav_basis="OFFICIAL_SETTLED")
    assert out["cap_evaluation"] == "EVALUATED"
    assert out["risk_allowed_cap_notional"] == "100000"
    assert "RISK_ALLOWED_CAP_COMPUTED" in out["reason_codes"]


def test_r1_estimated_intraday_known_policy_not_evaluated():
    out = _project(nav_basis="ESTIMATED_INTRADAY")
    assert out["cap_evaluation"] == "NOT_EVALUATED"
    assert out["risk_allowed_cap_notional"] is None
    assert out["risk_allowed_cap_nav_ratio"] is None
    assert out["nav_basis"] == "ESTIMATED_INTRADAY"
    assert out["account_nav"] == "1000000"
    assert out["nav_authority_refs"] == ["nav:settled:1"]
    assert "INTRADAY_NAV_QUALITY_NOT_PROVEN" in out["reason_codes"]
    assert "RISK_ALLOWED_CAP_COMPUTED" not in out["reason_codes"]


def test_r1_estimated_intraday_no_formal_cap():
    out = _project(nav_basis="ESTIMATED_INTRADAY")
    assert out["risk_allowed_cap_notional"] is None
    assert out["risk_allowed_cap_nav_ratio"] is None
    assert out.get("sell_state") is None


def test_r1_estimated_intraday_no_settled_fallback():
    out = _project(nav_basis="ESTIMATED_INTRADAY")
    assert out["nav_basis"] == "ESTIMATED_INTRADAY"
    assert out["nav_basis"] != "OFFICIAL_SETTLED"
    assert "INTRADAY_TO_SETTLED_FALLBACK=NO" in out["explainability"]["note"]
    assert "NAV_BASIS_PRESERVED" in out["explainability"]["note"]


def test_r1_unknown_policy_official_reason():
    out = _project(
        policy_version="rb.risk_budget.v9.9",
        nav_basis="OFFICIAL_SETTLED",
    )
    assert out["cap_evaluation"] == "NOT_EVALUATED"
    assert out["reason_codes"] == ["POLICY_VERSION_NOT_AVAILABLE"]
    assert out["risk_allowed_cap_notional"] is None
    assert out["risk_budget_ratio"] is None
    assert out["policy_authority_ref"] is None


def test_r1_known_policy_intraday_reason():
    out = _project(nav_basis="ESTIMATED_INTRADAY")
    assert out["reason_codes"] == ["INTRADAY_NAV_QUALITY_NOT_PROVEN"]
    assert out["cap_evaluation"] == "NOT_EVALUATED"


def test_r1_unknown_policy_and_intraday_cumulative_reasons():
    out = _project(
        policy_version="rb.unknown",
        nav_basis="ESTIMATED_INTRADAY",
    )
    assert out["cap_evaluation"] == "NOT_EVALUATED"
    assert out["reason_codes"] == [
        "POLICY_VERSION_NOT_AVAILABLE",
        "INTRADAY_NAV_QUALITY_NOT_PROVEN",
    ]
    assert out["risk_allowed_cap_notional"] is None
    assert out["risk_budget_ratio"] is None
    assert out["nav_basis"] == "ESTIMATED_INTRADAY"
