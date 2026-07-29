"""Decision analytics REST API (P2-4A).

GET /api/decision-analytics/adoption  -> adoption summary
GET /api/decision-analytics/outcome   -> outcome summary
GET /api/decision-analytics/stocks    -> per-stock summary
"""
from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException, Query

import decision_analytics_service as _svc
import decision_feedback_service as _fb_svc

router = APIRouter(prefix="/api/decision-analytics", tags=["decision-analytics"])

_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _validate_date(val: str | None, field: str) -> str | None:
    if val is None:
        return None
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", val):
        raise HTTPException(
            status_code=422,
            detail=f"非法 {field}，格式须为 YYYY-MM-DD",
        )
    return val


@router.get("/adoption")
def get_adoption_summary(
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
):
    """Return adoption status distribution."""
    date_from = _validate_date(date_from, "date_from")
    date_to = _validate_date(date_to, "date_to")
    try:
        result = _svc.get_adoption_summary(date_from=date_from, date_to=date_to)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"data": result}


@router.get("/outcome")
def get_outcome_summary(
    adoption_status: str | None = Query(None),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
):
    """Return outcome status distribution."""
    date_from = _validate_date(date_from, "date_from")
    date_to = _validate_date(date_to, "date_to")

    if adoption_status is not None and adoption_status not in _fb_svc.ADOPTION_STATUSES:
        raise HTTPException(
            status_code=422,
            detail=f"非法 adoption_status，须为 {sorted(_fb_svc.ADOPTION_STATUSES)} 之一",
        )

    try:
        result = _svc.get_outcome_summary(
            adoption_status=adoption_status,
            date_from=date_from,
            date_to=date_to,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"data": result}


@router.get("/stocks")
def get_stock_summary(
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
):
    """Return per-stock adoption+outcome aggregation."""
    date_from = _validate_date(date_from, "date_from")
    date_to = _validate_date(date_to, "date_to")

    try:
        result = _svc.get_stock_summary(date_from=date_from, date_to=date_to, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"data": result}
