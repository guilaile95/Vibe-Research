"""TrendRadar 雷达控制台服务（TR1-P1）。

Phase 1 只读工具面：把 pinned sidecar MCP 的**读类**工具包装成 Vibe-owned
typed 调用。名单是唯一生产 allow-list，且结构性排除外发/写类能力：

- 永不进入本名单：send_notification / trigger_crawl / sync_from_remote /
  read_article* / generate_summary_report / analyze_data_insights
  （通知与爬取触发属 Phase 3 授权面；文章抓取涉及服务端任意 URL 出网，
  留给显式安全评审 keeper；AI 报告类依赖 sidecar key，属 AI parity phase）。

每个调用都经 gateway.call_tool 的 strict 校验（默认拒绝 + loopback 强制 +
provenance envelope），本模块只做：参数白名单装配 → 名称校验 → 透传归一化结果。
不做投资语义加工：上游返回的 relevance/sentiment/hotness 一律原样携带，
由 UI 标注"关注度≠买卖建议"。
"""

from __future__ import annotations

from typing import Any, Callable

import trendradar_gateway as gw

CONSOLE_AUTHORITY_REF = "vibe:trendradar_console:v0.1"

# Phase 1 读类工具（名称全部来自 pinned 运行时 tools/list 实测清单）
READ_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "get_latest_news",
        "get_news_by_date",
        "list_available_dates",
        "get_latest_rss",
        "search_news",
        "search_rss",
        "get_rss_feeds_status",
        "get_trending_topics",
        "analyze_topic_trend",
        "analyze_sentiment",
        "aggregate_news",
        "compare_periods",
        "find_related_news",
        "get_system_status",
        "get_storage_status",
        "get_current_config",
        "get_notification_channels",
    }
)

# 结构性禁入（双保险：即使未来有人误改 READ_TOOL_NAMES 也拦得住）
FORBIDDEN_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "send_notification",
        "trigger_crawl",
        "sync_from_remote",
        "read_article",
        "read_articles_batch",
        "generate_summary_report",
        "analyze_data_insights",
    }
)


def call_read_tool(
    name: str,
    arguments: dict[str, Any],
    env: dict[str, str] | None = None,
    transport_factory: Callable[[gw.GatewayConfig], Any] = gw.default_transport_factory,
) -> dict[str, Any]:
    """控制台统一入口：strict 默认拒绝 + 工具名白名单 + 结果透传。"""
    if type(name) is not str or name not in READ_TOOL_NAMES:
        return gw._base_envelope(
            gw.STATUS_BAD_ARGUMENT,
            f"tool {name!r} is not part of the TrendRadar console read surface",
        )
    if name in FORBIDDEN_TOOL_NAMES:
        # pragma: defensive —— 名单自身错误时的结构断言
        return gw._base_envelope(
            gw.STATUS_BAD_ARGUMENT,
            f"tool {name!r} is structurally forbidden in the console surface",
        )
    envelope = gw.call_tool(
        name,
        arguments,
        allowed_names=READ_TOOL_NAMES,
        env=env,
        transport_factory=transport_factory,
    )
    if envelope["status"] in (gw.STATUS_OK, gw.STATUS_UPSTREAM_ERROR):
        envelope["tool"] = name
    envelope["authority_ref"] = CONSOLE_AUTHORITY_REF
    return envelope


def drop_none(args: dict[str, Any]) -> dict[str, Any]:
    """router 层 Query(None) 形参 → 仅包含用户显式给出的键。"""
    return {k: v for k, v in args.items() if v is not None}
