"""API router for Intel Daily Digest endpoints.

Exposes POST /api/intel-digests, GET /api/intel-digests/latest,
and GET /api/intel-digests.
"""

from __future__ import annotations

import urllib.parse
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

import intel_digest_service as svc
import intel_digest_store as store

router = APIRouter(prefix="/api", tags=["intel-digest"])


class IntelDigestInputItemIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    source: str
    published_at: str
    url: str
    summary: str | None = None

    @field_validator("title", "source")
    @classmethod
    def validate_non_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Field cannot be empty")
        return v.strip()

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        """Require http/https scheme, non-empty hostname, and a legal port.

        Accessing urlsplit(...).port may raise ValueError for illegal ports
        (e.g. 'bad-port'); convert that to a Pydantic validation error (422)
        so it never becomes a 500 inside the service layer.
        """
        if not v or not v.strip():
            raise ValueError("URL cannot be empty")
        stripped = v.strip()
        parts = urllib.parse.urlsplit(stripped)
        scheme = parts.scheme.lower()
        if scheme not in ("http", "https"):
            raise ValueError("URL must have http or https scheme")
        hostname = parts.hostname
        if not hostname:
            raise ValueError("URL must have a non-empty hostname")
        try:
            _ = parts.port  # raises ValueError on illegal port strings
        except ValueError as e:
            raise ValueError(f"URL has invalid port: {stripped}") from e
        return stripped

    @field_validator("published_at")
    @classmethod
    def validate_iso8601_date(cls, v: str) -> str:
        """Require parseable ISO-8601 with timezone offset or Z.

        Rejects bare dates ('2026-07-31') and naive datetimes
        ('2026-07-31T10:00:00') that lack timezone info.
        """
        if not v or not v.strip():
            raise ValueError("published_at cannot be empty")
        stripped = v.strip()
        try:
            dt = datetime.fromisoformat(stripped.replace("Z", "+00:00"))
        except Exception as e:
            raise ValueError(f"published_at must be valid ISO-8601 date: {stripped}") from e
        if dt.tzinfo is None:
            raise ValueError(
                "published_at must include timezone offset or Z "
                f"(got naive datetime: {stripped})"
            )
        return stripped


class IntelDigestSaveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sector_key: str
    status: Literal["normal", "partial", "unavailable"]
    summary_text: str = ""
    source_refs: list[Any] | dict[str, Any] | str = Field(default_factory=list)
    input_items: list[IntelDigestInputItemIn] = Field(default_factory=list)


@router.post("/intel-digests")
def save_intel_digest_endpoint(body: IntelDigestSaveIn):
    """
    Save generated intel digest.

    1. Validate sector_key whitelist (must return 422 if unknown key, even for unavailable status).
    2. Handle status == 'unavailable' -> HTTP 200 {"digest": null, "deduped": false} without saving.
    3. Validate summary_text and input_items non-empty for normal/partial.
    4. Save to DB.
    """
    if body.sector_key not in svc.VALID_SECTOR_KEYS:
        raise HTTPException(status_code=422, detail=f"未知板块代码: {body.sector_key}")

    if body.status == "unavailable":
        return {"digest": None, "deduped": False}

    if not body.summary_text or not body.summary_text.strip():
        raise HTTPException(status_code=422, detail="summary_text 不能为空")

    if not body.input_items or len(body.input_items) == 0:
        raise HTTPException(status_code=422, detail="input_items 至少需包含 1 条新闻素材")

    raw_input_items = [item.model_dump(mode="json") for item in body.input_items]

    try:
        record, deduped = svc.save_digest(
            sector_key=body.sector_key,
            status=body.status,
            summary_text=body.summary_text,
            source_refs=body.source_refs,
            input_items=raw_input_items,
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
