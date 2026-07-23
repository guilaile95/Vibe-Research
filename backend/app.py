"""Vibe-Research 后端 —— A股数据层 HTTP 接口（FastAPI）。

端点全部在 /api 下，前端 vite 代理 /api → localhost:8900。
只读、无状态，按用户传入代码返回行情 / 研报 / 资金等数据。

启动：
    uvicorn app:app --host 127.0.0.1 --port 8900
"""

from __future__ import annotations

import json
import os
import threading

import anyio

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, model_validator
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


app = FastAPI(title="Vibe-Research API", version="0.1.3")

# 每半小时后台刷新持仓数据
pf.start_scheduler(1800)

# CORS：默认放开（本地自托管友好）；公网部署时用 VR_ALLOW_ORIGINS 收紧成白名单。
#   例：VR_ALLOW_ORIGINS="https://myhost"  （逗号分隔多个）
_ORIGINS = [o.strip() for o in os.environ.get("VR_ALLOW_ORIGINS", "*").split(",") if o.strip()] or ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_ORIGINS,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# 可选鉴权：设了 VR_API_KEY 就要求所有 /api/* 带 `Authorization: Bearer <key>`
#   （本地自托管不设=开放；公网部署务必设，否则别人能读你的持仓/调你的后端）。
_API_KEY = os.environ.get("VR_API_KEY", "").strip()


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


@app.middleware("http")
async def _require_api_key(request: Request, call_next):
    if (
        _API_KEY
        and request.method != "OPTIONS"
        and request.url.path.startswith("/api/")
        and request.url.path != "/api/health"
    ):
        if request.headers.get("authorization", "") != f"Bearer {_API_KEY}":
            return JSONResponse({"detail": "未授权：缺少或错误的 API Key（VR_API_KEY）"}, status_code=401)
    return await call_next(request)

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
    if not req.llm.model:
        raise HTTPException(400, "缺少模型配置，请先在「接入 AI」里选择")

    is_cli = req.llm.provider.startswith("cli-")
    if is_cli:
        kind = req.llm.provider[4:]
        if not cli_runtime.detect_cli(kind):
            raise HTTPException(400, f"未检测到「{kind}」对应的本机命令。请先安装并登录该 CLI，或改用「API 接入」。")
    elif not req.llm.apiKey or not req.llm.baseURL:
        raise HTTPException(400, "缺少 Base URL 或 API Key，请先在「接入 AI」里填写")

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

    服务器链路：get_portfolio → generate_daily_review → context → 模型 → validator。
    空持仓 → 409；模型调用/输出无效 → 502（通用文案）；未预期异常 → 500。
    不接受客户端持仓/context/messages；不写持仓与复盘历史。
    """
    try:
        result = portfolio_advice_service.generate_portfolio_advice(
            req.llm.model_dump(),
            user_request=req.user_request,
        )
        return {"data": result}
    except portfolio_advice_service.PortfolioAdviceUnavailableError as e:
        raise HTTPException(409, str(e)) from e
    except portfolio_advice_service.PortfolioAdviceMarketDataError as e:
        # 市场核心数据不可用：503 + 安全业务文案（不泄漏底层网络异常）
        raise HTTPException(503, str(e) or "市场核心数据暂不可用，无法生成可靠的持仓操作建议") from None
    except portfolio_advice_service.PortfolioAdviceModelError:
        raise HTTPException(502, "持仓建议模型调用失败") from None
    except portfolio_advice_service.PortfolioAdviceModelOutputError:
        raise HTTPException(502, "持仓建议模型输出无效") from None
    except (TypeError, ValueError):
        raise HTTPException(400, "持仓建议请求参数无效") from None
    except pf.PortfolioDataCorruptedError:
        raise
    except Exception:  # noqa: BLE001 — 不向客户端暴露路径/持仓/密钥
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


class ReportMetaPatch(BaseModel):
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
    from datetime import datetime
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
    if not req.llm.model:
        raise HTTPException(400, "缺少模型配置，请先在「接入 AI」里选择")

    is_cli = req.llm.provider.startswith("cli-")
    if is_cli:
        kind = req.llm.provider[4:]
        if not cli_runtime.detect_cli(kind):
            raise HTTPException(400, f"未检测到「{kind}」对应的本机命令。请先安装并登录该 CLI，或改用「API 接入」。")
    elif not req.llm.apiKey or not req.llm.baseURL:
        raise HTTPException(400, "缺少 Base URL 或 API Key，请先在「接入 AI」里填写")

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
        return {"data": astock.tencent_quote(lst)}
    except Exception as e:  # noqa: BLE001 — 边界统一兜底
        raise HTTPException(502, f"行情源异常：{e}") from e


import time as _time
_PCT_CACHE: dict = {}


@app.get("/api/valuation/percentile")
def valuation_percentile(code: str = Query(...)):
    """PE-TTM / PB 历史分位（近5年）。全站缓存 30 分钟/代码（历史序列日频、变化慢）。"""
    code = _validate(code)
    hit = _PCT_CACHE.get(code)
    if hit and _time.time() - hit[0] < 1800:
        return {"data": hit[1]}
    try:
        data = astock.valuation_percentile(code)
        _PCT_CACHE[code] = (_time.time(), data)
        return {"data": data}
    except astock.DependencyMissing as e:
        raise HTTPException(501, str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"估值分位异常：{e}") from e


_ANN_CACHE: dict = {}


@app.get("/api/announcements")
def announcements(code: str = Query(...)):
    """个股近期公告（东财，仅 requests）。缓存 15 分钟/代码。"""
    code = _validate(code)
    hit = _ANN_CACHE.get(code)
    if hit and _time.time() - hit[0] < 900:
        return {"data": hit[1]}
    try:
        data = astock.announcements(code)
        _ANN_CACHE[code] = (_time.time(), data)
        return {"data": data}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"公告源异常：{e}") from e


_FIN_CACHE: dict = {}


@app.get("/api/financials")
def financials(code: str = Query(...)):
    """财务关键指标（同花顺财务摘要，最新报告期）。缓存 30 分钟/代码。"""
    code = _validate(code)
    hit = _FIN_CACHE.get(code)
    if hit and _time.time() - hit[0] < 1800:
        return {"data": hit[1]}
    try:
        data = astock.financials(code)
        _FIN_CACHE[code] = (_time.time(), data)
        return {"data": data}
    except astock.DependencyMissing as e:
        raise HTTPException(501, str(e)) from e
    except Exception as e:  # noqa: BLE001
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

_DC_CACHE: dict = {}  # key=(endpoint, code) -> (ts, data)


def _cached(endpoint: str, code: str, ttl: int, fetch):
    key = (endpoint, code)
    hit = _DC_CACHE.get(key)
    if hit and _time.time() - hit[0] < ttl:
        return hit[1]
    data = fetch()
    _DC_CACHE[key] = (_time.time(), data)
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
    hit = _DC_CACHE.get(key)
    if hit and _time.time() - hit[0] < 300:
        return {"data": hit[1]}
    try:
        data = astock.industry_comparison(top_n=top)
        _DC_CACHE[key] = (_time.time(), data)
        return {"data": data}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"行业排名异常：{e}") from e
