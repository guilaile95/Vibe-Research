"""P0-PH2 S2D-D：Current Thesis Projection（Formal Thesis 投影）。

只读投影：Campaign → immutable binding → Formal Thesis（frozen_revision 的
FORMAL_FREEZE snapshot + thesis_deltas 证据链），不写任何数据。

规则（fail-closed）：
- formal_state != frozen → NOT_READY/NOT_FROZEN，绝不把 thesis_revision_at_bind
  当作 Formal Original（grandfather pre-freeze binding 允许，但未冻结不投影）；
- Formal Original 永远取 frozen_revision 对应的 thesis_revisions snapshot；
- deltas 按 delta_sequence ASC；无 delta → effective_state=STABLE；
  仅 non-terminal → 最新 wins；terminal 之后仍有 delta → corrupted（500）；
  （读路径 validate_persisted_delta_chain 已 fail-closed，这里显式再校验一遍）
- thesis.strategy 与 binding.campaign_strategy_at_bind 不一致 → 409 semantic
  conflict（复用 campaign_service.CampaignThesisStrategyConflictError）。

本模块只读 evidence_thesis_*，绝不调用其写 API。
"""

from __future__ import annotations

from typing import Any

import campaign_service
import evidence_thesis_service  # READ ONLY：只用于 resolve_db_path
import evidence_thesis_store as evidence_store


TERMINAL_DELTA_STATES = ("DISPROVEN", "INVALIDATED")


class CurrentThesisProjectionError(RuntimeError):
    """投影无法产生 Formal Thesis（ledger 缺失/损坏/不一致，fail-closed → 500）。"""


def _effective_state(deltas: list[dict]) -> str:
    """无 delta → STABLE；仅 non-terminal → 最新 wins；terminal 后仍有 delta → corrupted。"""
    if not deltas:
        return "STABLE"
    for index, delta in enumerate(deltas):
        if delta["delta_state"] in TERMINAL_DELTA_STATES and index != len(deltas) - 1:
            raise CurrentThesisProjectionError(
                "terminal delta followed by later deltas (corrupted chain)"
            )
    return deltas[-1]["delta_state"]


def _binding_audit(binding: dict) -> dict:
    return {
        "thesis_revision_at_bind": binding["thesis_revision_at_bind"],
        "campaign_strategy_at_bind": binding["campaign_strategy_at_bind"],
        "bound_at": binding["bound_at"],
    }


def _not_ready_payload(
    campaign_id: str, thesis_id: str, binding: dict, thesis: dict
) -> dict:
    """未冻结：只给 binding audit facts + formal 状态，不伪造 Formal Original。"""
    return {
        "campaign_id": campaign_id,
        "thesis_id": thesis_id,
        "binding": _binding_audit(binding),
        "formal_state": thesis.get("formal_state"),
        "frozen_revision": thesis.get("frozen_revision"),
        "ready": False,
        "formal_status": "NOT_READY",
        "reason": "NOT_FROZEN",
    }


def project_current_thesis(campaign_id: str) -> dict:
    """生成 Campaign 的 Current Formal Thesis 投影（只读）。"""
    # 1. Campaign → immutable binding → Formal Thesis
    campaign_service.get_campaign(campaign_id)  # 404 / 422 / 500 语义与既有 API 一致
    binding = campaign_service.get_campaign_thesis_binding(campaign_id)
    thesis_id = binding["thesis_id"]

    db_path = evidence_thesis_service.resolve_db_path()

    def _do(conn: Any) -> dict:
        row = evidence_store._get_thesis_row(conn, thesis_id)
        if row is None:
            # binding 指向的 thesis 不存在 → 数据不一致，fail closed
            raise CurrentThesisProjectionError("bound thesis missing from ledger")
        # 读路径 fail-closed 校验（与 canonical get_thesis 同一套 validator）
        evidence_store.validate_persisted_thesis_main(row)
        evidence_store.validate_persisted_thesis_chain(conn, thesis_id, row)
        evidence_store.validate_persisted_delta_chain(conn, thesis_id)
        thesis = evidence_store._thesis_row_to_dict(row)

        # 2. 未冻结 → NOT_READY（不得用 thesis_revision_at_bind 冒充 Formal Original）
        if thesis["formal_state"] != "frozen":
            return _not_ready_payload(campaign_id, thesis_id, binding, thesis)

        # 3. deltas（同快照读取 + 显式校验 terminal 规则）
        delta_rows = conn.execute(
            "SELECT * FROM thesis_deltas WHERE thesis_id = ? "
            "ORDER BY delta_sequence ASC",
            (thesis_id,),
        ).fetchall()
        deltas = []
        for delta_row in delta_rows:
            delta = evidence_store._delta_row_to_dict(delta_row)
            # Delta evidence must come from the canonical immutable snapshots.
            # Do not join/read mutable evidence_records here: after the delta is
            # persisted, edits or soft-deletes to live evidence must not rewrite
            # this historical projection.
            link_rows = conn.execute(
                "SELECT * FROM thesis_delta_evidence_links "
                "WHERE delta_id = ? ORDER BY evidence_id",
                (delta["delta_id"],),
            ).fetchall()
            delta["evidence_links"] = [
                evidence_store._delta_evidence_row_to_dict(link_row)
                for link_row in link_rows
            ]
            deltas.append(delta)
        effective_state = _effective_state(deltas)

        # 4. Strategy consistency（不一致 → 409 semantic conflict）
        if thesis.get("strategy") != binding["campaign_strategy_at_bind"]:
            raise campaign_service.CampaignThesisStrategyConflictError(
                thesis.get("strategy"),
                binding["campaign_strategy_at_bind"],
            )

        # 5. Formal Original = snapshot(frozen_revision)
        frozen_revision = thesis["frozen_revision"]
        if frozen_revision is None:  # validator 已保证，防御性兜底
            raise CurrentThesisProjectionError("frozen thesis missing frozen_revision")
        rev_row = evidence_store._get_revision_row(conn, thesis_id, frozen_revision)
        if rev_row is None:
            raise CurrentThesisProjectionError("frozen revision snapshot missing")
        original_snapshot = evidence_store._revision_row_to_dict(rev_row)["snapshot"]

        return {
            "campaign_id": campaign_id,
            "thesis_id": thesis_id,
            "binding": _binding_audit(binding),
            "frozen_revision": frozen_revision,
            "original_snapshot": original_snapshot,
            "deltas": deltas,
            "effective_state": effective_state,
            "ready": True,
            "formal_status": "READY",
        }

    try:
        return evidence_store.read_transaction(db_path, _do)
    except FileNotFoundError as exc:
        raise CurrentThesisProjectionError("evidence ledger unavailable") from exc
