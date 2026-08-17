"""HR1 v0.1 tests for the named Current Thesis Hard Risk authority."""

from __future__ import annotations

import ast
import copy
import inspect
from pathlib import Path

import pytest

from hard_risk_contract import hard_risk_evaluation_from_mapping
from hard_risk_runtime import (
    HardRiskRuntimeError,
    THESIS_PROJECTION_SCHEMA_VERSION,
    evaluate_hard_risk,
)


BACKEND = Path(__file__).resolve().parents[1]
MODULE_PATH = BACKEND / "hard_risk_runtime.py"
AS_OF = "2026-08-16T00:00:00Z"
CAMPAIGN_A = "campaign_0123456789abcdef0123456789abcdef"
CAMPAIGN_B = "campaign_fedcba9876543210fedcba9876543210"


def _campaign(
    *,
    campaign_id: str = CAMPAIGN_A,
    security_code: str = "600519",
    strategy: str = "SWING",
) -> dict:
    return {
        "campaign_id": campaign_id,
        "security_code": security_code,
        "strategy": strategy,
        "status": "ACTIVE",
    }


def _thesis_envelope(
    *,
    campaign_id: str = CAMPAIGN_A,
    security_code: str = "600519",
    strategy: str = "SWING",
    as_of: str = AS_OF,
    formal_status: str = "READY",
    effective_state: str = "DISPROVEN",
    terminal: bool | None = None,
    schema_version: str = THESIS_PROJECTION_SCHEMA_VERSION,
    refs: list[str] | None = None,
    confirmed_at: str | None = "2026-08-15T00:00:00Z",
    fact_time: str | None = None,
) -> dict:
    if terminal is None:
        terminal = effective_state in {"DISPROVEN", "INVALIDATED"}
    latest_delta = {
        "delta_state": effective_state,
        "confirmed_at": confirmed_at,
    }
    envelope = {
        "campaign_id": campaign_id,
        "security_code": security_code,
        "strategy": strategy,
        "as_of": as_of,
        "authority_refs": refs if refs is not None else ["formal_current_thesis:v0.1"],
        "projection": {
            "schema_version": schema_version,
            "campaign_id": campaign_id,
            "strategy": strategy,
            "formal_status": formal_status,
            "effective_state": effective_state,
            "terminal": terminal,
            "latest_delta": latest_delta,
            "deltas": [latest_delta],
        },
    }
    if fact_time is not None:
        envelope["fact_time"] = fact_time
    return envelope


def _evaluate(
    formal_thesis_projection: dict | None,
    *,
    campaign: dict | None = None,
    as_of: str = AS_OF,
):
    current_campaign = campaign if campaign is not None else _campaign()
    return evaluate_hard_risk(
        campaign_id=current_campaign["campaign_id"],
        campaign=current_campaign,
        as_of=as_of,
        formal_thesis_projection=formal_thesis_projection,
    )


def test_ready_terminal_disproven_is_confirmed_and_evaluated():
    result = _evaluate(_thesis_envelope(effective_state="DISPROVEN"))

    assert result.hard_risk_state == "CONFIRMED"
    assert result.hard_risk_evaluation == "EVALUATED"
    assert "THESIS_CORE_FACT_DISPROVEN" in result.reason_codes
    assert result.authority_refs == ("formal_current_thesis:v0.1",)
    assert hard_risk_evaluation_from_mapping(result.to_dict()) == result


def test_ready_terminal_invalidated_is_confirmed_and_evaluated():
    result = _evaluate(_thesis_envelope(effective_state="INVALIDATED"))

    assert result.hard_risk_state == "CONFIRMED"
    assert result.hard_risk_evaluation == "EVALUATED"
    assert "THESIS_CORE_FACT_INVALIDATED" in result.reason_codes


@pytest.mark.parametrize("state", ["STABLE", "STRENGTHENED", "WEAKENED"])
def test_ready_non_terminal_thesis_is_unknown_and_never_clear(state):
    result = _evaluate(_thesis_envelope(effective_state=state, terminal=False))

    assert result.hard_risk_state == "UNKNOWN"
    assert result.hard_risk_evaluation == "UNKNOWN"
    assert result.hard_risk_state != "CLEAR"
    assert "THESIS_HARD_RISK_NOT_PROVEN" in result.reason_codes


