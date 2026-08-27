"""TrendRadar 最小网关 API（TR1-P0）。

只暴露 allow-list 的窄面：status / tool inventory / 只读 SQLite 观察。
无任意 MCP tool-call 透传；观察输出根目录只能来自服务端环境变量
VIBE_TRENDRADAR_OUTPUT_ROOT，客户端永远不能指定文件路径。

HTTP 语义：能被如实回答的状态（DISABLED/UNAVAILABLE/CONTRACT_MISMATCH/
NOT_FOUND 等）都是 200 + 显式 envelope status；仅输入非法（日期格式、
未知 kind）返回 422。前端按 status 渲染，不猜。
"""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, HTTPException

import trendradar_gateway as gateway
import trendradar_observation_adapter as observer

router = APIRouter(prefix="/api/trendradar", tags=["trendradar"])

OUTPUT_ROOT_ENV = "VIBE_TRENDRADAR_OUTPUT_ROOT"

_OBSERVERS = {
    "news": observer.observe_news,
    "rss": observer.observe_rss,
    "news-ai-filter": observer.observe_news_ai_filter,
}


def _output_root() -> str | None:
    value = os.environ.get(OUTPUT_ROOT_ENV, "").strip()
    if not value:
        return None
    return value


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
