"""Account Drawdown State projection tests (P0-DD1)."""

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

import account_drawdown_projection as dd


AS_OF = "2026-08-13T12:00:00Z"
PEAK_AT = "2026-08-01T00:00:00Z"
POLICY = dd.POLICY_VERSION_V01
PEAK = "1000000"


def _project(**overrides):
    base = {
        "as_of": AS_OF,
        "policy_version": POLICY,
        "current_account_nav": "1000000",
        "current_nav_basis": "OFFICIAL_SETTLED",
        "current_nav_authority_refs": ["nav:settled:1"],
        "recent_nav_peak": PEAK,
        "peak_nav_basis": "OFFICIAL_SETTLED",
        "nav_peak_at": PEAK_AT,
        "nav_peak_authority_refs": ["peak:settled:1"],
    }
    base.update(overrides)
    return dd.project_account_drawdown(**base)


def _frozen_ratio_str(peak: str, current: str) -> str:
    with localcontext(dd.ACCOUNT_DRAWDOWN_DECIMAL_CONTEXT.copy()):
        ratio = (Decimal(peak) - Decimal(current)) / Decimal(peak)
        s = format(ratio, "f")
        if "." in s:
            s = s.rstrip("0").rstrip(".")
        return s if s else "0"


# ---------------------------------------------------------------------------
# A–J threshold bands
# ---------------------------------------------------------------------------


def test_a_zero_drawdown_normal():
    out = _project(current_account_nav=PEAK)
    assert out["drawdown_evaluation"] == "EVALUATED"
    assert out["drawdown_ratio"] == "0"
    assert out["drawdown_state"] == "NORMAL"


def test_b_nine_percent_normal():
    out = _project(current_account_nav="910000")
    assert out["drawdown_ratio"] == "0.09"
    assert out["drawdown_state"] == "NORMAL"


def test_c_exact_10_percent_caution():
    out = _project(current_account_nav="900000")
    assert out["drawdown_ratio"] == "0.1"
    assert out["drawdown_state"] == "CAUTION"


def test_d_just_below_18_percent_caution():
    out = _project(recent_nav_peak="10000", current_account_nav="8201")
    assert Decimal(out["drawdown_ratio"]) < Decimal("0.18")
    assert Decimal(out["drawdown_ratio"]) >= Decimal("0.10")
    assert out["drawdown_state"] == "CAUTION"


def test_e_exact_18_percent_high_risk():
    out = _project(current_account_nav="820000")
    assert out["drawdown_ratio"] == "0.18"
    assert out["drawdown_state"] == "HIGH_RISK"


def test_f_just_below_25_percent_high_risk():
    out = _project(recent_nav_peak="10000", current_account_nav="7501")
    assert Decimal(out["drawdown_ratio"]) < Decimal("0.25")
    assert Decimal(out["drawdown_ratio"]) >= Decimal("0.18")
    assert out["drawdown_state"] == "HIGH_RISK"


def test_g_exact_25_percent_defensive():
    out = _project(current_account_nav="750000")
    assert out["drawdown_ratio"] == "0.25"
    assert out["drawdown_state"] == "DEFENSIVE"


def test_h_just_below_30_percent_defensive():
    out = _project(recent_nav_peak="10000", current_account_nav="7001")
    assert Decimal(out["drawdown_ratio"]) < Decimal("0.30")
    assert Decimal(out["drawdown_ratio"]) >= Decimal("0.25")
    assert out["drawdown_state"] == "DEFENSIVE"


def test_i_exact_30_percent_critical():
    out = _project(current_account_nav="700000")
    assert out["drawdown_ratio"] == "0.3"
    assert out["drawdown_state"] == "CRITICAL_DRAWDOWN"


def test_j_one_hundred_percent_critical():
    out = _project(current_account_nav="0")
    assert out["drawdown_ratio"] == "1"
    assert out["drawdown_state"] == "CRITICAL_DRAWDOWN"
    assert out["drawdown_evaluation"] == "EVALUATED"


# ---------------------------------------------------------------------------
# K–O fail closed
# ---------------------------------------------------------------------------


def test_k_current_nav_gt_peak_not_evaluated():
    out = _project(current_account_nav="1100000", recent_nav_peak="1000000")
    assert out["drawdown_evaluation"] == "NOT_EVALUATED"
    assert out["drawdown_ratio"] is None
    assert out["drawdown_state"] is None
    assert "NAV_PEAK_INCONSISTENT" in out["reason_codes"]
    assert out["current_account_nav"] == "1100000"
    assert out["recent_nav_peak"] == "1000000"
    assert "NO_SILENT_PEAK_REPAIR" in out["explainability"]["note"]


