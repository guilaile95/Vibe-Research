"""P0-HR1 production binding：Current Thesis authority → C core 全链证明。

不使用 fake Hard Risk evaluator：Current Thesis projection 经真实
formal_thesis_projection.project_current_thesis_from_normalized（pure-input
路径，域语义唯一来自 formal_thesis_projection_core）构造，随后走
decision_inbox_runtime_assembler 的 production Hard Risk port
（Current Thesis adapter → hard_risk_runtime.evaluate_hard_risk_mapping）。

覆盖工作单 §10 A-H：
A. READY + terminal + DISPROVEN  → CONFIRMED + EVALUATED
B. READY + terminal + INVALIDATED → CONFIRMED + EVALUATED
C. STABLE        → UNKNOWN（不绿）
D. STRENGTHENED  → UNKNOWN（不绿）
E. WEAKENED      → UNKNOWN（不绿）
F. missing/unbound projection（None）→ NOT_EVALUATED
G. NOT_READY projection → NOT_EVALUATED
H. v0.1 production CLEAR 不存在：全部有效输入永不产生 CLEAR
"""

from __future__ import annotations

import pytest

import decision_inbox_runtime_assembler as runtime
import formal_thesis_projection
from hard_risk_contract import HARD_RISK_STATES

CAMPAIGN_ID = "campaign_" + "0" * 32
THESIS_TS = "2026-08-01T00:00:00.000000+00:00"
AS_OF = "2026-08-16T00:00:00Z"

CAMPAIGN = {
    "campaign_id": CAMPAIGN_ID,
    "security_code": "600519",
    "strategy": "SWING",
    "status": "ACTIVE",
    "created_at": "2026-08-01T00:00:00.000000+00:00",
}

HORIZONS = {
    "SHORT": {"unit": "TRADING_DAY", "min": 1, "max": 10, "anchor": "FREEZE_AT"},
    "SWING": {"unit": "TRADING_DAY", "min": 5, "max": 45, "anchor": "FREEZE_AT"},
    "MEDIUM": {"unit": "TRADING_DAY", "min": 40, "max": 252, "anchor": "FREEZE_AT"},
}


def _snapshot(*, strategy="SWING") -> dict:
    return {
        "title": "t",
        "summary": "s",
        "core_claims": ["c1"],
        "catalysts": [],
        "risks": [],
        "invalidation_conditions": [],
        "free_notes": None,
        "strategy": strategy,
        "expected_horizon": HORIZONS[strategy],
        "status": "active",
        "current_revision": 2,
        "created_at": THESIS_TS,
        "updated_at": THESIS_TS,
    }


def _normalized_inputs(*, formal_state="frozen", deltas=None, strategy="SWING"):
    thesis_id = f"thesis_{'a' * 32}"
    binding = {
        "campaign_id": CAMPAIGN_ID,
        "thesis_id": thesis_id,
        "thesis_revision_at_bind": 2,
        "campaign_strategy_at_bind": strategy,
        "bound_at": THESIS_TS,
    }
    thesis = {
        "id": thesis_id,
        "formal_state": formal_state,
        "frozen_revision": 2 if formal_state == "frozen" else None,
        "strategy": strategy if formal_state == "frozen" else None,
        "expected_horizon": HORIZONS[strategy] if formal_state == "frozen" else None,
    }
    frozen_original = {
        "revision_number": 2,
        "snapshot": _snapshot(strategy=strategy),
    }
    delta_rows = []
    for sequence, state in deltas or ():
        delta_rows.append(
            {
                "delta_id": f"delta_{sequence:032x}",
                "thesis_id": thesis_id,
                "delta_sequence": sequence,
                "base_revision": 2,
                "delta_state": state,
                "reason": f"r{sequence}",
                "confirmed_at": THESIS_TS,
                "evidence_links": [],
            }
        )
    return binding, thesis, frozen_original, delta_rows


