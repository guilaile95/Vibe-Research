"""P0-DCH1 Decision Challenge finalize / read API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict

import campaign_service
import decision_challenge_runtime as runtime
import decision_commit_runtime as commit_runtime


router = APIRouter(prefix="/api", tags=["decision-challenge"])

_INVALID_INPUT = "Decision Challenge 参数无效"
_CONFIRMATION_REQUIRED = "必须显式确认后才能冻结 Decision Challenge"
_STALE = "Decision Proposal 已失效，请重新预览后再 Finalize Challenge"
_UNAVAILABLE = "Decision Challenge 暂不可用"
_NOT_FOUND = "Decision Challenge 不存在"
_CAMPAIGN_NOT_FOUND = "Campaign 不存在"


class DimensionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    text: str = ""


class DecisionChallengeFinalizeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_proposal_fingerprint: str
    as_of: str
    user_confirmed: bool
    dimensions: dict[str, DimensionIn]
    asset_view: dict[str, Any]
    trade_view: dict[str, Any]
    portfolio_view: dict[str, Any]
    review_by: str
    key_assumptions: list[Any]
    event_invalidation_conditions: list[Any]
    strategy_horizon: str
    draft_witness: dict[str, Any] | None = None


@router.post("/campaigns/{campaign_id}/decision-challenge/finalize")
def finalize_decision_challenge(
    campaign_id: str, body: DecisionChallengeFinalizeIn
) -> dict[str, Any]:
    if body.user_confirmed is not True:
        raise HTTPException(422, _CONFIRMATION_REQUIRED)
    try:
        result = runtime.finalize_decision_challenge(
            campaign_id,
            body.model_dump(mode="json"),
        )
    except campaign_service.CampaignNotFoundError:
        raise HTTPException(404, _CAMPAIGN_NOT_FOUND) from None
    except runtime.DecisionChallengeConfirmationRequiredError:
        raise HTTPException(422, _CONFIRMATION_REQUIRED) from None
    except runtime.DecisionChallengeStaleError:
        raise HTTPException(409, _STALE) from None
    except runtime.DecisionChallengeReplayConflictError:
        raise HTTPException(409, "Decision Challenge 与已冻结 Packet 冲突") from None
    except (
        runtime.DecisionChallengeInputError,
        commit_runtime.DecisionCommitInputError,
    ):
        raise HTTPException(422, _INVALID_INPUT) from None
    except runtime.DecisionChallengeRuntimeError:
        raise HTTPException(500, _UNAVAILABLE) from None
    except Exception:  # noqa: BLE001 — stable fail-closed boundary
        raise HTTPException(500, _UNAVAILABLE) from None
    return {"data": result}


@router.get("/decision-challenges/{challenge_id}")
def get_decision_challenge(challenge_id: str) -> dict[str, Any]:
    try:
        result = runtime.get_decision_challenge(challenge_id)
    except runtime.DecisionChallengeInputError:
        raise HTTPException(422, _INVALID_INPUT) from None
    except runtime.DecisionChallengeNotFoundError:
        raise HTTPException(404, _NOT_FOUND) from None
    except runtime.DecisionChallengeRuntimeError:
        raise HTTPException(500, _UNAVAILABLE) from None
    except Exception:  # noqa: BLE001
        raise HTTPException(500, _UNAVAILABLE) from None
    return {"data": result}


@router.get("/campaigns/{campaign_id}/decision-challenge")
def get_decision_challenge_for_proposal(
    campaign_id: str,
    proposal_fingerprint: str = Query(min_length=64, max_length=64),
) -> dict[str, Any]:
    try:
        result = runtime.get_decision_challenge_for_proposal(
            campaign_id, proposal_fingerprint
        )
    except runtime.DecisionChallengeInputError:
        raise HTTPException(422, _INVALID_INPUT) from None
    except runtime.DecisionChallengeNotFoundError:
        raise HTTPException(404, _NOT_FOUND) from None
    except runtime.DecisionChallengeRuntimeError:
        raise HTTPException(500, _UNAVAILABLE) from None
    except Exception:  # noqa: BLE001
        raise HTTPException(500, _UNAVAILABLE) from None
    return {"data": result}


__all__ = ["router"]
