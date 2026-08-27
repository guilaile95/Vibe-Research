"""TREND-RADAR1 TR1-P1 browser-vertical harness app.

Mounts the REAL trendradar_router on a bare FastAPI instance and patches
trendradar_gateway with deterministic in-process fakes so the Chromium
vertical can assert the product surface without a sidecar / MCP client
dependency (CI-safe).

Scenarios via env `TR_HARNESS_MODE`:
- ok    : status=OK with server identity + canned get_latest_news rows.
- down  : every radar read + status maps to explicit UNAVAILABLE envelope.
"""

from __future__ import annotations

import json
import os

from fastapi import FastAPI

import trendradar_console as console
import trendradar_gateway as gw
from trendradar_router import router as trendradar_router

MODE = os.environ.get("TR_HARNESS_MODE", "ok")
RADAR_FAILURE = os.environ.get("TR_HARNESS_RADAR_FAILURE", "").strip()

app = FastAPI(title="TrendRadar TR1-P1 harness", version="0.0.0")
app.include_router(trendradar_router)


def _identity() -> dict:
    return {
        "repo": "sansan0/TrendRadar",
        "source_commit": "8ee26026ba6c11dec41a95fb3895a7162876caa1",
        "core_version": "6.10.0",
        "mcp_version": "4.1.0",
        "license": "GPL-3.0",
        "core_image": "wantcat/trendradar:6.10.0@sha256:x",
        "mcp_image": "wantcat/trendradar-mcp:4.1.0@sha256:y",
        "integration_authority_ref": gw.GATEWAY_AUTHORITY_REF,
        "usage_boundary": "observation_only_not_an_investment_authority",
    }


def _envelope(status: str, **extra):
    env_ = {
        "status": status,
        "retrieved_at": "2026-08-27T00:00:00Z",
        "upstream": _identity(),
    }
    env_.update(extra)
    return env_


if MODE == "down":

    def _status_snapshot(env=None, transport_factory=None):  # noqa: ARG001
        out = _envelope(
            "UNAVAILABLE",
            error="initialize failed: connection refused (harness)",
            gateway={
                "enabled": True,
                "mcp_url_host": "127.0.0.1",
                "timeout_seconds": 15.0,
            },
            server=None,
        )
        return out

    def _call_tool(name, arguments, *, allowed_names, env=None, transport_factory=None):  # noqa: ARG001
        return _envelope(
            "UNAVAILABLE",
            error=f"tools/call:{name} failed: connection refused (harness)",
        )

else:

    def _status_snapshot(env=None, transport_factory=None):  # noqa: ARG001
        return _envelope(
            "OK",
            gateway={"enabled": True, "mcp_url_host": "127.0.0.1",
                     "timeout_seconds": 15.0},
            server={
                "server_name": "trendradar-news",
                "server_version": "4.1.0",
                "protocol_version": "2025-06-18",
            },
        )

    def _call_tool(name, arguments, *, allowed_names, env=None, transport_factory=None):  # noqa: ARG001
        if name not in console.READ_TOOL_NAMES:
            return _envelope("BAD_ARGUMENT", error=f"{name} not allow-listed")
        if name == RADAR_FAILURE:
            return _envelope("UNAVAILABLE", tool=name, error=f"{name} failed: harness")
        payloads = {
            "get_latest_news": [
                {"title": "FAKE 热榜 甲 · 固态电池量产提速", "platform": "weibo",
                 "platform_name": "微博", "rank": 1,
                 "timestamp": "2026-08-27 09:28:44", "url": ""},
                {"title": "FAKE 热榜 乙 · 某龙头获大额订单", "platform": "baidu",
                 "platform_name": "百度热搜", "rank": 2,
                 "timestamp": "2026-08-27 09:29:01", "url": ""},
            ],
            "get_trending_topics": {"topics": ["固态电池", "算力租赁"]},
        }
        result = payloads.get(name)
        # 使用真实 MCP 的文本返回形态，验证前端不会只依赖 structured result。
        return _envelope(
            "OK",
            tool=name,
            result_text=json.dumps(result if result is not None else {"ok": True}, ensure_ascii=False),
        )


gw.call_tool = _call_tool  # type: ignore[assignment]
gw.status_snapshot = _status_snapshot  # type: ignore[assignment]
