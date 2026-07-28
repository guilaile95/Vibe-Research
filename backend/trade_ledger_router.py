"""Trade ledger HTTP API."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

import trade_ledger_service as svc

router = APIRouter(prefix="/api", tags=["trades"])


def _parse_bool_param(name: str, raw: str | None) -> bool | None:
    if raw is None:
        return None
    if isinstance(raw, bool):
        return raw
    v = raw.strip()
    if v == "true":
        return True
    if v == "false":
        return False
    raise HTTPException(status_code=422, detail=f"非法参数 {name}")


@router.post("/trades")
async def create_trade(request: Request):
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="请求体必须是 JSON")
    try:
        record = svc.create_trade(data)
    except svc.TradeValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except svc.AdviceNotFoundError:
        raise HTTPException(status_code=404, detail="未找到对应交易日的持仓建议")
    except svc.AdviceConflictError:
        raise HTTPException(status_code=409, detail="建议已发生变化，generated_at 不一致")
    except svc.AdviceHoldingNotFoundError:
        raise HTTPException(status_code=404, detail="建议中未找到该股票代码")
    except svc.ThesisNotFoundError:
        raise HTTPException(status_code=404, detail="未找到投资逻辑")
    except svc.ThesisRevisionNotFoundError:
        raise HTTPException(status_code=404, detail="未找到投资逻辑版本")
    return {"data": record}


@router.get("/trades")
async def list_trades(
    code: str | None = None,
    operation: str | None = None,
    execution_status: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    include_voided: bool | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    include_voided_bool = _parse_bool_param("include_voided", include_voided) if include_voided is not None else False
    try:
        records = svc.list_trades(
            code=code,
            operation=operation,
            execution_status=execution_status,
            date_from=date_from,
            date_to=date_to,
            include_voided=include_voided_bool,
            limit=limit,
            offset=offset,
        )
    except svc.TradeValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"data": records}


@router.get("/trades/{trade_id}")
async def get_trade(trade_id: str):
    record = svc.get_trade(trade_id)
    if record is None:
        raise HTTPException(status_code=404, detail="交易记录不存在")
    return {"data": record}


@router.post("/trades/{trade_id}/void")
async def void_trade(trade_id: str, request: Request):
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="请求体必须是 JSON")
    reason = data.get("reason") if isinstance(data, dict) else None
    if not reason or not isinstance(reason, str) or not reason.strip():
        raise HTTPException(status_code=422, detail="reason 必填")
    try:
        record = svc.void_trade(trade_id, reason.strip())
    except svc.TradeNotFoundError:
        raise HTTPException(status_code=404, detail="交易记录不存在")
    except svc.TradeAlreadyVoidedError:
        raise HTTPException(status_code=409, detail="交易记录已作废")
    except svc.TradeValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"data": record}
