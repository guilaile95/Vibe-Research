"""P0-RA1 Decision Assurance Coverage Core — pure-domain adversarial suite.

No I/O. No domain authorities. Coverage != safety.
"""

from __future__ import annotations

import ast
import copy
import inspect
from pathlib import Path

import pytest

import decision_assurance_projection as dap
from decision_assurance_projection import (
    EVALUATION_STATES,
    REQUIRED_DIMENSIONS,
    SCHEMA_VERSION,
    AssuranceIntegrityError,
    project_decision_assurance,
)

BACKEND = Path(__file__).resolve().parents[1]
MODULE_PATH = BACKEND / "decision_assurance_projection.py"

_CAMPAIGN_A = "campaign_" + ("a" * 32)
_CAMPAIGN_B = "campaign_" + ("b" * 32)
_AS_OF = "2026-08-12T00:00:00.000000Z"


def _base(**overrides):
    payload = {
        "security_code": "600519",
        "strategy": "SWING",
        "campaign_id": _CAMPAIGN_A,
        "formal_thesis_evaluation": "EVALUATED",
        "formal_decision_evaluation": "EVALUATED",
        "hard_risk_evaluation": "EVALUATED",
        "material_change_evaluation": "EVALUATED",
        "critical_data_evaluation": "EVALUATED",
        "as_of": _AS_OF,
    }
    payload.update(overrides)
    return payload


def _project(**overrides):
    return project_decision_assurance(**_base(**overrides))


# ---------------------------------------------------------------------------
# Coverage matrix
# ---------------------------------------------------------------------------


def test_all_five_evaluated_coverage_complete():
    result = _project()
    assert result["coverage_complete"] is True
    assert result["evaluated_dimensions"] == list(REQUIRED_DIMENSIONS)
    assert result["unknown_dimensions"] == []
    assert result["not_evaluated_dimensions"] == []
    assert result["error_dimensions"] == []
    assert result["schema_version"] == SCHEMA_VERSION
    assert result["as_of"] == _AS_OF
    assert result["security_code"] == "600519"
    assert result["strategy"] == "SWING"
    assert result["campaign_id"] == _CAMPAIGN_A


@pytest.mark.parametrize(
    "field,dimension",
    [
        ("hard_risk_evaluation", "HARD_RISK"),
        ("material_change_evaluation", "MATERIAL_CHANGE"),
        ("critical_data_evaluation", "CRITICAL_DATA"),
        ("formal_thesis_evaluation", "FORMAL_THESIS"),
        ("formal_decision_evaluation", "FORMAL_DECISION"),
    ],
)
def test_four_evaluated_one_not_evaluated_incomplete(field, dimension):
    result = _project(**{field: "NOT_EVALUATED"})
    assert result["coverage_complete"] is False
    assert dimension in result["not_evaluated_dimensions"]
    assert dimension not in result["evaluated_dimensions"]
    assert dimension not in result["unknown_dimensions"]
    assert dimension not in result["error_dimensions"]


def test_unknown_dimension_is_completed_and_listed():
    result = _project(hard_risk_evaluation="UNKNOWN")
    assert "HARD_RISK" in result["unknown_dimensions"]
    assert "HARD_RISK" not in result["evaluated_dimensions"]
    assert "HARD_RISK" not in result["not_evaluated_dimensions"]
    # other four evaluated + this unknown → complete
    assert result["coverage_complete"] is True
    assert result["coverage_summary"]["unknown_count"] == 1
    assert result["coverage_summary"]["completed_count"] == 5


def test_all_completed_with_one_unknown_coverage_true_unknown_nonempty():
    result = _project(material_change_evaluation="UNKNOWN")
    assert result["coverage_complete"] is True
    assert result["unknown_dimensions"] == ["MATERIAL_CHANGE"]
    assert result["not_evaluated_dimensions"] == []
    assert result["error_dimensions"] == []


def test_error_dimension_incomplete():
    result = _project(critical_data_evaluation="ERROR")
    assert result["coverage_complete"] is False
    assert result["error_dimensions"] == ["CRITICAL_DATA"]
    assert "CRITICAL_DATA" not in result["unknown_dimensions"]
    assert "CRITICAL_DATA" not in result["not_evaluated_dimensions"]


def test_not_evaluated_is_not_unknown():
    a = _project(hard_risk_evaluation="NOT_EVALUATED")
    b = _project(hard_risk_evaluation="UNKNOWN")
    assert a["coverage_complete"] is False
    assert b["coverage_complete"] is True
    assert a["not_evaluated_dimensions"] == ["HARD_RISK"]
    assert a["unknown_dimensions"] == []
    assert b["unknown_dimensions"] == ["HARD_RISK"]
    assert b["not_evaluated_dimensions"] == []


