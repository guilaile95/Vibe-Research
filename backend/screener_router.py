"""HTTP router for candidate signal screener v0.1.

Compatibility note: the recovered screener predates the current technical-indicators v0.2
module. Keep the historical limitation-prefix contract available without replacing the
current KDJ-capable implementation.
"""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

import technical_indicators as ti

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
