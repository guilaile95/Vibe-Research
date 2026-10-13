"""Local OCR actions reuse the existing authentication and report authority."""
from __future__ import annotations
import asyncio
import base64
import binascii
import threading
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
import local_ocr
import myreports

router = APIRouter(prefix="/api/local-ocr", tags=["local-ocr"])


class ConfirmedLocalIn(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    confirm_local_processing: Literal[True]

    @field_validator("confirm_local_processing", mode="before")
    @classmethod
    def actual_boolean(cls, value):
        if value is not True:
            raise ValueError("Explicit true confirmation required")
        return value


class PreviewIn(ConfirmedLocalIn):
    model_config = ConfigDict(extra="forbid", strict=True)
    content_b64: str = Field(max_length=((local_ocr.MAX_BYTES + 2) // 3) * 4)
    extension: Literal[".png", ".jpg", ".jpeg"]
    language: Literal["eng", "chi_sim+eng"] = "eng"
    confirm_local_processing: Literal[True]


class ReportIn(ConfirmedLocalIn):
    model_config = ConfigDict(extra="forbid", strict=True)
    expected_file_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    language: Literal["eng", "chi_sim+eng"] = "eng"
    confirm_local_processing: Literal[True]


async def _action(request: Request, action):
    cancel = threading.Event()
    task = asyncio.create_task(asyncio.to_thread(action, cancel))
    try:
        while not task.done():
            if await request.is_disconnected():
                cancel.set()
            await asyncio.sleep(.05)
        return {"data": await task}
    except local_ocr.OcrError as exc:
        code = str(exc)
        raise HTTPException(409 if code in {"OCR_BUSY", "OCR_SOURCE_CHANGED"} else 400, code) from exc
    except myreports.fulltext.ReportTextIndexError as exc:
        raise HTTPException(409, "OCR_INDEX_UNAVAILABLE") from exc
    finally:
        cancel.set()
        # Let the bounded worker kill/reap its child before returning cancellation.
        if not task.done():
            try:
                await asyncio.shield(task)
            except (local_ocr.OcrError, asyncio.CancelledError):
                pass


@router.get("/capability")
def capability():
    return {"data": local_ocr.capability()}


@router.post("/preview")
async def preview(body: PreviewIn, request: Request):
    try:
        data = base64.b64decode(body.content_b64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(400, "OCR_INVALID_BASE64") from exc
    return await _action(request, lambda cancel: local_ocr.extract(data, body.extension, body.language, cancel))


@router.post("/reports/{report_id}")
async def report(report_id: str, body: ReportIn, request: Request):
    return await _action(request, lambda cancel: myreports.ocr_report_text(
        report_id, body.expected_file_sha256, body.language, cancel))


@router.get("/reports/{report_id}/identity")
def report_identity(report_id: str):
    try:
        return {"data": myreports.ocr_report_identity(report_id)}
    except local_ocr.OcrError as exc:
        raise HTTPException(400, str(exc)) from exc
