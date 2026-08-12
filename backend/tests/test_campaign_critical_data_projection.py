"""P0-CCD1 Campaign Critical Data Projection Core — pure-domain suite.

No I/O. No health/thesis/inbox authority imports.
Coverage/evaluation path != decision safety.
"""

from __future__ import annotations

import ast
import copy
import inspect
from pathlib import Path

import pytest

import campaign_critical_data_projection as ccd
from campaign_critical_data_projection import (
    CRITICAL_DATA_EVALUATIONS,
    CRITICAL_DATA_STATES,
    DEPENDENCY_RESULT_STATES,
    DEPENDENCY_SET_STATES,
    REASON_ALL_DEPENDENCIES_USABLE,
    REASON_DEPENDENCY_BLOCKED,
    REASON_DEPENDENCY_ERROR,
    REASON_DEPENDENCY_NOT_EVALUATED,
    REASON_DEPENDENCY_SET_AUTHORITATIVELY_EMPTY,
    REASON_DEPENDENCY_SET_ERROR,
    REASON_DEPENDENCY_SET_NOT_EVALUATED,
    REASON_DEPENDENCY_SET_UNKNOWN,
    REASON_DEPENDENCY_STALE,
    REASON_DEPENDENCY_UNKNOWN,
    SCHEMA_VERSION,
    CriticalDataIntegrityError,
    project_campaign_critical_data,
)

BACKEND = Path(__file__).resolve().parents[1]
MODULE_PATH = BACKEND / "campaign_critical_data_projection.py"

_CAMPAIGN_A = "campaign_" + ("a" * 32)
_CAMPAIGN_B = "campaign_" + ("b" * 32)
_AS_OF = "2026-08-12T00:00:00.000000Z"
_AS_OF_OTHER = "2026-08-11T00:00:00.000000Z"

_DEP_QUOTE = "dep.quote.intraday"
_DEP_FIN = "dep.financials.latest"
_DEP_ANN = "dep.announcements.material"


def _dep(
    dependency_id: str,
    state: str,
    *,
    as_of: str = _AS_OF,
    authority_refs: list[str] | None = None,
) -> dict:
    return {
        "dependency_id": dependency_id,
        "state": state,
        "as_of": as_of,
        "authority_refs": list(
            authority_refs if authority_refs is not None else [f"ref:{dependency_id}"]
        ),
    }


def _base(**overrides):
    payload = {
        "security_code": "600519",
        "strategy": "SWING",
        "campaign_id": _CAMPAIGN_A,
        "as_of": _AS_OF,
        "dependency_set_state": "RESOLVED",
        "dependency_set_authority_refs": ["depset:strategy_template_v0"],
        "required_dependency_ids": [_DEP_QUOTE, _DEP_FIN],
        "dependency_results": [
            _dep(_DEP_QUOTE, "USABLE"),
            _dep(_DEP_FIN, "USABLE"),
        ],
    }
    payload.update(overrides)
    return payload


def _project(**overrides):
    return project_campaign_critical_data(**_base(**overrides))


# ---------------------------------------------------------------------------
# 1-8: RESOLVED aggregation matrix
# ---------------------------------------------------------------------------


def test_1_all_required_dependencies_usable_evaluated():
    result = _project()
    assert result["critical_data_state"] == "USABLE"
    assert result["critical_data_evaluation"] == "EVALUATED"
    assert result["schema_version"] == SCHEMA_VERSION
    assert result["as_of"] == _AS_OF
    assert result["required_dependency_ids"] == [_DEP_QUOTE, _DEP_FIN]
    assert REASON_ALL_DEPENDENCIES_USABLE in result["reason_codes"]


def test_2_one_blocked_evaluated():
    result = _project(
        dependency_results=[
            _dep(_DEP_QUOTE, "BLOCKED"),
            _dep(_DEP_FIN, "USABLE"),
        ]
    )
    assert result["critical_data_state"] == "BLOCKED"
    assert result["critical_data_evaluation"] == "EVALUATED"
    assert REASON_DEPENDENCY_BLOCKED in result["reason_codes"]
    assert REASON_ALL_DEPENDENCIES_USABLE not in result["reason_codes"]


