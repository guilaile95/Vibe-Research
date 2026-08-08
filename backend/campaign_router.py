"""Campaign API v0.1（P0-S2A：Campaign Core Identity & Strategy Boundary）。

只读 + 创建：
- ``POST /api/campaigns``：创建 Campaign（status 恒为服务端 DRAFT）
- ``GET  /api/campaigns``：确定性列表 + 可选过滤（security_code / strategy / status）
- ``GET  /api/campaigns/{campaign_id}``：精确读取

不存在 PATCH / PUT / DELETE —— Strategy 结构性不可变、生命周期迁移
（P0-S2B 或后续 Slice）不在本轮开放。

安全边界：
- 所有错误响应只返回稳定脱敏 detail，绝不泄漏 str(e) / SQL / 文件路径 / traceback；
- 未预期异常 → 500 固定文本。

本 router 可独立挂载测试（test-only FastAPI app）；app.py 接线由
集成 Slice 处理（MAIN_APP_ROUTER_WIRING = DEFERRED_TO_INTEGRATION）。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict
from typing import Literal

import campaign_service
from campaign_service import (
    CampaignConflictError,
    CampaignInputError,
    CampaignNotFoundError,
    CampaignServiceError,
)

router = APIRouter(prefix="/api", tags=["campaigns"])

# 稳定脱敏错误文案（客户端唯一可见内容）
_INVALID_INPUT_DETAIL = "Campaign 参数无效"
_NOT_FOUND_DETAIL = "Campaign 不存在"
_CONFLICT_DETAIL = "Campaign 已存在"
_INTERNAL_ERROR_DETAIL = "Campaign 服务暂不可用"


class CampaignCreateIn(BaseModel):
    """创建 Campaign 请求体：status 由服务端决定，不接受客户端伪造。"""

    model_config = ConfigDict(extra="forbid")

    security_code: str
    strategy: Literal["SHORT", "SWING", "MEDIUM"]


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