def test_ready_unknown_projection_is_unknown_and_never_clear():
    result = _evaluate(_thesis_envelope(effective_state="UNKNOWN", terminal=False))

    assert result.hard_risk_state == "UNKNOWN"
    assert result.hard_risk_evaluation == "UNKNOWN"
    assert result.hard_risk_state != "CLEAR"
    assert "THESIS_PROJECTION_UNKNOWN" in result.reason_codes


def test_not_ready_thesis_is_not_evaluated_and_never_clear():
    result = _evaluate(
        _thesis_envelope(
            formal_status="NOT_READY",
            effective_state="STABLE",
            terminal=False,
        )
    )

    assert result.hard_risk_state == "NOT_EVALUATED"
    assert result.hard_risk_evaluation == "NOT_EVALUATED"
    assert result.hard_risk_state != "CLEAR"
    assert "THESIS_NOT_READY" in result.reason_codes


def test_absent_authority_is_not_evaluated_and_never_clear():
    result = _evaluate(None)

    assert result.hard_risk_state == "NOT_EVALUATED"
    assert result.hard_risk_evaluation == "NOT_EVALUATED"
    assert result.hard_risk_state != "CLEAR"
    assert "THESIS_AUTHORITY_NOT_AVAILABLE" in result.reason_codes


def test_malformed_campaign_identity_fails_closed():
    with pytest.raises(HardRiskRuntimeError):
        _evaluate(None, campaign=_campaign(security_code="60051"))


def test_campaign_locator_must_match_backend_campaign():
    with pytest.raises(HardRiskRuntimeError, match="CAMPAIGN_LOCATOR_MISMATCH"):
        evaluate_hard_risk(
            campaign_id=CAMPAIGN_B,
            campaign=_campaign(campaign_id=CAMPAIGN_A),
            as_of=AS_OF,
            formal_thesis_projection=None,
        )


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("campaign_id", CAMPAIGN_B, "AUTHORITY_SCOPE_MISMATCH"),
        ("security_code", "000001", "AUTHORITY_SCOPE_MISMATCH"),
        ("strategy", "SHORT", "AUTHORITY_SCOPE_MISMATCH"),
        ("as_of", "2026-08-15T00:00:00Z", "AUTHORITY_AS_OF_MISMATCH"),
    ],
)
def test_authority_scope_mismatch_fails_closed(field, value, reason):
    envelope = _thesis_envelope(**{field: value})
    result = _evaluate(envelope)

    assert result.hard_risk_state == "NOT_EVALUATED"
    assert result.hard_risk_evaluation == "NOT_EVALUATED"
    assert result.hard_risk_state != "CLEAR"
    assert reason in result.reason_codes


def test_backend_campaign_security_and_strategy_are_authority():
    result = _evaluate(
        _thesis_envelope(security_code="000001", strategy="SHORT")
    )

    assert result.security_code == "600519"
    assert result.strategy == "SWING"
    assert result.hard_risk_state == "NOT_EVALUATED"
    assert "AUTHORITY_SCOPE_MISMATCH" in result.reason_codes


def test_sibling_campaign_projection_cannot_leak_into_target():
    result = _evaluate(_thesis_envelope(campaign_id=CAMPAIGN_B))

    assert result.campaign_id == CAMPAIGN_A
    assert result.hard_risk_state == "NOT_EVALUATED"
    assert result.hard_risk_state != "CONFIRMED"


def test_envelope_fact_time_lookahead_fails_closed():
    result = _evaluate(
        _thesis_envelope(fact_time="2026-08-17T00:00:00Z")
    )

    assert result.hard_risk_state == "NOT_EVALUATED"
    assert result.hard_risk_evaluation == "NOT_EVALUATED"
    assert "AUTHORITY_LOOKAHEAD" in result.reason_codes


def test_projection_fact_time_lookahead_fails_closed():
    result = _evaluate(
        _thesis_envelope(confirmed_at="2026-08-17T00:00:00Z")
    )

    assert result.hard_risk_state == "NOT_EVALUATED"
    assert result.hard_risk_evaluation == "NOT_EVALUATED"
    assert "AUTHORITY_LOOKAHEAD" in result.reason_codes


def test_terminal_false_with_terminal_fact_is_unknown_not_confirmed():
    result = _evaluate(
        _thesis_envelope(effective_state="DISPROVEN", terminal=False)
    )

    assert result.hard_risk_state == "UNKNOWN"
    assert result.hard_risk_evaluation == "UNKNOWN"
    assert result.hard_risk_state != "CONFIRMED"
    assert "THESIS_TERMINAL_FLAG_CONFLICT" in result.reason_codes