def test_3_one_stale_evaluated():
    result = _project(
        dependency_results=[
            _dep(_DEP_QUOTE, "USABLE"),
            _dep(_DEP_FIN, "STALE"),
        ]
    )
    assert result["critical_data_state"] == "STALE"
    assert result["critical_data_evaluation"] == "EVALUATED"
    assert REASON_DEPENDENCY_STALE in result["reason_codes"]


def test_4_one_unknown_maps_unknown_unknown():
    result = _project(
        dependency_results=[
            _dep(_DEP_QUOTE, "USABLE"),
            _dep(_DEP_FIN, "UNKNOWN"),
        ]
    )
    assert result["critical_data_state"] == "UNKNOWN"
    assert result["critical_data_evaluation"] == "UNKNOWN"
    assert REASON_DEPENDENCY_UNKNOWN in result["reason_codes"]


def test_5_one_not_evaluated_maps_unknown_not_evaluated():
    result = _project(
        dependency_results=[
            _dep(_DEP_QUOTE, "USABLE"),
            _dep(_DEP_FIN, "NOT_EVALUATED"),
        ]
    )
    assert result["critical_data_state"] == "UNKNOWN"
    assert result["critical_data_evaluation"] == "NOT_EVALUATED"
    assert REASON_DEPENDENCY_NOT_EVALUATED in result["reason_codes"]


def test_6_one_error_maps_unknown_error():
    result = _project(
        dependency_results=[
            _dep(_DEP_QUOTE, "USABLE"),
            _dep(_DEP_FIN, "ERROR"),
        ]
    )
    assert result["critical_data_state"] == "UNKNOWN"
    assert result["critical_data_evaluation"] == "ERROR"
    assert REASON_DEPENDENCY_ERROR in result["reason_codes"]


def test_7_blocked_plus_error_preserves_both_layers_and_reasons():
    result = _project(
        dependency_results=[
            _dep(_DEP_QUOTE, "BLOCKED"),
            _dep(_DEP_FIN, "ERROR"),
        ]
    )
    assert result["critical_data_state"] == "BLOCKED"
    assert result["critical_data_evaluation"] == "ERROR"
    assert REASON_DEPENDENCY_BLOCKED in result["reason_codes"]
    assert REASON_DEPENDENCY_ERROR in result["reason_codes"]


def test_8_stale_plus_unknown_preserves_stale_and_unknown_eval():
    result = _project(
        dependency_results=[
            _dep(_DEP_QUOTE, "STALE"),
            _dep(_DEP_FIN, "UNKNOWN"),
        ]
    )
    assert result["critical_data_state"] == "STALE"
    assert result["critical_data_evaluation"] == "UNKNOWN"
    assert REASON_DEPENDENCY_STALE in result["reason_codes"]
    assert REASON_DEPENDENCY_UNKNOWN in result["reason_codes"]


# ---------------------------------------------------------------------------
# 9-11: dependency set non-RESOLVED
# ---------------------------------------------------------------------------


def test_9_dependency_set_unknown():
    result = _project(
        dependency_set_state="UNKNOWN",
        required_dependency_ids=[],
        dependency_results=[],
    )
    assert result["critical_data_state"] == "UNKNOWN"
    assert result["critical_data_evaluation"] == "UNKNOWN"
    assert result["reason_codes"] == [REASON_DEPENDENCY_SET_UNKNOWN]


def test_10_dependency_set_not_evaluated():
    result = _project(
        dependency_set_state="NOT_EVALUATED",
        required_dependency_ids=[],
        dependency_results=[],
    )
    assert result["critical_data_state"] == "UNKNOWN"
    assert result["critical_data_evaluation"] == "NOT_EVALUATED"
    assert result["reason_codes"] == [REASON_DEPENDENCY_SET_NOT_EVALUATED]


def test_11_dependency_set_error():
    result = _project(
        dependency_set_state="ERROR",
        required_dependency_ids=[],
        dependency_results=[],
    )
    assert result["critical_data_state"] == "UNKNOWN"
    assert result["critical_data_evaluation"] == "ERROR"
    assert result["reason_codes"] == [REASON_DEPENDENCY_SET_ERROR]


