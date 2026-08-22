"""Account execution policy REST API (P2-3).

GET  /api/account-execution-policy        → 返回当前策略 (200)
PUT  /api/account-execution-policy        → 更新策略 (200，body=已保存的策略)
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

import account_execution_policy as _svc

router = APIRouter(prefix="/api", tags=["account-execution-policy"])


class AccountExecutionPolicyModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lot_size: int
    min_cash_reserve_pct: float
    max_single_stock_allocation_pct: float
    tie_breaker_order: str
    allow_partial_execution: bool


@router.get("/account-execution-policy")
def get_policy() -> dict:
    return _svc.get_account_execution_policy_status()


@router.put("/account-execution-policy")
def update_policy(body: AccountExecutionPolicyModel) -> dict:
    try:
        saved = _svc.save_account_execution_policy(body.model_dump())
        return {"status": "configured", "data": saved, "reason_code": None}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
