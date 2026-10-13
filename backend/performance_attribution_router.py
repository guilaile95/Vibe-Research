"""Performance attribution REST API (P2-4B).

GET  /api/performance-attribution            -> live computation (no write)
POST /api/performance-attribution/snapshot   -> compute + freeze
GET  /api/performance-attribution/snapshots  -> list frozen snapshots
GET  /api/performance-attribution/snapshots/{snapshot_id} -> one snapshot
"""
from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, field_validator

import performance_attribution_service as _svc

router = APIRouter(prefix="/api/performance-attribution", tags=["performance-attribution"])

_CODE_RE = re.compile(r"\d{6}")


def _validate_date(val: str | None, field: str) -> str | None:
    if val is None:
        return None
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", val):
        raise HTTPException(
            status_code=422,
            detail=f"非法 {field}，格式须为 YYYY-MM-DD",
        )
    return val


class SnapshotRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date_from: str | None = None
    date_to: str | None = None
    price_map: dict[str, float] | None = None


    @field_validator("price_map", mode="before")
    @classmethod
    def validate_original_price_map(cls, value):
        # A normal float field coerces JSON true to 1.0; reject invalid quotes
        # before that information is lost, using the service's same contract.
        try:
            return _svc.validate_price_map(value)
        except ValueError as exc:
            # Pydantic's error payload retains the raw input. JSON overflow or
            # NaN would then crash FastAPI's JSON error serialization; return
            # only our safe validation detail, never the original quote map.
            raise HTTPException(status_code=422, detail=str(exc)) from None


@router.get("")
def get_attribution(
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
):
    """Compute attribution on the fly; nothing is persisted."""
    date_from = _validate_date(date_from, "date_from")
    date_to = _validate_date(date_to, "date_to")
    try:
        result = _svc.compute_attribution(date_from=date_from, date_to=date_to)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"data": result}


@router.post("/snapshot")
def create_snapshot(body: SnapshotRequest):
    """Compute attribution and freeze it as a snapshot."""
    date_from = _validate_date(body.date_from, "date_from")
    date_to = _validate_date(body.date_to, "date_to")
    try:
        result = _svc.compute_attribution(
            date_from=date_from, date_to=date_to, price_map=body.price_map
        )
        snapshot = _svc.save_attribution_snapshot(result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    payload = dict(snapshot)
    payload.pop("payload_json", None)
    return {"data": {"snapshot": payload, "attribution": result}}


@router.get("/snapshots")
def list_snapshots(
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """List frozen attribution snapshots (newest first)."""
    date_from = _validate_date(date_from, "date_from")
    date_to = _validate_date(date_to, "date_to")
    try:
        items = _svc.list_attribution_snapshots(
            date_from=date_from, date_to=date_to, limit=limit, offset=offset
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"data": {"items": items, "limit": limit, "offset": offset}}


@router.get("/snapshots/{snapshot_id}")
def get_snapshot(snapshot_id: str):
    """Return one frozen snapshot with its positions."""
    try:
        record = _svc.get_attribution_snapshot(snapshot_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if record is None:
        raise HTTPException(status_code=404, detail="收益归因快照不存在")
    return {"data": record}