# ---------------------------------------------------------------------------
# 12: authoritative empty set
# ---------------------------------------------------------------------------


def test_12_authoritative_empty_set_usable_evaluated_with_reason():
    result = _project(
        required_dependency_ids=[],
        dependency_results=[],
        dependency_set_authority_refs=["depset:explicit_empty_v1"],
    )
    assert result["critical_data_state"] == "USABLE"
    assert result["critical_data_evaluation"] == "EVALUATED"
    assert REASON_DEPENDENCY_SET_AUTHORITATIVELY_EMPTY in result["reason_codes"]
    assert result["required_dependency_ids"] == []
    assert result["dependency_results"] == []


def test_12b_empty_set_without_authority_refs_fail_closed():
    with pytest.raises(CriticalDataIntegrityError):
        _project(
            required_dependency_ids=[],
            dependency_results=[],
            dependency_set_authority_refs=[],
        )


def test_r1_resolved_nonempty_without_authority_refs_fail_closed():
    """RESOLVED + non-empty required set still needs provenance refs."""
    with pytest.raises(CriticalDataIntegrityError):
        _project(
            dependency_set_state="RESOLVED",
            required_dependency_ids=[_DEP_QUOTE, _DEP_FIN],
            dependency_results=[
                _dep(_DEP_QUOTE, "USABLE"),
                _dep(_DEP_FIN, "USABLE"),
            ],
            dependency_set_authority_refs=[],
        )


def test_r1_resolved_nonempty_with_authority_ref_unchanged():
    result = _project(
        dependency_set_state="RESOLVED",
        required_dependency_ids=[_DEP_QUOTE, _DEP_FIN],
        dependency_results=[
            _dep(_DEP_QUOTE, "USABLE"),
            _dep(_DEP_FIN, "USABLE"),
        ],
        dependency_set_authority_refs=["depset:strategy_template_v0"],
    )
    assert result["critical_data_state"] == "USABLE"
    assert result["critical_data_evaluation"] == "EVALUATED"
    assert result["dependency_set_authority_refs"] == [
        "depset:strategy_template_v0"
    ]
    assert REASON_ALL_DEPENDENCIES_USABLE in result["reason_codes"]


# ---------------------------------------------------------------------------
# 13-16: exact cover / same-as_of fail closed
# ---------------------------------------------------------------------------


def test_13_missing_dependency_result_fail_closed():
    with pytest.raises(CriticalDataIntegrityError):
        _project(
            required_dependency_ids=[_DEP_QUOTE, _DEP_FIN],
            dependency_results=[_dep(_DEP_QUOTE, "USABLE")],
        )


def test_14_extra_dependency_result_fail_closed():
    with pytest.raises(CriticalDataIntegrityError):
        _project(
            required_dependency_ids=[_DEP_QUOTE],
            dependency_results=[
                _dep(_DEP_QUOTE, "USABLE"),
                _dep(_DEP_FIN, "USABLE"),
            ],
        )


def test_15_duplicate_dependency_id_in_required_fail_closed():
    with pytest.raises(CriticalDataIntegrityError):
        _project(
            required_dependency_ids=[_DEP_QUOTE, _DEP_QUOTE],
            dependency_results=[
                _dep(_DEP_QUOTE, "USABLE"),
                _dep(_DEP_FIN, "USABLE"),
            ],
        )


def test_15b_duplicate_dependency_id_in_results_fail_closed():
    with pytest.raises(CriticalDataIntegrityError):
        _project(
            required_dependency_ids=[_DEP_QUOTE, _DEP_FIN],
            dependency_results=[
                _dep(_DEP_QUOTE, "USABLE"),
                _dep(_DEP_QUOTE, "BLOCKED"),
            ],
        )


def test_16_mismatched_as_of_fail_closed():
    with pytest.raises(CriticalDataIntegrityError):
        _project(
            dependency_results=[
                _dep(_DEP_QUOTE, "USABLE", as_of=_AS_OF),
                _dep(_DEP_FIN, "USABLE", as_of=_AS_OF_OTHER),
            ]
        )