def test_terminal_true_with_non_terminal_fact_is_unknown_not_confirmed():
    result = _evaluate(
        _thesis_envelope(effective_state="STABLE", terminal=True)
    )

    assert result.hard_risk_state == "UNKNOWN"
    assert result.hard_risk_state != "CONFIRMED"


def test_bad_projection_schema_fails_closed():
    result = _evaluate(
        _thesis_envelope(schema_version="formal_current_thesis.projection.v9")
    )

    assert result.hard_risk_state == "UNKNOWN"
    assert result.hard_risk_evaluation == "UNKNOWN"
    assert result.hard_risk_state != "CLEAR"
    assert "THESIS_PROJECTION_INVALID" in result.reason_codes


def test_missing_provenance_fails_closed():
    result = _evaluate(_thesis_envelope(refs=[]))

    assert result.hard_risk_state == "UNKNOWN"
    assert result.hard_risk_evaluation == "UNKNOWN"
    assert result.hard_risk_state != "CLEAR"
    assert "AUTHORITY_PROVENANCE_MISSING" in result.reason_codes


def test_public_api_has_only_named_current_thesis_authority_input():
    parameters = inspect.signature(evaluate_hard_risk).parameters
    assert tuple(parameters) == (
        "campaign_id",
        "campaign",
        "as_of",
        "formal_thesis_projection",
    )
    assert "hard_risk_state" not in parameters
    assert "severity" not in parameters
    assert "positive_proof" not in parameters
    assert "coverage" not in parameters

    with pytest.raises(TypeError):
        evaluate_hard_risk(
            campaign_id=CAMPAIGN_A,
            campaign=_campaign(),
            as_of=AS_OF,
            formal_thesis_projection=None,
            hard_risk_state="CONFIRMED",
            severity="HIGH",
            positive_proof=True,
        )


@pytest.mark.parametrize("keyword", ["top_risk", "technical_score", "critical_data"])
def test_non_authority_context_has_no_runtime_input_path(keyword):
    with pytest.raises(TypeError):
        evaluate_hard_risk(
            campaign_id=CAMPAIGN_A,
            campaign=_campaign(),
            as_of=AS_OF,
            formal_thesis_projection=None,
            **{keyword: {"state": "CONFIRMED", "score": 999}},
        )


def test_no_supported_v01_input_can_produce_clear():
    inputs = [
        None,
        _thesis_envelope(effective_state="STABLE", terminal=False),
        _thesis_envelope(effective_state="STRENGTHENED", terminal=False),
        _thesis_envelope(effective_state="WEAKENED", terminal=False),
        _thesis_envelope(effective_state="UNKNOWN", terminal=False),
        _thesis_envelope(
            formal_status="NOT_READY",
            effective_state="STABLE",
            terminal=False,
        ),
        _thesis_envelope(effective_state="DISPROVEN", terminal=False),
        _thesis_envelope(schema_version="bad-schema"),
    ]
    assert all(_evaluate(item).hard_risk_state != "CLEAR" for item in inputs)


def test_result_never_emits_action_fields():
    payload = _evaluate(_thesis_envelope()).to_dict()

    assert "BUY" not in payload
    assert "SELL" not in payload
    assert "EXIT" not in payload
    assert "action" not in payload


def test_input_and_output_are_detached():
    envelope = _thesis_envelope(refs=["z-ref", "a-ref"])
    original = copy.deepcopy(envelope)
    result = _evaluate(envelope)

    assert envelope == original
    payload = result.to_dict()
    payload["authority_refs"].append("caller:mutation")
    assert result.authority_refs == ("a-ref", "z-ref")


def test_output_and_reason_codes_are_deterministic():
    first = _evaluate(_thesis_envelope(refs=["z-ref", "a-ref"]))
    second = _evaluate(_thesis_envelope(refs=["a-ref", "z-ref"]))

    assert first == second
    assert first.reason_codes == (
        "HARD_RISK_CONFIRMED",
        "THESIS_CORE_FACT_DISPROVEN",
    )
    assert first.authority_refs == ("a-ref", "z-ref")


def test_repeated_evaluation_is_deterministic():
    envelope = _thesis_envelope()
    expected = _evaluate(envelope)
    for _ in range(25):
        assert _evaluate(copy.deepcopy(envelope)) == expected


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
    assert call_names.isdisjoint(
        {"open", "connect", "request", "post", "now", "utcnow", "today", "time"}
    )