def test_l_negative_current_nav_reject():
    with pytest.raises(dd.AccountDrawdownValidationError, match="current_account_nav"):
        _project(current_account_nav="-1")


def test_m_zero_peak_reject():
    with pytest.raises(dd.AccountDrawdownValidationError, match="recent_nav_peak"):
        _project(recent_nav_peak="0")


def test_n_negative_peak_reject():
    with pytest.raises(dd.AccountDrawdownValidationError, match="recent_nav_peak"):
        _project(recent_nav_peak="-100")


def test_o_nan_infinity_reject():
    with pytest.raises(dd.AccountDrawdownValidationError):
        _project(current_account_nav=float("nan"))
    with pytest.raises(dd.AccountDrawdownValidationError):
        _project(current_account_nav=float("inf"))
    with pytest.raises(dd.AccountDrawdownValidationError):
        _project(recent_nav_peak=float("nan"))
    with pytest.raises(dd.AccountDrawdownValidationError):
        _project(recent_nav_peak=math.inf)


# ---------------------------------------------------------------------------
# P–V NAV basis / policy
# ---------------------------------------------------------------------------


def test_p_official_official_evaluated():
    out = _project(
        current_nav_basis="OFFICIAL_SETTLED",
        peak_nav_basis="OFFICIAL_SETTLED",
    )
    assert out["drawdown_evaluation"] == "EVALUATED"
    assert out["drawdown_ratio"] is not None
    assert out["drawdown_state"] is not None
    assert "ACCOUNT_DRAWDOWN_COMPUTED" in out["reason_codes"]


def test_q_estimated_intraday_current_not_evaluated():
    out = _project(current_nav_basis="ESTIMATED_INTRADAY")
    assert out["drawdown_evaluation"] == "NOT_EVALUATED"
    assert "INTRADAY_NAV_QUALITY_NOT_PROVEN" in out["reason_codes"]


def test_r_intraday_no_settled_fallback():
    out = _project(current_nav_basis="ESTIMATED_INTRADAY")
    assert out["current_nav_basis"] == "ESTIMATED_INTRADAY"
    assert out["current_nav_basis"] != "OFFICIAL_SETTLED"
    assert "INTRADAY_TO_SETTLED_FALLBACK=NO" in out["explainability"]["note"]
    assert "NAV_BASIS_PRESERVED" in out["explainability"]["note"]


def test_s_intraday_no_formal_ratio_or_state():
    out = _project(current_nav_basis="ESTIMATED_INTRADAY")
    assert out["drawdown_ratio"] is None
    assert out["drawdown_state"] is None
    assert out["current_account_nav"] == "1000000"
    assert out["current_nav_authority_refs"] == ["nav:settled:1"]


def test_t_non_official_peak_basis_not_evaluated():
    out = _project(peak_nav_basis="ESTIMATED_INTRADAY")
    assert out["drawdown_evaluation"] == "NOT_EVALUATED"
    assert out["drawdown_ratio"] is None
    assert out["drawdown_state"] is None
    assert "NAV_PEAK_BASIS_NOT_FORMAL" in out["reason_codes"]


def test_u_unknown_policy_no_latest_fallback():
    out = _project(policy_version="dd.account_drawdown.v9.9")
    assert out["drawdown_evaluation"] == "NOT_EVALUATED"
    assert out["reason_codes"] == ["POLICY_VERSION_NOT_AVAILABLE"]
    assert out["policy_authority_ref"] is None
    assert out["drawdown_ratio"] is None
    assert out["drawdown_state"] is None


def test_v_unknown_policy_and_intraday_cumulative_reasons():
    out = _project(
        policy_version="dd.unknown",
        current_nav_basis="ESTIMATED_INTRADAY",
    )
    assert out["drawdown_evaluation"] == "NOT_EVALUATED"
    assert out["reason_codes"] == [
        "POLICY_VERSION_NOT_AVAILABLE",
        "INTRADAY_NAV_QUALITY_NOT_PROVEN",
    ]


# ---------------------------------------------------------------------------
# W–X time coordinates
# ---------------------------------------------------------------------------


def test_w_peak_at_le_as_of_ok():
    out = _project(nav_peak_at=AS_OF, as_of=AS_OF)
    assert out["drawdown_evaluation"] == "EVALUATED"
    assert out["nav_peak_at"] == AS_OF


def test_x_future_peak_timestamp_reject():
    with pytest.raises(dd.AccountDrawdownValidationError, match="nav_peak_at"):
        _project(nav_peak_at="2026-08-14T00:00:00Z", as_of="2026-08-13T12:00:00Z")


# ---------------------------------------------------------------------------
# Y numeric determinism
# ---------------------------------------------------------------------------


