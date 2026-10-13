"""Read-only archived membership navigation under existing local API guards."""
from fastapi import APIRouter, HTTPException, Query, Request
import cohort_identity_service as service

router = APIRouter(prefix="/api/market/cohort-identity", tags=["cohort-identity"])


@router.get("")
def get_cohort_identity(request: Request, trade_date: str = Query(...)):
    if set(request.query_params) != {"trade_date"} or len(request.query_params.getlist("trade_date")) != 1:
        raise HTTPException(status_code=422, detail="仅允许一个 trade_date；不支持路径、时点或其他选择参数")
    try:
        return {"data": service.query_cohort_identity(trade_date)}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
