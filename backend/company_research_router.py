"""Manual capture/generate and read-only research record retrieval."""
from __future__ import annotations
import json
import threading
import anyio
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, StrictBool
import company_research as service
router = APIRouter(prefix="/api/company-research", tags=["company-research"])

class SubjectIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    market: str = Field(pattern=r"^(A|HK|US)$")
    symbol: str = Field(min_length=1, max_length=15)

class CaptureIn(SubjectIn):
    confirm_public_fetch: StrictBool
    as_of: str | None = Field(default=None, pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")

class ModelIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: str = ""
    model: str = Field(min_length=1, max_length=200)
    baseURL: str = ""
    apiKey: str = Field(default="", repr=False)

class GenerateIn(SubjectIn):
    bundle_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    expected_bundle_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    confirm_model_calls: StrictBool
    llm: ModelIn

@router.post("/capture")
async def capture(body: CaptureIn, request: Request):
    if not body.confirm_public_fetch: raise HTTPException(400, "PUBLIC_FETCH_CONFIRMATION_REQUIRED")
    try: service.identity(body.market, body.symbol)
    except ValueError: raise HTTPException(422, "RESEARCH_IDENTITY_INVALID") from None
    cancelled = threading.Event()
    async def monitor():
        while True:
            if await request.is_disconnected(): cancelled.set(); return
            await anyio.sleep(.05)
    async with anyio.create_task_group() as group:
        group.start_soon(monitor)
        try:
            with anyio.fail_after(service.CAPTURE_SECONDS):
                result = await anyio.to_thread.run_sync(lambda: service.capture(body.market, body.symbol, cancelled=cancelled.is_set, as_of=body.as_of), abandon_on_cancel=True)
        except Exception:
            raise HTTPException(502, "PUBLIC_EVIDENCE_CAPTURE_FAILED") from None
        finally:
            cancelled.set(); group.cancel_scope.cancel()
    return {"data": result}

@router.post("/generate")
async def generate(body: GenerateIn):
    if not body.confirm_model_calls: raise HTTPException(400, "MODEL_BUDGET_CONFIRMATION_REQUIRED")
    if body.llm.provider.strip().startswith("cli-"): raise HTTPException(400, "六阶段研究仅使用现有 API 接入；订阅页内聊天边界不变")
    import app as app_module
    llm=app_module.LLMConfig.model_validate(body.llm.model_dump())
    app_module._require_llm_ready(llm)
    app_module._validate_probe_base_url(llm.baseURL)
    try:
        bundle=service.read_bundle(body.bundle_id)
        if bundle["subject"] != service.identity(body.market,body.symbol) or bundle["bundle_sha256"] != body.expected_bundle_sha256:
            raise ValueError()
    except Exception: raise HTTPException(409,"RESEARCH_BUNDLE_IDENTITY_OR_VERSION_CONFLICT") from None
    cancelled=threading.Event()
    async def events():
        source=service.generate(bundle,llm.model_dump(),cancelled)
        try:
            async for event in source:
                if cancelled.is_set(): return
                yield json.dumps(event,ensure_ascii=False,allow_nan=False)+"\n"
        finally:
            cancelled.set()
            with anyio.CancelScope(shield=True): await source.aclose()
    return app_module._LeadAnalysisStreamingResponse(events(),disconnect_event=cancelled,media_type="application/x-ndjson")

@router.get("/runs")
def runs():
    try: return {"data": service.list_runs()}
    except Exception: raise HTTPException(409,"RESEARCH_RECORD_CORRUPTED_OR_UNAVAILABLE") from None

@router.get("/bundles/{bundle_id}")
def read_bundle(bundle_id: str):
    try: return {"data": service.read_bundle(bundle_id)}
    except Exception: raise HTTPException(409,"RESEARCH_BUNDLE_CORRUPTED_OR_UNAVAILABLE") from None
