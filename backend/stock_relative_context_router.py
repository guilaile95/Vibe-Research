"""HTTP boundary for the read-only Stock Relative Context."""

from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException, Query

import stock_relative_context as service


router = APIRouter(prefix="/api/stock-relative-context", tags=["stock-relative-context"])
_CODE_RE = re.compile(r"^\d{6}$")


@router.get("")
def get_stock_relative_context(code: str = Query(..., min_length=6, max_length=6)):
    normalized = code.strip()
    if not _CODE_RE.fullmatch(normalized):
        raise HTTPException(status_code=422, detail="code must be a six-digit A-share code")
    try:
        return service.build_stock_relative_context(normalized)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception:
        # Do not expose paths, provider URLs, SQL, or tracebacks at the HTTP boundary.
        raise HTTPException(status_code=500, detail="个股相对表现暂不可用") from None


__all__ = ["router"]
