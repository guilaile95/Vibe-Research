"""Archive-only seal-quality GET under the application's local API boundary."""
from fastapi import APIRouter, HTTPException, Query, Request

import short_term_seal_quality_service as service

router = APIRouter(prefix="/api/market/seal-quality", tags=["seal-quality"])


@router.get("")
def get_seal_quality(request: Request, trade_date: str = Query(...)):
    if set(request.query_params) != {"trade_date"} or len(request.query_params.getlist("trade_date")) != 1:
        raise HTTPException(status_code=422, detail="仅允许一个 trade_date；不支持路径、时点或其他选择参数")
    try:
        result = service.query_seal_quality(trade_date)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return {"data": result}
