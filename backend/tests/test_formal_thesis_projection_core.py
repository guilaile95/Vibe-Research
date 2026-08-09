"""Formal Current Thesis Pure Projection Core v0.1 专项测试。

覆盖工作单 A~T 全部用例 + 输入不可变性 + 纯模块约束（零 filesystem side
effect、不 import store / FastAPI / AI 模块）+ R1 deep-output-isolation
（输出中所有 mutable nested objects 与输入解除引用共享）。全部为纯函数调用，
不联网、不落库、不写用户数据。
"""
from __future__ import annotations

import copy
import inspect
import os
import subprocess
import sys

import pytest

import formal_thesis_projection_core as ftp
from formal_thesis_projection_core import (
    ProjectionIntegrityError,
    ProjectionStrategyConflictError,
    project_current_thesis,
)

CAMPAIGN_ID = "campaign-001"
THESIS_ID = "a" * 32  # uuid4().hex 形状
FROZEN_REVISION = 2
STRATEGY = "SWING"
HORIZON = {"unit": "TRADING_DAY", "min": 5, "max": 45, "anchor": "FREEZE_AT"}
BOUND_AT = "2026-08-01T02:00:00+00:00"
CONFIRMED_AT = "2026-08-05T02:00:00+00:00"


def _binding(
    *,
    campaign_id: str = CAMPAIGN_ID,
    thesis_id: str = THESIS_ID,
    revision_at_bind: int = 1,
    strategy: str = STRATEGY,
    bound_at: str = BOUND_AT,
) -> dict:
    return {
        "campaign_id": campaign_id,
        "thesis_id": thesis_id,
        "thesis_revision_at_bind": revision_at_bind,
        "campaign_strategy_at_bind": strategy,
        "bound_at": bound_at,
    }


def _thesis(
    *,
    thesis_id: str = THESIS_ID,
    formal_state: str = "FROZEN",
    status: str = "active",
    strategy: str = STRATEGY,
    expected_horizon: dict | None = None,
    frozen_revision: int = FROZEN_REVISION,
) -> dict:
    if expected_horizon is None:
        expected_horizon = dict(HORIZON)
    return {
        "id": thesis_id,
        "formal_state": formal_state,
        "status": status,
        "strategy": strategy,
        "expected_horizon": expected_horizon,
        "frozen_revision": frozen_revision,
        "current_revision": frozen_revision,
        "confirmed_at": CONFIRMED_AT,
        "frozen_at": "2026-08-03T02:00:00+00:00",
        "archived_at": None,
    }


def _frozen_original(
    *, revision: int = FROZEN_REVISION, snapshot: dict | None = None
) -> dict:
    if snapshot is None:
        snapshot = {
            "title": "frozen original snapshot",
            "revision_number": revision,
            "core_claims": ["claim-1"],
        }
    return {"revision_number": revision, "snapshot": snapshot}


def _delta(
    sequence: int,
    state: str,
    *,
    delta_id: str | None = None,
    thesis_id: str = THESIS_ID,
    base_revision: int = FROZEN_REVISION,
    reason: str = "confirmed canonical delta",
) -> dict:
    return {
        "delta_id": delta_id or f"delta-{sequence:03d}",
        "thesis_id": thesis_id,
        "delta_sequence": sequence,
        "base_revision": base_revision,
        "delta_state": state,
        "reason": reason,
        "confirmed_at": CONFIRMED_AT,
        "evidence_snapshots": [{"evidence_id": f"ev-{sequence:03d}"}],
    }


def _inputs(
    *,
    binding: dict | None = None,
    thesis: dict | None = None,
    frozen_original: dict | None = None,
    deltas: list | None = None,
) -> dict:
    return {
        "campaign_id": CAMPAIGN_ID,
        "binding": binding if binding is not None else _binding(),
        "thesis": thesis if thesis is not None else _thesis(),
        "frozen_original": (
            frozen_original if frozen_original is not None else _frozen_original()
        ),
        "deltas": deltas if deltas is not None else [],
    }


# ---------------------------------------------------------------------------
# A. not frozen → NOT_READY / NOT_FROZEN
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("formal_state", [None, "DRAFT", "CONFIRMED", "legacy"])
def test_a_not_frozen_returns_not_ready(formal_state):
    thesis = _thesis(formal_state=formal_state)
    result = project_current_thesis(**_inputs(thesis=thesis))
    assert result == {
        "campaign_id": CAMPAIGN_ID,
        "thesis_id": THESIS_ID,
        "formal_status": "NOT_READY",
        "reason": "NOT_FROZEN",
    }


