"""HTTP boundary for the read-only current portfolio risk context."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

import portfolio_risk_context as service


router = APIRouter(prefix="/api", tags=["portfolio-risk-context"])


@router.get("/portfolio/risk-context")
def get_portfolio_risk_context():
    try:
        return {"data": service.build_portfolio_risk_context()}
    except Exception:
        # Do not expose paths, provider URLs, SQL, or traceback details.
        raise HTTPException(status_code=500, detail="组合风险概览暂不可用") from None


__all__ = ["router"]
