"""HTTP adapter for user-triggered Campaign AI decision drafts."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

import campaign_service
import decision_commit_runtime
import decision_draft_service


router = APIRouter(prefix="/api", tags=["decision-draft"])


class LLMConfigIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str = ""
    baseURL: str = ""
    apiKey: str = ""
    model: str


class DecisionDraftGenerateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    llm: LLMConfigIn
    focus: str | None = None


@router.post("/campaigns/{campaign_id}/decision-draft")
def generate_decision_draft(
    campaign_id: str, body: DecisionDraftGenerateIn
) -> dict:
    if not body.llm.model.strip():
        raise HTTPException(400, "缺少模型配置，请先在「接入 AI」里选择")
    try:
        result = decision_draft_service.generate_campaign_decision_draft(
            campaign_id,
            body.llm.model_dump(mode="json"),
            focus=body.focus,
        )
    except campaign_service.CampaignNotFoundError:
        raise HTTPException(404, "Campaign 不存在") from None
    except (
        decision_draft_service.DecisionDraftUnavailableError,
        decision_commit_runtime.CurrentThesisUnavailableError,
    ) as exc:
        raise HTTPException(409, str(exc) or "AI 草案上下文当前不可用") from None
    except decision_draft_service.DecisionDraftModelError:
        raise HTTPException(502, "AI 草案生成失败") from None
    except decision_draft_service.DecisionDraftModelOutputError:
        raise HTTPException(502, "AI 草案输出不符合严格结构") from None
    except decision_draft_service.DecisionDraftPersistError:
        raise HTTPException(500, "AI 草案持久化失败") from None
    except decision_commit_runtime.DecisionCommitRuntimeError:
        raise HTTPException(500, "AI 草案上下文读取失败") from None
    except Exception:  # noqa: BLE001 - stable fail-closed boundary
        raise HTTPException(500, "AI 草案暂不可用") from None
    return {"data": result}


__all__ = ["router"]
