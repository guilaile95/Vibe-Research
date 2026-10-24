"""HTTP boundary for explicit Campaign AI Draft generation."""
from __future__ import annotations

from typing import Any, Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

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
    revision: str | None = None
    model_config = ConfigDict(extra="forbid")

    provider: str = ""
    baseURL: str = ""
    apiKey: str = ""
    model: str


class CampaignAIDraftGenerateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    llm: DraftLlmConfigIn
    confirm_private_context: Literal[True]
    expected_context_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("confirm_private_context", mode="before")
    @classmethod
    def explicit_boolean(cls, value):
        if value is not True:
            raise ValueError("Explicit private-context confirmation required")
        return value


@router.post("/campaigns/{campaign_id}/ai-draft/consent-preview")
def preview_campaign_ai_draft_consent(campaign_id: str) -> dict[str, Any]:
    try:
        return {"data": service.preview_ai_draft_consent(campaign_id)}
    except campaign_service.CampaignNotFoundError:
        raise HTTPException(404, _CAMPAIGN_NOT_FOUND) from None
    except Exception:
        raise HTTPException(409, _CONTEXT_UNAVAILABLE) from None


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
        if llm.provider != "cli-codex":
            destination = urlsplit(llm.baseURL)
            if (destination.scheme not in {"http", "https"} or not destination.hostname
                    or destination.username is not None or destination.password is not None
                    or destination.query or destination.fragment):
                raise HTTPException(400, "模型接收地址不得含账号、密码、查询参数或片段")
        app_module._require_llm_ready(llm)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(400, _INVALID_INPUT) from None
    try:
        result = service.generate_ai_draft(llm.model_dump(), campaign_id, expected_context_fingerprint=body.expected_context_fingerprint)
    except campaign_service.CampaignNotFoundError:
        raise HTTPException(404, _CAMPAIGN_NOT_FOUND) from None
    except service.CampaignAIDraftWitnessStaleError:
        raise HTTPException(409, "私人上下文已改变，请重新确认后生成") from None
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
