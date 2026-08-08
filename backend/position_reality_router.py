"""P0-S1A position reality HTTP API (bootstrap / correction / derived / reconciliation)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request

import account_event_store
import position_reality_service as svc
import trade_ledger_store

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
    except Exception as exc:
        raise _map_errors(exc)
    return {"data": result}


@router.post("/position/correction")
async def create_correction(request: Request):
    try:
        payload = await _parse_json_body(request)
        result = svc.create_correction(payload)
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


@router.get("/position/reconciliation")
async def position_reconciliation():
    try:
        result = svc.reconcile_positions()
    except Exception as exc:
        raise _map_errors(exc)
    return {"data": result}
