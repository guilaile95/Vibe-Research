"""HTTP router for candidate signal screener v0.1.

Compatibility note: the recovered screener predates the current technical-indicators v0.2
module. Keep the historical limitation-prefix contract available without replacing the
current KDJ-capable implementation.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from typing import Literal

import technical_indicators as ti
import research_data_plane as rdp

if not hasattr(ti, "PRICE_RANGE_TRIGGER_UNAVAILABLE_PREFIX"):
    ti.PRICE_RANGE_TRIGGER_UNAVAILABLE_PREFIX = "价格区间触发不可评估"

import screener_service as svc
from screener_models import ScreenerEvaluateIn, ScreenerEvaluateOut, SectorRepresentativesOut

router = APIRouter(prefix="/api/screener", tags=["screener"])


@router.post("/evaluate", response_model=ScreenerEvaluateOut)
def evaluate_screener_endpoint(body: ScreenerEvaluateIn):
    """Evaluate technical conditions (AND) for up to 30 A-share codes."""
    try:
        return svc.evaluate_screener(body)
    except Exception:
        return JSONResponse(
            status_code=500,
            content={"detail": "筛选服务暂时不可用"},
        )


@router.get("/full-market")
def full_market_endpoint(
    as_of: str | None = Query(None),
    latest: bool = Query(True),
    filter_metric: str | None = Query(None),
    filter_operator: Literal["gt", "gte", "lt", "lte", "eq", "neq"] | None = Query(None),
    filter_value: float | None = Query(None),
    sort_by: str = Query("code"),
    sort_order: Literal["asc", "desc"] = Query("asc"),
    limit: int = Query(50, ge=1, le=rdp._MAX_LIMIT),
    offset: int = Query(0, ge=0),
):
    """Read-only Full Market mode; delegates to the RDP cross-section without per-stock evaluation."""
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


@router.get("/sources/sector-representatives", response_model=SectorRepresentativesOut)
def sector_representatives_endpoint():
    """Read-only list of sector representative codes from backend registry."""
    try:
        codes = svc.list_sector_representative_codes()
        return SectorRepresentativesOut(codes=codes, count=len(codes))
    except Exception:
        return JSONResponse(
            status_code=500,
            content={"detail": "读取板块代表公司失败"},
        )
