"""P0-DDA1 Critical Data Dependency Policy Core — pure-domain suite.

No I/O. No health/thesis/CCD/RA/DI authority imports.
"""

from __future__ import annotations

import ast
import copy
import inspect
from pathlib import Path

import pytest

import critical_data_dependency_policy as dda
from critical_data_dependency_policy import (
    CAP_CONTEXT_MARKET_SECTOR,
    CAP_SECURITY_DISCLOSURES,
    CAP_SECURITY_FINANCIALS,
    CAP_SECURITY_PRICE_REFERENCE,
    DEPENDENCY_SET_STATES,
    MEDIUM_REQUIRED,
    POLICY_AUTHORITY_REF_V01,
    POLICY_VERSION_V01,
    REASON_DEPENDENCY_POLICY_RESOLVED,
    REASON_POLICY_INTEGRITY_ERROR,
    REASON_POLICY_VERSION_NOT_AVAILABLE,
    SCHEMA_VERSION,
    SHORT_REQUIRED,
    SWING_REQUIRED,
    DependencyPolicyValidationError,
    resolve_strategy_dependencies,
    _adversarial_resolve_with_registry,
)

BACKEND = Path(__file__).resolve().parents[1]
MODULE_PATH = BACKEND / "critical_data_dependency_policy.py"

_CAMPAIGN_A = "campaign_" + ("a" * 32)
_CAMPAIGN_B = "campaign_" + ("b" * 32)
_AS_OF = "2026-08-12T00:00:00.000000Z"


def _base(**overrides):
    payload = {
        "security_code": "600519",
        "strategy": "SWING",
        "campaign_id": _CAMPAIGN_A,
        "as_of": _AS_OF,
        "policy_version": POLICY_VERSION_V01,
    }
    payload.update(overrides)
    return payload


def _resolve(**overrides):
    return resolve_strategy_dependencies(**_base(**overrides))


# ---------------------------------------------------------------------------
# Exact required sets
# ---------------------------------------------------------------------------


def test_short_exact_required_set():
    result = _resolve(strategy="SHORT")
    assert result["dependency_set_state"] == "RESOLVED"
    assert result["required_dependency_ids"] == list(SHORT_REQUIRED)
    assert result["required_dependency_ids"] == [
        CAP_SECURITY_PRICE_REFERENCE,
        CAP_CONTEXT_MARKET_SECTOR,
        CAP_SECURITY_DISCLOSURES,
    ]
    assert result["dependency_set_authority_refs"] == [POLICY_AUTHORITY_REF_V01]
    assert result["reason_codes"] == [REASON_DEPENDENCY_POLICY_RESOLVED]
    assert result["schema_version"] == SCHEMA_VERSION
    assert result["policy_version"] == POLICY_VERSION_V01
    assert result["as_of"] == _AS_OF


def test_swing_exact_required_set():
    result = _resolve(strategy="SWING")
    assert result["dependency_set_state"] == "RESOLVED"
    assert result["required_dependency_ids"] == list(SWING_REQUIRED)
    assert CAP_SECURITY_FINANCIALS not in result["required_dependency_ids"]


def test_medium_exact_required_set():
    result = _resolve(strategy="MEDIUM")
    assert result["dependency_set_state"] == "RESOLVED"
    assert result["required_dependency_ids"] == list(MEDIUM_REQUIRED)
    assert result["required_dependency_ids"] == [
        CAP_SECURITY_PRICE_REFERENCE,
        CAP_SECURITY_DISCLOSURES,
        CAP_SECURITY_FINANCIALS,
    ]
    assert CAP_CONTEXT_MARKET_SECTOR not in result["required_dependency_ids"]


def test_deterministic_ordering_not_alphabetical():
    # Policy order is the contract; financials would sort before price alphabetically.
    medium = _resolve(strategy="MEDIUM")["required_dependency_ids"]
    assert medium[0] == CAP_SECURITY_PRICE_REFERENCE
    assert medium[1] == CAP_SECURITY_DISCLOSURES
    assert medium[2] == CAP_SECURITY_FINANCIALS
    assert medium != sorted(medium)


# ---------------------------------------------------------------------------
# Policy version semantics
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value", [None, "", "   ", "\t"])
def test_missing_or_empty_policy_version_validation_error(value):
    with pytest.raises(DependencyPolicyValidationError):
        _resolve(policy_version=value)


