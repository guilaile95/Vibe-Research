"""Research-only HTTP routes; no provider calls or archive mutation."""
from fastapi import APIRouter, HTTPException, Query, Request
from fact_lake_store import FactLakeObservationConflictError, FactLakeNotInitializedError
from shortline_regime_annotations import save_regime_annotation
import shortline_research_service as service

router = APIRouter(prefix="/api/market/shortline-research", tags=["shortline-research"])


@router.get("")
def get_shortline_research(request: Request, trade_date: str = Query(...)):
    if set(request.query_params) != {"trade_date"} or len(request.query_params.getlist("trade_date")) != 1:
        raise HTTPException(status_code=422, detail="仅接受一个trade_date；不接受路径、as_of或隐式采集参数")
    try:
        return {"data": service.query_shortline_research(trade_date)}
    except ValueError:
        raise HTTPException(status_code=422, detail="trade_date必须为有效YYYY-MM-DD日期") from None


@router.post("/regime-events")
async def post_regime_event(request: Request):
    if request.query_params:
        raise HTTPException(status_code=422, detail="不支持路径或其他查询参数")
    parts, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > 10000:
            raise HTTPException(status_code=413, detail="记录内容过大")
        parts.append(chunk)
    body = b"".join(parts)
    try:
        from shortline_research_contract import decode
        return {"data": save_regime_annotation(decode(body))}
    except FactLakeObservationConflictError:
        raise HTTPException(status_code=409, detail="此保存标识已用于不同内容，请重新提交新记录") from None
    except (ValueError, TypeError, KeyError):
        raise HTTPException(status_code=422, detail="记录字段、日期或来源链接无效，或研究归档尚未配置") from None
    except FactLakeNotInitializedError:
        raise HTTPException(status_code=409, detail="研究归档尚未初始化；未自动创建") from None
    except Exception:
        raise HTTPException(status_code=503, detail="归档暂不可写，记录未确认保存") from None
