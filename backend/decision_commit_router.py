"""P0-DC1 Decision Proposal preview / explicit commit / read-back API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

import campaign_ai_draft_service as ai_draft_service
import campaign_service
import decision_commit_runtime as runtime


router = APIRouter(prefix="/api", tags=["decision-commit"])

_INVALID_INPUT = "Formal Decision 参数无效"
_CAMPAIGN_NOT_FOUND = "Campaign 不存在"
_THESIS_UNAVAILABLE = "Current Thesis 尚未完成同一 Campaign 的 Formal 评估"
_STALE_PROPOSAL = "Formal Decision Proposal 已失效，请重新预览"
_CONFIRMATION_REQUIRED = "必须显式确认后才能冻结 Formal Decision"
_COMMIT_UNAVAILABLE = "Formal Decision 提交暂不可用"
_DECISION_NOT_FOUND = "Frozen Decision 不存在"
_CHALLENGE_BIND = "Decision Challenge 无法绑定到这次 Freeze"


class DecisionProposalPreviewIn(BaseModel):
    """Only user-owned draft views and explicit commit fields are accepted."""

    model_config = ConfigDict(extra="forbid")

    asset_view: dict[str, Any]
    trade_view: dict[str, Any]
    portfolio_view: dict[str, Any]
    review_by: str
    key_assumptions: list[Any]
    event_invalidation_conditions: list[Any]
    strategy_horizon: str
    draft_witness: dict[str, Any] | None = None


class DecisionProposalCommitIn(DecisionProposalPreviewIn):
    model_config = ConfigDict(extra="forbid")

    as_of: str
    expected_proposal_fingerprint: str
    user_confirmed: bool
    challenge_id: str | None = None


def _draft_payload(body: DecisionProposalPreviewIn) -> dict[str, Any]:
    return body.model_dump(mode="json")


@router.post("/campaigns/{campaign_id}/decision-proposal/preview")
def preview_decision_proposal(
    campaign_id: str, body: DecisionProposalPreviewIn
) -> dict[str, Any]:
    try:
        result = runtime.preview_decision_proposal(
            campaign_id,
            _draft_payload(body),
        )
    except campaign_service.CampaignNotFoundError:
        raise HTTPException(404, _CAMPAIGN_NOT_FOUND) from None
    except runtime.DecisionCommitInputError:
        raise HTTPException(422, _INVALID_INPUT) from None
    except runtime.ProposalStaleError:
        raise HTTPException(409, _STALE_PROPOSAL) from None
    except runtime.CurrentThesisUnavailableError:
        raise HTTPException(409, _THESIS_UNAVAILABLE) from None
    except campaign_service.CampaignServiceError:
        raise HTTPException(500, _COMMIT_UNAVAILABLE) from None
    except runtime.DecisionCommitRuntimeError:
        raise HTTPException(500, _COMMIT_UNAVAILABLE) from None
    except Exception:  # noqa: BLE001 — stable fail-closed boundary
        raise HTTPException(500, _COMMIT_UNAVAILABLE) from None
    return {"data": result}


@router.post("/campaigns/{campaign_id}/decision-proposal/commit")
def commit_decision_proposal(
    campaign_id: str, body: DecisionProposalCommitIn
) -> dict[str, Any]:
    if body.user_confirmed is not True:
        raise HTTPException(422, _CONFIRMATION_REQUIRED)
    try:
        result = runtime.commit_decision_proposal(
            campaign_id,
            body.model_dump(mode="json"),
        )
    except campaign_service.CampaignNotFoundError:
        raise HTTPException(404, _CAMPAIGN_NOT_FOUND) from None
    except runtime.CommitConfirmationRequiredError:
        raise HTTPException(422, _CONFIRMATION_REQUIRED) from None
    except runtime.ProposalStaleError:
        raise HTTPException(409, _STALE_PROPOSAL) from None
    except ai_draft_service.CampaignAIDraftWitnessStaleError:
        raise HTTPException(409, _STALE_PROPOSAL) from None
    except runtime.ChallengeBindingError:
        raise HTTPException(409, _CHALLENGE_BIND) from None
    except runtime.DecisionCommitInputError:
        raise HTTPException(422, _INVALID_INPUT) from None
    except runtime.CurrentThesisUnavailableError:
        raise HTTPException(409, _STALE_PROPOSAL) from None
    except (
        runtime.FrozenDecisionIntegrityError,
        campaign_service.CampaignServiceError,
    ):
        raise HTTPException(500, _COMMIT_UNAVAILABLE) from None
    except runtime.DecisionCommitRuntimeError:
        raise HTTPException(500, _COMMIT_UNAVAILABLE) from None
    except Exception:  # noqa: BLE001 — stable fail-closed boundary
        raise HTTPException(500, _COMMIT_UNAVAILABLE) from None
    return {"data": result}


@router.get("/campaigns/{campaign_id}/decision-proposal/committed/{decision_id}")
def get_committed_decision(campaign_id: str, decision_id: str) -> dict[str, Any]:
    try:
        result = runtime.get_committed_decision(campaign_id, decision_id)
    except campaign_service.CampaignNotFoundError:
        raise HTTPException(404, _CAMPAIGN_NOT_FOUND) from None
    except runtime.DecisionCommitInputError:
        raise HTTPException(422, _INVALID_INPUT) from None
    except runtime.FrozenDecisionIntegrityError:
        raise HTTPException(404, _DECISION_NOT_FOUND) from None
    except runtime.CurrentThesisUnavailableError:
        raise HTTPException(409, _THESIS_UNAVAILABLE) from None
    except campaign_service.CampaignServiceError:
        raise HTTPException(500, _COMMIT_UNAVAILABLE) from None
    except runtime.DecisionCommitRuntimeError:
        raise HTTPException(500, _COMMIT_UNAVAILABLE) from None
    except Exception:  # noqa: BLE001 — stable fail-closed boundary
        raise HTTPException(500, _COMMIT_UNAVAILABLE) from None
    return {"data": result}


__all__ = ["router"]
