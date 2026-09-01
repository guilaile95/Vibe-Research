"""Campaign API v0.1（P0-S2A + P0-S2B：Identity + Lifecycle Transition）。

只读 + 创建 + 显式 transition：
- ``POST /api/campaigns``：创建 Campaign（status 恒为服务端 DRAFT）
- ``GET  /api/campaigns``：确定性列表 + 可选过滤（security_code / strategy / status）
- ``GET  /api/campaigns/{campaign_id}``：精确读取
- ``POST /api/campaigns/{campaign_id}/transitions``：原子状态迁移（CAS + 冻结 graph）
- ``GET  /api/campaigns/{campaign_id}/transitions``：durable transition 历史
- ``GET  /api/campaigns/{campaign_id}/next-actions``：下一合法动作 read-model
  （派生自 frozen graph 单一权威；前端不复制 graph，动作仍走 transition API）

不存在 PATCH / PUT / DELETE —— Strategy 结构性不可变、状态只能经 transition
graph 变更。

安全边界：
- 所有错误响应只返回稳定脱敏 detail，绝不泄漏 str(e) / SQL / 文件路径 / traceback；
- 未预期异常 → 500 固定文本。

本 router 可独立挂载测试（test-only FastAPI app）；app.py 接线由
集成 Slice 处理（MAIN_APP_ROUTER_WIRING = DEFERRED_TO_INTEGRATION）。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal

import campaign_service
from campaign_service import (
    CampaignActivationNotEligibleError,
    CampaignActivationTradeNotFoundError,
    CampaignConflictError,
    CampaignInputError,
    CampaignNotFoundError,
    CampaignServiceError,
    CampaignThesisArchivedError,
    CampaignThesisBindingConflictError,
    CampaignThesisFormalIncompleteError,
    CampaignThesisStrategyConflictError,
    CampaignTransitionConflictError,
    ThesisBindingNotFoundError,
    ThesisNotFoundError,
)

import formal_thesis_projection
from formal_thesis_projection import CurrentThesisProjectionError
import research_continuity_service

router = APIRouter(prefix="/api", tags=["campaigns"])

# 稳定脱敏错误文案（客户端唯一可见内容）
_INVALID_INPUT_DETAIL = "Campaign 参数无效"
_NOT_FOUND_DETAIL = "Campaign 不存在"
_THESIS_NOT_FOUND_DETAIL = "Thesis 不存在"
_BINDING_NOT_FOUND_DETAIL = "Thesis Binding 不存在"
_CONFLICT_DETAIL = "Campaign 已存在"
_TRANSITION_CONFLICT_DETAIL = "Campaign 状态冲突"
_ACTIVATION_NOT_ELIGIBLE_DETAIL = "Campaign 尚不满足真实买入激活条件"
_TRADE_NOT_FOUND_DETAIL = "Trade 不存在"
_BINDING_CONFLICT_DETAIL = "Thesis Binding 冲突"
_THESIS_ARCHIVED_DETAIL = "Thesis 已归档，不可绑定"
_THESIS_FORMAL_INCOMPLETE_DETAIL = "Thesis 未完成 Formal 化（NEEDS_USER_COMPLETION）"
_INTERNAL_ERROR_DETAIL = "Campaign 服务暂不可用"


def _strategy_conflict_detail(exc: CampaignThesisStrategyConflictError) -> str:
    """409 semantic conflict detail：说明两 strategy（枚举值已冻结，无敏感信息）。"""
    return (
        f"Thesis strategy {exc.thesis_strategy} "
        f"与 Campaign strategy {exc.campaign_strategy} 不一致"
    )


class CampaignCreateIn(BaseModel):
    """创建 Campaign 请求体：status 由服务端决定，不接受客户端伪造。"""

    model_config = ConfigDict(extra="forbid")

    security_code: str
    strategy: Literal["SHORT", "SWING", "MEDIUM"]


class CampaignTransitionIn(BaseModel):
    """显式 transition 意图：expected_status（CAS）+ to_status（冻结 graph）。"""

    model_config = ConfigDict(extra="forbid")

    expected_status: Literal[
        "DRAFT", "RESEARCHING", "PRE-ENTRY", "ACTIVE",
        "REDUCING", "CLOSED", "REJECTED", "EXPIRED",
    ]
    to_status: Literal[
        "DRAFT", "RESEARCHING", "PRE-ENTRY", "ACTIVE",
        "REDUCING", "CLOSED", "REJECTED", "EXPIRED",
    ]


class CampaignThesisBindingIn(BaseModel):
    """绑定请求体：只允许 thesis_id；不允许携带 strategy（422）。"""

    model_config = ConfigDict(extra="forbid")

    thesis_id: str


class CampaignTradeActivationIn(BaseModel):
    """显式激活意图：只接受已有 Trade identity，不接受客户端声明结果。"""

    model_config = ConfigDict(extra="forbid")

    trade_id: str


class ResearchContinuityBatchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    campaign_ids: list[str] = Field(min_length=1, max_length=100)


@router.post("/campaigns", status_code=201)
def create_campaign(body: CampaignCreateIn) -> dict:
    """创建 Campaign（新记录恒为 DRAFT，campaign_id 由服务端生成）。"""
    try:
        record = campaign_service.create_campaign(
            security_code=body.security_code,
            strategy=body.strategy,
        )
    except CampaignInputError:
        raise HTTPException(422, _INVALID_INPUT_DETAIL) from None
    except CampaignConflictError:
        raise HTTPException(409, _CONFLICT_DETAIL) from None
    except CampaignServiceError:
        raise HTTPException(500, _INTERNAL_ERROR_DETAIL) from None
    except Exception:  # noqa: BLE001 — 未预期逃逸，安全兜底
        raise HTTPException(500, _INTERNAL_ERROR_DETAIL) from None
    return {"data": record}


@router.get("/campaigns")
def list_campaigns(
    security_code: str | None = None,
    strategy: str | None = None,
    status: str | None = None,
) -> dict:
    """确定性列表（created_at ASC, campaign_id ASC）+ 可选过滤。"""
    try:
        records = campaign_service.list_campaigns(
            security_code=security_code,
            strategy=strategy,
            status=status,
        )
    except CampaignInputError:
        raise HTTPException(422, _INVALID_INPUT_DETAIL) from None
    except CampaignServiceError:
        raise HTTPException(500, _INTERNAL_ERROR_DETAIL) from None
    except Exception:  # noqa: BLE001 — 未预期逃逸，安全兜底
        raise HTTPException(500, _INTERNAL_ERROR_DETAIL) from None
    return {"data": records}


@router.get("/campaigns/{campaign_id}")
def get_campaign(campaign_id: str) -> dict:
    """按 campaign_id 精确读取；不存在 → 404（稳定 detail）。"""
    try:
        record = campaign_service.get_campaign(campaign_id)
    except CampaignInputError:
        raise HTTPException(422, _INVALID_INPUT_DETAIL) from None
    except CampaignNotFoundError:
        raise HTTPException(404, _NOT_FOUND_DETAIL) from None
    except CampaignServiceError:
        raise HTTPException(500, _INTERNAL_ERROR_DETAIL) from None
    except Exception:  # noqa: BLE001 — 未预期逃逸，安全兜底
        raise HTTPException(500, _INTERNAL_ERROR_DETAIL) from None
    return {"data": record}


@router.post("/campaigns/{campaign_id}/transitions")
def transition_campaign(campaign_id: str, body: CampaignTransitionIn) -> dict:
    """原子状态迁移：CAS（expected_status）+ 冻结 transition graph。

    成功返回 ``{"data": {"campaign": ..., "transition": ...}}``；
    409 = expected_status 不符 / graph 不允许 / transition_id 冲突。
    """
    try:
        campaign, transition = campaign_service.transition_campaign(
            campaign_id=campaign_id,
            expected_status=body.expected_status,
            to_status=body.to_status,
        )
    except CampaignInputError:
        raise HTTPException(422, _INVALID_INPUT_DETAIL) from None
    except CampaignNotFoundError:
        raise HTTPException(404, _NOT_FOUND_DETAIL) from None
    except CampaignTransitionConflictError:
        raise HTTPException(409, _TRANSITION_CONFLICT_DETAIL) from None
    except CampaignConflictError:
        raise HTTPException(409, _TRANSITION_CONFLICT_DETAIL) from None
    except CampaignServiceError:
        raise HTTPException(500, _INTERNAL_ERROR_DETAIL) from None
    except Exception:  # noqa: BLE001 — 未预期逃逸，安全兜底
        raise HTTPException(500, _INTERNAL_ERROR_DETAIL) from None
    return {"data": {"campaign": campaign, "transition": transition}}


@router.post("/campaigns/{campaign_id}/activate-from-trade")
def activate_campaign_from_trade(
    campaign_id: str,
    body: CampaignTradeActivationIn,
) -> dict:
    """在真实 BUY 已执行、正式归属且 Position Reality 已 OPEN 后显式激活。"""
    try:
        result = campaign_service.activate_pre_entry_campaign_from_trade(
            campaign_id=campaign_id,
            trade_id=body.trade_id,
        )
    except CampaignInputError:
        raise HTTPException(422, _INVALID_INPUT_DETAIL) from None
    except CampaignNotFoundError:
        raise HTTPException(404, _NOT_FOUND_DETAIL) from None
    except CampaignActivationTradeNotFoundError:
        raise HTTPException(404, _TRADE_NOT_FOUND_DETAIL) from None
    except CampaignActivationNotEligibleError:
        raise HTTPException(409, _ACTIVATION_NOT_ELIGIBLE_DETAIL) from None
    except CampaignTransitionConflictError:
        raise HTTPException(409, _TRANSITION_CONFLICT_DETAIL) from None
    except CampaignServiceError:
        raise HTTPException(500, _INTERNAL_ERROR_DETAIL) from None
    except Exception:  # noqa: BLE001 — 未预期逃逸，安全兜底
        raise HTTPException(500, _INTERNAL_ERROR_DETAIL) from None
    return {"data": result}


@router.get("/campaigns/{campaign_id}/transitions")
def list_campaign_transitions(campaign_id: str) -> dict:
    """Campaign 的 transition 历史（transitioned_at ASC, transition_id ASC）。"""
    try:
        records = campaign_service.list_campaign_transitions(campaign_id)
    except CampaignInputError:
        raise HTTPException(422, _INVALID_INPUT_DETAIL) from None
    except CampaignServiceError:
        raise HTTPException(500, _INTERNAL_ERROR_DETAIL) from None
    except Exception:  # noqa: BLE001 — 未预期逃逸，安全兜底
        raise HTTPException(500, _INTERNAL_ERROR_DETAIL) from None
    return {"data": records}


@router.get("/campaigns/{campaign_id}/next-actions")
def get_campaign_next_actions(campaign_id: str) -> dict:
    """下一合法动作 read-model（只读，派生自 frozen graph 单一权威）。

    响应自包含 campaign 身份与 status，前端不复制 graph；动作执行仍走
    正式 transition API（CAS + graph 校验）。terminal → next_actions 为空。
    """
    try:
        campaign, actions = campaign_service.next_campaign_actions(campaign_id)
    except CampaignInputError:
        raise HTTPException(422, _INVALID_INPUT_DETAIL) from None
    except CampaignNotFoundError:
        raise HTTPException(404, _NOT_FOUND_DETAIL) from None
    except CampaignServiceError:
        raise HTTPException(500, _INTERNAL_ERROR_DETAIL) from None
    except Exception:  # noqa: BLE001 — 未预期逃逸，安全兜底
        raise HTTPException(500, _INTERNAL_ERROR_DETAIL) from None
    return {
        "data": {
            "campaign_id": campaign["campaign_id"],
            "security_code": campaign["security_code"],
            "strategy": campaign["strategy"],
            "status": campaign["status"],
            "next_actions": actions,
        }
    }


@router.post("/campaigns/{campaign_id}/thesis-binding", status_code=201)
def bind_campaign_thesis(campaign_id: str, body: CampaignThesisBindingIn) -> dict:
    """建立 Campaign ↔ Existing Thesis 的不可变绑定（201）。

    校验：Campaign 存在 / Thesis 存在 / subject_type=stock /
    subject_id 与 security_code 完全一致 / revision 锚定 /
    Thesis 未 archived / formal_state=frozen / strategy 一致 / 快照 strategy。
    422 = 非法 body/ID；404 = Campaign/Thesis 不存在；
    409 = 绑定冲突 / archived / NEEDS_USER_COMPLETION / strategy semantic conflict。
    """
    try:
        binding = campaign_service.bind_campaign_thesis(
            campaign_id=campaign_id,
            thesis_id=body.thesis_id,
        )
    except CampaignInputError:
        raise HTTPException(422, _INVALID_INPUT_DETAIL) from None
    except CampaignNotFoundError:
        raise HTTPException(404, _NOT_FOUND_DETAIL) from None
    except ThesisNotFoundError:
        raise HTTPException(404, _THESIS_NOT_FOUND_DETAIL) from None
    except CampaignThesisArchivedError:
        raise HTTPException(409, _THESIS_ARCHIVED_DETAIL) from None
    except CampaignThesisFormalIncompleteError:
        raise HTTPException(409, _THESIS_FORMAL_INCOMPLETE_DETAIL) from None
    except CampaignThesisStrategyConflictError as exc:
        raise HTTPException(409, _strategy_conflict_detail(exc)) from None
    except CampaignThesisBindingConflictError:
        raise HTTPException(409, _BINDING_CONFLICT_DETAIL) from None
    except CampaignServiceError:
        raise HTTPException(500, _INTERNAL_ERROR_DETAIL) from None
    except Exception:  # noqa: BLE001 — 未预期逃逸，安全兜底
        raise HTTPException(500, _INTERNAL_ERROR_DETAIL) from None
    return {"data": binding}


@router.get("/campaigns/{campaign_id}/thesis-binding")
def get_campaign_thesis_binding(campaign_id: str) -> dict:
    """读取 Campaign 的 thesis binding；未绑定 → 404。"""
    try:
        binding = campaign_service.get_campaign_thesis_binding(campaign_id)
    except CampaignInputError:
        raise HTTPException(422, _INVALID_INPUT_DETAIL) from None
    except ThesisBindingNotFoundError:
        raise HTTPException(404, _BINDING_NOT_FOUND_DETAIL) from None
    except CampaignServiceError:
        raise HTTPException(500, _INTERNAL_ERROR_DETAIL) from None
    except Exception:  # noqa: BLE001 — 未预期逃逸，安全兜底
        raise HTTPException(500, _INTERNAL_ERROR_DETAIL) from None
    return {"data": binding}


@router.get("/campaigns/{campaign_id}/current-thesis")
def get_current_thesis(campaign_id: str) -> dict:
    """Current Formal Thesis Projection（P0-S2D-D，只读）。

    Campaign → immutable binding → Formal Thesis：
    - 未绑定 → 404；未冻结 → 200 + ready=false / NOT_READY / NOT_FROZEN；
    - 冻结 → 200 + Formal Original（frozen_revision snapshot）+ deltas +
      effective_state；
    - thesis.strategy 与 binding.campaign_strategy_at_bind 不一致 → 409
      semantic conflict；
    - ledger 缺失/损坏/不一致 → 500（fail-closed，绝不 silent truncate）。
    """
    try:
        projection = formal_thesis_projection.project_current_thesis(campaign_id)
    except CampaignInputError:
        raise HTTPException(422, _INVALID_INPUT_DETAIL) from None
    except CampaignNotFoundError:
        raise HTTPException(404, _NOT_FOUND_DETAIL) from None
    except ThesisBindingNotFoundError:
        raise HTTPException(404, _BINDING_NOT_FOUND_DETAIL) from None
    except ThesisNotFoundError:
        raise HTTPException(404, _THESIS_NOT_FOUND_DETAIL) from None
    except CampaignThesisStrategyConflictError as exc:
        raise HTTPException(409, _strategy_conflict_detail(exc)) from None
    except CurrentThesisProjectionError:
        raise HTTPException(500, _INTERNAL_ERROR_DETAIL) from None
    except CampaignServiceError:
        raise HTTPException(500, _INTERNAL_ERROR_DETAIL) from None
    except Exception:  # noqa: BLE001 — 未预期逃逸，安全兜底
        raise HTTPException(500, _INTERNAL_ERROR_DETAIL) from None
    return {"data": projection}


@router.get("/campaigns/{campaign_id}/research-continuity")
def get_research_continuity(campaign_id: str) -> dict:
    """Read-only immutable evidence delta and next disclosure context."""
    try:
        result = research_continuity_service.get_research_continuity(campaign_id)
    except CampaignInputError:
        raise HTTPException(422, _INVALID_INPUT_DETAIL) from None
    except CampaignNotFoundError:
        raise HTTPException(404, _NOT_FOUND_DETAIL) from None
    except CampaignServiceError:
        raise HTTPException(500, _INTERNAL_ERROR_DETAIL) from None
    except Exception:  # noqa: BLE001 — stable safe boundary
        raise HTTPException(500, _INTERNAL_ERROR_DETAIL) from None
    return {"data": result}


@router.post("/campaigns/research-continuity/batch")
def get_research_continuity_batch(body: ResearchContinuityBatchIn) -> dict:
    """Read many Campaigns while fetching one disclosure calendar per security."""
    try:
        items = research_continuity_service.get_research_continuities(body.campaign_ids)
    except CampaignInputError:
        raise HTTPException(422, _INVALID_INPUT_DETAIL) from None
    except CampaignNotFoundError:
        raise HTTPException(404, _NOT_FOUND_DETAIL) from None
    except CampaignServiceError:
        raise HTTPException(500, _INTERNAL_ERROR_DETAIL) from None
    except Exception:  # noqa: BLE001 — stable safe boundary
        raise HTTPException(500, _INTERNAL_ERROR_DETAIL) from None
    return {"data": {"items": items}}
