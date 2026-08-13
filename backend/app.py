"""Vibe-Research 后端 —— A股数据层 HTTP 接口（FastAPI）。

端点全部在 /api 下，前端 vite 代理 /api → localhost:8900。
只读、无状态，按用户传入代码返回行情 / 研报 / 资金等数据。

启动：
    uvicorn app:app --host 127.0.0.1 --port 8900
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections import OrderedDict
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from itertools import count

import anyio
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator
from starlette.concurrency import iterate_in_threadpool, run_in_threadpool

import account_profile
import ai_result_service
import astock
import chat as chat_layer
import cli_runtime
import daily_review
import gstock
import newsradar
import portfolio as pf
import portfolio_advice_service
import market
import myreports as mr
import review_compare
import review_history
import sector_research_data as srd
import northbound_capital_flow as ncf
import top_risk_service as trs
import watchlist_store
import evidence_thesis_router
import data_health_router
import trade_ledger_router
import decision_feedback_router
import decision_evidence_router
import signal_ledger_router
import decision_trace_store
import signal_ledger_store
import account_execution_policy_router
import decision_analytics_router
import performance_attribution_router
import performance_attribution_store
import technical_indicators_router
import bk11_history_router
import intel_digest_router
import position_reality_router
import account_reality_router
import cash_event_router
import campaign_router
import holdings_campaign_composition_router
import decision_inbox_runtime_router
from decision_cockpit_service import (
    generate_tomorrow_plan,
    freeze_tomorrow_plan,
    get_current_plan as dc_get_current_plan,
    get_overview,
    get_plan as dc_get_plan,
    list_plans as dc_list_plans,
    DecisionCockpitError,
    DecisionCockpitMarketDataError,
    DecisionCockpitModelError,
    DecisionCockpitSnapshotError,
)
from decision_cockpit_today import get_today_actions


class _DisconnectAwareStreamingResponse(StreamingResponse):
    """Always observe ASGI disconnects and expose them to blocking workers."""

    def __init__(self, *args, disconnect_event: threading.Event, **kwargs):
        super().__init__(*args, **kwargs)
        self.disconnect_event = disconnect_event

    async def __call__(self, scope, receive, send) -> None:
        async with anyio.create_task_group() as task_group:
            async def stream() -> None:
                try:
                    await self.stream_response(send)
                except OSError:
                    self.disconnect_event.set()
                finally:
                    task_group.cancel_scope.cancel()

            async def watch_disconnect() -> None:
                while True:
                    message = await receive()
                    if message["type"] == "http.disconnect":
                        self.disconnect_event.set()
                        task_group.cancel_scope.cancel()
                        return

            task_group.start_soon(stream)
            task_group.start_soon(watch_disconnect)

        if self.background is not None:
            await self.background()


def _safe_daily_review_ai_done_result(record) -> dict[str, str]:
    if not isinstance(record, dict):
        raise ai_result_service.AiResultValidationError("missing committed result")
    result_type, trade_date = ai_result_service.validate_result_identity(
        record.get("result_type"),
        record.get("trade_date"),
    )
    if result_type != ai_result_service.DAILY_REVIEW_AI:
        raise ai_result_service.AiResultValidationError("unexpected committed result type")
    schema_version = record.get("schema_version")
    if schema_version != "daily_review_ai.v1":
        raise ai_result_service.AiResultValidationError("unexpected committed schema")
    generated_at = ai_result_service._valid_timestamp(record.get("generated_at"), "generated_at")
    return {
        "result_type": result_type,
        "trade_date": trade_date,
        "schema_version": schema_version,
        "generated_at": generated_at,
    }


_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


def _parse_bind_host(raw: str) -> str:
    """规范化 VR_HOST：去空格/方括号；值必须是合法 IP 或纯主机名（无端口/协议/路径）。"""
    import ipaddress

    h = (raw or "").strip().lower()
    if h.startswith("["):
        h = h.strip("[]")
    if not h or any(c.isspace() for c in h) or "://" in h or "/" in h or "@" in h:
        raise RuntimeError(f"VR_HOST 非法：{raw!r}")
    try:
        ipaddress.ip_address(h)
    except ValueError:
        if not h or not all(c.isalnum() or c in ".-" for c in h):
            raise RuntimeError(f"VR_HOST 非法：{raw!r}") from None
    return h


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用启动时先强制校验访问边界（fail closed），再启动后台刷新调度器（幂等）。"""
    vr_host = os.environ.get("VR_HOST", "").strip()
    if vr_host and _parse_bind_host(vr_host) not in _LOOPBACK_HOSTS and not _API_KEY:
        raise RuntimeError("VR_HOST 非 loopback 绑定必须设置 VR_API_KEY，已拒绝启动")
    pf.start_scheduler(1800)
    yield


app = FastAPI(title="Vibe-Research API", version="0.1.3", lifespan=lifespan)

# ── 本地 API 访问边界（P0-SEC1） ──────────────────────────────────────────
# 127.0.0.1 不是鉴权机制：默认 CORS 只允许正式本地前端 Origin，恶意网页无法
# 从浏览器跨源读写私有 API；非 loopback 绑定且未配置 VR_API_KEY → fail closed。

_LOCAL_FRONTEND_ORIGINS = (
    "http://localhost:5899",
    "http://127.0.0.1:5899",
)


def _parse_origins(raw: str) -> list[str]:
    """严格解析 VR_ALLOW_ORIGINS：仅接受 http(s)://host[:port] 形式的 Origin。

    通配符 * / 空值 / 畸形值一律抛错（fail closed），绝不回落 *。
    """
    from urllib.parse import urlparse

    entries = [o.strip() for o in (raw or "").split(",") if o.strip()]
    if not entries:
        raise RuntimeError("VR_ALLOW_ORIGINS 不能为空；删除该环境变量可恢复默认本地前端白名单")
    origins: list[str] = []
    for entry in entries:
        if entry == "*":
            raise RuntimeError("VR_ALLOW_ORIGINS 不允许通配符 *（私有 API + 通配 Origin 为不安全配置）")
        p = urlparse(entry)
        if (
            p.scheme not in ("http", "https")
            or not p.hostname
            or p.path not in ("", "/")
            or p.query
            or p.fragment
            or p.params
            or p.username is not None
            or p.password is not None
        ):
            raise RuntimeError(f"VR_ALLOW_ORIGINS 包含非法 Origin：{entry!r}（应为 http(s)://host[:port]）")
        port = f":{p.port}" if p.port is not None else ""
        origins.append(f"{p.scheme}://{p.hostname}{port}")
    return origins


_ALLOW_ORIGINS_RAW = os.environ.get("VR_ALLOW_ORIGINS", "").strip()
# 未配置 = 仅允许官方本地前端；显式配置 = 严格解析（畸形/通配直接拒绝启动）。
_ALLOWED_ORIGINS = _parse_origins(_ALLOW_ORIGINS_RAW) if _ALLOW_ORIGINS_RAW else list(_LOCAL_FRONTEND_ORIGINS)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# 投资逻辑与证据账本：独立路由模块最小接入
app.include_router(evidence_thesis_router.router)
# 数据健康中心：只读聚合 API
app.include_router(data_health_router.router)
# 交易流水：独立存储与 API
app.include_router(trade_ledger_router.router)
# 决策反馈：独立存储与 API
app.include_router(decision_feedback_router.router)
# 决策追踪与证据表达：只读 API
app.include_router(decision_evidence_router.router)
# 信号账本：只读 API
app.include_router(signal_ledger_router.router)
# 账户资金执行策略：GET/PUT /api/account-execution-policy
app.include_router(account_execution_policy_router.router)
# 决策反馈分析：只读聚合 API
app.include_router(decision_analytics_router.router)
# 收益归因：计算 + 快照 API
app.include_router(performance_attribution_router.router)
# 技术指标与价格触发
app.include_router(technical_indicators_router.router)
# BK-11 短线市场历史只读查询
app.include_router(bk11_history_router.router)
# Intel Daily Digest
app.include_router(intel_digest_router.router)
# P0-S1A 持仓事实链：bootstrap / correction / derived / reconciliation
app.include_router(position_reality_router.router)
# P0-S1B-A 账户现实层（只读）：cash 双源 / settled 定价 / settled NAV candidate
app.include_router(account_reality_router.router)
app.include_router(cash_event_router.router)
app.include_router(campaign_router.router)
# P0-DI2A canonical Actual Holding → current Campaign read model
app.include_router(holdings_campaign_composition_router.router)
# P0-DI2 current-only Decision Inbox runtime read model
app.include_router(decision_inbox_runtime_router.router)


@app.exception_handler(evidence_thesis_router.RevisionConflictHTTPException)
async def _revision_conflict_handler(request: Request, exc: evidence_thesis_router.RevisionConflictHTTPException):
    """409 响应：body = {"detail": ..., "current_revision": ...}（顶层 current_revision）。"""
    return JSONResponse(
        status_code=409,
        content={"detail": exc.message, "current_revision": exc.current_revision},
    )

# 可选鉴权：设了 VR_API_KEY 就要求所有 /api/*（除 _PUBLIC_API_PATHS）带
#   `Authorization: Bearer <key>`。
# 本地 loopback 单用户模式可不设（浏览器跨源访问已被 Origin 白名单挡住）；
# 非 loopback 绑定且未设 key → 启动/请求 fail closed（见 _NonLoopbackGuard）。
_API_KEY = os.environ.get("VR_API_KEY", "").strip()

# 明确公开的 API 路径：除 health 外全部私有；health 只返回固定版本信息，不得含私有数据。
_PUBLIC_API_PATHS = frozenset({"/api/health"})


@app.exception_handler(RequestValidationError)
async def _validation_handler(request: Request, exc: RequestValidationError):
    """Pydantic 校验失败：/api/account-profile 与 /api/portfolio/holding 返回 400
    （严格类型 + 未知字段统一语义错误）；其它端点保持框架默认 422，避免影响现有契约。"""
    if request.url.path in ("/api/account-profile", "/api/portfolio/holding", "/api/portfolio/close"):
        errs = exc.errors()
        msg = "; ".join(
            (f"{'.'.join(str(p) for p in e.get('loc', []))}: {e.get('msg', 'invalid')}") for e in errs
        ) or "请求参数无效"
        return JSONResponse(status_code=400, content={"detail": msg})
    # 非目标端点：复用 FastAPI 默认 422 行为
    return JSONResponse(
        status_code=422,
        content={"detail": [{"loc": e.get("loc", []), "msg": e.get("msg", ""), "type": e.get("type", "")} for e in exc.errors()]},
    )



