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
- ``authority_refs`` 是 deterministic provenance，绑定实际 Current Thesis
  authority identity（campaign_id + thesis_id + frozen revision），
  不使用无实际 identity 的占位字符串。
"""

from __future__ import annotations

from typing import Any, Mapping

from formal_thesis_projection_core import (
    SCHEMA_VERSION as THESIS_PROJECTION_SCHEMA_VERSION,
    TERMINAL_DELTA_STATES,
)


def build_current_thesis_envelope(
    *,
    campaign: Mapping[str, Any],
    as_of: str,
    current_thesis_projection: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    """把现有 Current Thesis projection 适配为 C 的输入 envelope。

    - ``current_thesis_projection is None``（未绑定）→ 返回 None，
      C 将其视为 NOT_EVALUATED（authority not available）。
    - projection 非 None → envelope：{campaign_id, security_code, strategy,
      as_of, authority_refs, projection}；projection 部分补全
      schema_version / strategy / terminal。
    """
    if current_thesis_projection is None:
        return None
    effective_state = current_thesis_projection.get("effective_state")
    terminal = effective_state in TERMINAL_DELTA_STATES
    return {
        "campaign_id": current_thesis_projection.get("campaign_id")
        or campaign["campaign_id"],
        "security_code": campaign["security_code"],
        "strategy": campaign["strategy"],
        "as_of": as_of,
        "authority_refs": _authority_refs(campaign, current_thesis_projection),
        "projection": {
            **current_thesis_projection,
            "schema_version": THESIS_PROJECTION_SCHEMA_VERSION,
            "strategy": campaign["strategy"],
            "terminal": terminal,
        },
    }


def _authority_refs(
    campaign: Mapping[str, Any],
    projection: Mapping[str, Any],
) -> list[str]:
    """确定性 provenance：绑定实际 Current Thesis authority identity。

    形如 ``current_thesis:<campaign_id>:<thesis_id>:v<frozen_revision>``。
    projection 缺少 thesis_id 时退化为 campaign 级 identity（仍确定性）。
    """
    campaign_id = campaign["campaign_id"]
    thesis_id = projection.get("thesis_id")
    frozen_revision = projection.get("frozen_revision")
    if isinstance(thesis_id, str) and thesis_id:
        identity = f"current_thesis:{campaign_id}:{thesis_id}"
        if isinstance(frozen_revision, int):
            identity = f"{identity}:v{frozen_revision}"
        return [identity]
    return [f"current_thesis:{campaign_id}:unbound"]


__all__ = [
    "THESIS_PROJECTION_SCHEMA_VERSION",
    "build_current_thesis_envelope",
]
