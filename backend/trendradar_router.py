"""TrendRadar 网关 API（TR1-P0/P1）。

P0：status / tool inventory / 只读 SQLite 观察（root 仅来自服务端 env）。
P1：`/radar/*` 读类控制台面 —— 把 pinned sidecar 的 MCP **只读**工具包装为
typed 端点（白名单唯一来源 = trendradar_console.READ_TOOL_NAMES）。通知发送、
爬取触发、远程同步、文章抓取、AI 报告类工具结构性不在面上。

无任意 MCP tool-call 透传；观察输出根目录只能来自服务端环境变量
VIBE_TRENDRADAR_OUTPUT_ROOT，客户端永远不能指定文件路径。

HTTP 语义：能被如实回答的状态（DISABLED/UNAVAILABLE/CONTRACT_MISMATCH/
NOT_FOUND 等）都是 200 + 显式 envelope status；仅输入非法返回 422。
前端按 status 渲染，不猜。
"""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, HTTPException, Query

import trendradar_attention_context as attention_context
import trendradar_console as console
import trendradar_gateway as gateway
import trendradar_observation_adapter as observer
import trendradar_watchlist_context as watchlist_context
import watchlist_store

router = APIRouter(prefix="/api/trendradar", tags=["trendradar"])

OUTPUT_ROOT_ENV = "VIBE_TRENDRADAR_OUTPUT_ROOT"


def _output_root() -> str | None:
    value = os.environ.get(OUTPUT_ROOT_ENV, "").strip()
    if not value:
        return None
    return value


# ---------------------------------------------------------------------------
# P0 面
# ---------------------------------------------------------------------------


@router.get("/status")
def get_status() -> dict[str, Any]:
    """enable 态 + 已认证上游身份 + 可达时的服务端自报身份。"""
    return gateway.status_snapshot()


@router.get("/tools")
def get_tools() -> dict[str, Any]:
    """strict tools/list 发现（未启用/不可达时返回显式失败 envelope）。"""
    return gateway.tool_inventory()


@router.get("/observation/news/{date}")
def get_news_observation(date: str) -> dict[str, Any]:
    root = _output_root()
    if root is None:
        return observer.disabled_envelope(date, "news")
    result = observer.observe_news(root, date)
    if result["status"] == observer.STATUS_BAD_ARGUMENT:
        raise HTTPException(status_code=422, detail=result)
    return result


@router.get("/observation/rss/{date}")
def get_rss_observation(date: str) -> dict[str, Any]:
    root = _output_root()
    if root is None:
        return observer.disabled_envelope(date, "rss")
    result = observer.observe_rss(root, date)
    if result["status"] == observer.STATUS_BAD_ARGUMENT:
        raise HTTPException(status_code=422, detail=result)
    return result


@router.get("/observation/news-ai-filter/{date}")
def get_news_ai_filter_observation(date: str) -> dict[str, Any]:
    root = _output_root()
    if root is None:
        return observer.disabled_envelope(date, "news-ai-filter")
    result = observer.observe_news_ai_filter(root, date)
    if result["status"] == observer.STATUS_BAD_ARGUMENT:
        raise HTTPException(status_code=422, detail=result)
    return result


# ---------------------------------------------------------------------------
# P1 雷达控制台面（只读）
# ---------------------------------------------------------------------------


def _platforms_param(platforms: str | None) -> list[str] | None:
    """逗号分隔字符串 → 去空列表；空串视为未提供。"""
    if not platforms or not platforms.strip():
        return None
    parts = [p.strip() for p in platforms.split(",") if p.strip()]
    return parts or None


@router.get("/radar/dates")
def radar_dates(source: str = Query(default="both", pattern="^(both|news|rss)$")):
    return console.call_read_tool("list_available_dates", {"source": source})


@router.get("/radar/latest")
def radar_latest(
    limit: int | None = Query(default=None, ge=1, le=200),
    platforms: str | None = Query(default=None),
):
    args = console.drop_none(
        {"limit": limit, "platforms": _platforms_param(platforms)}
    )
    return console.call_read_tool("get_latest_news", args)


@router.get("/radar/hotlist/{date}")
def radar_hotlist_by_date(
    date: str,
    limit: int | None = Query(default=None, ge=1, le=200),
    platforms: str | None = Query(default=None),
):
    from datetime import date as _date

    try:
        _date.fromisoformat(date)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail={"status": "BAD_ARGUMENT", "error": "date must be YYYY-MM-DD"},
        ) from None
    args: dict[str, Any] = {"date_range": date}
    extra = console.drop_none({"limit": limit, "platforms": _platforms_param(platforms)})
    args.update(extra)
    return console.call_read_tool("get_news_by_date", args)


