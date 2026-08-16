"""P0-HR1 Current Thesis → Hard Risk input envelope adapter（shape adaptation only）。

把现有 Current Thesis projection（formal_thesis_projection I/O adapter 输出，
#73 API shape）适配为 hard_risk_runtime.evaluate_hard_risk() 的输入 envelope。

铁律：
- 只做 shape adaptation：补齐 I/O adapter 为 #73 API 裁剪掉的
  ``schema_version`` / ``strategy`` / ``terminal`` 三个字段。
- 复用 formal_thesis_projection_core 的 frozen 定义（SCHEMA_VERSION /
  TERMINAL_DELTA_STATES），绝不维护第二份 terminal / delta precedence 规则。
- 绝不接受或输出 hard_risk_state / severity / positive_proof / coverage /
  risk_type / caller conclusion —— 最终 Hard Risk state 只由
  hard_risk_runtime.evaluate_hard_risk() 决定。
- fail closed：projection-present 时若缺少 / 损坏 authority identity
  （campaign_id / thesis_id / binding / frozen_revision / READY 一致性），
  抛 CurrentThesisHardRiskAdapterError —— 绝不替 projection 制造
  identity / provenance，绝不 fallback 到 Campaign 值，绝不降级成
  NOT_EVALUATED 假装「只是没绑定」。
- authority_refs 是 deterministic provenance，严格绑定实际 Current Thesis
  authority identity，禁止 synthetic positive provenance（trusted / proof /
  unbound / unknown-thesis）。
"""

from __future__ import annotations

from typing import Any, Mapping

from formal_thesis_projection_core import (
    SCHEMA_VERSION as THESIS_PROJECTION_SCHEMA_VERSION,
    TERMINAL_DELTA_STATES,
)


class CurrentThesisHardRiskAdapterError(ValueError):
    """Current Thesis projection 缺少/损坏 authority identity（fail closed）。

    由 assembler 捕获并整体转为 500（integrity failure），
    绝不伪装成 NOT_EVALUATED 或 CONFIRMED。
    """


def _require_campaign_id(
    projection: Mapping[str, Any], campaign: Mapping[str, Any]
) -> str:
    value = projection.get("campaign_id")
    if not isinstance(value, str) or not value:
        raise CurrentThesisHardRiskAdapterError(
            "current thesis projection 缺少 campaign_id（禁止 fallback 到 Campaign）"
        )
    if value != campaign["campaign_id"]:
        raise CurrentThesisHardRiskAdapterError(
            "current thesis projection campaign_id 与 Campaign 不一致"
        )
    return value


def _require_thesis_id(projection: Mapping[str, Any]) -> str:
    value = projection.get("thesis_id")
    if not isinstance(value, str) or not value:
        raise CurrentThesisHardRiskAdapterError(
            "current thesis projection 缺少真实 thesis_id（禁止 synthetic identity）"
        )
    return value


def _require_binding(
    projection: Mapping[str, Any], campaign: Mapping[str, Any]
) -> Mapping[str, Any]:
    binding = projection.get("binding")
    if not isinstance(binding, Mapping):
        raise CurrentThesisHardRiskAdapterError(
            "current thesis projection binding 必须是 Mapping"
        )
    bind_strategy = binding.get("campaign_strategy_at_bind")
    if bind_strategy != campaign["strategy"]:
        raise CurrentThesisHardRiskAdapterError(
            "binding.campaign_strategy_at_bind 与 Campaign strategy 不一致"
        )
    return binding


def _require_readiness(projection: Mapping[str, Any]) -> bool:
    formal_status = projection.get("formal_status")
    ready = projection.get("ready")
    if formal_status == "READY":
        if ready is not True:
            raise CurrentThesisHardRiskAdapterError(
                "formal_status=READY 但 ready 不是 true（transport 不一致）"
            )
        return True
    if ready is True:
        raise CurrentThesisHardRiskAdapterError(
            "ready=true 但 formal_status 不是 READY（transport 不一致）"
        )
    return False


def _require_frozen_revision(projection: Mapping[str, Any]) -> int:
    value = projection.get("frozen_revision")
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise CurrentThesisHardRiskAdapterError(
            "READY projection 缺少 positive int frozen_revision"
        )
    return value


def _authority_refs(
    *,
    campaign_id: str,
    thesis_id: str,
    ready: bool,
    frozen_revision: int | None,
) -> list[str]:
    """确定性 provenance，严格绑定实际 Thesis authority identity。

    - READY：``current_thesis:<campaign_id>:<thesis_id>:v<frozen_revision>``
    - NOT_READY：``current_thesis:<campaign_id>:<thesis_id>``
    任何情况下都不产生 synthetic positive provenance。
    """
    base = f"current_thesis:{campaign_id}:{thesis_id}"
    if ready and frozen_revision is not None:
        return [f"{base}:v{frozen_revision}"]
    return [base]


def build_current_thesis_envelope(
    *,
    campaign: Mapping[str, Any],
    as_of: str,
    current_thesis_projection: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    """把现有 Current Thesis projection 适配为 C 的输入 envelope。

    - ``current_thesis_projection is None``（未绑定）→ 返回 None（legitimate
      authority absent），C 视为 NOT_EVALUATED。
    - projection 非 None → 先验证 transport/identity invariants（失败抛
      CurrentThesisHardRiskAdapterError，fail closed），再补 schema_version /
      strategy / terminal，输出 C envelope。
    """
    if current_thesis_projection is None:
        return None

    campaign_id = _require_campaign_id(current_thesis_projection, campaign)
    thesis_id = _require_thesis_id(current_thesis_projection)
    _require_binding(current_thesis_projection, campaign)
    ready = _require_readiness(current_thesis_projection)
    frozen_revision = (
        _require_frozen_revision(current_thesis_projection) if ready else None
    )

    effective_state = current_thesis_projection.get("effective_state")
    terminal = effective_state in TERMINAL_DELTA_STATES
    return {
        "campaign_id": campaign_id,
        "security_code": campaign["security_code"],
        "strategy": campaign["strategy"],
        "as_of": as_of,
        "authority_refs": _authority_refs(
            campaign_id=campaign_id,
            thesis_id=thesis_id,
            ready=ready,
            frozen_revision=frozen_revision,
        ),
        "projection": {
            **current_thesis_projection,
            "schema_version": THESIS_PROJECTION_SCHEMA_VERSION,
            "strategy": campaign["strategy"],
            "terminal": terminal,
        },
    }


__all__ = [
    "CurrentThesisHardRiskAdapterError",
    "THESIS_PROJECTION_SCHEMA_VERSION",
    "build_current_thesis_envelope",
]
