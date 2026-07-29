"""Signal ledger HTTP API router.

Provides read-only access to decision pipeline signal entries and outcomes.
"""

from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

import signal_ledger_service as svc
import signal_ledger_store as store

router = APIRouter(prefix="/api", tags=["signal-ledger"])

_CODE_RE = re.compile(r"^[0-9]{6}$")


def _check_allowed_params(request: Request, allowed_params: set[str]) -> None:
    unknown = set(request.query_params.keys()) - allowed_params
    if unknown:
        raise HTTPException(status_code=400, detail=f"未知筛选参数: {', '.join(sorted(unknown))}")


@router.get("/signal-ledger")
async def list_signal_entries(
    request: Request,
    decision_run_id: str | None = None,
    stage: str | None = None,
    code: str | None = None,
    severity: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    _check_allowed_params(
        request, {"decision_run_id", "stage", "code", "severity", "limit", "offset"}
    )

    if code is not None:
        if not isinstance(code, str) or not _CODE_RE.fullmatch(code.strip()):
            raise HTTPException(status_code=400, detail="非法 code 筛选参数，必须为6位数字代码")
        code = code.strip()

    if stage is not None:
        if stage not in svc.VALID_STAGES:
            raise HTTPException(
                status_code=400,
                detail=f"非法 stage 参数，须为: {', '.join(svc.VALID_STAGES)}",
            )

    if severity is not None:
        if severity not in svc.VALID_SEVERITIES:
            raise HTTPException(
                status_code=400,
                detail=f"非法 severity 参数，须为: {', '.join(svc.VALID_SEVERITIES)}",
            )

    try:
        res = store.query_signal_entries(
            decision_run_id=decision_run_id,
            stage=stage,
            code=code,
            severity=severity,
            limit=limit,
            offset=offset,
        )
        return {"data": res}
    except store.SignalLedgerCorruptedError as exc:
        raise HTTPException(status_code=500, detail=exc.MESSAGE) from exc


@router.get("/signal-ledger/run/{decision_run_id}")
async def get_run_signal_ledger(decision_run_id: str):
    if not isinstance(decision_run_id, str) or not decision_run_id.strip():
        raise HTTPException(status_code=400, detail="decision_run_id 不能为空")

    try:
        res = store.get_run_signal_ledger(decision_run_id.strip())
        return {"data": res}
    except store.SignalLedgerNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except store.SignalLedgerCorruptedError as exc:
        raise HTTPException(status_code=500, detail=exc.MESSAGE) from exc
