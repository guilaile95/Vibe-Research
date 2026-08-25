"""Read-only HTTP surface for the local research data plane."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

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


@router.get("/manifest")
def manifest():
    try:
        return rdp.read_manifest()
    except rdp.ResearchDataPlaneUnavailableError as exc:
        return rdp.build_unavailable_envelope(str(exc))
    except rdp.ResearchDataPlaneValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