def _readonly_projection(*, formal_state="frozen", deltas=None, strategy="SWING"):
    """真实 I/O adapter 的 pure-input 路径 → 现有 Current Thesis product payload。"""
    binding, thesis, frozen_original, delta_rows = _normalized_inputs(
        formal_state=formal_state, deltas=deltas, strategy=strategy
    )
    return formal_thesis_projection.project_current_thesis_from_normalized(
        campaign_id=CAMPAIGN_ID,
        binding=binding,
        thesis=thesis,
        frozen_original=frozen_original,
        deltas=delta_rows,
    )


def _definition() -> dict:
    return {
        "campaign_id": CAMPAIGN_ID,
        "security_code": CAMPAIGN["security_code"],
        "strategy": CAMPAIGN["strategy"],
        "as_of": AS_OF,
    }


def _production_eval(projection):
    """assembler production Hard Risk port（adapter → C runtime，无 fake）。"""
    return runtime._production_hard_risk_evaluator(
        _definition(), CAMPAIGN, projection
    )


# ---------------------------------------------------------------------------
# A. Terminal DISPROVEN → CONFIRMED
# ---------------------------------------------------------------------------

def test_disproven_confirmed_with_provenance():
    projection = _readonly_projection(deltas=((1, "DISPROVEN"),))
    assert projection["formal_status"] == "READY"
    assert projection["effective_state"] == "DISPROVEN"

    result = _production_eval(projection)
    assert result["hard_risk_state"] == "CONFIRMED"
    assert result["hard_risk_evaluation"] == "EVALUATED"
    assert "HARD_RISK_CONFIRMED" in result["reason_codes"]
    assert "THESIS_CORE_FACT_DISPROVEN" in result["reason_codes"]
    assert result["authority_refs"] != []
    assert result["authority_refs"][0].startswith(
        f"current_thesis:{CAMPAIGN_ID}:thesis_"
    )


# ---------------------------------------------------------------------------
# B. Terminal INVALIDATED → CONFIRMED
# ---------------------------------------------------------------------------

def test_invalidated_confirmed_with_provenance():
    projection = _readonly_projection(deltas=((1, "INVALIDATED"),))
    result = _production_eval(projection)
    assert result["hard_risk_state"] == "CONFIRMED"
    assert result["hard_risk_evaluation"] == "EVALUATED"
    assert "THESIS_CORE_FACT_INVALIDATED" in result["reason_codes"]
    assert result["authority_refs"] != []


# ---------------------------------------------------------------------------
# C/D/E. 非 terminal 合法状态 → UNKNOWN（绝不 CLEAR）
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("delta_state", ["STABLE", "STRENGTHENED", "WEAKENED"])
def test_non_terminal_never_clear(delta_state):
    projection = _readonly_projection(deltas=((1, delta_state),))
    assert projection["effective_state"] == delta_state
    result = _production_eval(projection)
    assert result["hard_risk_state"] == "UNKNOWN"
    assert result["hard_risk_evaluation"] == "UNKNOWN"
    assert result["hard_risk_state"] != "CLEAR"
    assert result["reason_codes"][0] == "THESIS_HARD_RISK_NOT_PROVEN"


# ---------------------------------------------------------------------------
# F. missing / unbound → NOT_EVALUATED
# ---------------------------------------------------------------------------

def test_missing_projection_not_evaluated():
    result = _production_eval(None)
    assert result["hard_risk_state"] == "NOT_EVALUATED"
    assert result["hard_risk_evaluation"] == "NOT_EVALUATED"
    assert result["reason_codes"][0] == "THESIS_AUTHORITY_NOT_AVAILABLE"


# ---------------------------------------------------------------------------
# G. NOT_READY projection → NOT_EVALUATED
# ---------------------------------------------------------------------------

def test_not_ready_projection_not_evaluated():
    projection = _readonly_projection(formal_state="draft")
    assert projection["formal_status"] == "NOT_READY"
    result = _production_eval(projection)
    assert result["hard_risk_state"] == "NOT_EVALUATED"
    assert result["hard_risk_evaluation"] == "NOT_EVALUATED"
    assert result["reason_codes"][0] == "THESIS_NOT_READY"