def test_non_resolved_set_with_required_ids_fail_closed():
    with pytest.raises(CriticalDataIntegrityError):
        _project(
            dependency_set_state="NOT_EVALUATED",
            required_dependency_ids=[_DEP_QUOTE],
            dependency_results=[],
        )


def test_non_resolved_set_with_results_fail_closed():
    with pytest.raises(CriticalDataIntegrityError):
        _project(
            dependency_set_state="UNKNOWN",
            required_dependency_ids=[],
            dependency_results=[_dep(_DEP_QUOTE, "USABLE")],
        )


# ---------------------------------------------------------------------------
# 17-18: campaign isolation / identity independence
# ---------------------------------------------------------------------------


def test_17_different_campaign_isolation():
    a = _project(campaign_id=_CAMPAIGN_A)
    b = _project(
        campaign_id=_CAMPAIGN_B,
        dependency_results=[
            _dep(_DEP_QUOTE, "BLOCKED"),
            _dep(_DEP_FIN, "USABLE"),
        ],
    )
    assert a["campaign_id"] == _CAMPAIGN_A
    assert b["campaign_id"] == _CAMPAIGN_B
    assert a["critical_data_state"] == "USABLE"
    assert b["critical_data_state"] == "BLOCKED"


def test_18_same_security_different_strategy_campaign_independent():
    swing = _project(strategy="SWING", campaign_id=_CAMPAIGN_A)
    medium = _project(
        strategy="MEDIUM",
        campaign_id=_CAMPAIGN_B,
        dependency_results=[
            _dep(_DEP_QUOTE, "STALE"),
            _dep(_DEP_FIN, "USABLE"),
        ],
    )
    assert swing["security_code"] == medium["security_code"] == "600519"
    assert swing["strategy"] == "SWING"
    assert medium["strategy"] == "MEDIUM"
    assert swing["critical_data_state"] == "USABLE"
    assert medium["critical_data_state"] == "STALE"


# ---------------------------------------------------------------------------
# 19: dynamic equal enum strings (no ``is`` interning)
# ---------------------------------------------------------------------------


def test_19_dynamic_equal_enum_strings():
    """Adversarial: equal-by-value dynamic strings must use == semantics."""
    blocked = "".join(["BL", "OCKED"])
    error = "".join(["ER", "ROR"])
    resolved = "".join(["RE", "SOLVED"])
    assert blocked == "BLOCKED"
    assert error == "ERROR"
    assert resolved == "RESOLVED"
    # Values are equal; identity is irrelevant and must not be required.
    assert blocked == "BLOCKED" and error == "ERROR" and resolved == "RESOLVED"

    result = _project(
        dependency_set_state=resolved,
        dependency_set_authority_refs=["depset:dynamic"],
        dependency_results=[
            _dep(_DEP_QUOTE, blocked),
            _dep(_DEP_FIN, error),
        ],
    )
    assert result["critical_data_state"] == "BLOCKED"
    assert result["critical_data_evaluation"] == "ERROR"


def test_19b_dynamic_set_state_not_evaluated():
    state = "".join(["NOT_", "EVALUATED"])
    assert state == "NOT_EVALUATED"
    result = _project(
        dependency_set_state=state,
        required_dependency_ids=[],
        dependency_results=[],
    )
    assert result["critical_data_evaluation"] == "NOT_EVALUATED"
    assert result["critical_data_state"] == "UNKNOWN"


def test_19c_source_has_no_string_identity_comparisons():
    """Forbid ``value is "ENUM"`` style checks; ``is None`` remains legal."""
    source = MODULE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)

    def _is_string_const(node: ast.AST) -> bool:
        return isinstance(node, ast.Constant) and isinstance(node.value, str)

    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        comparators = [node.left, *node.comparators]
        for op, left, right in zip(node.ops, comparators, comparators[1:]):
            if isinstance(op, (ast.Is, ast.IsNot)) and (
                _is_string_const(left) or _is_string_const(right)
            ):
                raise AssertionError(
                    "production must not use identity comparisons for string enums"
                )


