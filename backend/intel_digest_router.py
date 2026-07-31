"""API router for Intel Daily Digest endpoints.

Exposes POST /api/intel-digests, GET /api/intel-digests/latest,
and GET /api/intel-digests.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

import intel_digest_service as svc
import intel_digest_store as store

router = APIRouter(prefix="/api", tags=["intel-digest"])


class IntelDigestSaveIn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    sector_key: str
    status: str
    summary_text: str = ""
    source_refs: list[Any] | dict[str, Any] | str = Field(default_factory=list)
    input_items: list[dict[str, Any]] = Field(default_factory=list)
    sector_name: str | None = None


@router.post("/intel-digests")
def save_intel_digest_endpoint(body: IntelDigestSaveIn):
    """
    Save generated intel digest.

    Frontend submits summary_text and input_items.
    Backend derives authoritative digest_date, input_fingerprint, digest_id, created_at, generated_at.
    Returns {"digest": dict, "deduped": bool}.
    If status is 'unavailable' or summary is empty, returns {"digest": null, "deduped": false}.
    """
    try:
        if body.status == "unavailable" or not body.summary_text.strip():
            return {"digest": None, "deduped": False}

        record, deduped = svc.save_digest(
            sector_key=body.sector_key,
            status=body.status,
            summary_text=body.summary_text,
            source_refs=body.source_refs,
            input_items=body.input_items,
            sector_name=body.sector_name,
        )
        return {"digest": record, "deduped": deduped}
    except store.IntelDigestCorruptedError:
        return JSONResponse(
            status_code=500,
            content={"digest": None, "error": "Intel 摘要数据存储故障"},
        )
    except Exception:
        return JSONResponse(
            status_code=500,
            content={"digest": None, "error": "保存 Intel 摘要失败"},
        )


@router.get("/intel-digests/latest")
def get_latest_intel_digest_endpoint(sector_key: str = Query(...)):
    """
    Get latest digest for a sector.

    Returns {"digest": dict} if present, or {"digest": null} if not found.
    """
    try:
        record = svc.get_latest_digest(sector_key)
        return {"digest": record}
    except Exception:
        return {"digest": None}


@router.get("/intel-digests")
def get_intel_digests_endpoint(
    sector_key: str = Query(...),
    digest_date: str | None = Query(None),
):
    """
    Get digest by sector_key and optional digest_date.

    Returns {"digest": dict} or {"digest": null}.
    """
    try:
        if digest_date:
            record = svc.get_digest_by_date(sector_key, digest_date)
        else:
            record = svc.get_latest_digest(sector_key)
        return {"digest": record}
    except Exception:
        return {"digest": None}