# ---------------------------------------------------------------------------
# B. frozen + no delta → STABLE
# ---------------------------------------------------------------------------
def test_b_frozen_no_delta_stable():
    result = project_current_thesis(**_inputs())
    assert result["formal_status"] == "READY"
    assert result["effective_state"] == "STABLE"
    assert result["terminal"] is False
    assert result["latest_delta"] is None
    assert result["deltas"] == []
    assert result["original"]["revision"] == FROZEN_REVISION


# ---------------------------------------------------------------------------
# C/D/E/F. latest-wins 规则
# ---------------------------------------------------------------------------
def test_c_single_strengthened():
    result = project_current_thesis(**_inputs(deltas=[_delta(1, "STRENGTHENED")]))
    assert result["effective_state"] == "STRENGTHENED"
    assert result["terminal"] is False
    assert result["latest_delta"]["delta_sequence"] == 1


def test_d_strengthened_then_weakened():
    result = project_current_thesis(
        **_inputs(
            deltas=[_delta(1, "STRENGTHENED"), _delta(2, "WEAKENED")],
        )
    )
    assert result["effective_state"] == "WEAKENED"
    assert result["latest_delta"]["delta_sequence"] == 2


def test_e_weakened_then_unknown():
    result = project_current_thesis(
        **_inputs(deltas=[_delta(1, "WEAKENED"), _delta(2, "UNKNOWN")]),
    )
    assert result["effective_state"] == "UNKNOWN"
    assert result["terminal"] is False


def test_f_unknown_then_strengthened():
    result = project_current_thesis(
        **_inputs(deltas=[_delta(1, "UNKNOWN"), _delta(2, "STRENGTHENED")]),
    )
    assert result["effective_state"] == "STRENGTHENED"


# ---------------------------------------------------------------------------
# G/H. terminal
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("state", ["DISPROVEN", "INVALIDATED"])
def test_terminal_state(state):
    result = project_current_thesis(**_inputs(deltas=[_delta(1, state)]))
    assert result["effective_state"] == state
    assert result["terminal"] is True
    assert result["latest_delta"]["delta_state"] == state


# ---------------------------------------------------------------------------
# I. terminal 之后存在 delta → FAIL CLOSED
# ---------------------------------------------------------------------------
def test_i_post_terminal_delta_fails_closed():
    with pytest.raises(ProjectionIntegrityError):
        project_current_thesis(
            **_inputs(deltas=[_delta(1, "DISPROVEN"), _delta(2, "STRENGTHENED")]),
        )


def test_i2_terminal_not_last_nonterminal_after_fails_closed():
    with pytest.raises(ProjectionIntegrityError):
        project_current_thesis(
            **_inputs(
                deltas=[_delta(1, "STRENGTHENED"), _delta(2, "DISPROVEN"), _delta(3, "STABLE")],
            ),
        )


def test_i3_two_terminals_fails_closed():
    with pytest.raises(ProjectionIntegrityError):
        project_current_thesis(
            **_inputs(deltas=[_delta(1, "DISPROVEN"), _delta(2, "INVALIDATED")]),
        )


# ---------------------------------------------------------------------------
# J/K. sequence 完整性
# ---------------------------------------------------------------------------
def test_j_duplicate_sequence_fails_closed():
    with pytest.raises(ProjectionIntegrityError):
        project_current_thesis(
            **_inputs(deltas=[_delta(1, "STRENGTHENED"), _delta(1, "WEAKENED")]),
        )


def test_k_gap_sequence_fails_closed():
    with pytest.raises(ProjectionIntegrityError):
        project_current_thesis(
            **_inputs(deltas=[_delta(1, "STRENGTHENED"), _delta(3, "WEAKENED")]),
        )


def test_k2_sequence_not_starting_at_one_fails_closed():
    with pytest.raises(ProjectionIntegrityError):
        project_current_thesis(**_inputs(deltas=[_delta(2, "STRENGTHENED")]))


def test_k3_zero_sequence_fails_closed():
    with pytest.raises(ProjectionIntegrityError):
        project_current_thesis(**_inputs(deltas=[_delta(0, "STRENGTHENED")]))


# ---------------------------------------------------------------------------
# L. base_revision != frozen_revision → FAIL CLOSED
# ---------------------------------------------------------------------------
def test_l_base_revision_mismatch_fails_closed():
    with pytest.raises(ProjectionIntegrityError):
        project_current_thesis(
            **_inputs(deltas=[_delta(1, "STABLE", base_revision=1)]),
        )


# ---------------------------------------------------------------------------
# M. delta thesis_id mismatch → FAIL CLOSED
# ---------------------------------------------------------------------------
def test_m_delta_thesis_id_mismatch_fails_closed():
    with pytest.raises(ProjectionIntegrityError):
        project_current_thesis(
            **_inputs(deltas=[_delta(1, "STABLE", thesis_id="b" * 32)]),
        )