def test_y_global_decimal_prec_6_vs_50_same_output():
    # 2/3 is non-terminating; must not depend on process-global prec.
    original = getcontext().copy()
    try:
        getcontext().prec = 6
        out_a = _project(recent_nav_peak="3", current_account_nav="1")
        getcontext().prec = 50
        out_b = _project(recent_nav_peak="3", current_account_nav="1")
        assert out_a == out_b
        assert out_a["drawdown_ratio"] == out_b["drawdown_ratio"]
        assert out_a["drawdown_ratio"] == _frozen_ratio_str("3", "1")
        assert out_a["drawdown_state"] == "CRITICAL_DRAWDOWN"
    finally:
        getcontext().prec = original.prec
        getcontext().rounding = original.rounding


# ---------------------------------------------------------------------------
# Z / AA action and risk-budget isolation
# ---------------------------------------------------------------------------


def test_z_no_buy_sell_action_vocabulary():
    out = _project(current_account_nav="700000")
    forbidden = {
        "BUY NOW",
        "HOLD",
        "REDUCE",
        "EXIT",
        "WATCH_TO_REDUCE",
        "AVOID",
        "SCALE IN",
        "WAIT",
        "RESEARCH MORE",
    }
    for key in ("reason_codes", "drawdown_evaluation", "drawdown_state"):
        val = out.get(key)
        if isinstance(val, list):
            for item in val:
                assert item not in forbidden
        else:
            assert val not in forbidden
    assert "sell_state" not in out
    assert "recommended_position" not in out
    assert "action_envelope" not in out
    assert "risk_allowed_cap" not in out


def test_aa_no_risk_budget_mutation():
    for current, state in (
        ("1000000", "NORMAL"),
        ("900000", "CAUTION"),
        ("820000", "HIGH_RISK"),
        ("750000", "DEFENSIVE"),
        ("700000", "CRITICAL_DRAWDOWN"),
    ):
        out = _project(current_account_nav=current)
        assert out["drawdown_state"] == state
        assert out.get("risk_budget_adjustment") is None
        assert out.get("risk_budget_ratio") is None
        assert "NO_RISK_BUDGET_MUTATION" in out["explainability"]["cap_semantics"]


# ---------------------------------------------------------------------------
# AB–AD purity / provenance
# ---------------------------------------------------------------------------


def test_ab_deterministic_repeated_output():
    a = _project(current_account_nav="900000")
    b = _project(current_account_nav="900000")
    assert a == b


def test_ac_input_immutability():
    nav_refs = ["nav:1"]
    peak_refs = ["peak:1"]
    snap = copy.deepcopy({"nav": nav_refs, "peak": peak_refs})
    dd.project_account_drawdown(
        as_of=AS_OF,
        policy_version=POLICY,
        current_account_nav="900000",
        current_nav_basis="OFFICIAL_SETTLED",
        current_nav_authority_refs=nav_refs,
        recent_nav_peak=PEAK,
        peak_nav_basis="OFFICIAL_SETTLED",
        nav_peak_at=PEAK_AT,
        nav_peak_authority_refs=peak_refs,
    )
    assert nav_refs == snap["nav"]
    assert peak_refs == snap["peak"]


def test_ad_provenance_refs_required():
    with pytest.raises(
        dd.AccountDrawdownValidationError, match="current_nav_authority_refs"
    ):
        _project(current_nav_authority_refs=[])
    with pytest.raises(
        dd.AccountDrawdownValidationError, match="nav_peak_authority_refs"
    ):
        _project(nav_peak_authority_refs=[])


# ---------------------------------------------------------------------------
# AE–AG module contract
# ---------------------------------------------------------------------------


def test_ae_no_wall_clock():
    src = Path(dd.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in {"now", "utcnow", "today"}:
                pytest.fail(f"wall clock forbidden: {node.func.attr}")
    assert "datetime.now" not in src
    assert "time.time" not in src


def test_af_no_io_or_ai():
    src = Path(dd.__file__).read_text(encoding="utf-8")
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
        "risk_budget_projection",
        "account_reality_service",
        "portfolio_advice_service",
        "campaign_critical_data_projection",
        "decision_inbox_projection",
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] not in forbidden
        if isinstance(node, ast.ImportFrom) and node.module:
            assert node.module.split(".")[0] not in forbidden
    assert "open(" not in src


def test_ag_keyword_only_public_api():
    sig = inspect.signature(dd.project_account_drawdown)
    assert all(
        p.kind == inspect.Parameter.KEYWORD_ONLY for p in sig.parameters.values()
    )
    assert dd.POLICY_VERSION_V01 == "dd.account_drawdown.v0.1"
    assert dd.NUMERIC_PRECISION == 50
    assert dd.NUMERIC_ROUNDING == ROUND_HALF_EVEN