# ---------------------------------------------------------------------------
# 20-23: determinism / immutability
# ---------------------------------------------------------------------------


def test_20_deterministic_ordering_of_results_follows_required_ids():
    result = _project(
        required_dependency_ids=[_DEP_FIN, _DEP_QUOTE, _DEP_ANN],
        dependency_results=[
            _dep(_DEP_ANN, "USABLE"),
            _dep(_DEP_QUOTE, "USABLE"),
            _dep(_DEP_FIN, "USABLE"),
        ],
    )
    assert [item["dependency_id"] for item in result["dependency_results"]] == [
        _DEP_FIN,
        _DEP_QUOTE,
        _DEP_ANN,
    ]
    assert result["required_dependency_ids"] == [_DEP_FIN, _DEP_QUOTE, _DEP_ANN]


def test_21_repeated_call_identical():
    a = _project()
    b = _project()
    assert a == b


def test_22_input_zero_mutation():
    results = [
        _dep(_DEP_QUOTE, "USABLE"),
        _dep(_DEP_FIN, "BLOCKED"),
    ]
    required = [_DEP_QUOTE, _DEP_FIN]
    refs = ["depset:v1"]
    payload = _base(
        dependency_results=results,
        required_dependency_ids=required,
        dependency_set_authority_refs=refs,
    )
    before = copy.deepcopy(payload)
    _ = project_campaign_critical_data(**payload)
    assert payload == before
    assert results[0]["authority_refs"] == ["ref:dep.quote.intraday"]


def test_23_output_detached_from_inputs_and_self():
    results = [
        _dep(_DEP_QUOTE, "USABLE", authority_refs=["shared-ref"]),
        _dep(_DEP_FIN, "USABLE", authority_refs=["shared-ref-2"]),
    ]
    refs = ["depset:v1"]
    out = _project(
        dependency_results=results,
        dependency_set_authority_refs=refs,
    )
    out["dependency_results"][0]["authority_refs"].append("mutated")
    out["dependency_set_authority_refs"].append("mutated-set")
    out["reason_codes"].append("MUTATED")
    out["required_dependency_ids"].append("mutated-id")

    again = _project(
        dependency_results=results,
        dependency_set_authority_refs=refs,
    )
    assert "mutated" not in again["dependency_results"][0]["authority_refs"]
    assert "mutated-set" not in again["dependency_set_authority_refs"]
    assert "MUTATED" not in again["reason_codes"]
    assert "mutated-id" not in again["required_dependency_ids"]
    # original inputs untouched
    assert results[0]["authority_refs"] == ["shared-ref"]
    assert refs == ["depset:v1"]


# ---------------------------------------------------------------------------
# 24: cumulative reasons
# ---------------------------------------------------------------------------


def test_24_cumulative_reasons_not_collapsed_to_highest():
    result = _project(
        required_dependency_ids=[_DEP_QUOTE, _DEP_FIN, _DEP_ANN],
        dependency_results=[
            _dep(_DEP_QUOTE, "BLOCKED"),
            _dep(_DEP_FIN, "STALE"),
            _dep(_DEP_ANN, "ERROR"),
        ],
    )
    codes = result["reason_codes"]
    assert REASON_DEPENDENCY_BLOCKED in codes
    assert REASON_DEPENDENCY_STALE in codes
    assert REASON_DEPENDENCY_ERROR in codes
    # deterministic order by REASON_CODES catalog
    assert codes.index(REASON_DEPENDENCY_BLOCKED) < codes.index(
        REASON_DEPENDENCY_STALE
    )
    assert codes.index(REASON_DEPENDENCY_STALE) < codes.index(
        REASON_DEPENDENCY_ERROR
    )


# ---------------------------------------------------------------------------
# 25-27: no DI / investment / risk authority leakage
# ---------------------------------------------------------------------------


