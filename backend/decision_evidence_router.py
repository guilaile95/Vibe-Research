"""Decision evidence HTTP API router.

Provides read-only access to decision trace runs, evidence items, and explanations.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

import decision_evidence_service as svc
import decision_trace_store as store

router = APIRouter(prefix="/api", tags=["decision-evidence"])

_CODE_RE = re.compile(r"^[0-9]{6}$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# result_type 集中允许值；未知值返回稳定 400，不向前端泄漏内部状态。
_ALLOWED_RESULT_TYPES = {"portfolio_advice", "top_risk_analysis"}


def _validate_date_str(val: str, field_name: str) -> str:
    if not isinstance(val, str) or not _DATE_RE.fullmatch(val.strip()):
        raise HTTPException(status_code=400, detail=f"非法 {field_name}，格式须为 YYYY-MM-DD")
    try:
        y, m, d = map(int, val.strip().split("-"))
        date(y, m, d)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"非法 {field_name} 日期")
    return val.strip()


def _check_allowed_params(request: Request, allowed_params: set[str]) -> None:
    unknown = set(request.query_params.keys()) - allowed_params
    if unknown:
        raise HTTPException(status_code=400, detail=f"未知筛选参数: {', '.join(sorted(unknown))}")


@router.get("/decision-evidence")
async def list_decision_evidence(
    request: Request,
    code: str | None = None,
    trade_date: str | None = None,
    quality_status: str | None = None,
    trace_status: str | None = None,
    result_type: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    _check_allowed_params(
        request, {"code", "trade_date", "quality_status", "trace_status", "result_type", "limit", "offset"}
    )

    if code is not None:
        if not isinstance(code, str) or not _CODE_RE.fullmatch(code.strip()):
            raise HTTPException(status_code=400, detail="非法 code 筛选参数，必须为6位数字代码")
        code = code.strip()

    if trade_date is not None:
        trade_date = _validate_date_str(trade_date, "trade_date")

    if quality_status is not None:
        if quality_status not in svc.VALID_QUALITY_STATUSES:
            raise HTTPException(status_code=400, detail=f"非法 quality_status 参数，须为: {', '.join(svc.VALID_QUALITY_STATUSES)}")

    if trace_status is not None:
        valid_trace_statuses = {"archived", "failed", "partial"}
        if trace_status not in valid_trace_statuses:
            raise HTTPException(status_code=400, detail=f"非法 trace_status 参数，须为: {', '.join(sorted(valid_trace_statuses))}")

    if result_type is not None:
        if result_type not in _ALLOWED_RESULT_TYPES:
            raise HTTPException(
                status_code=400,
                detail=f"非法 result_type 参数，须为: {', '.join(sorted(_ALLOWED_RESULT_TYPES))}",
            )

    try:
        res = store.list_evidence_items(
            code=code,
            trade_date=trade_date,
            quality_status=quality_status,
            trace_status=trace_status,
            result_type=result_type,
            limit=limit,
            offset=offset,
        )
        return {"data": res}
    except store.DecisionTraceCorruptedError:
        raise HTTPException(status_code=500, detail="决策追踪数据损坏，已停止读写")
    except Exception:
        raise HTTPException(status_code=500, detail="决策追踪数据查询失败。")


@router.get("/decision-evidence/by-advice")
async def get_evidence_by_advice(
    request: Request,
    trade_date: str | None = None,
    generated_at: str | None = None,
):
    _check_allowed_params(request, {"trade_date", "generated_at"})

    if not trade_date or not trade_date.strip():
        raise HTTPException(status_code=400, detail="缺少必填参数 trade_date")
    if not generated_at or not generated_at.strip():
        raise HTTPException(status_code=400, detail="缺少必填参数 generated_at")

    trade_date_clean = _validate_date_str(trade_date, "trade_date")
    generated_at_clean = generated_at.strip()
    if " " in generated_at_clean:
        generated_at_clean = generated_at_clean.replace(" ", "+")

    run_id = svc.generate_decision_run_id(trade_date_clean, generated_at_clean)

    try:
        data = store.get_decision_run(run_id)
        if not data:
            raise HTTPException(status_code=404, detail="对应持仓建议的决策追踪记录不存在")
        return {"data": data}
    except store.DecisionTraceCorruptedError:
        raise HTTPException(status_code=500, detail="决策追踪数据损坏，已停止读写")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="决策追踪数据查询失败。")


@router.get("/decision-evidence/{decision_run_id}")
async def get_decision_evidence_by_id(
    decision_run_id: str,
):
    if not decision_run_id or not decision_run_id.strip():
        raise HTTPException(status_code=400, detail="非法 decision_run_id")

    try:
        data = store.get_decision_run(decision_run_id.strip())
        if not data:
            raise HTTPException(status_code=404, detail="决策追踪记录不存在")
        return {"data": data}
    except store.DecisionTraceCorruptedError:
        raise HTTPException(status_code=500, detail="决策追踪数据损坏，已停止读写")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="决策追踪数据查询失败。")
