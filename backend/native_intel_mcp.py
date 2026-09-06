"""Official MCP Streamable HTTP adapter for Native Intel Agent tools.

Hosted inside the existing Vibe FastAPI process. This is not a second daemon
and is never exposed to the internal page-aware Codex runtime.
"""

from __future__ import annotations

import json
from typing import Literal

from mcp.server import MCPServer

import native_intel_service as service
from version import read_version

SERVER_NAME = "vibe-native-intel"

mcp_server = MCPServer(
    SERVER_NAME,
    version=read_version(),
    instructions=(
        "Observation-only Native Intel tools. No Position, Account, Campaign, "
        "Thesis, Frozen Decision, Trade, Outcome, or NAV authority is exposed."
    ),
)


def _result(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, allow_nan=False)


@mcp_server.tool(structured_output=False)
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


@mcp_server.tool(structured_output=False)
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


@mcp_server.tool(structured_output=False)
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


@mcp_server.tool(structured_output=False)
def analyze_intel_sentiment(text: str = "", topic: str | None = None) -> str:
    """Run the non-authoritative structured sentiment analysis authority."""
    return _result(service.get_agent_tools().analyze_intel_sentiment(text=text, topic=topic))


@mcp_server.tool(structured_output=False)
def get_intel_status() -> str:
    """Return Native Intel run, source, freshness, proxy, and AI readiness status."""
    return _result(service.get_agent_tools().get_intel_status())


@mcp_server.tool(structured_output=False)
def trigger_intel_refresh(sources: list[str] | None = None) -> str:
    """Refresh all enabled sources or an explicit enabled source_id subset."""
    return _result(service.get_agent_tools().trigger_intel_refresh(sources=sources))


@mcp_server.tool(structured_output=False)
def resolve_intel_date_range(expression: str) -> str:
    """Resolve a bounded natural-language date expression."""
    return _result(service.get_agent_tools().resolve_intel_date_range(expression=expression))


# Parent FastAPI lifespan owns session_manager.run(); this starts no daemon.
mcp_http_app = mcp_server.streamable_http_app(
    streamable_http_path="/",
    json_response=True,
)
