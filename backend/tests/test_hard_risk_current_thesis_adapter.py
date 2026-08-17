"""P0-HR1 Current Thesis → Hard Risk envelope adapter 单测。

Adapter 只做 shape adaptation + transport/identity fail closed：
- 补齐 I/O adapter 为 #73 API 裁剪的 schema_version / strategy / terminal
- terminal 只来自 formal_thesis_projection_core 的 frozen TERMINAL_DELTA_STATES
- authority_refs 严格绑定实际 Thesis identity，禁止 synthetic provenance
- projection-present 时缺失/损坏 identity → CurrentThesisHardRiskAdapterError
  （fail closed，绝不 fallback 到 Campaign、绝不伪装 NOT_EVALUATED/CONFIRMED）
"""

from __future__ import annotations

import pytest

import hard_risk_current_thesis_adapter as adapter
import hard_risk_runtime as hr_runtime
from formal_thesis_projection_core import (
    SCHEMA_VERSION as CORE_SCHEMA_VERSION,
    TERMINAL_DELTA_STATES,
)

CAMPAIGN_ID = "campaign_" + "0" * 32
CAMPAIGN = {
    "campaign_id": CAMPAIGN_ID,
    "security_code": "600519",
    "strategy": "SWING",
    "status": "ACTIVE",
}
AS_OF = "2026-08-16T00:00:00Z"


def _projection(*, effective_state="STABLE", thesis_id="thesis_abc123", frozen_revision=2):
    return {
        "campaign_id": CAMPAIGN_ID,
        "thesis_id": thesis_id,
        "binding": {
            "thesis_revision_at_bind": 2,
            "campaign_strategy_at_bind": "SWING",
            "bound_at": "2026-08-01T00:00:00Z",
        },
        "frozen_revision": frozen_revision,
        "original_snapshot": {},
        "deltas": [],
        "effective_state": effective_state,
        "ready": True,
        "formal_status": "READY",
    }


def _envelope(**overrides):
    return adapter.build_current_thesis_envelope(
        campaign=CAMPAIGN, as_of=AS_OF, current_thesis_projection=_projection(**overrides)
    )


# ---------------------------------------------------------------------------
# shape adaptation（合法输入）
# ---------------------------------------------------------------------------

def test_none_projection_returns_none():
    assert adapter.build_current_thesis_envelope(
        campaign=CAMPAIGN, as_of=AS_OF, current_thesis_projection=None
    ) is None


def test_envelope_scope_fields_from_campaign_and_as_of():
    envelope = _envelope()
    assert envelope["campaign_id"] == CAMPAIGN_ID
    assert envelope["security_code"] == "600519"
    assert envelope["strategy"] == "SWING"
    assert envelope["as_of"] == AS_OF


def test_projection_gets_core_schema_version_and_strategy():
    envelope = _envelope()
    projection = envelope["projection"]
    assert projection["schema_version"] == CORE_SCHEMA_VERSION
    assert projection["schema_version"] == "formal_current_thesis.projection.v0.1"
    assert projection["strategy"] == "SWING"
    assert projection["effective_state"] == "STABLE"
    assert projection["formal_status"] == "READY"


@pytest.mark.parametrize(
    ("effective_state", "expected_terminal"),
    [
        ("STABLE", False),
        ("STRENGTHENED", False),
        ("WEAKENED", False),
        ("DISPROVEN", True),
        ("INVALIDATED", True),
        ("UNKNOWN", False),
    ],
)
def test_terminal_uses_core_definition(effective_state, expected_terminal):
    assert ("DISPROVEN", "INVALIDATED") == TERMINAL_DELTA_STATES
    envelope = _envelope(effective_state=effective_state)
    assert envelope["projection"]["terminal"] is expected_terminal


def test_authority_refs_bind_thesis_identity():
    envelope = _envelope()
    assert envelope["authority_refs"] == [
        f"current_thesis:{CAMPAIGN_ID}:thesis_abc123:v2"
    ]


def test_authority_refs_deterministic():
    first = _envelope()
    second = _envelope()
    assert first["authority_refs"] == second["authority_refs"]


def test_not_ready_refs_use_real_thesis_id_without_revision():
    projection = _projection()
    projection["formal_status"] = "NOT_READY"
    projection["ready"] = False
    envelope = adapter.build_current_thesis_envelope(
        campaign=CAMPAIGN, as_of=AS_OF, current_thesis_projection=projection
    )
    assert envelope["authority_refs"] == [
        f"current_thesis:{CAMPAIGN_ID}:thesis_abc123"
    ]


def test_adapter_never_injects_caller_conclusion():
    """输入 / 输出形状不含 hard_risk_state / severity / positive_proof 等。"""
    envelope = _envelope(effective_state="DISPROVEN")
    for forbidden in (
        "hard_risk_state",
        "hard_risk_evaluation",
        "severity",
        "positive_proof",
        "coverage",
        "risk_type",
    ):
        assert forbidden not in envelope
        assert forbidden not in envelope["projection"]


# ---------------------------------------------------------------------------
# fail closed：projection-present 时缺失/损坏 identity → adapter error
# ---------------------------------------------------------------------------

