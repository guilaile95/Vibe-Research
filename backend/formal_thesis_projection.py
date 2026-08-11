"""P0-PH2 S2D-D：Current Thesis Projection integrated I/O adapter.

只读投影：Campaign → immutable binding → Formal Thesis（frozen_revision 的
FORMAL_FREEZE snapshot + thesis_deltas 证据链），不写任何数据。

Integration authority (Project Consolidation / OPTION A):
- ``formal_thesis_projection_core`` is the **sole pure-domain projection
  authority** (NOT_FROZEN / effective_state / terminal-last / strategy /
  Formal Original semantics).
- This module is the **I/O + persistence validation + API adapter**:
  DB transaction, Campaign binding retrieval, persisted validators,
  revision/delta-chain validation, immutable delta evidence retrieval,
  exception mapping, and the existing #73 HTTP/API payload contract.
- Routers import this module only. Domain rules are not reimplemented here.

本模块只读 evidence_thesis_*，绝不调用其写 API。
"""

from __future__ import annotations

from typing import Any

import campaign_service
import evidence_thesis_service  # READ ONLY：只用于 resolve_db_path
import evidence_thesis_store as evidence_store
import formal_thesis_projection_core as projection_core
from formal_thesis_projection_core import (
    ProjectionIntegrityError,
    ProjectionStrategyConflictError,
)


class CurrentThesisProjectionError(RuntimeError):
    """投影无法产生 Formal Thesis（ledger 缺失/损坏/不一致，fail-closed → 500）。"""


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


def _core_delta_inputs(deltas: list[dict]) -> list[dict]:
    """Build pure-domain delta inputs (no I/O-only evidence_links)."""
    return [
        {
            "delta_id": delta.get("delta_id"),
            "thesis_id": delta["thesis_id"],
            "delta_sequence": delta["delta_sequence"],
            "base_revision": delta["base_revision"],
            "delta_state": delta["delta_state"],
            "reason": delta.get("reason"),
            "confirmed_at": delta.get("confirmed_at"),
            "evidence_snapshots": None,
        }
        for delta in deltas
    ]


def _adapt_ready_payload(
    *,
    campaign_id: str,
    thesis_id: str,
    binding: dict,
    core_result: dict,
    io_deltas: list[dict],
) -> dict:
    """Map pure-core READY result into the existing #73 runtime/API shape.

    Domain decisions (effective_state, formal_status, original revision,
    strategy/terminal implications) come exclusively from core_result.
    I/O-loaded deltas retain immutable evidence_links for the API surface.
    """
    ordered_io = sorted(io_deltas, key=lambda d: d["delta_sequence"])
    return {
        "campaign_id": campaign_id,
        "thesis_id": thesis_id,
        "binding": _binding_audit(binding),
        "frozen_revision": core_result["original"]["revision"],
        "original_snapshot": core_result["original"]["snapshot"],
        "deltas": ordered_io,
        "effective_state": core_result["effective_state"],
        "ready": True,
        "formal_status": "READY",
    }


def project_current_thesis_from_normalized(
    *,
    campaign_id: str,
    binding: dict,
    thesis: dict,
    frozen_original: dict,
    deltas: list,
) -> dict:
    """Pure-input path used by tests: core domain + #73 API adaptation only.

    No I/O. Callers that already hold normalized immutable values use this
    to prove core → adapter semantic parity without a database.
    """
    try:
        core_result = projection_core.project_current_thesis(
            campaign_id=campaign_id,
            binding=binding,
            thesis=thesis,
            frozen_original=frozen_original,
            deltas=_core_delta_inputs(list(deltas)),
        )
    except ProjectionStrategyConflictError as exc:
        thesis_strategy = thesis.get("strategy")
        bind_strategy = binding.get("campaign_strategy_at_bind")
        raise campaign_service.CampaignThesisStrategyConflictError(
            thesis_strategy,
            bind_strategy,
        ) from exc
    except ProjectionIntegrityError as exc:
        raise CurrentThesisProjectionError(str(exc)) from exc

    if core_result.get("formal_status") != "READY":
        return _not_ready_payload(
            campaign_id,
            binding.get("thesis_id") or thesis.get("id") or "",
            binding,
            thesis,
        )

    return _adapt_ready_payload(
        campaign_id=campaign_id,
        thesis_id=core_result["thesis_id"],
        binding=binding,
        core_result=core_result,
        io_deltas=list(deltas),
    )


def project_current_thesis(campaign_id: str) -> dict:
    """生成 Campaign 的 Current Formal Thesis 投影（只读 I/O adapter）。"""
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
        evidence_store.validate_persisted_revision_history(conn, thesis_id, row)
        evidence_store.validate_persisted_thesis_chain(conn, thesis_id, row)
        evidence_store.validate_persisted_delta_chain(conn, thesis_id)
        thesis = evidence_store._thesis_row_to_dict(row)

        # Load deltas + immutable evidence snapshots (I/O only).
        delta_rows = conn.execute(
            "SELECT * FROM thesis_deltas WHERE thesis_id = ? "
            "ORDER BY delta_sequence ASC",
            (thesis_id,),
        ).fetchall()
        deltas: list[dict] = []
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

        # Formal Original snapshot for pure-core input (only when frozen).
        frozen_original: dict = {}
        if thesis.get("formal_state") == "frozen" and thesis.get("frozen_revision") is not None:
            rev_row = evidence_store._get_revision_row(
                conn, thesis_id, int(thesis["frozen_revision"])
            )
            if rev_row is None:
                raise CurrentThesisProjectionError("frozen revision snapshot missing")
            frozen_original = {
                "revision_number": int(rev_row["revision_number"]),
                "snapshot": evidence_store._revision_row_to_dict(rev_row)["snapshot"],
            }

        # 2. Domain projection — sole authority is pure core (OPTION A).
        try:
            core_result = projection_core.project_current_thesis(
                campaign_id=campaign_id,
                binding=binding,
                thesis=thesis,
                frozen_original=frozen_original,
                deltas=_core_delta_inputs(deltas),
            )
        except ProjectionStrategyConflictError as exc:
            raise campaign_service.CampaignThesisStrategyConflictError(
                thesis.get("strategy"),
                binding["campaign_strategy_at_bind"],
            ) from exc
        except ProjectionIntegrityError as exc:
            raise CurrentThesisProjectionError(str(exc)) from exc

        if core_result.get("formal_status") != "READY":
            return _not_ready_payload(campaign_id, thesis_id, binding, thesis)

        return _adapt_ready_payload(
            campaign_id=campaign_id,
            thesis_id=thesis_id,
            binding=binding,
            core_result=core_result,
            io_deltas=deltas,
        )

    try:
        return evidence_store.read_transaction(db_path, _do)
    except FileNotFoundError as exc:
        raise CurrentThesisProjectionError("evidence ledger unavailable") from exc
