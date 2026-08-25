"""Read-only HTTP surface for the local research data plane."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from typing import Literal

import research_data_plane as rdp

router = APIRouter(prefix="/api/research-data", tags=["research-data"])


@router.get("/daily-bars")
def daily_bars(
    code: str | None = Query(None),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    limit: int = Query(200, ge=1, le=rdp._MAX_LIMIT),
    offset: int = Query(0, ge=0),
):
    try:
        return rdp.query_daily_bars(
            code=code,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
            offset=offset,
        )
    except rdp.ResearchDataPlaneUnavailableError as exc:
        return rdp.build_unavailable_envelope(str(exc))
    except rdp.ResearchDataPlaneValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/full-market")
def full_market(
    as_of: str | None = Query(None),
    latest: bool = Query(True),
    filter_metric: str | None = Query(None),
    filter_operator: Literal["gt", "gte", "lt", "lte", "eq", "neq"] | None = Query(None),
    filter_value: float | None = Query(None),
    sort_by: str = Query("code"),
    sort_order: Literal["asc", "desc"] = Query("asc"),
    limit: int = Query(200, ge=1, le=rdp._MAX_LIMIT),
    offset: int = Query(0, ge=0),
):
    """Bounded set-based full-market cross-section over the local RDP artifact."""
    try:
        return rdp.query_full_market(
            as_of=as_of,
            latest=latest,
            filter_metric=filter_metric,
            filter_operator=filter_operator,
            filter_value=filter_value,
            sort_by=sort_by,
            sort_order=sort_order,
            limit=limit,
            offset=offset,
        )
    except rdp.ResearchDataPlaneUnavailableError as exc:
        return rdp.build_full_market_unavailable_envelope(str(exc), as_of=as_of)
    except rdp.ResearchDataPlaneQueryValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except rdp.ResearchDataPlaneValidationError as exc:
        return rdp.build_full_market_unavailable_envelope(
            f"Full Market 数据校验失败：{exc}",
            as_of=as_of,
        )


@router.get("/manifest")
def manifest():
    try:
        return rdp.read_manifest()
    except rdp.ResearchDataPlaneUnavailableError as exc:
        return rdp.build_unavailable_envelope(str(exc))
    except rdp.ResearchDataPlaneValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