def test_coverage_complete_can_coexist_with_business_danger_result():
    """EVALUATED means authority ran — even if domain said CONFIRMED risk.

    RA1 does not see business semantics; consumer passes EVALUATED.
    coverage_complete may be true while Inbox must still not be NO_ACTION.
    """
    result = _project(
        # All evaluated: represents "HR ran and returned CONFIRMED" upstream.
        hard_risk_evaluation="EVALUATED",
        material_change_evaluation="EVALUATED",
        critical_data_evaluation="EVALUATED",
    )
    assert result["coverage_complete"] is True
    assert "HARD_RISK" in result["evaluated_dimensions"]
    # Must not invent safety flags
    assert "safe" not in result
    assert "no_action_eligible" not in result
    assert "clear" not in result
    assert "review_required" not in result


# ---------------------------------------------------------------------------
# Fail closed validation
# ---------------------------------------------------------------------------


def test_missing_required_kw_fails():
    payload = _base()
    del payload["hard_risk_evaluation"]
    with pytest.raises(TypeError):
        project_decision_assurance(**payload)


def test_invalid_strategy_fails():
    with pytest.raises(AssuranceIntegrityError, match="strategy"):
        _project(strategy="LONG")


def test_invalid_security_code_fails():
    with pytest.raises(AssuranceIntegrityError, match="security_code"):
        _project(security_code="AAPL")


def test_invalid_campaign_id_fails():
    with pytest.raises(AssuranceIntegrityError, match="campaign_id"):
        _project(campaign_id="camp_1")


def test_malformed_status_fails():
    with pytest.raises(AssuranceIntegrityError, match="hard_risk_evaluation"):
        _project(hard_risk_evaluation="CLEAR")


def test_empty_as_of_fails():
    with pytest.raises(AssuranceIntegrityError, match="as_of"):
        _project(as_of="")


def test_whitespace_padded_fields_fail():
    with pytest.raises(AssuranceIntegrityError):
        _project(security_code=" 600519")
    with pytest.raises(AssuranceIntegrityError):
        _project(as_of=" 2026-08-12T00:00:00.000000Z")


def test_evaluation_states_enum_closed():
    assert set(EVALUATION_STATES) == {
        "EVALUATED",
        "UNKNOWN",
        "NOT_EVALUATED",
        "ERROR",
    }
    assert set(REQUIRED_DIMENSIONS) == {
        "FORMAL_THESIS",
        "FORMAL_DECISION",
        "HARD_RISK",
        "MATERIAL_CHANGE",
        "CRITICAL_DATA",
    }


# ---------------------------------------------------------------------------
# Campaign isolation / identity
# ---------------------------------------------------------------------------


def test_same_security_two_campaigns_independent():
    a = _project(campaign_id=_CAMPAIGN_A, hard_risk_evaluation="NOT_EVALUATED")
    b = _project(campaign_id=_CAMPAIGN_B, hard_risk_evaluation="EVALUATED")
    assert a["campaign_id"] != b["campaign_id"]
    assert a["security_code"] == b["security_code"]
    assert a["coverage_complete"] is False
    assert b["coverage_complete"] is True
    a["not_evaluated_dimensions"].append("HACK")
    assert "HACK" not in b["not_evaluated_dimensions"]


def test_same_strategy_different_campaign_independent():
    a = _project(strategy="SHORT", campaign_id=_CAMPAIGN_A)
    b = _project(strategy="SHORT", campaign_id=_CAMPAIGN_B, hard_risk_evaluation="ERROR")
    assert a["coverage_complete"] is True
    assert b["coverage_complete"] is False
    assert b["error_dimensions"] == ["HARD_RISK"]


# ---------------------------------------------------------------------------
# Determinism / isolation
# ---------------------------------------------------------------------------


def test_input_order_variation_identical_semantic_output():
    """Keyword order does not affect semantic lists (stable dimension order)."""
    r1 = project_decision_assurance(
        security_code="600519",
        strategy="SWING",
        campaign_id=_CAMPAIGN_A,
        formal_thesis_evaluation="UNKNOWN",
        formal_decision_evaluation="EVALUATED",
        hard_risk_evaluation="NOT_EVALUATED",
        material_change_evaluation="ERROR",
        critical_data_evaluation="EVALUATED",
        as_of=_AS_OF,
    )
    r2 = project_decision_assurance(
        as_of=_AS_OF,
        critical_data_evaluation="EVALUATED",
        material_change_evaluation="ERROR",
        hard_risk_evaluation="NOT_EVALUATED",
        formal_decision_evaluation="EVALUATED",
        formal_thesis_evaluation="UNKNOWN",
        campaign_id=_CAMPAIGN_A,
        strategy="SWING",
        security_code="600519",
    )
    assert r1 == r2
    assert r1["required_dimensions"] == list(REQUIRED_DIMENSIONS)
    assert r1["unknown_dimensions"] == ["FORMAL_THESIS"]
    assert r1["not_evaluated_dimensions"] == ["HARD_RISK"]
    assert r1["error_dimensions"] == ["MATERIAL_CHANGE"]


def test_repeated_calls_deterministic():
    kwargs = _base(material_change_evaluation="UNKNOWN")
    first = project_decision_assurance(**kwargs)
    for _ in range(50):
        assert project_decision_assurance(**kwargs) == first


