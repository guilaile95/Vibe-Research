"""Exact-date inspection under the existing local API boundary."""
from fastapi import APIRouter, HTTPException, Query, Request
import evidence_readiness_service as service

router = APIRouter(prefix="/api/market/evidence-readiness", tags=["evidence-readiness"])


@router.get("")
def get_evidence_readiness(request: Request, trade_date: str = Query(...)):
    if set(request.query_params) != {"trade_date"} or len(request.query_params.getlist("trade_date")) != 1:
        raise HTTPException(status_code=422, detail="仅允许一个 trade_date；不支持路径、时点或其他选择参数")
    try:
        return {"data": service.query_evidence_readiness(trade_date)}
    except ValueError:
        raise HTTPException(status_code=422, detail="trade_date 必须为有效的 YYYY-MM-DD 日期") from None
    except Exception:
        # Never expose paths, credentials, provider text or SQLite errors.
        raise HTTPException(status_code=503, detail="归档检查暂不可用；未启动采集或修改数据") from None
