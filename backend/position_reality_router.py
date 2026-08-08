"""P0-S1A position reality HTTP API (bootstrap / correction / derived / reconciliation)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request

import account_event_store
import position_reality_service as svc
import trade_ledger_service
import trade_ledger_store

_MAX_REASON_LEN = 500

router = APIRouter(prefix="/api", tags=["position-reality"])


async def _parse_json_body(request: Request) -> dict[str, Any]:
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="请求体必须是 JSON")
    if not isinstance(data, dict):
        raise HTTPException(status_code=422, detail="请求体必须是 JSON 对象")
    return data


def _map_errors(exc: Exception) -> HTTPException:
    if isinstance(exc, svc.PositionValidationError):
        return HTTPException(status_code=422, detail=str(exc))
    if isinstance(exc, trade_ledger_service.TradeValidationError):
        return HTTPException(status_code=422, detail=str(exc))
    if isinstance(exc, (svc.BootstrapAlreadyExistsError, svc.LedgerNotEmptyError)):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, svc.CorrectionTargetNotFoundError):
        return HTTPException(status_code=404, detail="修正目标不存在")
    if isinstance(exc, (svc.PositionDerivationError,)):
        return HTTPException(status_code=500, detail=str(exc))
    if isinstance(exc, account_event_store.AccountEventCorruptedError):
        return HTTPException(status_code=500, detail="账户事件数据损坏，已停止读写")
    if isinstance(exc, trade_ledger_store.TradeLedgerCorruptedError):
        return HTTPException(status_code=500, detail="交易流水数据损坏，已停止读写")
    return HTTPException(status_code=500, detail="内部错误")


@router.post("/position/bootstrap-preview")
async def bootstrap_preview(request: Request):
    try:
        payload = await _parse_json_body(request)
        result = svc.bootstrap_preview(payload)
    except svc.PositionValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"data": result}


@router.post("/position/bootstrap-commit")
async def bootstrap_commit(request: Request):
    try:
        payload = await _parse_json_body(request)
        result = svc.bootstrap_commit(payload)
    except HTTPException:
        # JSON 解析错误（400/422）原样返回，不得经 _map_errors 变成 500（P2-1）
        raise
    except Exception as exc:
        raise _map_errors(exc)
    return {"data": result}


@router.post("/position/correction")
async def create_correction(request: Request):
    try:
        payload = await _parse_json_body(request)
        result = svc.create_correction(payload)
    except HTTPException:
        raise
    except Exception as exc:
        raise _map_errors(exc)
    return {"data": result}


@router.get("/position/derived")
async def derived_positions():
    try:
        result = svc.derive_positions()
    except Exception as exc:
        raise _map_errors(exc)
    return {"data": result}


@router.post("/position/trades/{trade_id}/void")
async def void_trade_cascade(trade_id: str, request: Request):
    """作废一笔交易并级联作废指向它的 CORRECTION 事件（防止孤儿修正锁死账本）。"""
    try:
        payload = await _parse_json_body(request)
    except HTTPException:
        raise
    reason = payload.get("reason")
    if not reason or not isinstance(reason, str) or not reason.strip():
        raise HTTPException(status_code=422, detail="reason 必填且必须是非空字符串")
    if len(reason.strip()) > _MAX_REASON_LEN:
        raise HTTPException(status_code=422, detail=f"reason 超过最大长度 {_MAX_REASON_LEN}")
    try:
        result = svc.void_trade_with_cascade(trade_id, reason.strip())
    except svc.PositionValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except (trade_ledger_service.TradeNotFoundError, trade_ledger_store.TradeNotFoundError) as exc:
        raise HTTPException(status_code=404, detail="交易记录不存在")
    except (trade_ledger_service.TradeAlreadyVoidedError, trade_ledger_store.TradeAlreadyVoidedError) as exc:
        raise HTTPException(status_code=409, detail="交易记录已作废")
    except Exception as exc:
        raise _map_errors(exc)
    return {"data": result}


@router.get("/position/reconciliation")
async def position_reconciliation():
    try:
        result = svc.reconcile_positions()
    except Exception as exc:
        raise _map_errors(exc)
    return {"data": result}
