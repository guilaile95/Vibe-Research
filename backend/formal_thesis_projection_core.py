"""Pure-domain Formal Current Thesis projection core v0.1 — no I/O / DB / AI.

Integration authority (Project Consolidation / OPTION B):
- Not the runtime Current Thesis API. Routers and services must use
  `formal_thesis_projection` (PR #73 integrated adapter).
- This module remains pure-domain unit-test authority only (no I/O).

Formal Current Thesis 纯确定性 Projection Core v0.1 —— 无 I/O、无 DB、无 AI。

输入为已规范化的 immutable 值（Campaign Binding / Formal Thesis metadata /
Frozen Original Snapshot / Canonical Thesis Deltas），输出 deterministic
Current Thesis Projection。同一输入永远产生同一输出；本模块不落库、不建
mutable current pointer，也不直接访问 SQLite / filesystem / env / network /
FastAPI / AI provider。

R5 冻结契约（不得重新设计）：
- Formal State：LEGACY = formal_state NULL / DRAFT / CONFIRMED / FROZEN
- Formal Original Source：``thesis_revisions.snapshot(thesis.frozen_revision)``，
  ``thesis_revision_at_bind`` 只是 Binding Audit Fact，不得作为 Formal Original；
- Canonical Delta enum：STRENGTHENED / STABLE / WEAKENED / DISPROVEN /
  INVALIDATED / UNKNOWN；DISPROVEN 与 INVALIDATED 为 TERMINAL；
- Delta 只增不改：USER CONFIRMED ONLY / APPEND ONLY / NO UPDATE / NO DELETE / NO PATCH。

Projection 规则（v0.1，全部 fail closed）：
1. binding.thesis_id 必须等于 thesis.id（且 binding.campaign_id 等于 campaign_id），
   否则 ProjectionIntegrityError；
2. thesis.formal_state 不是 FROZEN → 返回 NOT_READY / NOT_FROZEN（普通 domain
   result，不用异常；不允许用 thesis_revision_at_bind 冒充 Formal Original）；
3. thesis.frozen_revision 为正整数，且 frozen_original.revision_number 与之相等，
   否则 ProjectionIntegrityError；
4. thesis.strategy 必须等于 binding.campaign_strategy_at_bind，否则
   ProjectionStrategyConflictError（SEMANTIC_CONFLICT，不继续 projection）；
5. 每个 delta：thesis_id 匹配、base_revision == frozen_revision、
   delta_sequence 为正整数且序列严格为 1..N 连续（无重复/无 gap/无 0/负数），
   否则 ProjectionIntegrityError；允许先排序用于 deterministic processing；
6. 无 delta → effective_state = STABLE；
7. 只有 non-terminal delta → 最大 delta_sequence 胜出（latest wins）；
8. terminal（DISPROVEN / INVALIDATED）必须是最后一个 sequence：terminal 之后
   不得存在任何 delta（含另一 terminal），否则 ProjectionIntegrityError，
   不得 truncate / ignore / latest-wins；
9. UNKNOWN 不是 terminal，其后允许 STABLE/STRENGTHENED/WEAKENED/DISPROVEN/INVALIDATED；
10. archived 是 lifecycle fact：不自动改变 effective_state，也不推导
    INVALIDATED；archived frozen thesis + existing grandfather binding 仍允许 projection。

本模块不与任何并行 lane 的 store / service / router 耦合。
"""

from __future__ import annotations

import copy

SCHEMA_VERSION = "formal_current_thesis.projection.v0.1"

# ---- R5 冻结枚举 ----
FORMAL_STATE_FROZEN = "FROZEN"
DELTA_STATES = (
    "STRENGTHENED",
    "STABLE",
    "WEAKENED",
    "DISPROVEN",
    "INVALIDATED",
    "UNKNOWN",
)
TERMINAL_DELTA_STATES = ("DISPROVEN", "INVALIDATED")
VALID_STRATEGIES = ("SHORT", "SWING", "MEDIUM")


class FormalThesisProjectionError(Exception):
    """Formal Current Thesis projection 领域异常基类。"""