def test_unknown_policy_version_not_evaluated():
    result = _resolve(policy_version="dda.strategy_dependency.v9.9")
    assert result["dependency_set_state"] == "NOT_EVALUATED"
    assert result["required_dependency_ids"] == []
    assert result["dependency_set_authority_refs"] == []
    assert result["reason_codes"] == [REASON_POLICY_VERSION_NOT_AVAILABLE]
    assert result["policy_version"] == "dda.strategy_dependency.v9.9"
    assert "UNKNOWN" not in result["dependency_set_state"]


def test_unknown_not_used_by_v01_success_path():
    result = _resolve()
    assert result["dependency_set_state"] in DEPENDENCY_SET_STATES
    assert result["dependency_set_state"] != "UNKNOWN"
    assert "UNKNOWN" not in DEPENDENCY_SET_STATES


# ---------------------------------------------------------------------------
# Integrity adversarial (test seam only)
# ---------------------------------------------------------------------------


def test_known_policy_missing_strategy_entry_error():
    broken = {
        POLICY_VERSION_V01: {
            "SHORT": SHORT_REQUIRED,
            "SWING": SWING_REQUIRED,
            # MEDIUM missing
        }
    }
    result = _adversarial_resolve_with_registry(
        security_code="600519",
        strategy="MEDIUM",
        campaign_id=_CAMPAIGN_A,
        as_of=_AS_OF,
        policy_version=POLICY_VERSION_V01,
        registry=broken,
        authority_ref_by_version={POLICY_VERSION_V01: POLICY_AUTHORITY_REF_V01},
    )
    assert result["dependency_set_state"] == "ERROR"
    assert result["required_dependency_ids"] == []
    assert result["dependency_set_authority_refs"] == [POLICY_AUTHORITY_REF_V01]
    assert result["reason_codes"] == [REASON_POLICY_INTEGRITY_ERROR]


def test_known_policy_duplicate_dependency_error():
    broken = {
        POLICY_VERSION_V01: {
            "SHORT": (
                CAP_SECURITY_PRICE_REFERENCE,
                CAP_SECURITY_PRICE_REFERENCE,
                CAP_SECURITY_DISCLOSURES,
            ),
            "SWING": SWING_REQUIRED,
            "MEDIUM": MEDIUM_REQUIRED,
        }
    }
    result = _adversarial_resolve_with_registry(
        security_code="600519",
        strategy="SHORT",
        campaign_id=_CAMPAIGN_A,
        as_of=_AS_OF,
        policy_version=POLICY_VERSION_V01,
        registry=broken,
        authority_ref_by_version={POLICY_VERSION_V01: POLICY_AUTHORITY_REF_V01},
    )
    assert result["dependency_set_state"] == "ERROR"
    assert result["required_dependency_ids"] == []
    assert result["reason_codes"] == [REASON_POLICY_INTEGRITY_ERROR]


def test_known_policy_empty_dependency_set_error():
    broken = {
        POLICY_VERSION_V01: {
            "SHORT": (),
            "SWING": SWING_REQUIRED,
            "MEDIUM": MEDIUM_REQUIRED,
        }
    }
    result = _adversarial_resolve_with_registry(
        security_code="600519",
        strategy="SHORT",
        campaign_id=_CAMPAIGN_A,
        as_of=_AS_OF,
        policy_version=POLICY_VERSION_V01,
        registry=broken,
        authority_ref_by_version={POLICY_VERSION_V01: POLICY_AUTHORITY_REF_V01},
    )
    assert result["dependency_set_state"] == "ERROR"
    assert result["required_dependency_ids"] == []
    assert result["reason_codes"] == [REASON_POLICY_INTEGRITY_ERROR]


def test_production_public_api_has_no_registry_injection():
    sig = inspect.signature(resolve_strategy_dependencies)
    assert "registry" not in sig.parameters
    assert "authority_refs" not in sig.parameters
    assert "dependency_set_authority_refs" not in sig.parameters


# ---------------------------------------------------------------------------
# Identity validation
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
    ],
)
def test_invalid_identity_fields_fail_closed(field, value):
    with pytest.raises(DependencyPolicyValidationError):
        _resolve(**{field: value})


# ---------------------------------------------------------------------------
# Provenance / immutability / isolation
# ---------------------------------------------------------------------------


def test_caller_cannot_inject_authority_refs():
    with pytest.raises(TypeError):
        resolve_strategy_dependencies(
            security_code="600519",
            strategy="SWING",
            campaign_id=_CAMPAIGN_A,
            as_of=_AS_OF,
            policy_version=POLICY_VERSION_V01,
            dependency_set_authority_refs=["caller:forged"],
        )