# ---------------------------------------------------------------------------
# Adversarial: state != action; no silent repairs
# ---------------------------------------------------------------------------


def test_adversarial_states_are_not_actions():
    mapping = {
        "NORMAL": "1000000",
        "CAUTION": "900000",
        "HIGH_RISK": "820000",
        "DEFENSIVE": "750000",
        "CRITICAL_DRAWDOWN": "700000",
    }
    for state, current in mapping.items():
        out = _project(current_account_nav=current)
        assert out["drawdown_state"] == state
        assert "DRAWDOWN_STATE_NE_INVESTMENT_ACTION" in out["explainability"][
            "cap_semantics"
        ]
        assert out.get("recommended_action") is None
        assert "BUY" not in out["reason_codes"]
        assert "SELL" not in out["reason_codes"]
        assert "EXIT" not in out["reason_codes"]
        assert "REDUCE" not in out["reason_codes"]


def test_adversarial_no_silent_peak_reset():
    out = _project(current_account_nav="2000000", recent_nav_peak="1000000")
    assert out["recent_nav_peak"] == "1000000"
    assert out["drawdown_ratio"] is not None or out["drawdown_evaluation"] == (
        "NOT_EVALUATED"
    )
    assert out["drawdown_ratio"] != "0"
    assert out["drawdown_state"] != "NORMAL"


def test_adversarial_intraday_does_not_become_settled():
    out = _project(current_nav_basis="ESTIMATED_INTRADAY")
    assert out["current_nav_basis"] == "ESTIMATED_INTRADAY"
    assert out["drawdown_evaluation"] == "NOT_EVALUATED"


def test_just_below_10_percent_still_normal():
    out = _project(recent_nav_peak="10000", current_account_nav="9001")
    assert Decimal(out["drawdown_ratio"]) < Decimal("0.10")
    assert out["drawdown_state"] == "NORMAL"


def test_threshold_compared_on_decimal_not_percent_string():
    # Repeating 1/6 ≈ 0.1666... must stay CAUTION, not jump after percent rounding.
    out = _project(recent_nav_peak="6", current_account_nav="5")
    assert out["drawdown_state"] == "CAUTION"
    assert out["drawdown_ratio"] == _frozen_ratio_str("6", "5")


def test_policy_version_required():
    with pytest.raises(TypeError):
        dd.project_account_drawdown(
            as_of=AS_OF,
            current_account_nav="1000000",
            current_nav_basis="OFFICIAL_SETTLED",
            current_nav_authority_refs=["n"],
            recent_nav_peak=PEAK,
            peak_nav_basis="OFFICIAL_SETTLED",
            nav_peak_at=PEAK_AT,
            nav_peak_authority_refs=["p"],
        )


def test_as_of_does_not_select_policy():
    a = _project(
        as_of="2020-01-01T00:00:00Z",
        nav_peak_at="2019-12-01T00:00:00Z",
        policy_version=POLICY,
    )
    b = _project(
        as_of="2030-01-01T00:00:00Z",
        nav_peak_at="2019-12-01T00:00:00Z",
        policy_version=POLICY,
    )
    assert a["drawdown_state"] == b["drawdown_state"] == "NORMAL"
    u = _project(
        as_of="2030-01-01T00:00:00Z",
        nav_peak_at="2019-12-01T00:00:00Z",
        policy_version="dd.unknown",
    )
    assert u["drawdown_evaluation"] == "NOT_EVALUATED"


def test_malformed_as_of_reject():
    with pytest.raises(dd.AccountDrawdownValidationError, match="as_of"):
        _project(as_of="2026-08-13")


def test_cumulative_intraday_and_informal_peak_and_inconsistent():
    out = _project(
        policy_version="dd.unknown",
        current_nav_basis="ESTIMATED_INTRADAY",
        peak_nav_basis="ESTIMATED_INTRADAY",
        current_account_nav="2000000",
        recent_nav_peak="1000000",
    )
    assert out["reason_codes"] == [
        "POLICY_VERSION_NOT_AVAILABLE",
        "INTRADAY_NAV_QUALITY_NOT_PROVEN",
        "NAV_PEAK_BASIS_NOT_FORMAL",
        "NAV_PEAK_INCONSISTENT",
    ]


def test_numeric_context_has_no_global_decimal_calls():
    src = Path(dd.__file__).read_text(encoding="utf-8")
    assert "getcontext(" not in src
    assert ".quantize(" not in src
    assert "round(" not in src
    assert dd.ACCOUNT_DRAWDOWN_DECIMAL_CONTEXT.prec == 50


def test_reload_pure():
    importlib.reload(dd)
    out = _project()
    assert out["schema_version"] == dd.SCHEMA_VERSION
    assert out["drawdown_state"] == "NORMAL"