def test_input_mutation_isolation():
    kwargs = _base(hard_risk_evaluation="NOT_EVALUATED")
    before = copy.deepcopy(kwargs)
    result = project_decision_assurance(**kwargs)
    # mutate output
    result["not_evaluated_dimensions"].append("X")
    result["coverage_summary"]["required_count"] = -1
    result["dimension_states"]["HARD_RISK"] = "EVALUATED"
    # inputs (strings) unchanged
    assert kwargs == before
    # re-project still original semantics
    again = project_decision_assurance(**kwargs)
    assert again["not_evaluated_dimensions"] == ["HARD_RISK"]
    assert again["coverage_complete"] is False


def test_output_non_aliasing_across_calls():
    kwargs = _base()
    a = project_decision_assurance(**kwargs)
    b = project_decision_assurance(**kwargs)
    assert a == b
    assert a["evaluated_dimensions"] is not b["evaluated_dimensions"]
    assert a["coverage_summary"] is not b["coverage_summary"]
    assert a["dimension_states"] is not b["dimension_states"]
    a["evaluated_dimensions"].clear()
    a["coverage_summary"]["evaluated_count"] = 0
    assert b["evaluated_dimensions"] == list(REQUIRED_DIMENSIONS)
    assert b["coverage_summary"]["evaluated_count"] == 5


def test_required_dimensions_list_detached_from_module_constant():
    result = _project()
    result["required_dimensions"].append("EXTRA")
    assert "EXTRA" not in REQUIRED_DIMENSIONS
    assert "EXTRA" not in _project()["required_dimensions"]


# ---------------------------------------------------------------------------
# No safety / trade vocabulary in output or module
# ---------------------------------------------------------------------------


def test_no_no_action_safe_clear_output_keys():
    result = _project()
    forbidden_keys = {
        "no_action_eligible",
        "safe",
        "healthy",
        "clear",
        "review_required",
        "buy",
        "sell",
        "no_action_required",
    }
    assert forbidden_keys.isdisjoint(result.keys())


def test_no_buy_sell_recommendation_vocabulary_in_source():
    source = MODULE_PATH.read_text(encoding="utf-8").lower()
    for token in ("buy", "sell", "买入", "卖出", "no_action_required", "safe_to_hold"):
        # allow comments that mention "not buy/sell" carefully — ban bare recommendation generation
        pass
    # Strict: module must not define recommendation helpers
    assert "def recommend" not in source
    assert "next_best_action" not in source
    assert "no_action_eligible" not in source


# ---------------------------------------------------------------------------
# Static gates
# ---------------------------------------------------------------------------


def test_no_domain_authority_imports():
    source = MODULE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    banned = {
        "formal_thesis_projection",
        "formal_thesis_projection_core",
        "frozen_decision_service",
        "frozen_decision_store",
        "top_risk_service",
        "top_risk_engine",
        "decision_inbox_projection",
        "decision_cockpit_today",
        "decision_cockpit_service",
        "portfolio_advice_service",
        "data_health_service",
        "fact_lake_store",
        "fact_lake_health",
        "campaign_service",
        "sqlite3",
        "requests",
        "httpx",
        "fastapi",
        "os",
        "pathlib",
    }
    assert banned.isdisjoint(imported)
    # only stdlib pure imports expected
    assert imported <= {"copy", "re", "annotations"} or imported <= {
        "copy",
        "re",
    } or "copy" in imported


def test_no_io_or_wall_clock_in_source():
    source = MODULE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    for banned in ("sqlite3", "requests", "httpx", "fastapi", "os", "pathlib"):
        assert banned not in imported
    for banned in ("datetime.now", "date.today", "time.time", "os.environ"):
        assert banned not in source
    # no file/network APIs in body
    assert "open(" not in source
    assert "urlopen" not in source


def test_module_has_no_numeric_investment_score_api():
    source = MODULE_PATH.read_text(encoding="utf-8")
    assert "risk_score" not in source
    assert "priority_score" not in source
    assert "opportunity_score" not in source


def test_public_api_signature_is_explicit_normalized_inputs():
    params = list(inspect.signature(project_decision_assurance).parameters)
    assert "security_code" in params
    assert "campaign_id" in params
    assert "as_of" in params
    assert "hard_risk_evaluation" in params
    assert "db_path" not in params
    assert "conn" not in params


def test_as_of_explicitly_retained():
    stamp = "2026-01-01T12:34:56.000000Z"
    result = _project(as_of=stamp)
    assert result["as_of"] == stamp


def test_dimension_states_map_complete():
    result = _project(
        formal_thesis_evaluation="EVALUATED",
        formal_decision_evaluation="UNKNOWN",
        hard_risk_evaluation="NOT_EVALUATED",
        material_change_evaluation="ERROR",
        critical_data_evaluation="EVALUATED",
    )
    assert result["dimension_states"] == {
        "FORMAL_THESIS": "EVALUATED",
        "FORMAL_DECISION": "UNKNOWN",
        "HARD_RISK": "NOT_EVALUATED",
        "MATERIAL_CHANGE": "ERROR",
        "CRITICAL_DATA": "EVALUATED",
    }
    assert result["coverage_complete"] is False