# ---------------------------------------------------------------------------
# H. v0.1 production CLEAR 不存在
# ---------------------------------------------------------------------------

def test_production_v01_never_emits_clear():
    candidates = [
        _production_eval(None),
        _production_eval(_readonly_projection(deltas=((1, "DISPROVEN"),))),
        _production_eval(_readonly_projection(deltas=((1, "INVALIDATED"),))),
        _production_eval(_readonly_projection(deltas=((1, "STABLE"),))),
        _production_eval(_readonly_projection(formal_state="draft")),
    ]
    for result in candidates:
        assert result["hard_risk_state"] != "CLEAR"
        assert result["hard_risk_state"] in HARD_RISK_STATES
        # 合法 pair：CONFIRMED/UNKNOWN/NOT_EVALUATED 对应合法 evaluation
        assert result["hard_risk_state"] in (
            "CONFIRMED", "UNKNOWN", "NOT_EVALUATED",
        )


# ---------------------------------------------------------------------------
# 契约：结果必须通过 shared contract validation（O 三闸的第一闸）
# ---------------------------------------------------------------------------

def test_production_result_passes_shared_contract():
    from hard_risk_contract import hard_risk_evaluation_from_mapping

    for projection in [
        None,
        _readonly_projection(deltas=((1, "DISPROVEN"),)),
        _readonly_projection(deltas=((1, "STABLE"),)),
        _readonly_projection(formal_state="draft"),
    ]:
        raw = _production_eval(projection)
        normalized = hard_risk_evaluation_from_mapping(raw)
        assert normalized.hard_risk_state == raw["hard_risk_state"]
        assert normalized.as_of == AS_OF


# ---------------------------------------------------------------------------
# §7：malformed READY projection 经 production port 必须 fail closed
# ---------------------------------------------------------------------------

def test_malformed_ready_without_thesis_id_cannot_confirm():
    """effective_state=DISPROVEN 但缺 thesis_id → adapter error 传播，
    production port 绝不得返回 CONFIRMED。"""
    from hard_risk_current_thesis_adapter import CurrentThesisHardRiskAdapterError

    projection = _readonly_projection(deltas=((1, "DISPROVEN"),))
    assert projection["effective_state"] == "DISPROVEN"
    projection.pop("thesis_id")

    with pytest.raises(CurrentThesisHardRiskAdapterError):
        runtime._production_hard_risk_evaluator(
            _definition(), CAMPAIGN, projection
        )


def test_malformed_ready_binding_strategy_mismatch_fails_closed():
    from hard_risk_current_thesis_adapter import CurrentThesisHardRiskAdapterError

    projection = _readonly_projection(deltas=((1, "INVALIDATED"),))
    projection["binding"]["campaign_strategy_at_bind"] = "MEDIUM"
    with pytest.raises(CurrentThesisHardRiskAdapterError):
        runtime._production_hard_risk_evaluator(
            _definition(), CAMPAIGN, projection
        )


def test_assembler_level_malformed_projection_fails_closed_500():
    """assembler 层：production port 的 adapter error 必须转 DecisionInboxRuntimeError
    （500 fail closed），而不是产生 CONFIRMED/NOT_EVALUATED 结果。"""
    from hard_risk_current_thesis_adapter import CurrentThesisHardRiskAdapterError

    projection = _readonly_projection(deltas=((1, "DISPROVEN"),))
    projection.pop("thesis_id")

    def broken_evaluator(definition, campaign, current_thesis_projection):
        raise CurrentThesisHardRiskAdapterError("malformed")

    # 直接验证 assembler 的 _evaluate_hard_risk 对 evaluator 异常的整体 fail closed：
    # adapter error 属于 evaluator 异常 → DecisionInboxRuntimeError。
    from decision_inbox_runtime_assembler import (
        DecisionInboxRuntimeError,
        _evaluate_hard_risk,
    )

    class _Ports:
        hard_risk_evaluator = staticmethod(broken_evaluator)

    with pytest.raises(DecisionInboxRuntimeError):
        _evaluate_hard_risk(_Ports(), _definition(), CAMPAIGN, projection)