@router.get("/radar/rss-latest")
def radar_rss_latest(
    days: int | None = Query(default=None, ge=1, le=30),
    limit: int | None = Query(default=None, ge=1, le=200),
    include_summary: bool = False,
):
    args = console.drop_none(
        {
            "days": days,
            "limit": limit,
            "include_summary": include_summary or None,
        }
    )
    return console.call_read_tool("get_latest_rss", args)


@router.get("/radar/search")
def radar_search(
    q: str = Query(min_length=1, max_length=200),
    days_back: int | None = Query(default=None, ge=1, le=90),
    limit: int | None = Query(default=None, ge=1, le=200),
    platforms: str | None = Query(default=None),
):
    args: dict[str, Any] = {"query": q, "include_url": True}
    if days_back is not None:
        # 相对窗口走自然语言形参，由上游 resolve_date_range 语义解析
        args["date_range"] = f"最近{days_back}天"
    extra = console.drop_none({"limit": limit, "platforms": _platforms_param(platforms)})
    args.update(extra)
    return console.call_read_tool("search_news", args)


@router.get("/radar/trending")
def radar_trending(top_n: int | None = Query(default=None, ge=1, le=100)):
    return console.call_read_tool("get_trending_topics", console.drop_none({"top_n": top_n}))


@router.get("/radar/topic-trend")
def radar_topic_trend(
    topic: str = Query(min_length=1, max_length=120),
    analysis_type: str = Query(
        default="trend", pattern="^(trend|lifecycle|viral|predict)$"
    ),
    days_back: int | None = Query(default=None, ge=1, le=90),
):
    args: dict[str, Any] = {"topic": topic, "analysis_type": analysis_type}
    if days_back is not None:
        args["date_range"] = f"最近{days_back}天"
    return console.call_read_tool("analyze_topic_trend", args)


@router.get("/radar/sentiment")
def radar_sentiment(
    topic: str | None = Query(default=None, min_length=1, max_length=120),
    days_back: int | None = Query(default=None, ge=1, le=90),
    platforms: str | None = Query(default=None),
    limit: int | None = Query(default=None, ge=1, le=200),
):
    args: dict[str, Any] = {}
    extra = console.drop_none(
        {
            "topic": topic,
            "date_range": f"最近{days_back}天" if days_back else None,
            "platforms": _platforms_param(platforms),
            "limit": limit,
        }
    )
    args.update(extra)
    return console.call_read_tool("analyze_sentiment", args)


@router.get("/radar/aggregate")
def radar_aggregate(
    date: str | None = Query(default=None, min_length=6, max_length=40),
    platforms: str | None = Query(default=None),
    limit: int | None = Query(default=None, ge=1, le=200),
):
    args = console.drop_none(
        {
            "date_range": date,
            "platforms": _platforms_param(platforms),
            "limit": limit,
            "include_url": True,
        }
    )
    return console.call_read_tool("aggregate_news", args)


@router.get("/radar/related")
def radar_related(
    title: str = Query(min_length=2, max_length=200),
    days_back: int | None = Query(default=None, ge=1, le=90),
    limit: int | None = Query(default=None, ge=1, le=200),
):
    args: dict[str, Any] = {"reference_title": title, "include_url": True}
    if days_back is not None:
        args["date_range"] = f"最近{days_back}天"
    if limit is not None:
        args["limit"] = limit
    return console.call_read_tool("find_related_news", args)


@router.get("/radar/system-status")
def radar_system_status():
    return console.call_read_tool("get_system_status", {})


@router.get("/radar/storage-status")
def radar_storage_status():
    return console.call_read_tool("get_storage_status", {})


@router.get("/attention-context/{code}")
def attention_context_for_security(code: str):
    """单证券公开关注上下文；只读 observation projection，不进入投资权威链。"""
    if not isinstance(code, str) or len(code) != 6 or not code.isdigit():
        raise HTTPException(
            status_code=422,
            detail={"status": "BAD_ARGUMENT", "error": "code must be a 6-digit A-share code"},
        )
    return attention_context.build_attention_context(code)


@router.get("/watchlist-context")
def attention_context_for_watchlist():
    """后端权威自选股的批量关注上下文；只读 observation projection。"""
    try:
        status = watchlist_store.get_watchlist_status()
        if status.get("status") == "valid":
            codes = status.get("data", {}).get("codes", [])
        else:
            codes = []
        return watchlist_context.build_watchlist_context(
            codes,
            watchlist_status=str(status.get("status", "unavailable")),
        )
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail={"status": gateway.STATUS_BAD_ARGUMENT, "error": "watchlist contains invalid codes"},
        ) from None
