"""Explicit API-only comparison and bounded read-only frozen history."""
from __future__ import annotations

import json
import threading

import anyio
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, StrictBool

import company_comparison as service

router = APIRouter(prefix="/api/company-comparison", tags=["company-comparison"])


class SubjectIn(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    market: str = Field(pattern=r"^(A|HK|US)$")
    symbol: str = Field(min_length=1, max_length=15)
    bundle_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    expected_bundle_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ModelIn(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    provider: str = Field(default="", max_length=200)
    model: str = Field(min_length=1, max_length=200)
    baseURL: str = Field(default="", max_length=2048)
    apiKey: str = Field(default="", max_length=4096, repr=False)


class GenerateIn(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    subjects: list[SubjectIn] = Field(min_length=2, max_length=2)
    as_of: str = Field(pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
    confirm_model_calls: StrictBool
    llm: ModelIn


def _query(request, expected=()):
    items = list(request.query_params.multi_items())
    if len(items) != len(expected) or {key for key, _ in items} != set(expected):
        raise HTTPException(422, "COMPARISON_QUERY_INVALID")


@router.post("/generate")
async def generate(body: GenerateIn, request: Request):
    _query(request)
    if not body.confirm_model_calls:
        raise HTTPException(400, "MODEL_BUDGET_CONFIRMATION_REQUIRED")
    if body.llm.provider.strip().startswith("cli-"):
        raise HTTPException(400, "双公司对比仅支持现有 API 接入；不调用订阅运行时，也不自动回退")
    import app as app_module
    llm = app_module.LLMConfig.model_validate(body.llm.model_dump())
    app_module._require_llm_ready(llm)
    app_module._validate_probe_base_url(llm.baseURL)
    try:
        bundles = service.resolve_inputs([ref.model_dump() for ref in body.subjects], body.as_of)
        pair = service.make_pair(bundles, body.as_of)
        service.comparison_messages(bundles, pair)
        service._model_meta(llm.model_dump())
    except Exception:
        raise HTTPException(409, "COMPARISON_BUNDLE_IDENTITY_VERSION_CUTOFF_OR_SIZE_CONFLICT") from None
    cancelled = threading.Event()

    async def events():
        source = service.generate(bundles, body.as_of, llm.model_dump(), cancelled)
        try:
            async for event in source:
                if cancelled.is_set():
                    return
                yield json.dumps(event, ensure_ascii=False, allow_nan=False) + "\n"
        except Exception:
            if not cancelled.is_set():
                yield json.dumps({"type": "error", "code": "COMPARISON_UNAVAILABLE",
                                  "message": "对比暂不可用；没有完成的对比报告"},
                                 ensure_ascii=False) + "\n"
        finally:
            cancelled.set()
            with anyio.CancelScope(shield=True):
                # Service cleanup is already bounded. Bound adapter ownership
                # too so failed ASGI send cannot keep its iterator alive.
                with anyio.move_on_after(service.CLEANUP_SECONDS * 3):
                    await source.aclose()
    return app_module._LeadAnalysisStreamingResponse(
        events(), disconnect_event=cancelled, media_type="application/x-ndjson")


@router.get("/bundles")
def bundles(request: Request, market: str, symbol: str, as_of: str):
    _query(request, ("market", "symbol", "as_of"))
    try:
        return {"data": service.list_bundles(market, symbol, as_of)}
    except Exception:
        raise HTTPException(409, "COMPARISON_BUNDLE_CORRUPTED_OR_UNAVAILABLE") from None


@router.get("/runs")
def runs(request: Request):
    if not request.query_params:
        return {"data": _legacy_runs()}
    required = {"first_market", "first_symbol", "second_market", "second_symbol", "as_of"}
    supplied = set(request.query_params)
    if not required <= supplied or not supplied <= required | {"before", "limit"}:
        raise HTTPException(422, "COMPARISON_QUERY_INVALID")
    _query(request, supplied)
    q = request.query_params
    try:
        if any(not q[k].isascii() or not q[k].isdigit() or len(q[k]) > 19 for k in ("before", "limit") if k in q):
            raise ValueError()
        return {"data": service.list_run_page(
            {"market": q["first_market"], "symbol": q["first_symbol"]},
            {"market": q["second_market"], "symbol": q["second_symbol"]}, q["as_of"],
            before=int(q["before"]) if "before" in q else None,
            limit=int(q.get("limit", service.MAX_HISTORY)))}
    except Exception:
        raise HTTPException(409, "COMPARISON_RECORD_CORRUPTED_OR_UNAVAILABLE") from None


@router.get("/runs/{run_id}")
def run(run_id: str, request: Request):
    _query(request)
    try:
        return {"data": service.read_run(run_id)}
    except Exception:
        raise HTTPException(409, "COMPARISON_RECORD_CORRUPTED_OR_UNAVAILABLE") from None


def _legacy_runs():
    try:
        return service.list_runs()
    except Exception:
        raise HTTPException(409, "COMPARISON_RECORD_CORRUPTED_OR_UNAVAILABLE") from None