def test_ready_missing_thesis_id_fails_closed():
    """READY + missing thesis_id → adapter error，绝不产生可 CONFIRMED 的 envelope。"""
    projection = _projection(effective_state="DISPROVEN")
    projection.pop("thesis_id")
    with pytest.raises(adapter.CurrentThesisHardRiskAdapterError):
        adapter.build_current_thesis_envelope(
            campaign=CAMPAIGN, as_of=AS_OF, current_thesis_projection=projection
        )


def test_missing_projection_campaign_id_no_fallback():
    """缺失 projection campaign_id → adapter error，禁止 fallback 到 Campaign id。"""
    projection = _projection()
    projection.pop("campaign_id")
    with pytest.raises(adapter.CurrentThesisHardRiskAdapterError):
        adapter.build_current_thesis_envelope(
            campaign=CAMPAIGN, as_of=AS_OF, current_thesis_projection=projection
        )


def test_projection_campaign_id_mismatch_fails_closed():
    projection = _projection()
    projection["campaign_id"] = "campaign_" + "f" * 32
    with pytest.raises(adapter.CurrentThesisHardRiskAdapterError):
        adapter.build_current_thesis_envelope(
            campaign=CAMPAIGN, as_of=AS_OF, current_thesis_projection=projection
        )


def test_binding_strategy_mismatch_fails_closed():
    projection = _projection()
    projection["binding"]["campaign_strategy_at_bind"] = "MEDIUM"
    with pytest.raises(adapter.CurrentThesisHardRiskAdapterError):
        adapter.build_current_thesis_envelope(
            campaign=CAMPAIGN, as_of=AS_OF, current_thesis_projection=projection
        )


def test_binding_missing_fails_closed():
    projection = _projection()
    projection.pop("binding")
    with pytest.raises(adapter.CurrentThesisHardRiskAdapterError):
        adapter.build_current_thesis_envelope(
            campaign=CAMPAIGN, as_of=AS_OF, current_thesis_projection=projection
        )


@pytest.mark.parametrize("frozen_revision", [None, 0, -1, True, "2", 2.0])
def test_ready_invalid_frozen_revision_fails_closed(frozen_revision):
    projection = _projection()
    projection["frozen_revision"] = frozen_revision
    with pytest.raises(adapter.CurrentThesisHardRiskAdapterError):
        adapter.build_current_thesis_envelope(
            campaign=CAMPAIGN, as_of=AS_OF, current_thesis_projection=projection
        )


def test_readiness_transport_conflict_fails_closed():
    """formal_status=READY 但 ready=false → transport 不一致 → adapter error。"""
    projection = _projection()
    projection["ready"] = False
    with pytest.raises(adapter.CurrentThesisHardRiskAdapterError):
        adapter.build_current_thesis_envelope(
            campaign=CAMPAIGN, as_of=AS_OF, current_thesis_projection=projection
        )


def test_ready_true_but_not_ready_status_fails_closed():
    projection = _projection()
    projection["formal_status"] = "NOT_READY"
    with pytest.raises(adapter.CurrentThesisHardRiskAdapterError):
        adapter.build_current_thesis_envelope(
            campaign=CAMPAIGN, as_of=AS_OF, current_thesis_projection=projection
        )


# ---------------------------------------------------------------------------
# canonical 输入 → C runtime 语义保持（adapter → runtime 全链）
# ---------------------------------------------------------------------------

def _runtime_result(projection):
    envelope = adapter.build_current_thesis_envelope(
        campaign=CAMPAIGN, as_of=AS_OF, current_thesis_projection=projection
    )
    return hr_runtime.evaluate_hard_risk_mapping(
        campaign_id=CAMPAIGN_ID,
        campaign=CAMPAIGN,
        as_of=AS_OF,
        formal_thesis_projection=envelope,
    )


def test_canonical_ready_disproven_still_confirmed():
    result = _runtime_result(_projection(effective_state="DISPROVEN"))
    assert result["hard_risk_state"] == "CONFIRMED"
    assert result["hard_risk_evaluation"] == "EVALUATED"
    assert "THESIS_CORE_FACT_DISPROVEN" in result["reason_codes"]
    assert result["authority_refs"][0].startswith(
        f"current_thesis:{CAMPAIGN_ID}:thesis_abc123:v"
    )


def test_canonical_ready_invalidated_still_confirmed():
    result = _runtime_result(_projection(effective_state="INVALIDATED"))
    assert result["hard_risk_state"] == "CONFIRMED"
    assert "THESIS_CORE_FACT_INVALIDATED" in result["reason_codes"]


def test_canonical_stable_still_unknown():
    result = _runtime_result(_projection(effective_state="STABLE"))
    assert result["hard_risk_state"] == "UNKNOWN"
    assert result["hard_risk_state"] != "CLEAR"


def test_none_projection_still_legitimate_not_evaluated():
    result = hr_runtime.evaluate_hard_risk_mapping(
        campaign_id=CAMPAIGN_ID,
        campaign=CAMPAIGN,
        as_of=AS_OF,
        formal_thesis_projection=None,
    )
    assert result["hard_risk_state"] == "NOT_EVALUATED"
    assert result["reason_codes"][0] == "THESIS_AUTHORITY_NOT_AVAILABLE"