# ---------------------------------------------------------------------------
# N. frozen_original revision != frozen_revision → FAIL CLOSED
# ---------------------------------------------------------------------------
def test_n_frozen_original_revision_mismatch_fails_closed():
    with pytest.raises(ProjectionIntegrityError):
        project_current_thesis(
            **_inputs(frozen_original=_frozen_original(revision=1)),
        )


def test_n2_frozen_revision_missing_fails_closed():
    thesis = _thesis()
    del thesis["frozen_revision"]
    with pytest.raises(ProjectionIntegrityError):
        project_current_thesis(**_inputs(thesis=thesis))


# ---------------------------------------------------------------------------
# O. strategy 语义冲突
# ---------------------------------------------------------------------------
def test_o_strategy_conflict_campaign_swing_thesis_medium():
    thesis = _thesis(strategy="MEDIUM")
    with pytest.raises(ProjectionStrategyConflictError):
        project_current_thesis(**_inputs(thesis=thesis))


def test_o2_strategy_conflict_reverse_direction():
    binding = _binding(strategy="SHORT")
    with pytest.raises(ProjectionStrategyConflictError):
        project_current_thesis(**_inputs(binding=binding))


def test_o3_strategy_conflict_is_domain_error():
    thesis = _thesis(strategy="MEDIUM")
    with pytest.raises(ftp.FormalThesisProjectionError):
        project_current_thesis(**_inputs(thesis=thesis))


# ---------------------------------------------------------------------------
# P. bind revision != frozen_revision：projection 用 frozen_revision，bind 仅审计
# ---------------------------------------------------------------------------
def test_p_bind_revision_only_audit():
    result = project_current_thesis(
        **_inputs(binding=_binding(revision_at_bind=1), frozen_original=_frozen_original(revision=2)),
    )
    assert result["formal_status"] == "READY"
    assert result["original"]["revision"] == 2
    assert result["binding_audit"]["thesis_revision_at_bind"] == 1
    assert result["effective_state"] == "STABLE"


# ---------------------------------------------------------------------------
# Q/R. archived frozen thesis
# ---------------------------------------------------------------------------
def test_q_archived_frozen_thesis_still_projects():
    thesis = _thesis(status="archived")
    result = project_current_thesis(
        **_inputs(thesis=thesis, deltas=[_delta(1, "STABLE")]),
    )
    assert result["formal_status"] == "READY"
    assert result["effective_state"] == "STABLE"


def test_r_archived_does_not_imply_invalidated():
    thesis = _thesis(status="archived")
    result = project_current_thesis(
        **_inputs(thesis=thesis, deltas=[_delta(1, "STABLE")]),
    )
    assert result["terminal"] is False
    assert result["effective_state"] != "INVALIDATED"


# ---------------------------------------------------------------------------
# S. 输入乱序但序列合法 → 输出 deterministic（按 delta_sequence 排序）
# ---------------------------------------------------------------------------
def test_s_random_input_order_deterministic():
    deltas = [_delta(1, "STRENGTHENED"), _delta(2, "WEAKENED"), _delta(3, "UNKNOWN")]
    expected = project_current_thesis(**_inputs(deltas=deltas))
    shuffled = project_current_thesis(
        **_inputs(deltas=[deltas[2], deltas[0], deltas[1]]),
    )
    assert shuffled == expected
    assert [d["delta_sequence"] for d in shuffled["deltas"]] == [1, 2, 3]
    assert shuffled["effective_state"] == "UNKNOWN"
    assert shuffled["latest_delta"]["delta_sequence"] == 3


# ---------------------------------------------------------------------------
# T. 同一输入运行 100 次 → deep-equal
# ---------------------------------------------------------------------------
def test_t_100_runs_deep_equal():
    inputs = _inputs(
        deltas=[
            _delta(1, "STRENGTHENED"),
            _delta(2, "UNKNOWN"),
            _delta(3, "WEAKENED"),
        ],
    )
    baseline = project_current_thesis(**inputs)
    for _ in range(100):
        assert project_current_thesis(**inputs) == baseline


# ---------------------------------------------------------------------------
# 输入不可变性 / 无别名共享
# ---------------------------------------------------------------------------
def test_inputs_never_mutated_ready_path():
    inputs = _inputs(
        deltas=[_delta(1, "STRENGTHENED"), _delta(2, "WEAKENED")],
    )
    before = copy.deepcopy(inputs)
    project_current_thesis(**inputs)
    assert inputs == before


def test_inputs_never_mutated_not_ready_path():
    inputs = _inputs(thesis=_thesis(formal_state="DRAFT"))
    before = copy.deepcopy(inputs)
    project_current_thesis(**inputs)
    assert inputs == before