def test_25_no_di_state_generation_in_output_or_source():
    result = _project()
    forbidden = {
        "NO_ACTION_REQUIRED",
        "BLOCKED_BY_DATA",
        "REVIEW_REQUIRED",
        "SETUP_REQUIRED",
        "NEXT_WORKFLOW_ACTION",
    }
    blob = repr(result)
    for token in forbidden:
        assert token not in blob
    source = MODULE_PATH.read_text(encoding="utf-8")
    for token in forbidden:
        assert token not in source


def test_26_no_buy_sell_hold_exit_in_source_or_output():
    result = _project()
    forbidden = ("BUY", "SELL", "HOLD", "EXIT", "REDUCE", "SAFE", "CLEAR")
    # Source may mention them only in prohibition comments; enforce no generation
    # by checking output values and public function return keys.
    for value in result.values():
        if isinstance(value, str):
            assert value not in forbidden
    assert "recommendation" not in result
    assert "next_best_action" not in result
    assert "visible_state" not in result


def test_27_no_hard_risk_or_material_change_fields():
    result = _project()
    for key in result:
        assert "hard_risk" not in key.lower()
        assert "material_change" not in key.lower()
        assert "thesis" not in key.lower()


# ---------------------------------------------------------------------------
# 28-30: pure domain / no I/O / no forbidden imports
# ---------------------------------------------------------------------------


def test_28_no_io_imports_in_module_ast():
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    forbidden_modules = {
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
        "data_health_service",
        "data_health_adapters",
        "fact_lake_health",
        "fact_lake_health_adapter",
        "fact_lake_store",
        "portfolio_advice_service",
        "decision_cockpit_service",
        "decision_cockpit_today",
        "formal_thesis_projection",
        "frozen_decision_service",
        "campaign_store",
        "campaign_service",
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                assert root not in forbidden_modules
                assert alias.name not in forbidden_modules
        elif isinstance(node, ast.ImportFrom):
            if node.module is None:
                continue
            root = node.module.split(".")[0]
            assert root not in forbidden_modules
            assert node.module not in forbidden_modules


def test_29_no_wall_clock_usage():
    source = MODULE_PATH.read_text(encoding="utf-8")
    # Parsing as_of is allowed via datetime.fromisoformat; wall clock is not.
    assert "datetime.now" not in source
    assert "datetime.utcnow" not in source
    assert "time.time" not in source
    assert "timezone.now" not in source
    # Ensure project function signature has no hidden clock injection.
    sig = inspect.signature(project_campaign_critical_data)
    assert "now" not in sig.parameters
    assert "clock" not in sig.parameters


def test_30_no_direct_h1_or_data_health_domain_authority_import():
    source = MODULE_PATH.read_text(encoding="utf-8")
    for token in (
        "import data_health",
        "from data_health",
        "import fact_lake_health",
        "from fact_lake_health",
        "import portfolio_advice",
        "from portfolio_advice",
        "import decision_cockpit",
        "from decision_cockpit",
    ):
        assert token not in source


# ---------------------------------------------------------------------------
# Additional integrity matrix
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field,value",
    [
        ("security_code", "60051"),
        ("security_code", "600519A"),
        ("security_code", " 600519"),
        ("strategy", "swing"),
        ("strategy", "LONG"),
        ("campaign_id", "campaign_not_hex"),
        ("campaign_id", "camp_" + ("a" * 32)),
        ("as_of", "2026-08-12"),
        ("as_of", "2026-08-12T00:00:00"),
        ("as_of", "2026-08-12T00:00:00+08:00"),
        ("dependency_set_state", "RESOLVE"),
        ("dependency_set_state", "resolved"),
    ],
)
def test_invalid_top_level_fields_fail_closed(field, value):
    with pytest.raises(CriticalDataIntegrityError):
        _project(**{field: value})


def test_unknown_dependency_result_state_fail_closed():
    with pytest.raises(CriticalDataIntegrityError):
        _project(
            dependency_results=[
                _dep(_DEP_QUOTE, "USABLE"),
                _dep(_DEP_FIN, "DEGRADED"),
            ]
        )


