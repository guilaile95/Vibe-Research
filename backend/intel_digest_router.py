"""API router for Intel Daily Digest endpoints.

Exposes POST /api/intel-digests, GET /api/intel-digests/latest,
and GET /api/intel-digests.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

import intel_digest_service as svc
import intel_digest_store as store

router = APIRouter(prefix="/api", tags=["intel-digest"])


class IntelDigestSaveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sector_key: str
    status: Literal["normal", "partial", "unavailable"]
    summary_text: str = ""
    source_refs: list[Any] | dict[str, Any] | str = Field(default_factory=list)
    input_items: list[dict[str, Any]] = Field(default_factory=list)


@router.post("/intel-digests")
def save_intel_digest_endpoint(body: IntelDigestSaveIn):
    """
    Save generated intel digest.

    Frontend submits summary_text and input_items.
    Backend derives authoritative digest_date, input_fingerprint, digest_id, created_at, generated_at, sector_name.
    Returns {"digest": dict, "deduped": bool}.
    If status is 'unavailable', returns {"digest": null, "deduped": false} without saving.
    """
    if body.status == "unavailable":
        return {"digest": None, "deduped": False}

    if body.sector_key not in svc.VALID_SECTOR_KEYS:
        raise HTTPException(status_code=422, detail=f"未知板块代码: {body.sector_key}")

    if not body.summary_text or not body.summary_text.strip():
        raise HTTPException(status_code=422, detail="summary_text 不能为空")

    if not body.input_items or len(body.input_items) == 0:
        raise HTTPException(status_code=422, detail="input_items 至少需包含 1 条新闻素材")

    try:
        record, deduped = svc.save_digest(
            sector_key=body.sector_key,
            status=body.status,
            summary_text=body.summary_text,
            source_refs=body.source_refs,
            input_items=body.input_items,
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

    Returns {"digest": dict} (HTTP 200) if found, {"digest": null} (HTTP 200) if not found,
    or HTTP 500 with error envelope on storage failure.
    """
    if sector_key not in svc.VALID_SECTOR_KEYS:
        raise HTTPException(status_code=422, detail=f"未知板块代码: {sector_key}")

    try:
        record = svc.get_latest_digest(sector_key)
        return {"digest": record}
    except store.IntelDigestCorruptedError:
        return JSONResponse(
            status_code=500,
            content={"digest": None, "error": "Intel 摘要数据存储故障"},
        )
    except Exception:
        return JSONResponse(
            status_code=500,
            content={"digest": None, "error": "读取 Intel 摘要失败"},
        )


@router.get("/intel-digests")
def get_intel_digests_endpoint(
    sector_key: str = Query(...),
    digest_date: str | None = Query(None),
):
    """
    Get digest by sector_key and optional digest_date.
    """
    if sector_key not in svc.VALID_SECTOR_KEYS:
        raise HTTPException(status_code=422, detail=f"未知板块代码: {sector_key}")

    try:
        if digest_date:
            record = svc.get_digest_by_date(sector_key, digest_date)
        else:
            record = svc.get_latest_digest(sector_key)
        return {"digest": record}
    except store.IntelDigestCorruptedError:
        return JSONResponse(
            status_code=500,
            content={"digest": None, "error": "Intel 摘要数据存储故障"},
        )
    except Exception:
        return JSONResponse(
            status_code=500,
            content={"digest": None, "error": "读取 Intel 摘要失败"},
        )
