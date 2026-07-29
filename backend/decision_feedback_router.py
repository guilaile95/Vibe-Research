"""Decision feedback HTTP API router."""
from __future__ import annotations

import re
from datetime import date
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

import decision_feedback_service as svc
import decision_feedback_store as store

router = APIRouter(prefix="/api", tags=["decision-feedback"])

_CODE_RE = re.compile(r"^[0-9]{6}$")


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


@router.post("/decision-feedback")
async def create_feedback(request: Request):
    try:
        raw_body = await request.body()
        if not raw_body:
            raise HTTPException(status_code=400, detail="请求体必须是 JSON")
        data = await request.json()
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=400, detail="请求体必须是 JSON")

    if not isinstance(data, dict):
        raise HTTPException(status_code=422, detail="请求体必须是 JSON 对象")

    try:
        record = svc.create_feedback(data)
    except svc.DecisionFeedbackValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except svc.AdviceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except svc.AdviceConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except svc.AdviceHoldingNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except svc.TradeNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except svc.TradeInvalidError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except store.DecisionFeedbackCorruptedError:
        raise HTTPException(status_code=500, detail="决策反馈数据损坏，已停止读写")

    return {"data": record}


@router.get("/decision-feedback")
async def list_feedbacks(
    request: Request,
    code: str | None = None,
    adoption_status: str | None = None,
    outcome_status: str | None = None,
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

    if adoption_status is not None:
        if adoption_status not in svc.ADOPTION_STATUSES:
            raise HTTPException(status_code=422, detail="非法 adoption_status 筛选参数")

    if outcome_status is not None:
        if outcome_status not in svc.OUTCOME_STATUSES:
            raise HTTPException(status_code=422, detail="非法 outcome_status 筛选参数")

    validated_date_from = None
    if date_from is not None:
        validated_date_from = _validate_date_str(date_from, "date_from")

    validated_date_to = None
    if date_to is not None:
        validated_date_to = _validate_date_str(date_to, "date_to")

    if validated_date_from and validated_date_to and validated_date_from > validated_date_to:
        raise HTTPException(status_code=422, detail="date_from 不能大于 date_to")

    try:
        records = svc.list_feedbacks(
            code=code,
            adoption_status=adoption_status,
            outcome_status=outcome_status,
            date_from=validated_date_from,
            date_to=validated_date_to,
            include_voided=include_voided,
            limit=limit,
            offset=offset,
        )
    except svc.DecisionFeedbackValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except store.DecisionFeedbackCorruptedError:
        raise HTTPException(status_code=500, detail="决策反馈数据损坏，已停止读写")

    return {"data": records}


@router.get("/decision-feedback/{feedback_id}")
async def get_feedback(feedback_id: str):
    try:
        record = svc.get_feedback(feedback_id)
    except store.DecisionFeedbackCorruptedError:
        raise HTTPException(status_code=500, detail="决策反馈数据损坏，已停止读写")

    if record is None:
        raise HTTPException(status_code=404, detail="决策反馈不存在")
    return {"data": record}


@router.post("/decision-feedback/{feedback_id}/void")
async def void_feedback(feedback_id: str, request: Request):
    data: dict[str, Any] = {}
    try:
        raw_body = await request.body()
        if raw_body:
            data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="请求体必须是 JSON")

    if not isinstance(data, dict):
        raise HTTPException(status_code=422, detail="请求体必须是 JSON 对象")

    try:
        record = svc.void_feedback(feedback_id, data)
    except (svc.DecisionFeedbackNotFoundError, store.DecisionFeedbackNotFoundError):
        raise HTTPException(status_code=404, detail="决策反馈不存在")
    except (svc.DecisionFeedbackAlreadyVoidedError, store.DecisionFeedbackAlreadyVoidedError):
        raise HTTPException(status_code=409, detail="决策反馈已作废")
    except svc.DecisionFeedbackValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except store.DecisionFeedbackCorruptedError:
        raise HTTPException(status_code=500, detail="决策反馈数据损坏，已停止读写")

    return {"data": record}
