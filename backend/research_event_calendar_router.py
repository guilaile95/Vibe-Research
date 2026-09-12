"""HTTP boundary for the bounded, read-only Research Event Calendar."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

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
    return {"data": result}


__all__ = ["router"]
