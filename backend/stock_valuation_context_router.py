"""HTTP boundary for the read-only Stock Valuation Context."""

from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException, Query

import stock_valuation_context as service


router = APIRouter(prefix="/api/stock-valuation-context", tags=["stock-valuation-context"])
_CODE_RE = re.compile(r"^\d{6}$")


@router.get("")
def get_stock_valuation_context(code: str = Query(..., min_length=6, max_length=6)):
    normalized = code.strip()
    if not _CODE_RE.fullmatch(normalized):
        raise HTTPException(status_code=422, detail="code must be a six-digit A-share code")
    try:
        return service.build_stock_valuation_context(normalized)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception:
        raise HTTPException(status_code=500, detail="个股相对行业估值暂不可用") from None


__all__ = ["router"]