@app.exception_handler(pf.PortfolioDataCorruptedError)
async def _portfolio_corrupted_handler(request: Request, exc: pf.PortfolioDataCorruptedError):
    """持仓数据文件损坏：HTTP 500 + 固定安全文案（不透文件路径/内容/traceback）。"""
    return JSONResponse(status_code=500, content={"detail": pf.PortfolioDataCorruptedError.MESSAGE})


@app.exception_handler(mr.ReportIndexCorruptedError)
async def _reports_corrupted_handler(request, exc):
    """研报索引文件损坏：HTTP 500 + 固定安全文案。"""
    return JSONResponse(status_code=500, content={"detail": mr.ReportIndexCorruptedError.MESSAGE})


@app.exception_handler(decision_trace_store.DecisionTraceCorruptedError)
async def _decision_trace_corrupted_handler(request, exc):
    """决策追踪数据损坏：HTTP 500 + 固定安全文案。"""
    return JSONResponse(status_code=500, content={"detail": decision_trace_store.DecisionTraceCorruptedError.MESSAGE})


@app.exception_handler(signal_ledger_store.SignalLedgerCorruptedError)
async def _signal_ledger_corrupted_handler(request, exc):
    """信号账本数据损坏：HTTP 500 + 固定安全文案。"""
    return JSONResponse(status_code=500, content={"detail": signal_ledger_store.SignalLedgerCorruptedError.MESSAGE})


@app.exception_handler(performance_attribution_store.PerformanceAttributionCorruptedError)
async def _performance_attribution_corrupted_handler(request, exc):
    """收益归因数据损坏：HTTP 500 + 固定安全文案。"""
    return JSONResponse(status_code=500, content={"detail": performance_attribution_store.PerformanceAttributionCorruptedError.MESSAGE})


@app.middleware("http")
async def _require_api_key(request: Request, call_next):
    if (
        _API_KEY
        and request.method != "OPTIONS"
        and request.url.path.startswith("/api/")
        and request.url.path not in _PUBLIC_API_PATHS
    ):
        if request.headers.get("authorization", "") != f"Bearer {_API_KEY}":
            return JSONResponse({"detail": "未授权：缺少或错误的 API Key（VR_API_KEY）"}, status_code=401)
    return await call_next(request)


def _serialized_origin(scheme: str, host_header: str) -> str:
    """scheme + Host 头 → Origin 序列化形式（小写，去默认端口）。"""
    host = (host_header or "").strip().lower()
    if scheme == "http" and host.endswith(":80"):
        host = host[: -len(":80")]
    if scheme == "https" and host.endswith(":443"):
        host = host[: -len(":443")]
    return f"{scheme}://{host}"


def _origin_allowed(origin_header: str, host_header: str, scheme: str) -> bool:
    """Origin gate 判定：缺 Origin（非浏览器客户端）/ 白名单 / same-origin → 放行。"""
    origin = (origin_header or "").strip()
    if not origin:
        return True
    if origin in _ALLOWED_ORIGINS:
        return True
    return origin == _serialized_origin(scheme, host_header)


class _OriginGate:
    """服务端 Origin 边界：/api/* 上，浏览器携带非白名单且非 same-origin 的
    Origin → 在路由执行前 403（CORSMiddleware 只控制浏览器可读性，不阻止执行）。

    语义：缺 Origin = 非浏览器客户端（curl/本地脚本）→ 放行。
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope.get("path", "").startswith("/api/"):
            headers = dict(scope.get("headers") or [])
            origin = headers.get(b"origin", b"").decode("latin-1", "replace")
            host = headers.get(b"host", b"").decode("latin-1", "replace")
            if not _origin_allowed(origin, host, scope.get("scheme", "http")):
                resp = JSONResponse({"detail": "Origin not allowed"}, status_code=403)
                await resp(scope, receive, send)
                return
        await self.app(scope, receive, send)


# OriginGate 在 API Key 之前执行：跨源浏览器请求在鉴权/路由前即被拒绝。
app.add_middleware(_OriginGate)


# TestClient 的 "testserver" 是进程内传输（永不暴露网络），视作 loopback 等价。
_LOOPBACK_BINDS = _LOOPBACK_HOSTS | {"testserver"}


def _parse_trusted_hosts(raw: str) -> set[str]:
    """严格解析 VR_TRUSTED_HOSTS：仅接受纯主机名（无端口/协议/路径），拒绝畸形值。"""
    entries = [h.strip() for h in (raw or "").split(",") if h.strip()]
    for entry in entries:
        if ":" in entry or "/" in entry or "@" in entry or not all(c.isalnum() or c in ".-" for c in entry):
            raise RuntimeError(f"VR_TRUSTED_HOSTS 包含非法主机名：{entry!r}")
    return set(entries)


_ALLOWED_HOSTS = {"localhost", "127.0.0.1", "[::1]", "testserver"} | _parse_trusted_hosts(
    os.environ.get("VR_TRUSTED_HOSTS", "")
)


def _host_header_name(host_header: str) -> str:
    """Host 头 → 主机名：去端口；IPv6 字面量保留方括号。"""
    h = (host_header or "").strip().lower()
    if h.startswith("["):
        end = h.find("]")
        return h[: end + 1] if end != -1 else h
    return h.split(":", 1)[0]


class _LocalHostGate:
    """最小 Host 边界：拒绝未知 Host（防 DNS rebinding / hostile Host），不反射原值。

    starlette 的 TrustedHostMiddleware 会把 `[::1]:port` 按冒号切成 `[`，无法
    干净支持 IPv6 字面量，故采用这个最小实现；额外主机名走 VR_TRUSTED_HOSTS。
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            headers = dict(scope.get("headers") or [])
            host = headers.get(b"host", b"").decode("latin-1", "replace")
            # 缺失 Host 头放行：只出现在原始 ASGI 直调（测试）或 HTTP/1.0，
            # 不构成 DNS rebinding 攻击面（真实 HTTP/1.1 缺 Host 会被服务器先行拒绝）。
            if host and _host_header_name(host) not in _ALLOWED_HOSTS:
                resp = JSONResponse({"detail": "Host 头不在允许列表"}, status_code=400)
                await resp(scope, receive, send)
                return
        await self.app(scope, receive, send)


_NON_LOOPBACK_NO_KEY_DETAIL = "服务绑定在非 loopback 地址但未配置 VR_API_KEY，已拒绝服务"


