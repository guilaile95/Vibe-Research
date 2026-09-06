"""Vibe-native Agent Tool Surface (TREND-PARITY Wave 5).

Provides native Agent tools parity for external and controlled agent clients:
- query_intel: 资讯与报告查询（支持 current, daily, incremental, report, aggregate, dates; 支持 standalone 来源）
- search_intel: 事实关键词与实体检索
- analyze_intel_trend: 话题趋势、相似性与平台共现分析（严格复用 Wave 4 reporting.analyze_topic / similar_items 权威算法）
- analyze_intel_sentiment: 结构化舆情风向与争议分析
- get_intel_status: 系统运行、数据源、新鲜度与真实 Codex/API 运行时状态查询（严格调用 agent_runtime.status()）
- trigger_intel_refresh: 资料抓取与刷新显式触发（仅刷新观察事实，绝不触发正式投资决策）
- resolve_intel_date_range: 自然语言日期范围解析

Security Boundaries:
- Read-only data access from existing Vibe services.
- Refresh trigger only refreshes observations, NEVER writes formal investment authorities
  (Position, Account, Campaign, Formal Thesis, Frozen Decision, Trade, Outcome).
- Pure Vibe-native implementation: zero TrendRadar runtime, zero TrendRadar package, zero GPL code.
- Internal page-aware Codex runtime continues to isolate and reject mcp_tool_call.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import agent_runtime
import native_intel_reporting as reporting
import native_intel_service as service
import native_intel_store as store
import native_intel_timeline as timeline
from version import read_version

logger = logging.getLogger(__name__)

LOCAL_TZ = timezone(timedelta(hours=8))


def resolve_intel_date_range(
    expression: str, now: datetime | None = None
) -> dict[str, Any]:
    """将自然语言日期表达式解析为标准日期范围。"""
    expr = (expression or "").strip().lower()
    current = (now or datetime.now(timezone.utc)).astimezone(LOCAL_TZ)
    today = current.date()

    if expr in ("今天", "today"):
        start = today
        end = today
        desc = "今天"
    elif expr in ("昨天", "yesterday"):
        start = today - timedelta(days=1)
        end = today - timedelta(days=1)
        desc = "昨天"
    elif expr in ("本周", "this week"):
        # 周一为起始 (isoweekday 1)
        start = today - timedelta(days=today.isoweekday() - 1)
        end = today
        desc = "本周"
    elif expr in ("上周", "last week"):
        monday_this_week = today - timedelta(days=today.isoweekday() - 1)
        start = monday_this_week - timedelta(days=7)
        end = monday_this_week - timedelta(days=1)
        desc = "上周"
    elif expr in ("最近7天", "last 7 days", "7天"):
        start = today - timedelta(days=6)
        end = today
        desc = "最近7天"
    elif expr in ("最近30天", "last 30 days", "30天"):
        start = today - timedelta(days=29)
        end = today
        desc = "最近30天"
    elif expr in ("本月", "this month"):
        start = today.replace(day=1)
        end = today
        desc = "本月"
    else:
        m = re.match(r"(?:最近|last\s*)(\d+)(?:天|\s*days?)", expr)
        if m:
            try:
                days = int(m.group(1))
            except ValueError:
                days = 7
            start = today - timedelta(days=max(1, days) - 1)
            end = today
            desc = f"最近{days}天"
        else:
            start = today - timedelta(days=6)
            end = today
            desc = f"未知表达式'{expression}'，默认最近7天"

    return {
        "success": True,
        "expression": expression,
        "date_range": {
            "start": start.strftime("%Y-%m-%d"),
            "end": end.strftime("%Y-%m-%d"),
        },
        "description": desc,
    }


class NativeIntelAgentTools:
    """Vibe-native Agent 工具实现集。"""

    def __init__(self, db_path: str | Path | None = None):
        self.db_path = str(db_path) if db_path else None

    def query_intel(
        self,
        mode: str = "current",
        scope: str = "all",
        source_type: str = "all",
        limit: int = 50,
        date: str | None = None,
        profile_id: str = "default",
    ) -> dict[str, Any]:
        """查询资讯与报告数据。

        Args:
            mode: current / daily / incremental / report / aggregate / dates
            scope: all / my_interests
            source_type: all / hotlist / rss / standalone
            limit: 最大返回条数
            date: 日期 (YYYY-MM-DD, 供 daily 模式)
        """
        mode_upper = mode.upper()
        if mode_upper == "DATES":
            path = self.db_path or store.get_default_db_path()
            with store._connect(path) as conn:
                rows = conn.execute(
                    "SELECT DISTINCT substr(observed_at, 1, 10) as d FROM intel_observations WHERE observed_at IS NOT NULL ORDER BY d DESC LIMIT 60"
                ).fetchall()
                dates = [r["d"] for r in rows if r["d"]]
            return {
                "success": True,
                "mode": "dates",
                "available_dates": dates,
                "data_basis": "OBSERVATION_FACTS",
                "usage_boundary": "OBSERVATION_ONLY_NOT_AN_INVESTMENT_AUTHORITY",
            }

        # 真正处理 standalone 查询请求
        if source_type.lower() == "standalone":
            st_res = service.get_standalone_items(path=self.db_path)
            items = st_res.get("items", [])[:limit]
            return {
                "success": True,
                "mode": mode,
                "scope": scope,
                "source_type": "standalone",
                "total": st_res.get("total", len(items)),
                "returned": len(items),
                "items": items,
                "data_basis": "OBSERVATION_FACTS",
                "usage_boundary": "OBSERVATION_ONLY_NOT_AN_INVESTMENT_AUTHORITY",
            }

        # mode="REPORT" 完整报告生成模式
        if mode_upper == "REPORT":
            now_dt = None
            if date:
                try:
                    now_dt = datetime.fromisoformat(date + "T23:59:59+08:00")
                except Exception:
                    now_dt = None
            report = reporting.generate_report(
                path=str(self.db_path) if self.db_path else None,
                mode="CURRENT",
                scope=scope,
                profile_id=profile_id,
                now=now_dt,
                commit=False,
            )
            return {
                "success": True,
                "mode": "report",
                "scope": scope,
                "report": report,
                "data_basis": "OBSERVATION_FACTS",
                "usage_boundary": "OBSERVATION_ONLY_NOT_AN_INVESTMENT_AUTHORITY",
            }

        # mode="AGGREGATE" 跨来源聚合模式
        if mode_upper == "AGGREGATE":
            report = reporting.generate_report(
                path=str(self.db_path) if self.db_path else None,
                mode="CURRENT",
                scope=scope,
                profile_id=profile_id,
                commit=False,
            )
            raw_items = report.get("items", [])
            aggregated: dict[str, list[dict]] = {}
            for it in raw_items:
                st = it.get("source_type") or (
                    "rss" if it.get("hint") == "rss" else "hotlist"
                )
                aggregated.setdefault(st, []).append(it)
            return {
                "success": True,
                "mode": "aggregate",
                "scope": scope,
                "aggregated": {k: v[:limit] for k, v in aggregated.items()},
                "total": len(raw_items),
                "data_basis": "OBSERVATION_FACTS",
                "usage_boundary": "OBSERVATION_ONLY_NOT_AN_INVESTMENT_AUTHORITY",
            }

        if mode_upper in ("CURRENT", "DAILY", "INCREMENTAL"):
            now_dt = None
            if date:
                try:
                    now_dt = datetime.fromisoformat(date + "T23:59:59+08:00")
                except Exception:
                    now_dt = None
            report = reporting.generate_report(
                path=str(self.db_path) if self.db_path else None,
                mode=mode_upper,
                scope=scope,
                profile_id=profile_id,
                now=now_dt,
                commit=False,
            )
            raw_items = report.get("items", [])
            filtered_items = []
            for it in raw_items:
                st = it.get("source_type") or (
                    "rss" if it.get("hint") == "rss" else "hotlist"
                )
                if source_type != "all" and st != source_type:
                    continue
                filtered_items.append(it)

            return {
                "success": True,
                "mode": mode_upper,
                "scope": scope,
                "source_type": source_type,
                "total": len(filtered_items),
                "returned": len(filtered_items[:limit]),
                "items": filtered_items[:limit],
                "data_basis": "OBSERVATION_FACTS",
                "observation_boundary": report.get("observation_boundary", 0),
                "generated_at": report.get("generated_at", ""),
                "usage_boundary": "OBSERVATION_ONLY_NOT_AN_INVESTMENT_AUTHORITY",
            }

        return {
            "success": False,
            "error": "BAD_ARGUMENT",
            "message": f"unsupported query mode '{mode}'",
        }

    def search_intel(
        self,
        query: str,
        search_mode: str = "keyword",
        source_type: str = "all",
        limit: int = 20,
    ) -> dict[str, Any]:
        """事实关键词或实体检索。"""
        clean_query = (query or "").strip()
        if not clean_query:
            return {"success": True, "query": "", "total": 0, "items": []}

        if not isinstance(limit, int):
            return {
                "success": False,
                "error": "BAD_ARGUMENT",
                "message": "limit 必须为整数",
            }
        max_limit = max(1, min(limit, 100))
        path = Path(self.db_path) if self.db_path else store.get_default_db_path()
        store.initialize_store(path)

        with store._LOCK:
            try:
                with store._connect(path) as conn:
                    if search_mode == "entity":
                        sql = """
                            SELECT DISTINCT i.item_id, i.item_key, i.title, i.summary,
                                   i.source_id, i.hint, i.published_at, i.last_seen_at
                            FROM intel_items i
                            JOIN intel_item_entities e ON i.item_id = e.item_id
                            WHERE e.term LIKE ? OR e.security_code LIKE ?
                            ORDER BY i.last_seen_at DESC LIMIT ?
                        """
                        rows = conn.execute(
                            sql, (f"%{clean_query}%", f"%{clean_query}%", max_limit)
                        ).fetchall()
                    else:
                        sql = """
                            SELECT i.item_id, i.item_key, i.title, i.summary,
                                   i.source_id,
                                   COALESCE(NULLIF(i.hint, ''), s.source_type, 'hotlist') AS item_hint,
                                   s.source_type, i.published_at, i.last_seen_at
                            FROM intel_items i
                            LEFT JOIN intel_sources s ON i.source_id = s.source_id
                            WHERE (i.title LIKE ? OR i.summary LIKE ?)
                        """
                        params: list[Any] = [f"%{clean_query}%", f"%{clean_query}%"]
                        if source_type == "rss":
                            sql += " AND s.source_type = 'rss'"
                        elif source_type == "hotlist":
                            sql += " AND s.source_type = 'hotlist'"
                        sql += " ORDER BY i.last_seen_at DESC LIMIT ?"
                        params.append(max_limit)
                        rows = conn.execute(sql, tuple(params)).fetchall()

                    items = []
                    for r in rows:
                        items.append(
                            {
                                "item_id": r["item_id"],
                                "item_key": r["item_key"],
                                "title": r["title"],
                                "summary": r["summary"] or "",
                                "source_id": r["source_id"],
                                "hint": r["item_hint"]
                                if "item_hint" in r.keys()
                                else (r["hint"] if "hint" in r.keys() else ""),
                                "published_at": r["published_at"],
                                "last_seen_at": r["last_seen_at"],
                            }
                        )

                    return {
                        "success": True,
                        "query": clean_query,
                        "search_mode": search_mode,
                        "total": len(items),
                        "items": items,
                        "usage_boundary": "OBSERVATION_ONLY_NOT_AN_INVESTMENT_AUTHORITY",
                    }
            except Exception as e:
                logger.error("search_intel failed: %s", e)
                return {"success": False, "error": str(e)}

    def analyze_intel_trend(
        self,
        topic: str | None = None,
        keyword: str | None = None,
        similar_to: str | int | None = None,
        insight_type: str | None = None,
        days: int = 7,
        data_basis: str = "CURRENT_ELIGIBLE",
        compare_period: str | int | None = None,
    ) -> dict[str, Any]:
        """趋势与洞察分析工具。严格复用 Wave 4 reporting 权威计算。"""
        try:
            target_topic = (topic or keyword or "").strip()
            path = self.db_path or str(store.get_default_db_path())

            # 1. 相似资讯检索：标题只负责确定性解析 reference item_id；
            # 相似度、阈值与窗口全部由 Wave 4 reporting.similar_items 唯一决定。
            if similar_to:
                try:
                    reference_item_id = int(similar_to)
                    reference_title = None
                except (ValueError, TypeError):
                    reference_title = str(similar_to).strip()
                    with store._connect(path) as conn:
                        rows = conn.execute(
                            "SELECT item_id, title FROM intel_items WHERE title = ? ORDER BY item_id ASC",
                            (reference_title,),
                        ).fetchall()
                    if not rows:
                        return {
                            "success": False,
                            "error": "REFERENCE_ITEM_NOT_FOUND",
                            "message": f"未找到标题为 '{reference_title}' 的参考条目",
                        }
                    if len(rows) > 1:
                        return {
                            "success": False,
                            "error": "REFERENCE_ITEM_AMBIGUOUS",
                            "message": f"标题 '{reference_title}' 匹配到多个条目",
                            "matching_item_ids": [row["item_id"] for row in rows],
                        }
                    reference_item_id = rows[0]["item_id"]

                try:
                    similar_result = reporting.similar_items(
                        item_id=reference_item_id,
                        path=path,
                    )
                except ValueError as exc:
                    return {
                        "success": False,
                        "error": "REFERENCE_ITEM_NOT_FOUND",
                        "message": str(exc),
                    }
                result = {
                    "success": True,
                    "method": "similar_items",
                    "reference_item_id": reference_item_id,
                    "items": [
                        entry["item"] for entry in similar_result["similar_items"]
                    ],
                    "similarity_details": similar_result["similar_items"],
                    "threshold": similar_result["threshold"],
                    "algorithm": similar_result["algorithm"],
                    "data_basis": similar_result["data_basis"],
                    "usage_boundary": "OBSERVATION_ONLY_NOT_AN_INVESTMENT_AUTHORITY",
                }
                if reference_title is not None:
                    result["reference_title"] = reference_title
                return result

            # 2. 当 topic 为空时，作为 get_trending_topics 对等入口，返回当前热点与话题
            if not target_topic:
                profile = service.get_filter_profile("default", path)
                topics = [
                    g["name"]
                    for g in profile.get("keyword_rules", {}).get("groups", [])
                ]
                report = reporting.generate_report(
                    path=path, mode="CURRENT", commit=False
                )
                top_items = report.get("items", [])[:15]
                return {
                    "success": True,
                    "method": "trending_topics",
                    "topics": topics,
                    "items": top_items,
                    "data_basis": data_basis,
                    "usage_boundary": "OBSERVATION_ONLY_NOT_AN_INVESTMENT_AUTHORITY",
                }

            # 3. 话题趋势分析：调用 Wave 4 reporting.analyze_topic
            bounded_days = max(2, min(30, int(days)))
            valid_basis = (
                "RAW_HISTORY"
                if str(data_basis).upper() == "RAW_HISTORY"
                else "CURRENT_ELIGIBLE"
            )
            analysis_now = datetime.now(timezone.utc)
            topic_res = reporting.analyze_topic(
                path=path,
                topic=target_topic,
                days=bounded_days,
                data_basis=valid_basis,
                now=analysis_now,
            )

            # 4. 仅提供 Wave 4 能诚实表达的相邻等长窗口比较。
            # Pinned compare_periods 的任意 period1/period2/compare_type 仍标 NOT_YET_PARITY。
            if compare_period:
                if compare_period != "previous_equal_window":
                    return {
                        "success": False,
                        "error": "BAD_ARGUMENT",
                        "message": "compare_period 仅支持 previous_equal_window",
                    }
                previous_result = reporting.analyze_topic(
                    path=path,
                    topic=target_topic,
                    days=bounded_days,
                    data_basis=valid_basis,
                    now=analysis_now - timedelta(days=bounded_days),
                )
                current_count = sum(
                    bucket["mention_count"] for bucket in topic_res["trend"]
                )
                previous_count = sum(
                    bucket["mention_count"] for bucket in previous_result["trend"]
                )
                change_percent = (
                    round((current_count - previous_count) * 100 / previous_count, 2)
                    if previous_count
                    else None
                )
                if previous_count == 0:
                    direction = "上升" if current_count else "稳定"
                elif change_percent is not None and change_percent > 10:
                    direction = "上升"
                elif change_percent is not None and change_percent < -10:
                    direction = "下降"
                else:
                    direction = "稳定"
                topic_res["comparison"] = {
                    "semantics": "ADJACENT_EQUAL_WINDOWS",
                    "authority": "native_intel_reporting.analyze_topic",
                    "period_a": {
                        "window": topic_res["window"],
                        "mention_count": current_count,
                    },
                    "period_b": {
                        "window": previous_result["window"],
                        "mention_count": previous_count,
                    },
                    "delta_mention_count": current_count - previous_count,
                    "change_percent": change_percent,
                    "trend_direction": direction,
                }

            # 5. insight_type 投影支持（直接投影 Wave 4 输出，不重新计算）
            if insight_type:
                itype = str(insight_type).lower().strip()
                if itype in ("platform", "platforms"):
                    return {
                        "success": True,
                        "insight_type": itype,
                        "topic": target_topic,
                        "platforms": topic_res.get("platforms", {}),
                        "platform_note": topic_res.get("platform_note"),
                        "data_basis": valid_basis,
                        "usage_boundary": "OBSERVATION_ONLY_NOT_AN_INVESTMENT_AUTHORITY",
                    }
                elif itype in ("cooccurrence", "co-occurrence"):
                    return {
                        "success": True,
                        "insight_type": itype,
                        "topic": target_topic,
                        "cooccurrence": topic_res.get("cooccurrence", []),
                        "data_basis": valid_basis,
                        "usage_boundary": "OBSERVATION_ONLY_NOT_AN_INVESTMENT_AUTHORITY",
                    }
                elif itype in ("lifecycle", "lifecycle_stage"):
                    return {
                        "success": True,
                        "insight_type": itype,
                        "topic": target_topic,
                        "lifecycle": topic_res.get("lifecycle"),
                        "data_basis": valid_basis,
                        "usage_boundary": "OBSERVATION_ONLY_NOT_AN_INVESTMENT_AUTHORITY",
                    }
                elif itype == "viral":
                    return {
                        "success": True,
                        "insight_type": "viral",
                        "topic": target_topic,
                        "viral": topic_res["viral"],
                        "data_basis": valid_basis,
                        "usage_boundary": "OBSERVATION_ONLY_NOT_AN_INVESTMENT_AUTHORITY",
                    }
                elif itype in ("prediction", "outlook"):
                    return {
                        "success": True,
                        "insight_type": itype,
                        "topic": target_topic,
                        "prediction": topic_res.get("prediction"),
                        "data_basis": valid_basis,
                        "usage_boundary": "OBSERVATION_ONLY_NOT_AN_INVESTMENT_AUTHORITY",
                    }

            return {
                "success": True,
                "method": "topic_trend",
                "topic": target_topic,
                "days": bounded_days,
                "data": topic_res,
                "data_basis": valid_basis,
                "usage_boundary": "OBSERVATION_ONLY_NOT_AN_INVESTMENT_AUTHORITY",
            }
        except Exception as e:
            logger.error("analyze_intel_trend failed: %s", e)
            return {"success": False, "error": str(e)}

    def analyze_intel_sentiment(
        self, text: str = "", topic: str | None = None
    ) -> dict[str, Any]:
        """舆情风向与争议分析工具。"""
        try:
            return service.analyze_ai_sentiment(
                text=text, topic=topic, path=self.db_path
            )
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_intel_status(self) -> dict[str, Any]:
        """获取 Native Intel 综合运行状态。

        调用真实 agent_runtime.status() 获取 Codex 真实状态。
        绝不泄露 API Key、Token 或代理账密。
        """
        base_status = service.status(path=self.db_path)
        cfg = store.get_native_intel_config(self.db_path)
        timeline_policy = timeline.get_policy(path=self.db_path)

        # 真实读取 Codex Runtime 状态
        try:
            codex_rt = agent_runtime.status()
        except Exception:
            codex_rt = {
                "installed": False,
                "authenticated": False,
                "available": False,
                "status": "runtime_unavailable",
            }

        ai_provider = (
            cfg.get("ai_provider") or cfg.get("ai_analysis_provider") or "cli-codex"
        )
        ai_model = cfg.get("ai_model") or cfg.get("ai_analysis_model") or "gpt-5-codex"

        if ai_provider == "cli-codex":
            ai_available = bool(codex_rt.get("available"))
            ai_installed = bool(codex_rt.get("installed"))
            ai_authenticated = bool(codex_rt.get("authenticated"))
            ai_runtime_status = str(codex_rt.get("status") or "runtime_unavailable")
        else:
            # API Compatible: 检查是否配置了有效凭据（绝不在返回中暴露密钥）
            has_credentials = bool(cfg.get("ai_base_url") and cfg.get("ai_api_key"))
            ai_available = has_credentials
            ai_installed = True
            ai_authenticated = has_credentials
            ai_runtime_status = (
                "ready" if has_credentials else "credentials_missing_in_server_context"
            )

        return {
            "success": True,
            "status": base_status.get("status"),
            "run_state": base_status.get("last_run", {}),
            "sources_summary": base_status.get("sources", {}),
            "freshness": base_status.get(
                "freshness",
                {
                    "rss_freshness_enabled": cfg.get("rss_freshness_enabled", False),
                    "rss_global_max_age_days": cfg.get("rss_global_max_age_days", 1),
                },
            ),
            "proxy": {
                "crawler_proxy_enabled": cfg.get("crawler_proxy_enabled", False),
                "crawler_proxy_configured": bool(cfg.get("crawler_proxy_url")),
                "rss_proxy_enabled": cfg.get("rss_proxy_enabled", False),
                "rss_proxy_configured": bool(cfg.get("rss_proxy_url")),
            },
            "standalone": {
                "enabled": cfg.get("standalone_enabled", True),
                "count": len(cfg.get("standalone_source_ids", [])),
            },
            "timeline": {
                "enabled": timeline_policy.get("enabled", False),
                "preset": timeline_policy.get("preset", "morning_evening"),
            },
            "ai": {
                "provider": ai_provider,
                "model": ai_model,
                "available": ai_available,
                "installed": ai_installed,
                "authenticated": ai_authenticated,
                "runtime_status": ai_runtime_status,
                "analysis_enabled": cfg.get("ai_analysis_enabled", False),
                "translation_enabled": cfg.get("ai_translation_enabled", False),
            },
            "usage_boundary": "OBSERVATION_ONLY_NOT_AN_INVESTMENT_AUTHORITY",
        }

    def trigger_intel_refresh(self, sources: list[str] | None = None) -> dict[str, Any]:
        """显式触发资料抓取与刷新。

        调用已有的 run_fetch。绝不触发任何正式投资决策或交易。
        """
        if sources is not None:
            valid_sources = (
                isinstance(sources, list)
                and bool(sources)
                and all(
                    isinstance(source_id, str) and source_id.strip()
                    for source_id in sources
                )
                and len(sources) == len(set(sources))
            )
            if not valid_sources:
                return {
                    "success": False,
                    "error": "BAD_ARGUMENT",
                    "message": "sources 必须为非空、无重复的 source_id 字符串数组",
                }

        try:
            result = service.run_fetch(
                trigger="agent",
                path=self.db_path or str(store.get_default_db_path()),
                source_ids=sources,
            )
        except ValueError as exc:
            return {
                "success": False,
                "error": "BAD_ARGUMENT",
                "message": str(exc),
            }
        return {
            "success": result["status"]
            in (store.RUN_STATUS_OK, store.RUN_STATUS_PARTIAL),
            "run_id": result["run_id"],
            "status": result["status"],
            "source_ok": result["source_ok"],
            "source_failed": result["source_failed"],
            "item_seen": result["item_seen"],
            "item_new": result["item_new"],
            "requested_sources": sources,
            "data_basis": "OBSERVATION_FACTS",
            "usage_boundary": "OBSERVATION_ONLY_NOT_AN_INVESTMENT_AUTHORITY",
        }

    def resolve_intel_date_range(
        self, expression: str, now: datetime | None = None
    ) -> dict[str, Any]:
        """自然语言日期范围解析。"""
        return resolve_intel_date_range(expression, now=now)


# ---------------------------------------------------------------------------
# Vibe-Native MCP JSON-RPC 2.0 Protocol Adapter
# ---------------------------------------------------------------------------

NATIVE_INTEL_MCP_TOOLS = [
    {
        "name": "query_intel",
        "description": "查询最新热榜、RSS或重点独立区资讯与报告数据",
        "inputSchema": {
            "type": "object",
            "properties": {
                "mode": {
                    "type": "string",
                    "enum": [
                        "current",
                        "daily",
                        "incremental",
                        "report",
                        "aggregate",
                        "dates",
                    ],
                    "default": "current",
                    "description": "查询模式",
                },
                "scope": {
                    "type": "string",
                    "enum": ["all", "my_interests"],
                    "default": "all",
                },
                "source_type": {
                    "type": "string",
                    "enum": ["all", "hotlist", "rss", "standalone"],
                    "default": "all",
                },
                "limit": {
                    "type": "integer",
                    "default": 50,
                    "description": "最大返回条数",
                },
                "date": {"type": "string", "description": "YYYY-MM-DD (供 daily 模式)"},
            },
        },
    },
    {
        "name": "search_intel",
        "description": "基于事实关键词或实体查询资讯条目",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索词"},
                "search_mode": {
                    "type": "string",
                    "enum": ["keyword", "entity"],
                    "default": "keyword",
                },
                "source_type": {
                    "type": "string",
                    "enum": ["all", "hotlist", "rss"],
                    "default": "all",
                },
                "limit": {"type": "integer", "default": 20},
            },
            "required": ["query"],
        },
    },
    {
        "name": "analyze_intel_trend",
        "description": "分析话题热度趋势、平台共现、相似资讯或趋势预测（严格复用 Wave 4 权威计算）",
        "inputSchema": {
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": "话题名称，为空时返回当前热点话题列表",
                },
                "similar_to": {
                    "type": "string",
                    "description": "用于相似性比对的标题或条目ID",
                },
                "insight_type": {
                    "type": "string",
                    "enum": [
                        "platform",
                        "cooccurrence",
                        "lifecycle",
                        "viral",
                        "prediction",
                    ],
                    "description": "特定洞察维度投影",
                },
                "days": {"type": "integer", "default": 7, "minimum": 2, "maximum": 30},
                "data_basis": {
                    "type": "string",
                    "enum": ["CURRENT_ELIGIBLE", "RAW_HISTORY"],
                    "default": "CURRENT_ELIGIBLE",
                },
                "compare_period": {"type": "string", "description": "周期对比参数"},
            },
        },
    },
    {
        "name": "analyze_intel_sentiment",
        "description": "分析指定资讯文本或话题的舆情风向与争议",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "资讯文本"},
                "topic": {"type": "string", "description": "话题"},
            },
        },
    },
    {
        "name": "get_intel_status",
        "description": "获取 Native Intel 系统运行状态、数据源健康度、新鲜度及 AI 引擎真实就绪状态",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "trigger_intel_refresh",
        "description": "显式触发资讯抓取与观测刷新（仅刷新观察事实，绝不触发正式交易）",
        "inputSchema": {
            "type": "object",
            "properties": {
                "sources": {"type": "array", "items": {"type": "string"}},
            },
        },
    },
    {
        "name": "resolve_intel_date_range",
        "description": "将自然语言日期表达式（如'最近7天'、'本周'）解析为标准日期范围",
        "inputSchema": {
            "type": "object",
            "properties": {
                "expression": {"type": "string", "description": "日期表达式"},
            },
            "required": ["expression"],
        },
    },
]


def dispatch_mcp_message(
    msg: dict[str, Any], tools: NativeIntelAgentTools
) -> dict[str, Any]:
    """处理标准 MCP JSON-RPC 2.0 协议请求。"""
    rid = msg.get("id")
    method = msg.get("method")
    params = msg.get("params") or {}

    if method == "notifications/initialized":
        return {"jsonrpc": "2.0", "result": {}}

    if method == "initialize":
        proto = params.get("protocolVersion", "2024-11-05")
        return {
            "jsonrpc": "2.0",
            "id": rid,
            "result": {
                "protocolVersion": proto,
                "capabilities": {"tools": {}},
                "serverInfo": {
                    "name": "vibe-native-intel",
                    "version": read_version(),
                },
            },
        }

    if method == "ping":
        return {"jsonrpc": "2.0", "id": rid, "result": {}}

    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": rid,
            "result": {
                "tools": NATIVE_INTEL_MCP_TOOLS,
            },
        }

    if method == "tools/call":
        tool_name = params.get("name", "")
        args = params.get("arguments") or {}

        try:
            if tool_name == "query_intel":
                data = tools.query_intel(
                    mode=str(args.get("mode") or "current"),
                    scope=str(args.get("scope") or "all"),
                    source_type=str(args.get("source_type") or "all"),
                    limit=int(args.get("limit", 50)),
                    date=args.get("date"),
                )
            elif tool_name == "search_intel":
                data = tools.search_intel(
                    query=str(args.get("query") or ""),
                    search_mode=str(args.get("search_mode") or "keyword"),
                    source_type=str(args.get("source_type") or "all"),
                    limit=int(args.get("limit", 20)),
                )
            elif tool_name == "analyze_intel_trend":
                data = tools.analyze_intel_trend(
                    topic=args.get("topic"),
                    similar_to=args.get("similar_to"),
                    insight_type=args.get("insight_type"),
                    days=int(args.get("days", 7)),
                    data_basis=str(args.get("data_basis") or "CURRENT_ELIGIBLE"),
                    compare_period=args.get("compare_period"),
                )
            elif tool_name == "analyze_intel_sentiment":
                data = tools.analyze_intel_sentiment(
                    text=str(args.get("text") or ""),
                    topic=args.get("topic"),
                )
            elif tool_name == "get_intel_status":
                data = tools.get_intel_status()
            elif tool_name == "trigger_intel_refresh":
                data = tools.trigger_intel_refresh(sources=args.get("sources"))
            elif tool_name == "resolve_intel_date_range":
                data = tools.resolve_intel_date_range(
                    expression=str(args.get("expression") or "")
                )
            else:
                return {
                    "jsonrpc": "2.0",
                    "id": rid,
                    "error": {"code": -32601, "message": f"Unknown tool: {tool_name}"},
                }

            is_error = isinstance(data, dict) and (
                not data.get("success", True) or "error" in data
            )
            return {
                "jsonrpc": "2.0",
                "id": rid,
                "result": {
                    "content": [
                        {"type": "text", "text": json.dumps(data, ensure_ascii=False)}
                    ],
                    "isError": is_error,
                },
            }
        except Exception as e:
            return {
                "jsonrpc": "2.0",
                "id": rid,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(
                                {"success": False, "error": str(e)}, ensure_ascii=False
                            ),
                        }
                    ],
                    "isError": True,
                },
            }

    return {
        "jsonrpc": "2.0",
        "id": rid,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }
