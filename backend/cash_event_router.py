"""P0-S1B-B cash event HTTP API（POST/GET /api/account/cash-events）。

按任务书 §十五：不挂主 app.py（避免 stacked diff 扩大），wiring 标记为
MAIN_APP_ROUTER_WIRING = DEFERRED_TO_INTEGRATION；API 行为由 test-only FastAPI app 验证。
内部错误统一脱敏 500（不泄漏 SQLite 消息 / 路径 / traceback / SQL）。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request

import account_event_store
import cash_event_service as svc

router = APIRouter(prefix="/api", tags=["cash-events"])


async def _parse_json_body(request: Request) -> dict[str, Any]:
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="请求体必须是 JSON")
    if not isinstance(data, dict):
        raise HTTPException(status_code=422, detail="请求体必须是 JSON 对象")
    return data


@router.post("/account/cash-events")
async def create_cash_event(request: Request):
    try:
        payload = await _parse_json_body(request)
        event = svc.create_cash_event(payload)
    except HTTPException:
        raise
    except svc.CashEventValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except account_event_store.AccountEventCorruptedError:
        raise HTTPException(status_code=500, detail="内部错误")
    except Exception:
        raise HTTPException(status_code=500, detail="内部错误")
    return {"data": event}


@router.get("/account/cash-events")
async def list_cash_events():
    try:
        events = svc.list_cash_events()
    except account_event_store.AccountEventCorruptedError:
        raise HTTPException(status_code=500, detail="内部错误")
    except Exception:
        raise HTTPException(status_code=500, detail="内部错误")
    return {"data": events}


@router.get("/account/cash-events/{event_id}")
async def get_cash_event(event_id: str):
    try:
        event = svc.get_cash_event(event_id)
    except account_event_store.AccountEventCorruptedError:
        raise HTTPException(status_code=500, detail="内部错误")
    except Exception:
        raise HTTPException(status_code=500, detail="内部错误")
    if event is None:
        raise HTTPException(status_code=404, detail="现金事件不存在")
    return {"data": event}