class ProjectionIntegrityError(FormalThesisProjectionError):
    """输入 / persisted 数据损坏或违反冻结契约 → fail closed。"""


class ProjectionStrategyConflictError(FormalThesisProjectionError):
    """Campaign strategy 与 Formal Thesis strategy 语义冲突（SEMANTIC_CONFLICT）。"""


def _positive_int(value, field: str) -> int:
    """正整数校验（排除 bool）；缺失 / 非 int / <=0 → fail closed。"""
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ProjectionIntegrityError(
            f"{field} must be a positive integer, got {value!r}"
        )
    return value


def _is_frozen(formal_state) -> bool:
    """FROZEN 判定：大小写 / 首尾空白归一化后比较，避免把枚举写成单一字面量。"""
    return (
        isinstance(formal_state, str)
        and formal_state.strip().upper() == FORMAL_STATE_FROZEN
    )


def _delta_record(delta: dict) -> dict:
    """delta → 输出记录（新 dict；所有 mutable payload 与输入解除引用共享）。

    ``evidence_snapshots`` 是 list[dict]，必须 deep-copy：既不能 alias 输入 delta，
    也不能让 latest_delta 与 ``deltas[]`` 中的另一份记录共享同一嵌套对象。
    """
    return {
        "delta_id": delta.get("delta_id"),
        "delta_sequence": delta["delta_sequence"],
        "delta_state": delta["delta_state"],
        "reason": delta.get("reason"),
        "confirmed_at": delta.get("confirmed_at"),
        "evidence_snapshots": copy.deepcopy(delta.get("evidence_snapshots")),
    }


