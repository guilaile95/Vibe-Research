"""Official MCP Streamable HTTP adapter for Native Intel Agent tools.

Hosted inside the existing Vibe FastAPI process. This is not a second daemon
and is never exposed to the internal page-aware Codex runtime.

Each FastAPI lifespan gets a fresh MCPServer/session manager. The SDK manager
can only be started once per instance, and TestClient re-enters lifespan.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Literal

from mcp.server import MCPServer
from starlette.types import Receive, Scope, Send

import native_intel_service as service
from version import read_version

SERVER_NAME = "vibe-native-intel"


def _result(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, allow_nan=False)


def query_intel(
    mode: Literal["current", "daily", "incremental", "report", "aggregate", "dates"] = "current",
    scope: Literal["all", "my_interests"] = "all",
    source_type: Literal["all", "hotlist", "rss", "standalone"] = "all",
    limit: int = 50,
    date: str | None = None,
) -> str:
    """Query Native Intel observations or Wave 4 reports."""
    return _result(
        service.get_agent_tools().query_intel(
            mode=mode,
            scope=scope,
            source_type=source_type,
            limit=limit,
            date=date,
        )
    )


def search_intel(
    query: str,
    search_mode: Literal["keyword", "entity"] = "keyword",
    source_type: Literal["all", "hotlist", "rss"] = "all",
    limit: int = 20,
) -> str:
    """Search Native Intel observation facts by keyword or entity."""
    return _result(
        service.get_agent_tools().search_intel(
            query=query,
            search_mode=search_mode,
            source_type=source_type,
            limit=limit,
        )
    )


def analyze_intel_trend(
    topic: str | None = None,
    similar_to: str | int | None = None,
    insight_type: Literal["platform", "cooccurrence", "lifecycle", "viral", "prediction"] | None = None,
    days: int = 7,
    data_basis: Literal["CURRENT_ELIGIBLE", "RAW_HISTORY"] = "CURRENT_ELIGIBLE",
    compare_period: Literal["previous_equal_window"] | None = None,
) -> str:
    """Project Wave 4 trend, similarity, lifecycle, viral, and prediction analytics."""
    return _result(
        service.get_agent_tools().analyze_intel_trend(
            topic=topic,
            similar_to=similar_to,
            insight_type=insight_type,
            days=days,
            data_basis=data_basis,
            compare_period=compare_period,
        )
    )


def analyze_intel_sentiment(text: str = "", topic: str | None = None) -> str:
    """Run the non-authoritative structured sentiment analysis authority."""
    return _result(service.get_agent_tools().analyze_intel_sentiment(text=text, topic=topic))


def get_intel_status() -> str:
    """Return Native Intel run, source, freshness, proxy, and AI readiness status."""
    return _result(service.get_agent_tools().get_intel_status())


def trigger_intel_refresh(sources: list[str] | None = None) -> str:
    """Refresh all enabled sources or an explicit enabled source_id subset."""
    return _result(service.get_agent_tools().trigger_intel_refresh(sources=sources))


def resolve_intel_date_range(expression: str) -> str:
    """Resolve a bounded natural-language date expression."""
    return _result(service.get_agent_tools().resolve_intel_date_range(expression=expression))


def build_mcp_server() -> MCPServer[Any]:
    server = MCPServer(
        SERVER_NAME,
        version=read_version(),
        instructions=(
            "Observation-only Native Intel tools. No Position, Account, Campaign, "
            "Thesis, Frozen Decision, Trade, Outcome, or NAV authority is exposed."
        ),
    )
    for fn in (
        query_intel,
        search_intel,
        analyze_intel_trend,
        analyze_intel_sentiment,
        get_intel_status,
        trigger_intel_refresh,
        resolve_intel_date_range,
    ):
        server.add_tool(fn, structured_output=False)
    return server


class McpMount:
    """ASGI proxy so FastAPI can mount a path before a lifespan-scoped server exists."""

    def __init__(self) -> None:
        self._app: Any = None

    def attach(self, app: Any) -> None:
        self._app = app

    def detach(self) -> None:
        self._app = None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if self._app is None:
            raise RuntimeError("Native Intel MCP mount is not running")
        await self._app(scope, receive, send)


mcp_http_app = McpMount()


@asynccontextmanager
async def running_mcp(mount: McpMount | None = None) -> AsyncIterator[MCPServer[Any]]:
    target = mount if mount is not None else mcp_http_app
    server = build_mcp_server()
    asgi = server.streamable_http_app(streamable_http_path="/", json_response=True)
    target.attach(asgi)
    try:
        async with server.session_manager.run():
            yield server
    finally:
        target.detach()
