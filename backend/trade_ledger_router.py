"""Trade ledger HTTP API."""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

import trade_ledger_service as svc
import trade_ledger_store as store

router = APIRouter(prefix="/api", tags=["trades"])

_CODE_RE = re.compile(r"^[0-9]{6}$")
_OPERATIONS = frozenset({"buy", "add", "reduce", "sell"})
_EXECUTION_STATUSES = frozenset({"full", "partial", "not_executed"})


def _parse_strict_include_voided(request: Request) -> bool:
    values = request.query_params.getlist("include_voided")
    if not values:
        return False
    if len(values) > 1:
        raise HTTPException(status_code=422, detail="include_voided 仅允许单个值")
    raw = values[0]
    if raw == "true":
        return True
    if raw == "false":
        return False
    raise HTTPException(status_code=422, detail="非法参数 include_voided")


def _validate_date_str(val: str, field_name: str) -> str:
    if not isinstance(val, str) or not re.fullmatch(r"^\d{4}-\d{2}-\d{2}$", val):
        raise HTTPException(status_code=422, detail=f"非法 {field_name}，格式须为 YYYY-MM-DD")
    try:
        y, m, d = map(int, val.split("-"))
        date(y, m, d)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"非法 {field_name} 日期")
    return val


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
    except store.TradeLedgerSchemaError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except store.TradeLedgerCorruptedError:
        raise HTTPException(status_code=500, detail="交易流水数据损坏，已停止读写")
    return {"data": record}


@router.get("/trades")
async def list_trades(
    request: Request,
    code: str | None = None,
    operation: str | None = None,
    execution_status: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    include_voided = _parse_strict_include_voided(request)

    if code is not None:
        if not isinstance(code, str) or not _CODE_RE.fullmatch(code.strip()):
            raise HTTPException(status_code=422, detail="非法 code 筛选参数")
        code = code.strip()

    if operation is not None:
        if operation not in _OPERATIONS:
            raise HTTPException(status_code=422, detail="非法 operation 筛选参数")

    if execution_status is not None:
        if execution_status not in _EXECUTION_STATUSES:
            raise HTTPException(status_code=422, detail="非法 execution_status 筛选参数")

    validated_date_from = None
    if date_from is not None:
        validated_date_from = _validate_date_str(date_from, "date_from")

    validated_date_to = None
    if date_to is not None:
        validated_date_to = _validate_date_str(date_to, "date_to")

    if validated_date_from and validated_date_to and validated_date_from > validated_date_to:
        raise HTTPException(status_code=422, detail="date_from 不能大于 date_to")

    try:
        records = svc.list_trades(
            code=code,
            operation=operation,
            execution_status=execution_status,
            date_from=validated_date_from,
            date_to=validated_date_to,
            include_voided=include_voided,
            limit=limit,
            offset=offset,
        )
    except svc.TradeValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except store.TradeLedgerCorruptedError:
        raise HTTPException(status_code=500, detail="交易流水数据损坏，已停止读写")

    return {"data": records}


@router.get("/trades/{trade_id}")
async def get_trade(trade_id: str):
    try:
        record = svc.get_trade(trade_id)
    except store.TradeLedgerCorruptedError:
        raise HTTPException(status_code=500, detail="交易流水数据损坏，已停止读写")

    if record is None:
        raise HTTPException(status_code=404, detail="交易记录不存在")
    return {"data": record}


@router.post("/trades/{trade_id}/void")
async def void_trade(trade_id: str, request: Request):
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="请求体必须是 JSON")
    if not isinstance(data, dict):
        raise HTTPException(status_code=422, detail="请求体必须是 JSON 对象")
    reason = data.get("reason")
    if not reason or not isinstance(reason, str) or not reason.strip():
        raise HTTPException(status_code=422, detail="reason 必填")
    try:
        record = svc.void_trade(trade_id, reason.strip())
    except (svc.TradeNotFoundError, store.TradeNotFoundError):
        raise HTTPException(status_code=404, detail="交易记录不存在")
    except (svc.TradeAlreadyVoidedError, store.TradeAlreadyVoidedError):
        raise HTTPException(status_code=409, detail="交易记录已作废")
    except svc.TradeValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except store.TradeLedgerCorruptedError:
        raise HTTPException(status_code=500, detail="交易流水数据损坏，已停止读写")
    return {"data": record}