def test_authority_refs_generated_internally_only():
    result = _resolve()
    assert result["dependency_set_authority_refs"] == [POLICY_AUTHORITY_REF_V01]
    assert result["dependency_set_authority_refs"][0].startswith(
        "dda:strategy_dependency_policy:"
    )


def test_same_input_identical_output():
    a = _resolve()
    b = _resolve()
    assert a == b


def test_output_detached():
    out = _resolve()
    out["required_dependency_ids"].append("mutated")
    out["dependency_set_authority_refs"].append("mutated")
    out["reason_codes"].append("MUTATED")
    again = _resolve()
    assert "mutated" not in again["required_dependency_ids"]
    assert "mutated" not in again["dependency_set_authority_refs"]
    assert "MUTATED" not in again["reason_codes"]


def test_campaign_isolation_same_security_different_strategy():
    swing = _resolve(strategy="SWING", campaign_id=_CAMPAIGN_A)
    medium = _resolve(strategy="MEDIUM", campaign_id=_CAMPAIGN_B)
    assert swing["security_code"] == medium["security_code"] == "600519"
    assert swing["required_dependency_ids"] != medium["required_dependency_ids"]
    assert CAP_CONTEXT_MARKET_SECTOR in swing["required_dependency_ids"]
    assert CAP_SECURITY_FINANCIALS in medium["required_dependency_ids"]


def test_as_of_does_not_select_policy():
    a = _resolve(as_of="2026-08-12T00:00:00Z")
    b = _resolve(as_of="2020-01-01T00:00:00Z")
    assert a["required_dependency_ids"] == b["required_dependency_ids"]
    assert a["policy_version"] == b["policy_version"] == POLICY_VERSION_V01
    assert a["as_of"] != b["as_of"]


# ---------------------------------------------------------------------------
# Pure domain / no forbidden imports
# ---------------------------------------------------------------------------


def test_no_io_or_forbidden_authority_imports():
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
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
        "data_health_service",
        "fact_lake_health",
        "fact_lake_store",
        "campaign_store",
        "campaign_service",
        "formal_thesis_projection",
        "frozen_decision_service",
        "campaign_critical_data_projection",
        "decision_assurance_projection",
        "decision_inbox_projection",
        "portfolio_advice_service",
        "decision_cockpit_service",
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                assert root not in forbidden
                assert alias.name not in forbidden
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            root = node.module.split(".")[0]
            assert root not in forbidden
            assert node.module not in forbidden


def test_no_wall_clock_usage():
    source = MODULE_PATH.read_text(encoding="utf-8")
    assert "datetime.now" not in source
    assert "datetime.utcnow" not in source
    assert "time.time" not in source
    sig = inspect.signature(resolve_strategy_dependencies)
    assert "now" not in sig.parameters
    assert "clock" not in sig.parameters


def test_no_string_identity_comparisons_for_enums():
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


def test_dynamic_equal_enum_strings():
    short = "".join(["SH", "ORT"])
    version = "".join(["dda.strategy_dependency.", "v0.1"])
    assert short == "SHORT"
    assert version == POLICY_VERSION_V01
    result = _resolve(strategy=short, policy_version=version)
    assert result["dependency_set_state"] == "RESOLVED"
    assert result["required_dependency_ids"] == list(SHORT_REQUIRED)


def test_ccd1_compatible_not_evaluated_and_error_have_empty_required_ids():
    unknown = _resolve(policy_version="dda.strategy_dependency.v9.9")
    assert unknown["dependency_set_state"] == "NOT_EVALUATED"
    assert unknown["required_dependency_ids"] == []
    assert unknown["dependency_set_authority_refs"] == []

    broken = {
        POLICY_VERSION_V01: {
            "SHORT": SHORT_REQUIRED,
            "SWING": SWING_REQUIRED,
            # missing MEDIUM
        }
    }
    err = _adversarial_resolve_with_registry(
        security_code="600519",
        strategy="MEDIUM",
        campaign_id=_CAMPAIGN_A,
        as_of=_AS_OF,
        policy_version=POLICY_VERSION_V01,
        registry=broken,
        authority_ref_by_version={POLICY_VERSION_V01: POLICY_AUTHORITY_REF_V01},
    )
    assert err["dependency_set_state"] == "ERROR"
    assert err["required_dependency_ids"] == []


def test_input_zero_mutation():
    payload = _base()
    before = copy.deepcopy(payload)
    _ = resolve_strategy_dependencies(**payload)
    assert payload == before