def test_output_does_not_alias_input():
    inputs = _inputs(deltas=[_delta(1, "STRENGTHENED")])
    result = project_current_thesis(**inputs)
    result["deltas"][0]["reason"] = "mutated by caller"
    assert inputs["deltas"][0]["reason"] == "confirmed canonical delta"


# ---------------------------------------------------------------------------
# R1 Deep Output Isolation：输出中所有 mutable nested objects 与输入解除引用共享
# ---------------------------------------------------------------------------
def test_r1_mutate_original_snapshot_does_not_touch_input():
    snapshot = {"title": "frozen original snapshot", "claims": ["claim-1"]}
    inputs = _inputs(frozen_original=_frozen_original(snapshot=snapshot))
    result = project_current_thesis(**inputs)
    result["original"]["snapshot"]["title"] = "mutated"
    result["original"]["snapshot"]["claims"].append("hacked")
    assert inputs["frozen_original"]["snapshot"]["title"] == "frozen original snapshot"
    assert inputs["frozen_original"]["snapshot"]["claims"] == ["claim-1"]


def test_r1_mutate_expected_horizon_does_not_touch_input():
    inputs = _inputs()
    result = project_current_thesis(**inputs)
    result["expected_horizon"]["min"] = 999
    result["expected_horizon"]["anchor"] = "HACKED"
    assert inputs["thesis"]["expected_horizon"]["min"] == 5
    assert inputs["thesis"]["expected_horizon"]["anchor"] == "FREEZE_AT"


def test_r1_mutate_deltas_evidence_snapshots_does_not_touch_input():
    inputs = _inputs(deltas=[_delta(1, "STRENGTHENED")])
    result = project_current_thesis(**inputs)
    result["deltas"][0]["evidence_snapshots"][0]["evidence_id"] = "changed"
    assert inputs["deltas"][0]["evidence_snapshots"][0]["evidence_id"] == "ev-001"


def test_r1_latest_delta_is_independent_of_input_and_deltas_record():
    """latest_delta 是独立拷贝：修改它既不影响输入，也不影响 result['deltas'] 中另一份记录。"""
    inputs = _inputs(
        deltas=[_delta(1, "STRENGTHENED"), _delta(2, "WEAKENED")],
    )
    result = project_current_thesis(**inputs)
    latest = result["latest_delta"]
    record = result["deltas"][1]
    latest["evidence_snapshots"][0]["evidence_id"] = "changed-latest"
    assert inputs["deltas"][1]["evidence_snapshots"][0]["evidence_id"] == "ev-002"
    assert record["evidence_snapshots"][0]["evidence_id"] == "ev-002"


def test_r1_whole_output_mutation_leaves_inputs_unchanged():
    inputs = _inputs(
        deltas=[_delta(1, "STRENGTHENED"), _delta(2, "UNKNOWN")],
    )
    before = copy.deepcopy(inputs)
    result = project_current_thesis(**inputs)
    result["original"]["snapshot"]["title"] = "mutated"
    result["expected_horizon"]["min"] = 999
    result["latest_delta"]["evidence_snapshots"][0]["evidence_id"] = "changed"
    result["deltas"][0]["evidence_snapshots"][0]["evidence_id"] = "changed"
    assert inputs == before


# ---------------------------------------------------------------------------
# 纯模块约束：零 filesystem side effect + 不依赖 store/FastAPI/AI
# ---------------------------------------------------------------------------
def test_module_imports_no_store_or_ai_modules():
    source = inspect.getsource(ftp)
    for forbidden in (
        "evidence_thesis_store",
        "evidence_thesis_service",
        "evidence_thesis_router",
        "campaign_store",
        "campaign_service",
        "campaign_router",
        "fastapi",
        "ai_result",
        "app",
    ):
        assert forbidden not in source, f"projection module must not reference {forbidden}"


def test_module_import_zero_filesystem_side_effects():
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    # conftest 已把 VR_DATA_DIR 指到临时目录（mkdtemp 存在）；直接监视该目录：
    # import 前后目录内容必须完全一致。
    watch_dir = os.environ["VR_DATA_DIR"]
    script = (
        "import os, sys\n"
        "sys.path.insert(0, r'%s')\n"
        "watch = r'%s'\n"
        "before = set(os.listdir(watch))\n"
        "import formal_thesis_projection_core\n"
        "after = set(os.listdir(watch))\n"
        "created = after - before\n"
        "assert not created, 'import created files: %%s' %% created\n"
        "print('CLEAN_IMPORT')\n"
    ) % (backend_dir, watch_dir)
    env = dict(os.environ)
    env["VR_DATA_DIR"] = watch_dir
    proc = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
        cwd=backend_dir,
    )
    assert proc.returncode == 0, proc.stderr
    assert "CLEAN_IMPORT" in proc.stdout
