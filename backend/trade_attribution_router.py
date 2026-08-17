"""P0-TAR1 Manual Trade attribution and reconciliation API."""

from __future__ import annotations

from fastapi import APIRouter, Body, HTTPException

import formal_trade_attribution_store as attribution_store
import trade_attribution_runtime as runtime
import trade_ledger_store
import trade_origin_store

router = APIRouter(prefix="/api", tags=["trade-attribution"])


def _error(exc: Exception) -> HTTPException:
    if isinstance(exc, runtime.TradeAttributionNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, (runtime.TradeAttributionConflictError, attribution_store.FormalTradeAttributionStoreConflictError, trade_origin_store.TradeOriginStoreConflictError)):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, (runtime.TradeAttributionValidationError, ValueError)):
        return HTTPException(status_code=422, detail=str(exc))
    if isinstance(exc, (attribution_store.FormalTradeAttributionStoreError, trade_origin_store.TradeOriginStoreError, trade_ledger_store.TradeLedgerCorruptedError)):
        return HTTPException(status_code=500, detail="交易归属权威数据损坏，已停止读写")
    return HTTPException(status_code=500, detail="交易归属运行时失败")


@router.get("/trades/{trade_id}/attribution-candidates")
async def attribution_candidates(trade_id: str):
    try:
        return {"data": runtime.list_candidates(trade_id)}
    except Exception as exc:
        raise _error(exc)


@router.post("/trades/{trade_id}/attribution")
async def create_attribution(trade_id: str, body: object = Body(...)):
    try:
        return {"data": runtime.attribute(trade_id, body)}
    except Exception as exc:
        raise _error(exc)


@router.post("/trades/{trade_id}/unplanned")
async def mark_unplanned(trade_id: str, body: object = Body(...)):
    try:
        return {"data": runtime.mark_unplanned(trade_id, body)}
    except Exception as exc:
        raise _error(exc)


@router.get("/trades/{trade_id}/reconciliation")
async def reconciliation(trade_id: str):
    try:
        return {"data": runtime.reconciliation_for_trade(trade_id)}
    except Exception as exc:
        raise _error(exc)
