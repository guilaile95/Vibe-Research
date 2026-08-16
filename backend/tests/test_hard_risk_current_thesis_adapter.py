"""P0-HR1 Current Thesis → Hard Risk envelope adapter 单测。

Adapter 只做 shape adaptation：
- 补齐 I/O adapter 为 #73 API 裁剪的 schema_version / strategy / terminal
- terminal 只来自 formal_thesis_projection_core 的 frozen TERMINAL_DELTA_STATES
- authority_refs 是绑定实际 Thesis identity 的确定性 provenance
- 绝不接受 / 输出 caller conclusion（state / severity / positive_proof）
"""

from __future__ import annotations

import pytest

import hard_risk_current_thesis_adapter as adapter
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


def test_none_projection_returns_none():
    assert adapter.build_current_thesis_envelope(
        campaign=CAMPAIGN, as_of=AS_OF, current_thesis_projection=None
    ) is None


def test_envelope_scope_fields_from_campaign_and_as_of():
    envelope = adapter.build_current_thesis_envelope(
        campaign=CAMPAIGN, as_of=AS_OF, current_thesis_projection=_projection()
    )
    assert envelope["campaign_id"] == CAMPAIGN_ID
    assert envelope["security_code"] == "600519"
    assert envelope["strategy"] == "SWING"
    assert envelope["as_of"] == AS_OF


def test_projection_gets_core_schema_version_and_strategy():
    envelope = adapter.build_current_thesis_envelope(
        campaign=CAMPAIGN, as_of=AS_OF, current_thesis_projection=_projection()
    )
    projection = envelope["projection"]
    assert projection["schema_version"] == CORE_SCHEMA_VERSION
    assert projection["schema_version"] == "formal_current_thesis.projection.v0.1"
    assert projection["strategy"] == "SWING"
    # 原 projection 字段全部保留（shape adaptation，不裁剪）
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
    envelope = adapter.build_current_thesis_envelope(
        campaign=CAMPAIGN,
        as_of=AS_OF,
        current_thesis_projection=_projection(effective_state=effective_state),
    )
    assert envelope["projection"]["terminal"] is expected_terminal


def test_authority_refs_bind_thesis_identity():
    envelope = adapter.build_current_thesis_envelope(
        campaign=CAMPAIGN, as_of=AS_OF, current_thesis_projection=_projection()
    )
    assert envelope["authority_refs"] == [
        f"current_thesis:{CAMPAIGN_ID}:thesis_abc123:v2"
    ]


def test_authority_refs_deterministic():
    projection = _projection()
    first = adapter.build_current_thesis_envelope(
        campaign=CAMPAIGN, as_of=AS_OF, current_thesis_projection=projection
    )
    second = adapter.build_current_thesis_envelope(
        campaign=CAMPAIGN, as_of=AS_OF, current_thesis_projection=projection
    )
    assert first["authority_refs"] == second["authority_refs"]


def test_authority_refs_unbound_fallback_when_no_thesis_id():
    projection = _projection()
    projection.pop("thesis_id")
    envelope = adapter.build_current_thesis_envelope(
        campaign=CAMPAIGN, as_of=AS_OF, current_thesis_projection=projection
    )
    assert envelope["authority_refs"] == [f"current_thesis:{CAMPAIGN_ID}:unbound"]


def test_adapter_never_injects_caller_conclusion():
    """输入 / 输出形状不含 hard_risk_state / severity / positive_proof 等。

    adapter 只把 projection 数据传给 C 的 envelope；任何 caller conclusion
    都无法通过 adapter 影响最终 state（state 只由 hard_risk_runtime 决定）。
    """
    projection = _projection(effective_state="DISPROVEN")
    envelope = adapter.build_current_thesis_envelope(
        campaign=CAMPAIGN, as_of=AS_OF, current_thesis_projection=projection
    )
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
