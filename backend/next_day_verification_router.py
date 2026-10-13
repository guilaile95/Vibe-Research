"""Dedicated user-write surface; never registered as an AI/agent tool."""
from datetime import date
import re

from fastapi import APIRouter, HTTPException, Request

import next_day_verification as verification

router = APIRouter(prefix="/api/next-day-verification", tags=["next-day-verification"])


def _date(day: str) -> None:
    try:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
            raise ValueError()
        date.fromisoformat(day)
    except ValueError as exc:
        raise HTTPException(422, "日期必须为 YYYY-MM-DD") from exc


def _execute(day, action):
    _date(day)
    try:
        return {"data": action()}
    except verification.VerificationError as exc:
        raise HTTPException(409, str(exc)) from exc
    except verification.JournalError as exc:
        raise HTTPException(503, str(exc)) from exc


@router.get("/{day}")
def read(day: str, request: Request):
    if request.query_params:
        raise HTTPException(422, "不支持额外参数或调用方时间戳")
    return _execute(day, lambda: verification.view(day))


@router.put("/{day}")
def replace(day: str, body: verification.SavePlan, request: Request):
    if request.query_params:
        raise HTTPException(422, "不支持额外参数或调用方时间戳")
    return _execute(day, lambda: verification.replace_plan(day, body))