def test_malformed_authority_refs_fail_closed():
    with pytest.raises(CriticalDataIntegrityError):
        _project(dependency_set_authority_refs=["ok", "  bad  "])
    with pytest.raises(CriticalDataIntegrityError):
        _project(dependency_set_authority_refs="not-a-list")
    with pytest.raises(CriticalDataIntegrityError):
        _project(
            dependency_results=[
                _dep(_DEP_QUOTE, "USABLE", authority_refs=[""]),
                _dep(_DEP_FIN, "USABLE"),
            ]
        )


def test_result_missing_field_fail_closed():
    bad = _dep(_DEP_QUOTE, "USABLE")
    del bad["authority_refs"]
    with pytest.raises(CriticalDataIntegrityError):
        _project(
            required_dependency_ids=[_DEP_QUOTE],
            dependency_results=[bad],
        )


def test_result_extra_field_fail_closed():
    bad = _dep(_DEP_QUOTE, "USABLE")
    bad["score"] = 1
    with pytest.raises(CriticalDataIntegrityError):
        _project(
            required_dependency_ids=[_DEP_QUOTE],
            dependency_results=[bad],
        )


def test_public_enums_exported():
    assert "USABLE" in CRITICAL_DATA_STATES
    assert "BLOCKED" in CRITICAL_DATA_STATES
    assert "UNKNOWN" in CRITICAL_DATA_STATES
    assert "STALE" in CRITICAL_DATA_STATES
    assert set(CRITICAL_DATA_EVALUATIONS) == {
        "EVALUATED",
        "UNKNOWN",
        "NOT_EVALUATED",
        "ERROR",
    }
    assert set(DEPENDENCY_SET_STATES) == {
        "RESOLVED",
        "UNKNOWN",
        "NOT_EVALUATED",
        "ERROR",
    }
    assert set(DEPENDENCY_RESULT_STATES) == {
        "USABLE",
        "BLOCKED",
        "STALE",
        "UNKNOWN",
        "NOT_EVALUATED",
        "ERROR",
    }


def test_authority_refs_accumulate_set_and_dependency_refs():
    result = _project(
        dependency_set_authority_refs=["set-ref"],
        dependency_results=[
            _dep(_DEP_QUOTE, "USABLE", authority_refs=["q-ref"]),
            _dep(_DEP_FIN, "BLOCKED", authority_refs=["f-ref", "set-ref"]),
        ],
    )
    assert result["authority_refs"][0] == "set-ref"
    assert "q-ref" in result["authority_refs"]
    assert "f-ref" in result["authority_refs"]
    # de-duplicated, order-preserving
    assert result["authority_refs"].count("set-ref") == 1


def test_blocked_evaluated_is_valid_ra1_completed_path():
    """USABLE/BLOCKED/STALE + EVALUATED are completed evaluation paths."""
    for state in ("USABLE", "BLOCKED", "STALE"):
        result = _project(
            required_dependency_ids=[_DEP_QUOTE],
            dependency_results=[_dep(_DEP_QUOTE, state)],
        )
        assert result["critical_data_state"] == state
        assert result["critical_data_evaluation"] == "EVALUATED"


def test_module_has_no_filesystem_side_effects_on_import():
    # Re-import path already exercised by pytest collection; assert no path
    # constants pointing at user data dirs / sqlite imports.
    source = MODULE_PATH.read_text(encoding="utf-8")
    assert "VR_DATA_DIR" not in source
    assert ".vibe-research" not in source
    assert "import sqlite3" not in source
    assert "from sqlite3" not in source


def test_severity_blocked_dominates_stale():
    result = _project(
        dependency_results=[
            _dep(_DEP_QUOTE, "STALE"),
            _dep(_DEP_FIN, "BLOCKED"),
        ]
    )
    assert result["critical_data_state"] == "BLOCKED"
    assert result["critical_data_evaluation"] == "EVALUATED"


def test_eval_error_dominates_not_evaluated():
    result = _project(
        dependency_results=[
            _dep(_DEP_QUOTE, "NOT_EVALUATED"),
            _dep(_DEP_FIN, "ERROR"),
        ]
    )
    assert result["critical_data_state"] == "UNKNOWN"
    assert result["critical_data_evaluation"] == "ERROR"
