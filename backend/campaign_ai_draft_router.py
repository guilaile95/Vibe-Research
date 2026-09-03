"""HTTP boundary for explicit Campaign AI Draft generation."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

import campaign_ai_draft_service as service
import campaign_service

router = APIRouter(prefix="/api", tags=["campaign-ai-draft"])

_INVALID_INPUT = "Campaign AI Draft 参数无效"
_CAMPAIGN_NOT_FOUND = "Campaign 不存在"
_CONTEXT_UNAVAILABLE = "Campaign / Current Thesis 上下文暂不可用，请先修复 authority"
_MODEL_ERROR = "AI Draft 模型调用失败"
_OUTPUT_ERROR = "AI Draft 模型输出无效"
_UNAVAILABLE = "Campaign AI Draft 暂不可用"


class DraftLlmConfigIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str = ""
    baseURL: str = ""
    apiKey: str = ""
    model: str


class CampaignAIDraftGenerateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    llm: DraftLlmConfigIn


@router.post("/campaigns/{campaign_id}/ai-draft/generate")
def generate_campaign_ai_draft(
    campaign_id: str, body: CampaignAIDraftGenerateIn
) -> dict[str, Any]:
    # app owns the existing LLMConfig and provider readiness boundary.
    # Import lazily because app includes this router before its LLM classes are
    # declared during module initialization.
    try:
        import app as app_module

        llm = app_module.LLMConfig.model_validate(body.llm.model_dump(mode="json"))
        app_module._require_llm_ready(llm)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(400, _INVALID_INPUT) from None
    try:
        result = service.generate_ai_draft(llm.model_dump(), campaign_id)
    except campaign_service.CampaignNotFoundError:
        raise HTTPException(404, _CAMPAIGN_NOT_FOUND) from None
    except service.CampaignAIDraftContextError:
        raise HTTPException(409, _CONTEXT_UNAVAILABLE) from None
    except service.CampaignAIDraftOutputError:
        raise HTTPException(502, _OUTPUT_ERROR) from None
    except service.CampaignAIDraftModelError:
        raise HTTPException(502, _MODEL_ERROR) from None
    except service.CampaignAIDraftInputError:
        raise HTTPException(422, _INVALID_INPUT) from None
    except campaign_service.CampaignServiceError:
        raise HTTPException(500, _UNAVAILABLE) from None
    except Exception:
        raise HTTPException(500, _UNAVAILABLE) from None
    return {"data": result}


__all__ = ["router", "CampaignAIDraftGenerateIn"]
