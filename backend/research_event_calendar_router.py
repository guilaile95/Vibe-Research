"""HTTP boundary for the bounded, read-only Research Event Calendar."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, StrictInt
import research_event_review as review

import research_event_calendar as service


router = APIRouter(prefix="/api", tags=["research-events"])

_INVALID_DETAIL = "Research Event Calendar 查询参数无效"
_UNAVAILABLE_DETAIL = "Research Event Calendar 暂不可用"


@router.get("/research-events")
def get_research_events(
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    event_types: list[str] | None = Query(None),
    campaign_ids: list[str] | None = Query(None),
    security_code: str | None = Query(None),
):
    """Return only a bounded projection; this endpoint has no write method."""
    try:
        result = service.build_research_event_calendar(
            date_from=date_from,
            date_to=date_to,
            event_types=event_types,
            campaign_ids=campaign_ids,
            security_code=security_code,
        )
    except service.ResearchEventCalendarValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except service.ResearchEventCalendarError:
        raise HTTPException(status_code=500, detail=_UNAVAILABLE_DETAIL) from None
    except Exception:
        raise HTTPException(status_code=500, detail=_UNAVAILABLE_DETAIL) from None
    for event in result["events"]:
        event["observation_hash"] = review.fingerprint(event)
        event["observation_receipt"] = review.issue_receipt(event)
    return {"data": result}


__all__ = ["router"]


class EventReviewBind(BaseModel):
    model_config = ConfigDict(extra="forbid")
    campaign_id: str
    thesis_id: str
    expected_thesis_revision: StrictInt = Field(gt=0)
    event_id: str
    event_type: str
    observation_receipt: str
    expected_observation_hash: str
    expectation: str = Field(min_length=1, max_length=2000)


class ReviewEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    edit_token: str


class EventReviewJudgment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: StrictInt = Field(gt=0)
    outcome: str
    reason: str = Field(min_length=1, max_length=2000)
    evidence: list[ReviewEvidence] = Field(min_length=1, max_length=20)


def _review_call(fn):
    try:
        return {"data": fn()}
    except review.ReviewConflict as exc:
        raise HTTPException(409, str(exc)) from None
    except (ValueError, LookupError) as exc:
        raise HTTPException(422, str(exc)) from None
    except Exception:
        raise HTTPException(503, "事件复核暂不可用，请确认 Campaign 已绑定正式研究逻辑后重试") from None


@router.get("/research-events/reviews/context/{campaign_id}")
def event_review_context(campaign_id: str):
    return _review_call(lambda: review.context(campaign_id))


@router.get("/research-events/reviews/history")
def event_review_history(
    security_code: str | None = Query(None),
    campaign_id: str | None = Query(None, max_length=150),
    cursor: str | None = Query(None, max_length=1000),
    limit: int = Query(50, ge=1, le=100),
):
    return _review_call(lambda: review.history(security_code=security_code, campaign_id=campaign_id,
                                             cursor=cursor, limit=limit))


@router.get("/research-events/reviews/{campaign_id}")
def event_reviews(campaign_id: str):
    return _review_call(lambda: review.list_reviews(campaign_id))


@router.post("/research-events/reviews")
def bind_event_review(payload: EventReviewBind):
    return _review_call(lambda: review.bind(payload.model_dump()))


@router.post("/research-events/reviews/{review_id}/judgment")
def judge_event_review(review_id: str, payload: EventReviewJudgment):
    return _review_call(lambda: review.judge(review_id, payload.model_dump()))
