"""HTTP router for candidate signal screener v0.1."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

import screener_service as svc
from screener_models import ScreenerEvaluateIn

router = APIRouter(prefix="/api/screener", tags=["screener"])


@router.post("/evaluate")
def evaluate_screener_endpoint(body: ScreenerEvaluateIn):
    """Evaluate technical conditions (AND) for up to 30 A-share codes."""
    try:
        result = svc.evaluate_screener(body)
        return result
    except Exception:
        return JSONResponse(
            status_code=500,
            content={"detail": "筛选服务暂时不可用"},
        )