def project_current_thesis(
    *,
    campaign_id: str,
    binding: dict,
    thesis: dict,
    frozen_original: dict,
    deltas: list,
) -> dict:
    """由规范化输入确定性推导 Formal Current Thesis Projection。

    返回 ``formal_status``：
    - ``READY``：完整 projection（original + binding_audit + effective_state +
      latest_delta + terminal + deltas）；
    - ``NOT_READY`` / ``NOT_FROZEN``：thesis 尚未 FROZEN，无法形成 Formal
      Current Thesis（普通 domain result，不抛异常）。

    输入损坏（序列断裂、base_revision 不匹配、frozen original 缺失等）一律
    ``ProjectionIntegrityError``；strategy 语义冲突抛
    ``ProjectionStrategyConflictError``。本函数不修改任何输入对象。
    """
    # ---- 输入容器与 campaign/binding/thesis 一致性（规则 1）----
    if not isinstance(binding, dict):
        raise ProjectionIntegrityError("binding must be a dict")
    if not isinstance(thesis, dict):
        raise ProjectionIntegrityError("thesis must be a dict")
    if not isinstance(frozen_original, dict):
        raise ProjectionIntegrityError("frozen_original must be a dict")
    if not isinstance(deltas, list):
        raise ProjectionIntegrityError("deltas must be a list")

    if not isinstance(campaign_id, str) or not campaign_id:
        raise ProjectionIntegrityError("campaign_id must be a non-empty string")
    if binding.get("campaign_id") != campaign_id:
        raise ProjectionIntegrityError("binding.campaign_id does not match campaign_id")

    thesis_id = binding.get("thesis_id")
    if not isinstance(thesis_id, str) or not thesis_id:
        raise ProjectionIntegrityError("binding.thesis_id must be a non-empty string")
    if thesis.get("id") != thesis_id:
        raise ProjectionIntegrityError("binding.thesis_id does not match thesis.id")

    # ---- 规则 2：未 FROZEN → NOT_READY（不允许用 bind revision 冒充 Original）----
    if not _is_frozen(thesis.get("formal_state")):
        return {
            "campaign_id": campaign_id,
            "thesis_id": thesis_id,
            "formal_status": "NOT_READY",
            "reason": "NOT_FROZEN",
        }

    # ---- 规则 3：frozen_revision 正整数 + frozen original 对齐（fail closed）----
    frozen_revision = _positive_int(
        thesis.get("frozen_revision"), "thesis.frozen_revision"
    )
    original_revision = _positive_int(
        frozen_original.get("revision_number"), "frozen_original.revision_number"
    )
    if original_revision != frozen_revision:
        raise ProjectionIntegrityError(
            "frozen_original.revision_number"
            f" ({original_revision}) != thesis.frozen_revision ({frozen_revision})"
        )

    # ---- 规则 4：strategy 语义冲突（SEMANTIC_CONFLICT，不继续 projection）----
    thesis_strategy = thesis.get("strategy")
    bind_strategy = binding.get("campaign_strategy_at_bind")
    for value, field in (
        (thesis_strategy, "thesis.strategy"),
        (bind_strategy, "binding.campaign_strategy_at_bind"),
    ):
        if value not in VALID_STRATEGIES:
            raise ProjectionIntegrityError(
                f"{field} must be one of {VALID_STRATEGIES}, got {value!r}"
            )
    if thesis_strategy != bind_strategy:
        raise ProjectionStrategyConflictError(
            "SEMANTIC_CONFLICT: thesis.strategy"
            f" ({thesis_strategy}) != campaign_strategy_at_bind ({bind_strategy})"
        )

    # ---- 规则 5：delta 完整性（thesis_id / base_revision / 连续 1..N 序列）----
    for index, delta in enumerate(deltas):
        if not isinstance(delta, dict):
            raise ProjectionIntegrityError(f"deltas[{index}] must be a dict")
        if delta.get("thesis_id") != thesis_id:
            raise ProjectionIntegrityError(
                f"deltas[{index}].thesis_id does not match thesis.id"
            )
        _positive_int(delta.get("delta_sequence"), f"deltas[{index}].delta_sequence")
        if delta.get("base_revision") != frozen_revision:
            raise ProjectionIntegrityError(
                f"deltas[{index}].base_revision must equal"
                f" thesis.frozen_revision ({frozen_revision})"
            )
        if delta.get("delta_state") not in DELTA_STATES:
            raise ProjectionIntegrityError(
                f"deltas[{index}].delta_state must be one of {DELTA_STATES},"
                f" got {delta.get('delta_state')!r}"
            )

    ordered = sorted(deltas, key=lambda d: d["delta_sequence"])
    sequences = [d["delta_sequence"] for d in ordered]
    if sequences != list(range(1, len(ordered) + 1)):
        raise ProjectionIntegrityError(
            "delta_sequence must be strictly contiguous 1..N"
            f" (no duplicate/gap/0/negative), got {sequences}"
        )

    # ---- 规则 8：terminal 必须是最后一个 sequence（fail closed，不得 truncate）----
    terminal_deltas = [d for d in ordered if d["delta_state"] in TERMINAL_DELTA_STATES]
    if terminal_deltas:
        max_sequence = ordered[-1]["delta_sequence"]
        for td in terminal_deltas:
            if td["delta_sequence"] != max_sequence:
                raise ProjectionIntegrityError(
                    "terminal delta must be the last delta_sequence;"
                    " found delta(s) after terminal (corruption, fail closed)"
                )

    # ---- 规则 6 / 7 / 9：无 delta → STABLE；否则 latest wins ----
    if not ordered:
        effective_state = "STABLE"
        latest_delta = None
    else:
        effective_state = ordered[-1]["delta_state"]
        latest_delta = _delta_record(ordered[-1])

    return {
        "schema_version": SCHEMA_VERSION,
        "campaign_id": campaign_id,
        "thesis_id": thesis_id,
        "formal_status": "READY",
        "original": {
            "revision": frozen_revision,
            "snapshot": copy.deepcopy(frozen_original.get("snapshot")),
        },
        "binding_audit": {
            "thesis_revision_at_bind": binding.get("thesis_revision_at_bind"),
            "campaign_strategy_at_bind": bind_strategy,
            "bound_at": binding.get("bound_at"),
        },
        "strategy": thesis_strategy,
        "expected_horizon": copy.deepcopy(thesis.get("expected_horizon")),
        "effective_state": effective_state,
        "latest_delta": latest_delta,
        "terminal": effective_state in TERMINAL_DELTA_STATES,
        "deltas": [_delta_record(d) for d in ordered],
    }