class _NonLoopbackGuard:
    """运行时 bind 边界：实际监听地址非 loopback 且无鉴权 → 全部请求 503（含 health）。

    scope["server"] 是 ASGI server（uvicorn）实际 bind 的接口地址，与 VR_HOST
    声明无关，因此无论以何种方式启动都 fail closed；无法判定时放行。
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and not _API_KEY:
            server = scope.get("server")
            if server and server[0] not in _LOOPBACK_BINDS:
                resp = JSONResponse({"detail": _NON_LOOPBACK_NO_KEY_DETAIL}, status_code=503)
                await resp(scope, receive, send)
                return
        await self.app(scope, receive, send)


# 注册顺序即执行顺序（后注册在外层）：NonLoopbackGuard → HostGate → OriginGate → API Key → CORS。
app.add_middleware(_LocalHostGate)
app.add_middleware(_NonLoopbackGuard)

_CODE_RE = r"^\d{6}$"


def _validate(code: str) -> str:
    code = (code or "").strip()
    if not code.isdigit() or len(code) != 6:
        raise HTTPException(400, "代码必须是 6 位数字")
    return code


@app.get("/api/health")
def health():
    return {"ok": True, "service": "vibe-research-api", "version": "0.1.3"}


class LLMConfig(BaseModel):
    provider: str = ""       # cli-* = 订阅接入（调本机 CLI）；其余 = API 接入
    baseURL: str = ""        # 订阅接入时留空
    apiKey: str = ""         # 订阅接入时留空
    model: str


def _require_llm_ready(llm: LLMConfig) -> bool:
    """校验接入 AI 配置是否可调用；不通过则抛 HTTP 400。

    Returns
    -------
    bool
        True 表示订阅 CLI 路径；False 表示 API 路径。
    """
    if not (llm.model or "").strip():
        raise HTTPException(400, "缺少模型配置，请先在「接入 AI」里选择")
    is_cli = (llm.provider or "").startswith("cli-")
    if is_cli:
        kind = llm.provider[4:]
        if not cli_runtime.detect_cli(kind):
            raise HTTPException(
                400,
                f"未检测到「{kind}」对应的本机命令。请先安装并登录该 CLI，或改用「API 接入」。",
            )
        return True
    if not (llm.apiKey or "").strip() or not (llm.baseURL or "").strip():
        raise HTTPException(400, "缺少 Base URL 或 API Key，请先在「接入 AI」里填写")
    return False


class ChatReq(BaseModel):
    messages: list[dict]
    context: str = ""
    llm: LLMConfig


@app.post("/api/chat")
def chat(req: ChatReq):
    """系统 AI 对话，**流式** NDJSON（每行一个事件 {type: tool|delta|done|error}）。

    - API 接入：OpenAI 兼容 function-calling，边流答案边推工具调用事件。
    - 订阅接入（provider=cli-*）：调本机已登录的 CLI，stdout 边出边流（数据靠 context）。
    配置错误（缺 key / 未装 CLI）走 HTTP 400；运行时错误走流内 error 事件。用户配置随请求传入，后端不持久化。
    """
    if not req.messages:
        raise HTTPException(400, "messages 不能为空")
    is_cli = _require_llm_ready(req.llm)

    cfg = req.llm.model_dump()

    def gen():
        try:
            events = (chat_layer.run_chat_cli_stream if is_cli else chat_layer.run_chat_stream)(cfg, req.messages, req.context)
            for ev in events:
                yield json.dumps(ev, ensure_ascii=False) + "\n"
        except Exception as e:  # noqa: BLE001 — 运行时错误以流内事件上报，不中断连接
            yield json.dumps({"type": "error", "message": f"对话失败：{e}"}, ensure_ascii=False) + "\n"

    return StreamingResponse(gen(), media_type="application/x-ndjson")


def _reject_bool_str(v, field: str) -> None:
    """拒绝布尔值和字符串类型的字段值。"""
    if isinstance(v, bool):
        raise ValueError(f"{field} 不能是布尔值")
    if isinstance(v, str):
        raise ValueError(f"{field} 不能是字符串")


class HoldingIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str
    shares: int
    cost: float

    @model_validator(mode="before")
    @classmethod
    def _strict_types(cls, values):
        if isinstance(values, dict):
            _reject_bool_str(values.get("shares"), "shares")
            _reject_bool_str(values.get("cost"), "cost")
            if isinstance(values.get("shares"), float):
                raise ValueError("shares 不能是小数")
        return values


class HoldingUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str
    shares: int
    cost: float

    @model_validator(mode="before")
    @classmethod
    def _strict_types(cls, values):
        if isinstance(values, dict):
            _reject_bool_str(values.get("shares"), "shares")
            _reject_bool_str(values.get("cost"), "cost")
            if isinstance(values.get("shares"), float):
                raise ValueError("shares 不能是小数")
        return values


@app.get("/api/portfolio")
def portfolio_get():
    """持仓 + 实时盈亏（浮动盈亏红涨绿跌）。"""
    try:
        return {"data": pf.get_portfolio()}
    except pf.PortfolioDataCorruptedError:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"持仓读取异常：{e}") from e


class PortfolioAdviceRequest(BaseModel):
    """持仓操作建议请求。

    持仓与市场上下文由服务器读取/聚合；客户端不可注入 portfolio/context/messages。
    llm 复用通用聊天的 LLMConfig。禁止额外字段。
    """

    model_config = ConfigDict(extra="forbid")

    user_request: str | None = None
    llm: LLMConfig


@app.post("/api/portfolio/advice")
def portfolio_advice(req: PortfolioAdviceRequest):
    """独立持仓操作建议（普通 JSON，非流式）。

    服务器链路：校验 LLM → get_portfolio → generate_daily_review → context → 模型 → validator → save。
    未配置模型 / 缺 key / 未装 CLI → 400；
    空持仓 → 409；行情/市场不可用 → 503；
    模型调用失败 → 502（区分鉴权/网络/CLI/通用，不回传密钥与上游 body）；
    模型输出无效 → 502；
    内部 TypeError/ValueError → 500（安全日志，不再误报「请求参数无效」）。
    请求结构错误由 Pydantic → 422。不接受客户端持仓/context/messages。
    """
    log = logging.getLogger("portfolio_advice")
    # 与 /api/chat、/api/daily-review/analyze 对齐：配置问题先 400，避免伪装成模型 502
    _require_llm_ready(req.llm)
    try:
        result = portfolio_advice_service.generate_portfolio_advice(
            req.llm.model_dump(),
            user_request=req.user_request,
        )
        return {"data": result}
    except portfolio_advice_service.PortfolioAdviceUnavailableError as e:
        raise HTTPException(409, str(e)) from e
    except portfolio_advice_service.PortfolioAdviceMarketDataError as e:
        # 市场核心数据 / 复盘交易日不可用：503 + 安全业务文案
        raise HTTPException(
            503, str(e) or "市场核心数据暂不可用，无法生成可靠的持仓操作建议"
        ) from None
    except portfolio_advice_service.PortfolioAdviceModelError as e:
        # 固定安全分类文案；不透传可能含密钥/路径的原始异常
        from portfolio_advice_errors import public_model_error_detail

        detail = public_model_error_detail(e)
        log.warning(
            "portfolio_advice model error class=%s type=%s",
            detail,
            type(e.__cause__ or e).__name__,
        )
        raise HTTPException(502, detail) from None
    except portfolio_advice_service.PortfolioAdviceModelOutputError:
        raise HTTPException(502, "持仓建议模型输出无效") from None
    except portfolio_advice_service.PortfolioAdvicePersistError as e:
        log.warning(
            "portfolio_advice persist failed stage=%s type=%s",
            getattr(e, "stage", "persist"),
            type(e.__cause__ or e).__name__,
        )
        raise HTTPException(500, "持仓建议结果保存失败") from None
    except pf.PortfolioDataCorruptedError:
        raise
    except (TypeError, ValueError) as e:
        # 服务内部编程/数据契约错误：500，禁止伪装成客户端参数错误
        log.exception(
            "portfolio_advice internal error type=%s stage=handler",
            type(e).__name__,
        )
        raise HTTPException(500, "持仓操作建议生成失败") from None
    except Exception as e:  # noqa: BLE001 — 不向客户端暴露路径/持仓/密钥
        log.exception(
            "portfolio_advice unexpected error type=%s",
            type(e).__name__,
        )
        raise HTTPException(500, "持仓操作建议生成失败") from None


@app.post("/api/portfolio/holding")
def portfolio_add(h: HoldingIn):
    """加一笔持仓（同代码按加权平均成本合并）。存本地，不上传。"""
    code = (h.code or "").strip()
    if not code.isdigit() or len(code) != 6:
        raise HTTPException(400, "代码必须是 6 位数字")
    if h.shares <= 0:
        raise HTTPException(400, "数量必须大于 0")
    # 成本价不限正负，但必须是有限数字
    if h.cost != h.cost or h.cost in (float("inf"), float("-inf")):
        raise HTTPException(400, "成本价必须是有效数字")
    return {"data": pf.add_holding(code, h.shares, h.cost)}


@app.delete("/api/portfolio/holding")
def portfolio_remove(code: str = Query(...)):
    return {"data": pf.remove_holding(code.strip())}


@app.put("/api/portfolio/holding")
def portfolio_update(h: HoldingUpdate):
    """精确替换指定持仓的数量和成本价。不执行加权平均。code 不存在 → 404。

    语义：精确覆盖 shares/cost；不新增不存在代码；不改 code；不写清仓记录；不调用建议。
    """
    code = (h.code or "").strip()
    if not code.isdigit() or len(code) != 6:
        raise HTTPException(400, "代码必须是 6 位数字")
    # bool 是 int 子类，model_validator 已拦；此处再保证 >0 正整数
    if isinstance(h.shares, bool) or not isinstance(h.shares, int) or h.shares <= 0:
        raise HTTPException(400, "数量必须为正整数")
    if isinstance(h.cost, bool) or not isinstance(h.cost, (int, float)):
        raise HTTPException(400, "成本价必须是有效数字")
    if not (h.cost == h.cost) or h.cost in (float("inf"), float("-inf")):
        raise HTTPException(400, "成本价必须是有效数字")
    try:
        return {"data": pf.update_holding(code, h.shares, float(h.cost))}
    except ValueError as e:
        raise HTTPException(404, str(e)) from e
    except pf.PortfolioDataCorruptedError:
        raise
    except Exception:  # noqa: BLE001 — 不向客户端泄漏路径/traceback
        raise HTTPException(502, "持仓编辑失败") from None


# ---- 账户资金（用户手工填写，存本地、不上传、不进仓库）----

class AccountProfileIn(BaseModel):
    """账户资金手工填写请求。updated_at 由后端生成，禁止客户端提交。"""

    model_config = ConfigDict(extra="forbid")

    total_assets: float
    available_cash: float

    @model_validator(mode="before")
    @classmethod
    def _strict_amounts(cls, values):
        """严格类型：拒绝字符串、布尔值（Pydantic 默认会强转）。"""
        if isinstance(values, dict):
            for field in ("total_assets", "available_cash"):
                v = values.get(field)
                if isinstance(v, bool) or isinstance(v, str):
                    raise ValueError(f"{field} 必须是数字，不能是 {type(v).__name__}")
        return values


@app.get("/api/account-profile")
def account_profile_get():
    """账户资金。未配置 → configured=false, data=null；不把未配置解释为 0。"""
    try:
        d = account_profile.load_account_profile()
        if d is None:
            return {"configured": False, "data": None}
        return {"configured": True, "data": d}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"账户资金读取异常：{e}") from e


@app.put("/api/account-profile")
def account_profile_save(req: AccountProfileIn):
    """保存账户资金。后端校验 + 生成 updated_at，返回保存后的数据。"""
    try:
        total, cash = account_profile.validate_account_payload(req.model_dump())
        data = account_profile.save_account_profile(total, cash)
        return {"configured": True, "data": data}
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"账户资金保存异常：{e}") from e


# ---- 我的研报（用户上传自己的研报，存本地、不上传、不进开源仓库）----

class ReportIn(BaseModel):
    name: str
    content_b64: str
    title: str | None = None
    institution: str | None = None
    publish_date: str | None = None
    sector_keys: list[str] | None = None
    source_url: str | None = None
    source_kind: str | None = None
    model_config = ConfigDict(extra="forbid")


class ReportMetaPatch(BaseModel):
    """PATCH 元数据：字段未出现 = 保持原值；"" / [] = 明确清空；null = 由路由拒绝 400。"""
    model_config = ConfigDict(extra="forbid")
    title: str | None = None
    institution: str | None = None
    publish_date: str | None = None
    sector_keys: list[str] | None = None
    source_url: str | None = None
    source_kind: str | None = None


@app.get("/api/myreports")
def myreports_list():
    return {"data": mr.list_reports()}


@app.post("/api/myreports")
def myreports_upload(r: ReportIn):
    """上传一份研报（base64）→ 存本地 + 按文件名自动打行业标签。支持可选丰富元数据。"""
    try:
        return {"data": mr.save_report(
            r.name, r.content_b64,
            title=r.title, institution=r.institution,
            publish_date=r.publish_date, sector_keys=r.sector_keys,
            source_url=r.source_url, source_kind=r.source_kind,
        )}
    except mr.ReportError as e:
        raise HTTPException(400, str(e)) from e


@app.get("/api/myreports/file/{rid}")
def myreports_file(rid: str):
    """下载/预览某份研报原文件。"""
    hit = mr.report_path(rid)
    if not hit:
        raise HTTPException(404, "研报不存在")
    path, name = hit
    return FileResponse(str(path), filename=name)


@app.delete("/api/myreports/{rid}")
def myreports_delete(rid: str):
    return {"data": {"ok": mr.delete_report(rid)}}


@app.get("/api/myreports/browse")
def myreports_browse(group: str = Query(...), sector_key: str | None = None):
    """按 year / industry / institution 分组浏览研报档案。"""
    try:
        return {"data": mr.build_browse(mr.list_reports(), group, sector_key=sector_key)}
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@app.get("/api/myreports/search")
def myreports_search(q: str = ""):
    """全文检索：匹配 name / title / institution / sector_keys。"""
    return {"data": mr.search_reports(mr.list_reports(), q)}


@app.patch("/api/myreports/{rid}")
def myreports_update(rid: str, body: ReportMetaPatch):
    """部分更新研报元数据（标题 / 机构 / 发布日期 / 关联赛道 / 来源 / 类型）。"""
    try:
        updated = mr.update_report_meta(rid, body.model_dump(exclude_unset=True))
    except mr.ReportError as e:
        raise HTTPException(400, str(e)) from e
    if updated is None:
        raise HTTPException(404, "研报不存在")
    return {"data": updated}


class CloseIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str
    date: str
    price: float
    shares: int
    cost: float

    @model_validator(mode="before")
    @classmethod
    def _strict_types(cls, values):
        if isinstance(values, dict):
            _reject_bool_str(values.get("price"), "price")
            _reject_bool_str(values.get("shares"), "shares")
            _reject_bool_str(values.get("cost"), "cost")
            if isinstance(values.get("shares"), float):
                raise ValueError("shares 不能是小数")
        return values


@app.post("/api/portfolio/close")
def portfolio_close(c: CloseIn):
    """记一笔已清仓（已实现盈亏）。存本地。"""
    code = (c.code or "").strip()
    if not code.isdigit() or len(code) != 6:
        raise HTTPException(400, "代码必须是 6 位数字")
    if isinstance(c.price, bool) or not isinstance(c.price, (int, float)):
        raise HTTPException(400, "清仓价必须是有效数字")
    if c.price <= 0 or c.price != c.price or c.price in (float("inf"), float("-inf")):
        raise HTTPException(400, "清仓价必须大于 0")
    if isinstance(c.shares, bool) or not isinstance(c.shares, int) or c.shares <= 0:
        raise HTTPException(400, "股数必须为正整数")
    if isinstance(c.cost, bool) or not isinstance(c.cost, (int, float)):
        raise HTTPException(400, "成本价必须是有效数字")
    if c.cost != c.cost or c.cost in (float("inf"), float("-inf")):
        raise HTTPException(400, "成本价必须是有效数字")
    # 买入成本不限正负（同持仓录入）：按 (清仓价 - 成本) × 股数 的结果计算已实现盈亏。
    date = (c.date or "").strip()
    if not date:
        raise HTTPException(400, "请填清仓日期")
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(400, "清仓日期格式应为 YYYY-MM-DD") from None
    return {"data": pf.close_position(code, date, c.price, c.shares, c.cost)}


@app.delete("/api/portfolio/close")
def portfolio_close_remove(index: int = Query(...)):
    return {"data": pf.remove_closed(index)}


@app.post("/api/portfolio/refresh")
def portfolio_refresh():
    """手动刷新：立即重拉行情算盈亏。"""
    try:
        return {"data": pf.get_portfolio()}
    except pf.PortfolioDataCorruptedError:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"刷新失败：{e}") from e


@app.get("/api/radar")
def radar():
    """资讯雷达：12 赛道公开 RSS 资讯（读缓存，无缓存返回赛道骨架）。"""
    try:
        return {"data": newsradar.get_radar(force=False)}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"资讯雷达异常：{e}") from e


@app.post("/api/radar/refresh")
def radar_refresh():
    """强制重抓全部 RSS 源（耗时约 20-40s），更新缓存。"""
    try:
        return {"data": newsradar.fetch_radar()}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"资讯雷达刷新失败：{e}") from e


@app.get("/api/market/overview")
def market_overview():
    """市场情绪 + 板块资金流（板块/大盘级，全站共享缓存 5 分钟）。"""
    try:
        return {"data": market.get_overview()}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"市场总览异常：{e}") from e


@app.get("/api/market/emotion")
def market_emotion():
    """短线情绪：连板梯队 / 最高连板 / 炸板率 / 封板率 / 晋级率 / 涨跌停家数 + 连板股清单。全站共享缓存 5 分钟。"""
    try:
        return {"data": market.get_short_term_emotion()}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"短线情绪异常：{e}") from e


@app.get("/api/market/turnover-top")
def market_turnover_top():
    """全市场成交额榜 Top20。全站共享缓存 5 分钟。"""
    try:
        return {"data": market.get_turnover_top()}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"成交额榜异常：{e}") from e


@app.get("/api/market/breadth")
def market_breadth():
    """全A股市场广度、总成交额、成交额榜与高换手榜。共享缓存 5 分钟。

    市场层始终返回 status 信封（normal/partial/unavailable）→ HTTP 200；
    仅真正逃逸的未预期异常 → HTTP 502。
    """
    try:
        return {"data": market.get_market_breadth()}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"市场广度异常：{e}") from e


@app.get("/api/market/boards")
def market_boards(
    type: str = Query("industry", description="板块类型：industry | concept | region"),
    top_n: int = Query(20, description="最强/最弱各取前 N（1~100）"),
):
    """行业 / 概念 / 地域板块涨跌幅排名。共享缓存 5 分钟（底层固定抓 100，再按 top_n 切片）。

    - normal / partial / unavailable → HTTP 200（状态在 body.data.status）
    - 非法 type / top_n → HTTP 400
    - 未预期异常 → HTTP 502
    """
    try:
        return {"data": market.get_board_ranking(type, top_n)}
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"板块排名异常：{e}") from e


@app.get("/api/market/northbound")
def market_northbound():
    """北向资金（沪股通 / 深股通）权威日统计。共享缓存 15 分钟（unavailable 不缓存）。

    - 正常 / 部分 / 不可用 → 均返回 HTTP 200，状态以 body.data.status 为准。
    - 上游失败不抛 5xx，降级为 unavailable 信封。
    """
    key = ("market_northbound", "")
    hit = _DC_CACHE.get(key, 900)
    if hit is not _CACHE_MISS:
        return {"data": hit}

    try:
        data = ncf.get_northbound_capital_flow()
    except Exception:  # noqa: BLE001
        data = ncf.unavailable_envelope(reason_code="UPSTREAM_UNAVAILABLE")

    st = data.get("status") if isinstance(data, dict) else None
    if st != "unavailable":
        # unavailable 不缓存，下次直接重试
        _DC_CACHE.set(key, data)

    try:
        import data_health_event_store as _dhes
        if st == "normal":
            _dhes.safe_call(_dhes.record_success, "northbound_capital_flow")
        elif st == "partial":
            _dhes.safe_call(_dhes.record_partial, "northbound_capital_flow")
        else:
            _dhes.safe_call(_dhes.record_failure, "northbound_capital_flow", "SOURCE_UNAVAILABLE")
    except Exception:
        pass

    return {"data": data}


@app.get("/api/market/top-risk")
def market_top_risk(
    code: str = Query(..., min_length=1, max_length=16, description="6 位股票代码"),
    days: int = Query(120, ge=10, le=800, description="回看交易日数"),
):
    """顶部风险分析（影子模式，第一版）。

    - 正常 / 部分 / 不可用 → 均返回 HTTP 200，状态以 body.data.status 为准；
    - signal 恒为 unknown，signal_eligible 恒为 False（不改最终交易结论 / 仓位）；
    - 上游失败不抛 5xx，降级为 unavailable 信封（fail-closed）。
    """
    code = (code or "").strip()
    if not code:
        raise HTTPException(400, "code 不能为空")
    try:
        env = trs.analyze_top_risk(code, days)
    except Exception:  # noqa: BLE001 — 不应发生，仍兜底为不可用（通过公开函数）
        env = trs.attach_trace_and_archive(
            trs.unavailable_envelope(
                code,
                [{"field": "service", "reason_code": "UPSTREAM_UNAVAILABLE", "detail": "顶部风险服务当前不可用。"}],
            )
        )
    return {"data": env.model_dump()}


# ---------------------------------------------------------------------------
# 自选股（后端权威 JSON，前端 localStorage 仅作缓存/草稿）
# ---------------------------------------------------------------------------


@app.get("/api/watchlist")
def watchlist_get():
    """后端权威自选股 + etag。未配置 → status=not_configured, data=null。"""
    try:
        return {"data": watchlist_store.get_watchlist_status()}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"自选股读取异常：{e}") from e


class WatchlistIn(BaseModel):
    """全量保存自选股。updated_at 由后端生成，禁止客户端提交。"""

    model_config = ConfigDict(extra="forbid")

    codes: list[str]
    expected_etag: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _strict_codes(cls, values):
        if isinstance(values, dict):
            codes = values.get("codes")
            if codes is not None and not isinstance(codes, list):
                raise ValueError("codes 必须是数组")
        return values


@app.put("/api/watchlist")
def watchlist_save(req: WatchlistIn):
    """全量保存自选股（原子写入 + 可选 etag 乐观锁）。冲突 → 409。"""
    try:
        result = watchlist_store.save_watchlist(req.codes, expected_etag=req.expected_etag)
        return {"data": result}
    except watchlist_store.WatchlistVersionConflictError as e:
        raise HTTPException(409, str(e)) from e
    except watchlist_store.WatchlistLimitExceededError as e:
        raise HTTPException(400, str(e)) from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"自选股保存异常：{e}") from e


class WatchlistImportLocalIn(BaseModel):
    """显式把前端 localStorage 草稿并入后端。"""

    model_config = ConfigDict(extra="forbid")

    codes: list[str]
    expected_etag: str | None = None


@app.post("/api/watchlist/import-local")
def watchlist_import_local(req: WatchlistImportLocalIn):
    """并入前端 localStorage → 后端（保留后端已有 + 去重并入）。冲突 → 409。"""
    try:
        result = watchlist_store.merge_watchlist(req.codes, expected_etag=req.expected_etag)
        return {"data": result}
    except watchlist_store.WatchlistVersionConflictError as e:
        raise HTTPException(409, str(e)) from e
    except watchlist_store.WatchlistLimitExceededError as e:
        raise HTTPException(400, str(e)) from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"自选股并入异常：{e}") from e


# ---------------------------------------------------------------------------
# 明日决策驱动舱（tomorrow-plan）
# ---------------------------------------------------------------------------


class TomorrowPlanGenerateIn(BaseModel):
    """生成明日计划请求。trade_date 由客户端指定；llm 可选。"""

    model_config = ConfigDict(extra="forbid")

    trade_date: str
    llm: LLMConfig | None = None
    force: bool = False


@app.get("/api/decision-cockpit/overview")
def decision_cockpit_overview(
    trade_date: str = Query(..., description="交易日 YYYY-MM-DD"),
):
    """驱动舱总览（只读聚合）：市场 / 账户 / 持仓建议 / 当前计划 / 候选池。

    非法 trade_date → 400；历史日只读已保存计划，不混入今日实时行情。
    """
    try:
        return {"data": get_overview(trade_date)}
    except DecisionCockpitError as e:
        # trade_date 非法 / 未来日等
        raise HTTPException(400, str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"驱动舱总览异常：{e}") from e


@app.get("/api/decision-cockpit/today-actions")
def decision_cockpit_today_actions(
    trade_date: str = Query(..., description="交易日 YYYY-MM-DD"),
):
    """今日实时行动（只读聚合）：持仓 + 当前计划信号 + 建议 + 自选异动。

    不生成计划、不调模型、不写 sqlite。非法 trade_date → 400；其它异常 → 500。
    """
    try:
        return {"data": get_today_actions(trade_date)}
    except DecisionCockpitError as e:
        raise HTTPException(400, str(e)) from e
    except Exception:  # noqa: BLE001 — 不向客户端暴露内部细节
        raise HTTPException(500, "今日实时行动聚合失败") from None


@app.post("/api/decision-cockpit/tomorrow-plan/generate")
def decision_cockpit_generate(req: TomorrowPlanGenerateIn):
    """生成新的明日计划版本（候选池 + 信号 + 解释 + 持久化）。

    - 非法 trade_date → 400
    - 非最新复盘 trade_date / 缺快照 → 409（明日计划只能基于最新已保存复盘生成）
    - 市场广度不可用 → 503
    - 候选池为空 → 409
    - LLM 调用失败 → 自动回退确定性摘要（仍返回 200，但 explanation.source=deterministic）
    """
    try:
        cfg = req.llm.model_dump() if req.llm else None
        result = generate_tomorrow_plan(req.trade_date, cfg=cfg, force=req.force)
        return {"data": result}
    except DecisionCockpitMarketDataError as e:
        raise HTTPException(503, str(e) or "市场核心数据暂不可用，无法生成明日计划") from None
    except DecisionCockpitSnapshotError as e:
        raise HTTPException(409, str(e)) from e
    except DecisionCockpitModelError as e:
        raise HTTPException(502, f"明日计划解释生成失败：{e}") from e
    except DecisionCockpitError as e:
        msg = str(e)
        # 日期格式/日历/未来日 → 400；业务拒绝（空池等）→ 409
        if any(
            k in msg
            for k in (
                "trade_date",
                "YYYY-MM-DD",
                "非法",
                "未来",
                "不能为空",
            )
        ) and "候选池" not in msg:
            raise HTTPException(400, msg) from e
        raise HTTPException(409, msg) from e
    except Exception:  # noqa: BLE001 — 不向客户端暴露内部细节
        raise HTTPException(500, "明日计划生成失败") from None


@app.get("/api/decision-cockpit/tomorrow-plan/current")
def decision_cockpit_current(
    trade_date: str = Query(..., description="交易日 YYYY-MM-DD"),
):
    """读取指定交易日的 current 计划（含信号）；不存在返回 data=null。"""
    try:
        plan = dc_get_current_plan(trade_date)
        return {"data": plan}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"读取当前计划异常：{e}") from e


@app.get("/api/decision-cockpit/tomorrow-plan/history")
def decision_cockpit_history(
    trade_date: str | None = Query(None, description="按交易日过滤"),
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """列计划元数据（不含 payload，只读）。"""
    try:
        return {"data": dc_list_plans(trade_date, limit=limit, offset=offset)}
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"计划历史异常：{e}") from e


@app.get("/api/decision-cockpit/tomorrow-plan/{plan_id}")
def decision_cockpit_get(plan_id: int):
    """按主键读取单个计划（含信号）。不存在 → 404。"""
    try:
        plan = dc_get_plan(plan_id)
        if plan is None:
            raise HTTPException(404, "计划不存在")
        return {"data": plan}
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"读取计划异常：{e}") from e


class FreezePlanIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int


@app.post("/api/decision-cockpit/tomorrow-plan/{plan_id}/freeze")
def decision_cockpit_freeze(plan_id: int, req: FreezePlanIn):
    """冻结指定计划（draft → frozen）。版本冲突 / 状态不符 → 409。"""
    try:
        plan = freeze_tomorrow_plan(plan_id, req.expected_version)
        return {"data": plan}
    except ValueError as e:
        raise HTTPException(409, str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"冻结计划异常：{e}") from e


@app.get("/api/daily-review")
def daily_review_snapshot():
    """结构化 A 股每日复盘数据包（展示路径，可 stale-while-revalidate）。

    聚合层已对组件异常做隔离；normal/partial/unavailable 均为 HTTP 200。
    仅展示聚合逃逸的未预期异常 → HTTP 502。
    响应保持 ``data`` 为复盘包；可选 ``cache_meta``（source/stale/refreshing 等）。
    本接口不接受 date/refresh 等参数，不支持历史日期查询。
    持仓建议等业务仍走 generate_daily_review fresh 路径，不用本接口 stale 结果。
    """
    try:
        payload = daily_review.get_daily_review_for_display()
        # 保证 data 位置；cache_meta 可选透传
        out = {"data": payload.get("data")}
        meta = payload.get("cache_meta")
        if isinstance(meta, dict):
            out["cache_meta"] = meta
        return out
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"每日复盘聚合异常：{e}") from e


@app.post("/api/daily-review/refresh")
def daily_review_refresh():
    """用户显式刷新复盘完整包：绕过 300s 内存缓存，真正 single-flight。

    不调用 AI、不写 daily_review_snapshots、不生成持仓建议。
    成功质量结果 → 200 + 新 data；失败保留服务端上次成功，返回非 2xx
    （前端保留旧 UI 并提示「最新数据刷新失败…」）。
    """
    try:
        payload = daily_review.refresh_daily_review_for_display()
        out = {"data": payload.get("data")}
        meta = payload.get("cache_meta")
        if isinstance(meta, dict):
            out["cache_meta"] = meta
        data = out.get("data")
        if not isinstance(data, dict):
            raise HTTPException(503, "市场核心数据暂不可用，无法刷新每日复盘")
        return out
    except daily_review.DailyReviewRefreshError as e:
        # 不把降级包当成功返回；旧成功仍在内存/磁盘，供后续 GET
        reason = getattr(e, "reason", "") or ""
        if reason in (
            "unavailable",
            "critical_unavailable",
            "partial_with_existing_normal",
            "persist_failed",
            "store_rejected",
            "invalid_result",
            "invalid_status",
        ):
            raise HTTPException(
                503,
                str(e) or "市场核心数据暂不可用，无法刷新每日复盘",
            ) from None
        raise HTTPException(
            502,
            str(e) or "市场数据刷新失败，请稍后重试",
        ) from None
    except HTTPException:
        raise
    except Exception:  # noqa: BLE001 — 不向客户端暴露内部细节
        raise HTTPException(502, "每日复盘刷新异常") from None


class DailyReviewAnalyzeRequest(BaseModel):
    """每日复盘 AI 分析请求。

    仅接受 user_request；市场上下文由服务器端聚合投影生成，客户端不可注入。
    llm 复用通用聊天的 LLMConfig（非第二套模型配置字段）。
    """
    user_request: str | None = None
    llm: LLMConfig


@app.post("/api/daily-review/analyze")
async def analyze_daily_review(req: DailyReviewAnalyzeRequest, request: Request):
    """每日复盘 AI 流式分析（NDJSON，协议与 /api/chat 相同）。

    服务器链路：generate_daily_review → render AI context → build messages → stream_messages。
    上下文准备失败 → HTTP 502；模型运行时错误 → 流内 error 事件。
    不接受客户端 context/messages/system_prompt。
    """
    _require_llm_ready(req.llm)

    try:
        prepared = await run_in_threadpool(
            chat_layer.prepare_daily_review_analysis,
            req.user_request,
        )
        review = prepared["review"]
        messages = prepared["messages"]
    except Exception:  # noqa: BLE001 — no prompt, path, or source error leakage
        raise HTTPException(502, "每日复盘AI上下文准备失败") from None

    cfg = req.llm.model_dump()
    disconnect_event = threading.Event()
    cfg["_cancel_event"] = disconnect_event

    async def gen():
        source = iter(chat_layer.stream_messages(cfg, messages, use_tools=False))
        try:
            parts: list[str] = []
            saw_done = False
            trace: list[dict] = []
            rounds = 0
            async for ev in iterate_in_threadpool(source):
                if disconnect_event.is_set():
                    return
                if not isinstance(ev, dict):
                    continue
                event_type = ev.get("type")
                if event_type == "delta":
                    if saw_done:
                        raise chat_layer.ModelStreamIncompleteError()
                    text = ev.get("text")
                    if text is None:
                        continue
                    if not isinstance(text, str):
                        text = str(text)
                    parts.append(text)
                    yield json.dumps({"type": "delta", "text": text}, ensure_ascii=False) + "\n"
                elif event_type == "error":
                    raise RuntimeError("upstream stream error")
                elif event_type == "done":
                    if saw_done:
                        raise chat_layer.ModelStreamIncompleteError()
                    saw_done = True
                    trace = ev.get("trace") if isinstance(ev.get("trace"), list) else []
                    rounds = ev.get("rounds") if isinstance(ev.get("rounds"), int) else 0
            if not saw_done:
                raise chat_layer.ModelStreamIncompleteError()
            markdown = "".join(parts)
            if not markdown.strip():
                raise ValueError("empty model output")
            if disconnect_event.is_set():
                return
            saved_record = await run_in_threadpool(
                ai_result_service.save_daily_review_ai,
                review,
                markdown,
                cfg,
                should_cancel=disconnect_event.is_set,
            )
            if disconnect_event.is_set():
                return
            result = _safe_daily_review_ai_done_result(saved_record)
            yield json.dumps(
                {"type": "done", "trace": trace, "rounds": rounds, "result": result},
                ensure_ascii=False,
            ) + "\n"
        except Exception:  # noqa: BLE001 — fixed safe stream error; old persisted row remains
            if disconnect_event.is_set():
                return
            yield json.dumps(
                {"type": "error", "message": "对话失败：每日复盘AI生成或保存失败"},
                ensure_ascii=False,
            ) + "\n"
        finally:
            close = getattr(source, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass

    return _DisconnectAwareStreamingResponse(
        gen(),
        media_type="application/x-ndjson",
        disconnect_event=disconnect_event,
    )


@app.get("/api/ai-results/{result_type}")
def get_ai_result(
    result_type: str,
    trade_date: str | None = Query(None),
):
    """Restore one authoritative AI result without model or fresh aggregation."""
    try:
        result = ai_result_service.get_ai_result(
            result_type,
            trade_date=trade_date,
        )
        return {"data": result}
    except ai_result_service.AiResultValidationError:
        raise HTTPException(422, "AI结果查询参数无效") from None
    except Exception:  # noqa: BLE001 — never expose path, SQL, payload, or traceback
        raise HTTPException(500, "AI结果读取失败") from None


# ---- 每日复盘历史（显式保存；GET 与 analyze 均不写 daily_review_snapshots）----

@app.post("/api/daily-review/history/save")
def daily_review_history_save():
    """显式保存当前每日复盘快照到历史库。

    inserted=true/false 均为 HTTP 200（内容去重不算错误）。
    不可保存（unavailable / 无 trade_date 等）→ HTTP 409。
    不接受客户端 db_path。
    """
    try:
        return {"data": review_history.save_current_daily_review()}
    except review_history.ReviewSnapshotNotSavableError as e:
        raise HTTPException(409, str(e)) from e
    except Exception:  # noqa: BLE001 — 不向客户端暴露路径/SQL
        raise HTTPException(500, "每日复盘历史保存失败") from None


@app.get("/api/daily-review/history")
def daily_review_history_list(
    trade_date: str | None = Query(None),
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """历史快照元数据列表（不含完整 review）。"""
    try:
        items = review_history.list_review_history(
            trade_date=trade_date,
            limit=limit,
            offset=offset,
        )
        return {
            "data": {
                "items": items,
                "trade_date": trade_date,
                "limit": limit,
                "offset": offset,
                "count": len(items),
            }
        }
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except Exception:  # noqa: BLE001
        raise HTTPException(500, "每日复盘历史列表读取失败") from None


@app.get("/api/daily-review/history/latest")
def daily_review_history_latest(
    trade_date: str | None = Query(None),
):
    """最新历史快照（含完整 review）。须定义在 {snapshot_id} 之前。"""
    try:
        snapshot = review_history.get_latest_review_history_snapshot(
            trade_date=trade_date,
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except Exception:  # noqa: BLE001
        raise HTTPException(500, "每日复盘最新历史读取失败") from None
    if snapshot is None:
        raise HTTPException(404, "未找到每日复盘历史快照")
    return {"data": snapshot}


@app.get("/api/daily-review/history/compare")
def daily_review_history_compare(
    base_id: int = Query(..., ge=1),
    target_id: int = Query(..., ge=1),
    board_limit: int = Query(10, ge=1, le=20),
    stock_limit: int = Query(10, ge=1, le=30),
):
    """比较两份历史快照（纯读取，无写库/无 AI）。

    须定义在 {snapshot_id} 之前，避免 compare 被当成 ID。
    comparison_status 为 normal/partial/unavailable 时均 HTTP 200。
    允许 base_id == target_id。
    不接受客户端 db_path。
    """
    try:
        base_snapshot = review_history.get_review_history_snapshot(base_id)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except Exception:  # noqa: BLE001
        raise HTTPException(500, "每日复盘历史快照比较失败") from None
    if base_snapshot is None:
        raise HTTPException(404, "未找到基础每日复盘历史快照")

    try:
        target_snapshot = review_history.get_review_history_snapshot(target_id)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except Exception:  # noqa: BLE001
        raise HTTPException(500, "每日复盘历史快照比较失败") from None
    if target_snapshot is None:
        raise HTTPException(404, "未找到目标每日复盘历史快照")

    try:
        comparison = review_compare.compare_daily_review_snapshots(
            base_snapshot,
            target_snapshot,
            board_limit=board_limit,
            stock_limit=stock_limit,
        )
    except (TypeError, ValueError):
        raise HTTPException(400, "每日复盘快照比较参数或数据结构无效") from None
    except Exception:  # noqa: BLE001
        raise HTTPException(500, "每日复盘历史快照比较失败") from None

    return {"data": comparison}


@app.get("/api/daily-review/history/{snapshot_id}")
def daily_review_history_detail(snapshot_id: int):
    """按 ID 读取历史快照详情（含完整 review）。"""
    try:
        snapshot = review_history.get_review_history_snapshot(snapshot_id)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except Exception:  # noqa: BLE001
        raise HTTPException(500, "每日复盘历史详情读取失败") from None
    if snapshot is None:
        raise HTTPException(404, "未找到每日复盘历史快照")
    return {"data": snapshot}


@app.get("/api/global/indices")
def global_indices():
    """全球指数快照（道指 / 标普500 / 纳斯达克 / 恒生 / 恒生科技）—— A 股看隔夜外围脸色。缓存 5 分钟。"""
    try:
        return {"data": market.get_global_indices()}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"全球指数异常：{e}") from e


@app.get("/api/global/stock")
def global_stock(symbol: str = Query(..., min_length=1, max_length=16)):
    """美股 / 港股个股聚合：行情 + 关键财务指标（东财域内源）。symbol 如 AAPL / BABA / 00700。"""
    try:
        data = gstock.us_hk_stock(symbol.strip())
        if not data:
            raise HTTPException(404, f"未找到美股/港股代码「{symbol}」")
        return {"data": data}
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"美港股查询异常：{e}") from e


@app.get("/api/indices")
def indices():
    """A股大盘指数实时行情（上证/深证成指/创业板指/沪深300）。仅标准库。"""
    try:
        return {"data": astock.index_quote()}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"指数行情异常：{e}") from e


@app.get("/api/quote")
def quote(codes: str = Query(..., description="逗号分隔的 6 位代码")):
    """实时行情：现价/涨跌/PE/PB/市值/换手/涨跌停。仅标准库，永远可用。"""
    lst = [c.strip() for c in codes.split(",") if c.strip()]
    if not lst or any(not c.isdigit() or len(c) != 6 for c in lst):
        raise HTTPException(400, "codes 必须是逗号分隔的 6 位数字")
    try:
        data = astock.tencent_quote(lst)
        # 健康事件：最近一次真实 quotes 调用（覆盖不持久化）
        try:
            import data_health_event_store as _dhes
            if not isinstance(data, dict) or not data:
                _dhes.safe_call(_dhes.record_failure, "quotes", "SOURCE_UNAVAILABLE")
            elif any(c not in data for c in lst):
                _dhes.safe_call(_dhes.record_partial, "quotes")
            else:
                _dhes.safe_call(_dhes.record_success, "quotes")
        except Exception:
            pass
        return {"data": data}
    except Exception as e:  # noqa: BLE001 — 边界统一兜底
        try:
            import data_health_event_store as _dhes
            _dhes.safe_call(_dhes.record_failure, "quotes", "SOURCE_UNAVAILABLE")
        except Exception:
            pass
        raise HTTPException(502, f"行情源异常：{e}") from e


_CACHE_MISS = object()


class TTLCache:
    """带 TTL 过期和容量上限的 LRU 缓存，避免长期运行内存无限增长。"""

    def __init__(self, max_entries: int = 512):
        self._data: OrderedDict = OrderedDict()
        self._max = max_entries
        self._lock = threading.Lock()

    def get(self, key, ttl: float):
        with self._lock:
            hit = self._data.get(key, _CACHE_MISS)
            if hit is _CACHE_MISS:
                return _CACHE_MISS
            ts, val = hit
            if time.time() - ts < ttl:
                self._data.move_to_end(key)
                return val
            del self._data[key]
            return _CACHE_MISS

    def set(self, key, val):
        with self._lock:
            if key in self._data:
                self._data.move_to_end(key)
            self._data[key] = (time.time(), val)
            while len(self._data) > self._max:
                self._data.popitem(last=False)


_PCT_CACHE = TTLCache()


@app.get("/api/valuation/percentile")
def valuation_percentile(code: str = Query(...)):
    """PE-TTM / PB 历史分位（近5年）。全站缓存 30 分钟/代码（历史序列日频、变化慢）。"""
    code = _validate(code)
    hit = _PCT_CACHE.get(code, 1800)
    if hit is not _CACHE_MISS:
        return {"data": hit}
    try:
        data = astock.valuation_percentile(code)
        _PCT_CACHE.set(code, data)
        return {"data": data}
    except astock.DependencyMissing as e:
        raise HTTPException(501, str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"估值分位异常：{e}") from e


_ANN_CACHE = TTLCache()


@app.get("/api/announcements")
def announcements(code: str = Query(...)):
    """个股近期公告（东财，仅 requests）。缓存 15 分钟/代码。"""
    code = _validate(code)
    hit = _ANN_CACHE.get(code, 900)
    if hit is not _CACHE_MISS:
        return {"data": hit}
    try:
        data = astock.announcements(code)
        _ANN_CACHE.set(code, data)
        try:
            import data_health_event_store as _dhes
            # 合法空列表是 normal
            _dhes.safe_call(_dhes.record_success, "announcements")
        except Exception:
            pass
        return {"data": data}
    except Exception as e:  # noqa: BLE001
        try:
            import data_health_event_store as _dhes
            _dhes.safe_call(_dhes.record_failure, "announcements", "SOURCE_UNAVAILABLE")
        except Exception:
            pass
        raise HTTPException(502, f"公告源异常：{e}") from e


_FIN_CACHE = TTLCache()


@app.get("/api/financials")
def financials(code: str = Query(...)):
    """财务关键指标（同花顺财务摘要，最新报告期）。缓存 30 分钟/代码。"""
    code = _validate(code)
    hit = _FIN_CACHE.get(code, 1800)
    if hit is not _CACHE_MISS:
        return {"data": hit}
    try:
        data = astock.financials(code)
        _FIN_CACHE.set(code, data)
        try:
            import data_health_event_store as _dhes
            if not isinstance(data, dict) or not data:
                _dhes.safe_call(_dhes.record_failure, "financials", "SOURCE_UNAVAILABLE")
            elif data.get("revenue") is None and data.get("net_profit") is None:
                _dhes.safe_call(_dhes.record_partial, "financials")
            else:
                _dhes.safe_call(_dhes.record_success, "financials")
        except Exception:
            pass
        return {"data": data}
    except astock.DependencyMissing as e:
        try:
            import data_health_event_store as _dhes
            _dhes.safe_call(_dhes.record_failure, "financials", "SOURCE_UNAVAILABLE")
        except Exception:
            pass
        raise HTTPException(501, str(e)) from e
    except Exception as e:  # noqa: BLE001
        try:
            import data_health_event_store as _dhes
            _dhes.safe_call(_dhes.record_failure, "financials", "SOURCE_UNAVAILABLE")
        except Exception:
            pass
        raise HTTPException(502, f"财务摘要异常：{e}") from e


@app.get("/api/valuation")
def valuation(code: str = Query(...)):
    """完整估值：行情 + 一致预期 + 前向PE/PEG/消化年数。"""
    code = _validate(code)
    try:
        return {"data": astock.full_valuation(code)}
    except ValueError as e:
        raise HTTPException(404, str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"估值计算异常：{e}") from e


@app.get("/api/reports")
def reports(code: str = Query(...), pages: int = Query(2, ge=1, le=5)):
    """个股研报列表（东财，含 PDF 链接）。仅需 requests。"""
    code = _validate(code)
    try:
        rows = astock.eastmoney_reports(code, max_pages=pages)
        for r in rows:
            r["pdfUrl"] = astock.pdf_url(r.get("infoCode", "")) if r.get("infoCode") else None
        return {"data": rows}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"研报源异常：{e}") from e


@app.get("/api/news")
def news(code: str = Query(...), limit: int = Query(20, ge=1, le=50)):
    """个股新闻（东财，需 akshare）。"""
    code = _validate(code)
    try:
        return {"data": astock.stock_news(code, limit=limit)}
    except astock.DependencyMissing as e:
        raise HTTPException(501, str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"新闻源异常：{e}") from e


@app.get("/api/info")
def info(code: str = Query(...)):
    """个股基本面：行业/股本/上市时间（需 akshare）。"""
    code = _validate(code)
    try:
        return {"data": astock.individual_info(code)}
    except astock.DependencyMissing as e:
        raise HTTPException(501, str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"基本面源异常：{e}") from e


@app.get("/api/disclosure")
def disclosure(code: str = Query(...)):
    """巨潮公告列表（需 akshare）。"""
    code = _validate(code)
    try:
        return {"data": astock.disclosure(code)}
    except astock.DependencyMissing as e:
        raise HTTPException(501, str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"公告源异常：{e}") from e


@app.get("/api/kline")
def kline(code: str = Query(...), category: int = Query(4), offset: int = Query(60, ge=1, le=800)):
    """K线（需 mootdx）。category 4=日 5=周 6=月 11=60分钟。"""
    code = _validate(code)
    try:
        return {"data": astock.kline(code, category=category, offset=offset)}
    except astock.DependencyMissing as e:
        raise HTTPException(501, str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"K线源异常：{e}") from e


@app.get("/api/finance")
def finance(code: str = Query(...)):
    """季报财务快照（需 mootdx）。"""
    code = _validate(code)
    try:
        return {"data": astock.finance(code)}
    except astock.DependencyMissing as e:
        raise HTTPException(501, str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"财务源异常：{e}") from e


# ---------------------------------------------------------------------------
# 资金面 / 筹码 / 信号（东财数据中心，v3.3 并入）—— 均为「用户查的那只股」的公开数据。
# 东财有 1s 限流，这些多为日/季级静态数据，统一走 30 分钟缓存，进一步降低被封风险。
# ---------------------------------------------------------------------------

_DC_CACHE = TTLCache(max_entries=1024)  # key=(endpoint, code) -> (ts, data)


def _cached(endpoint: str, code: str, ttl: int, fetch):
    key = (endpoint, code)
    hit = _DC_CACHE.get(key, ttl)
    if hit is not _CACHE_MISS:
        return hit
    data = fetch()
    _DC_CACHE.set(key, data)
    return data


@app.get("/api/margin")
def margin(code: str = Query(...)):
    """融资融券明细（东财，日级）。缓存 30 分钟。"""
    code = _validate(code)
    try:
        return {"data": _cached("margin", code, 1800, lambda: astock.margin_trading(code))}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"融资融券异常：{e}") from e


@app.get("/api/block-trade")
def block_trade(code: str = Query(...)):
    """大宗交易（东财）。缓存 30 分钟。"""
    code = _validate(code)
    try:
        return {"data": _cached("block", code, 1800, lambda: astock.block_trade(code))}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"大宗交易异常：{e}") from e


@app.get("/api/holders")
def holders(code: str = Query(...)):
    """股东户数变化（东财，季度级）。缓存 30 分钟。"""
    code = _validate(code)
    try:
        return {"data": _cached("holders", code, 1800, lambda: astock.holder_num_change(code))}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"股东户数异常：{e}") from e


@app.get("/api/dividend")
def dividend(code: str = Query(...)):
    """分红送转历史（东财）。缓存 30 分钟。"""
    code = _validate(code)
    try:
        return {"data": _cached("dividend", code, 1800, lambda: astock.dividend_history(code))}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"分红送转异常：{e}") from e


@app.get("/api/fund-flow")
def fund_flow(code: str = Query(...)):
    """个股资金流（东财 push2his，120 日主力净流入）。缓存 15 分钟。
    注：push2his 对部分大陆住宅 IP 有间歇风控，可能返回空（非代码问题）。"""
    code = _validate(code)
    try:
        return {"data": _cached("fundflow", code, 900, lambda: astock.stock_fund_flow_120d(code))}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"资金流异常：{e}") from e


@app.get("/api/dragon-tiger")
def dragon_tiger(code: str = Query(...)):
    """龙虎榜：该股近期上榜记录 + 买卖席位 + 机构净买（东财）。缓存 30 分钟。"""
    code = _validate(code)
    try:
        return {"data": _cached("dt", code, 1800, lambda: astock.dragon_tiger_board(code))}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"龙虎榜异常：{e}") from e


@app.get("/api/lockup")
def lockup(code: str = Query(...)):
    """限售解禁日历：历史解禁 + 未来 90 天待解禁（东财）。缓存 30 分钟。"""
    code = _validate(code)
    try:
        return {"data": _cached("lockup", code, 1800, lambda: astock.lockup_expiry(code))}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"解禁日历异常：{e}") from e


@app.get("/api/blocks")
def blocks(code: str = Query(...)):
    """个股所属板块/概念归属（东财 slist）。缓存 30 分钟。"""
    code = _validate(code)
    try:
        return {"data": _cached("blocks", code, 1800, lambda: astock.concept_blocks(code))}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"板块归属异常：{e}") from e


@app.get("/api/hot-concepts")
def hot_concepts(code: str = Query(...)):
    """个股当下被市场归到哪些概念在炒（东财热门概念命中）。缓存 15 分钟。"""
    code = _validate(code)
    try:
        return {"data": _cached("hotcon", code, 900, lambda: astock.hot_concepts(code))}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"热门概念异常：{e}") from e


@app.get("/api/investor-qa")
def investor_qa(code: str = Query(...)):
    """互动易问答（巨潮）：投资者提问 + 公司回复。缓存 15 分钟。"""
    code = _validate(code)
    try:
        return {"data": _cached("irm", code, 900, lambda: astock.investor_qa(code))}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"互动易异常：{e}") from e


@app.get("/api/industry")
def industry(top: int = Query(20, ge=5, le=50)):
    """全行业涨跌幅排名（东财行业板块，板块级、零个股名单）。缓存 5 分钟。"""
    key = ("industry", str(top))
    hit = _DC_CACHE.get(key, 300)
    if hit is not _CACHE_MISS:
        return {"data": hit}
    try:
        data = astock.industry_comparison(top_n=top)
        _DC_CACHE.set(key, data)
        return {"data": data}
    except Exception as e:  # noqa: BL001
        raise HTTPException(502, f"行业排名异常：{e}") from e


# ---------------------------------------------------------------------------
# 板块研究工作台：研报发现 / 导入 / 动态数据（第一批仅 PCB 真实可用）
# ---------------------------------------------------------------------------


class SectorReportImportIn(BaseModel):
    """导入研报请求：只接受 external_id；禁止 info_code/URL/标题等可改目标字段。"""
    model_config = ConfigDict(extra="forbid")
    external_id: str = Field(..., min_length=1, max_length=64)


_ALLOWED_REPORT_SCOPES = frozenset({"industry", "company", "all"})
_PDF_DOWNLOAD_MAX_REDIRECTS = 5
_PDF_HOST_ALLOW = frozenset({"pdf.dfcfw.com", "pdfcdn.eastmoney.com"})

# 服务端发现缓存：键 (sector_key, external_id) → 规范化元数据（无 PDF 正文）
# 容量必须 ≥ MAX_DISCOVERY_RESULTS，保证「前端可见的每一条」在 TTL 内可导入。
_DISCOVERY_CACHE_TTL_SECONDS = 20 * 60  # 20 分钟
_DISCOVERY_CACHE_MAX_ENTRIES = max(500, int(getattr(srd, "MAX_DISCOVERY_RESULTS", 300)))


@dataclass
class CachedDiscovery:
    sector_key: str
    external_id: str
    info_code: str
    title: str
    institution: str
    publish_date: str
    report_scope: str
    source_provider: str
    discovered_at: datetime
    seq: int  # 单调序号，避免同秒 FIFO 不明确


# OrderedDict 保插入序；seq 用于明确淘汰顺序
_DISCOVERY_CACHE: OrderedDict[tuple[str, str], CachedDiscovery] = OrderedDict()
_DISCOVERY_CACHE_LOCK = threading.Lock()
_DISCOVERY_SEQ = count(1)


def _cache_discoveries(sector_key: str, reports: list[dict]) -> None:
    """把「实际返回前端」的发现结果写入有界短期缓存。

    只缓存与 API 返回完全相同的列表；不缓存被截断的无关记录。
    """
    now = datetime.now(timezone.utc)
    with _DISCOVERY_CACHE_LOCK:
        for r in reports:
            ext_id = r.get("external_id")
            if not ext_id or not isinstance(ext_id, str):
                continue
            key = (sector_key, ext_id)
            # 更新时移到队尾（最近写入）
            if key in _DISCOVERY_CACHE:
                del _DISCOVERY_CACHE[key]
            _DISCOVERY_CACHE[key] = CachedDiscovery(
                sector_key=sector_key,
                external_id=ext_id,
                info_code=(r.get("info_code") or "") if isinstance(r.get("info_code"), str) else "",
                title=(r.get("title") or "") if isinstance(r.get("title"), str) else "",
                institution=(r.get("institution") or "") if isinstance(r.get("institution"), str) else "",
                publish_date=(r.get("publish_date") or "") if isinstance(r.get("publish_date"), str) else "",
                report_scope=(r.get("report_scope") or "") if isinstance(r.get("report_scope"), str) else "",
                source_provider=(r.get("source_provider") or "eastmoney")
                if isinstance(r.get("source_provider"), (str, type(None)))
                else "eastmoney",
                discovered_at=now,
                seq=next(_DISCOVERY_SEQ),
            )
        # 容量上限：按 seq 升序剔除最旧（OrderedDict 队头）
        while len(_DISCOVERY_CACHE) > _DISCOVERY_CACHE_MAX_ENTRIES:
            _DISCOVERY_CACHE.popitem(last=False)


def _get_cached_discovery(sector_key: str, external_id: str) -> CachedDiscovery | None:
    """读取缓存；过期则删除并返回 None。淘汰顺序保持明确 FIFO。"""
    now = datetime.now(timezone.utc)
    with _DISCOVERY_CACHE_LOCK:
        key = (sector_key, external_id)
        cached = _DISCOVERY_CACHE.get(key)
        if cached is None:
            return None
        age = (now - cached.discovered_at).total_seconds()
        if age > _DISCOVERY_CACHE_TTL_SECONDS:
            del _DISCOVERY_CACHE[key]
            return None
        return cached


def _clear_discovery_cache() -> None:
    """测试辅助：清空发现缓存。"""
    with _DISCOVERY_CACHE_LOCK:
        _DISCOVERY_CACHE.clear()


@app.get("/api/sector-research/reports/{sector_key}")
def sector_research_reports(
    sector_key: str,
    days: int | None = Query(None, ge=1, le=3650),
    max_pages: int = Query(3, ge=1, le=10),
    scope: str = Query("industry"),
):
    """发现板块研报（只返回发现结果，不自动归档）。scope=industry|company|all。"""
    if scope not in _ALLOWED_REPORT_SCOPES:
        raise HTTPException(400, f"scope 无效，支持：{' / '.join(sorted(_ALLOWED_REPORT_SCOPES))}")
    result = srd.discover_sector_reports(
        sector_key,
        days=days,
        max_pages=max_pages,
        scope=scope,
        max_results=srd.MAX_DISCOVERY_RESULTS,
    )
    # 缓存与返回使用完全相同的列表
    if not result.error:
        _cache_discoveries(sector_key, result.discovered)
    return {
        "data": {
            "sector_key": result.source_key,
            "discovered": result.discovered,
            "filtered": result.filtered,
            "error": result.error,
            "total_discovered": result.total_discovered,
            "returned": result.returned,
            "truncated": result.truncated,
        }
    }


@app.get("/api/sector-research/data/{sector_key}")
def sector_research_data(sector_key: str):
    """板块动态数据（一致预期 / 公告 / 新闻）。缺失字段用 null，不猜测。"""
    try:
        data = srd.get_sector_dynamic_data(sector_key)
        try:
            import data_health_event_store as _dhes
            st = data.get("status") if isinstance(data, dict) else None
            if st == "normal":
                _dhes.safe_call(_dhes.record_success, "sector_research")
            elif st == "partial":
                _dhes.safe_call(_dhes.record_partial, "sector_research")
            else:
                _dhes.safe_call(_dhes.record_failure, "sector_research", "SOURCE_UNAVAILABLE")
        except Exception:
            pass
    except Exception as e:  # noqa: BL001
        try:
            import data_health_event_store as _dhes
            _dhes.safe_call(_dhes.record_failure, "sector_research", "SOURCE_UNAVAILABLE")
        except Exception:
            pass
        raise HTTPException(502, f"板块动态数据异常：{e}") from e
    return {"data": data}


@app.post("/api/sector-research/import/{sector_key}")
def sector_research_import(sector_key: str, body: SectorReportImportIn):
    """导入研报：只接受 external_id；优先使用缓存中的发现记录。

    缓存未命中或过期时返回 400，要求前端重新发现；不静默用默认 days 重发现。
    PDF 仅由缓存中的 info_code 生成；不信任前端标题/URL/info_code。
    """
    src = srd.get_sector_source(sector_key)
    if src is None:
        raise HTTPException(404, f"未注册的板块：{sector_key}")

    cached = _get_cached_discovery(sector_key, body.external_id)
    if cached is None:
        raise HTTPException(400, "发现结果已过期，请重新点击“开始发现”")

    info_code = cached.info_code
    if not info_code:
        raise HTTPException(400, "缓存记录缺少 info_code，无法安全下载")
    external_id = cached.external_id

    pdf_url = astock.pdf_url(info_code)
    if not srd.pdf_url_allowed(pdf_url):
        raise HTTPException(400, "PDF 链接不在允许域名或非 HTTPS")
    try:
        blob = _download_pdf(pdf_url)
    except mr.ReportError as e:
        raise HTTPException(400, str(e)) from e
    except Exception as e:  # noqa: BL001
        raise HTTPException(502, f"PDF 下载失败：{e}") from e
    if not blob:
        raise HTTPException(502, "PDF 内容为空")

    industry_label = (
        "PCB" if sector_key == "pcb"
        else (src.label.split("（")[0].strip() if src.label else sector_key)
    )
    safe_title = cached.title or info_code
    safe_name = f"{str(safe_title).replace('/', '_').replace(chr(92), '_')[:180]}.pdf"
    try:
        meta = mr.import_report_bytes(
            name=safe_name,
            content=blob,
            metadata={
                "title": safe_title,
                "institution": cached.institution,
                "publish_date": cached.publish_date,
                "sector_keys": [sector_key],
                "source_url": pdf_url,
                "source_kind": "report",
                "source_provider": cached.source_provider or "eastmoney",
                "external_id": external_id,
                "info_code": info_code,
                "report_scope": cached.report_scope,
                "report_type": "brokerage",
                "industry": industry_label,
            },
        )
    except mr.ReportError as e:
        raise HTTPException(400, str(e)) from e
    return {"data": meta}


def _report_download_session():
    import requests
    s = requests.Session()
    s.headers.update({
        "User-Agent": getattr(astock, "UA", "Mozilla/5.0"),
        "Referer": "https://data.eastmoney.com/",
    })
    # 应用层自管重定向，便于校验每一跳最终 URL
    s.max_redirects = _PDF_DOWNLOAD_MAX_REDIRECTS
    return s


def _pdf_url_host_ok(url: str) -> bool:
    """HTTPS + 允许域名 + 拒绝 IP / userinfo / 非默认端口 / 本地地址。"""
    from urllib.parse import urlparse
    try:
        p = urlparse(url)
    except Exception:
        return False
    if (p.scheme or "").lower() != "https":
        return False
    if p.username is not None or p.password is not None:
        return False
    host = (p.hostname or "").lower()
    if not host:
        return False
    if host in ("localhost", "127.0.0.1", "::1") or host.endswith(".local"):
        return False
    # 拒绝纯 IP（IPv4 / 简单 IPv6）
    if all(c.isdigit() or c == "." for c in host) or ":" in host:
        return False
    if p.port is not None and p.port != 443:
        return False
    return host in _PDF_HOST_ALLOW


def _download_pdf(url: str, max_bytes: int = 25 * 1024 * 1024) -> bytes:
    """安全下载 PDF：HTTPS 白名单、重定向校验、流式累计、魔术字节。

    失败抛 mr.ReportError（业务/安全）或底层网络异常。
    不写任何实体文件或索引。
    """
    import requests
    from urllib.parse import urljoin

    if not _pdf_url_host_ok(url):
        raise mr.ReportError("PDF URL 未通过 SSRF 防护校验")

    session = _report_download_session()
    current = url
    resp = None
    for _ in range(_PDF_DOWNLOAD_MAX_REDIRECTS + 1):
        if not _pdf_url_host_ok(current):
            raise mr.ReportError("重定向目标不在允许域名或非 HTTPS")
        try:
            resp = session.get(current, timeout=60, stream=True, allow_redirects=False)
        except requests.RequestException as e:
            raise mr.ReportError(f"PDF 下载网络错误：{e}") from e
        if resp.is_redirect or resp.status_code in (301, 302, 303, 307, 308):
            loc = resp.headers.get("Location")
            if not loc:
                raise mr.ReportError("重定向缺少 Location")
            current = urljoin(current, loc)
            continue
        break
    else:
        raise mr.ReportError(f"重定向次数超过上限 {_PDF_DOWNLOAD_MAX_REDIRECTS}")

    assert resp is not None
    try:
        resp.raise_for_status()
    except requests.HTTPError as e:
        raise mr.ReportError(f"PDF 下载 HTTP 错误：{e}") from e

    # 最终 URL 再校验一次
    final_url = getattr(resp, "url", None) or current
    if not _pdf_url_host_ok(str(final_url)):
        raise mr.ReportError("最终下载 URL 未通过 SSRF 防护校验")

    ctype = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
    if ctype and ctype not in ("application/pdf", "application/octet-stream", "binary/octet-stream"):
        # 不唯依赖 Content-Type，但明确 HTML/JS 直接拒绝
        if "html" in ctype or "javascript" in ctype or "json" in ctype or "text/" in ctype:
            raise mr.ReportError(f"响应 Content-Type 非 PDF：{ctype}")

    buf = bytearray()
    for chunk in resp.iter_content(chunk_size=1 << 16):
        if not chunk:
            continue
        buf.extend(chunk)
        if len(buf) > max_bytes:
            raise mr.ReportError(f"文件过大，上限 {max_bytes // 1024 // 1024}MB")
    if not buf:
        raise mr.ReportError("PDF 内容为空")
    if not bytes(buf[:4]).startswith(b"%PDF"):
        raise mr.ReportError("响应非 PDF 内容（可能为反爬拦截页），已拒绝")
    return bytes(buf)
