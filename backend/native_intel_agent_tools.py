"""Vibe-native Agent Tool Surface (TREND-PARITY Wave 5).

Provides native Agent tools parity for external and controlled agent clients:
- query_intel: 资讯与报告查询
- search_intel: 事实关键词与实体检索
- analyze_intel_trend: 话题趋势、相似性与平台共现分析
- get_intel_status: 系统运行、数据源、新鲜度与 AI 状态查询
- trigger_intel_refresh: 资料抓取与刷新显式触发
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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import native_intel_reporting as reporting
import native_intel_service as service
import native_intel_store as store
import native_intel_timeline as timeline

logger = logging.getLogger(__name__)

LOCAL_TZ = timezone(timedelta(hours=8))


def resolve_intel_date_range(expression: str, now: datetime | None = None) -> dict[str, Any]:
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
        # 尝试匹配 "最近N天" 或 "last N days"
        import re
        m = re.match(r"(?:最近|last\s*)(\d+)(?:天|\s*days?)", expr)
        if m:
            days = int(m.group(1))
            start = today - timedelta(days=max(1, days) - 1)
            end = today
            desc = f"最近{days}天"
        else:
            # 默认最近7天
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
            mode: current / daily / incremental / report / dates
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

        if mode_upper in ("CURRENT", "DAILY", "INCREMENTAL"):
            now_dt = None
            if date:
                try:
                    now_dt = datetime.fromisoformat(date + "T23:59:59+08:00")
                except Exception:
                    now_dt = None
            # 使用现有 Wave 4 确定性报告生成器（commit=False，不推进 cursor）
            report = reporting.generate_report(
                path=str(self.db_path) if self.db_path else None,
                mode=mode_upper,
                scope=scope,
                profile_id=profile_id,
                now=now_dt,
                commit=False,
            )
            raw_items = report.get("items", [])
            # 按 source_type 过滤
            filtered_items = []
            for it in raw_items:
                st = it.get("source_type") or ("rss" if it.get("hint") == "rss" else "hotlist")
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

        # 默认回退到当前快照
        hotlist_data = service.get_hotlist(limit=limit, scope=scope, path=self.db_path)
        return {
            "success": True,
            "mode": "current",
            "items": hotlist_data.get("items", []),
            "total": len(hotlist_data.get("items", [])),
            "data_basis": "OBSERVATION_FACTS",
            "usage_boundary": "OBSERVATION_ONLY_NOT_AN_INVESTMENT_AUTHORITY",
        }

    def search_intel(
        self,
        query: str,
        search_mode: str = "keyword",
        source_type: str = "all",
        limit: int = 20,
    ) -> dict[str, Any]:
        """事实关键词或实体检索。

        Args:
            query: 搜索关键词或实体名
            search_mode: keyword / entity
            source_type: all / hotlist / rss
            limit: 最大返回条数 (上限 100)
        """
        clean_query = (query or "").strip()
        if not clean_query:
            return {"success": True, "query": "", "total": 0, "items": []}

        max_limit = max(1, min(int(limit), 100))
        path = Path(self.db_path) if self.db_path else store.get_default_db_path()
        store.initialize_store(path)

        with store._LOCK:
            try:
                with store._connect(path) as conn:
                    if search_mode == "entity":
                        # 联合检索 intel_item_entities 与 intel_items
                        sql = """
                            SELECT DISTINCT i.item_id, i.item_key, i.title, i.summary,
                                   i.source_id, i.hint, i.published_at, i.last_seen_at
                            FROM intel_items i
                            JOIN intel_item_entities e ON i.item_id = e.item_id
                            WHERE e.term LIKE ? OR e.security_code LIKE ?
                            ORDER BY i.last_seen_at DESC LIMIT ?
                        """
                        rows = conn.execute(sql, (f"%{clean_query}%", f"%{clean_query}%", max_limit)).fetchall()
                    else:
                        # 关键词模式（匹配 title + summary）
                        sql = """
                            SELECT i.item_id, i.item_key, i.title, i.summary,
                                   i.source_id,
                                   COALESCE(NULLIF(i.hint, ''), s.source_type, 'hotlist') AS item_hint,
                                   s.source_type, i.published_at, i.last_seen_at
                            FROM intel_items i
                            LEFT JOIN intel_sources s ON i.source_id = s.source_id
                            WHERE (i.title LIKE ? OR i.summary LIKE ?)
                        """
                        params = [f"%{clean_query}%", f"%{clean_query}%"]
                        if source_type == "rss":
                            sql += " AND s.source_type = 'rss'"
                        elif source_type == "hotlist":
                            sql += " AND s.source_type = 'hotlist'"
                        sql += " ORDER BY i.last_seen_at DESC LIMIT ?"
                        params.append(max_limit)
                        rows = conn.execute(sql, tuple(params)).fetchall()

                    items = []
                    for r in rows:
                        items.append({
                            "item_id": r["item_id"],
                            "item_key": r["item_key"],
                            "title": r["title"],
                            "summary": r["summary"] or "",
                            "source_id": r["source_id"],
                            "hint": r["item_hint"] if "item_hint" in r.keys() else (r["hint"] if "hint" in r.keys() else ""),
                            "published_at": r["published_at"],
                            "last_seen_at": r["last_seen_at"],
                        })

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
        similar_to: str | None = None,
        insight_type: str | None = None,
        days: int = 7,
    ) -> dict[str, Any]:
        """趋势与洞察分析工具。"""
        try:
            target_topic = topic or keyword
            path = self.db_path or store.get_default_db_path()
            if similar_to:
                # 寻找相似资讯
                with store._connect(path) as conn:
                    rows = conn.execute(
                        "SELECT item_id, item_key, title, summary, source_id, published_at FROM intel_items WHERE title LIKE ? LIMIT 10",
                        (f"%{similar_to[:10]}%",)
                    ).fetchall()
                    similar_items = [dict(r) for r in rows]
                return {
                    "success": True,
                    "method": "similar_items",
                    "reference": similar_to,
                    "items": similar_items,
                    "data_basis": "RAW_HISTORY",
                }

            # 默认单话题趋势分析
            with store._connect(path) as conn:
                row = conn.execute(
                    """
                    SELECT count(*) as count, min(first_seen_at) as first_seen, max(last_seen_at) as last_seen
                    FROM intel_items WHERE title LIKE ? OR summary LIKE ?
                    """,
                    (f"%{target_topic}%", f"%{target_topic}%")
                ).fetchone()
                mention_count = row["count"] if row else 0

            trend_data = {
                "topic": target_topic,
                "mention_count": mention_count,
                "first_seen": row["first_seen"] if row else None,
                "last_seen": row["last_seen"] if row else None,
                "days": days,
            }
            return {
                "success": True,
                "method": "topic_trend",
                "topic": target_topic,
                "days": days,
                "data": trend_data,
                "data_basis": "CURRENT_ELIGIBLE",
                "usage_boundary": "OBSERVATION_ONLY_NOT_AN_INVESTMENT_AUTHORITY",
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_intel_status(self) -> dict[str, Any]:
        """获取 Native Intel 综合运行状态。

        包含：抓取状态、源健康度、新鲜度配置、代理脱敏状态、timeline 策略、AI 提供商就绪度。
        绝不泄露 API Key、Token 或代理账密。
        """
        base_status = service.status(path=self.db_path)
        cfg = store.get_native_intel_config(self.db_path)
        timeline_policy = timeline.get_policy(path=self.db_path)

        # AI 状态
        ai_provider = cfg.get("ai_analysis_provider", "cli-codex")
        ai_model = cfg.get("ai_analysis_model", "gpt-5-codex")
        ai_available = True
        if ai_provider == "openai-compatible":
            ai_available = bool(cfg.get("ai_base_url") and cfg.get("ai_api_key"))

        return {
            "success": True,
            "status": base_status.get("status"),
            "run_state": base_status.get("last_run", {}),
            "sources_summary": base_status.get("sources", {}),
            "freshness": base_status.get("freshness", {
                "rss_freshness_enabled": cfg.get("rss_freshness_enabled", False),
                "rss_global_max_age_days": cfg.get("rss_global_max_age_days", 1),
            }),
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
                "analysis_enabled": cfg.get("ai_analysis_enabled", False),
                "translation_enabled": cfg.get("ai_translation_enabled", False),
            },
            "usage_boundary": "OBSERVATION_ONLY_NOT_AN_INVESTMENT_AUTHORITY",
        }

    def trigger_intel_refresh(self, sources: list[str] | None = None) -> dict[str, Any]:
        """显式触发资料抓取与刷新。

        调用已有的 run_fetch。绝不触发任何正式投资决策或交易。
        """
        res = service.run_fetch(trigger="agent", path=self.db_path)
        return {
            "success": res.get("status") in (store.RUN_STATUS_OK, store.RUN_STATUS_PARTIAL),
            "run_id": res.get("run_id", ""),
            "status": res.get("status", ""),
            "source_ok": res.get("source_ok", 0),
            "source_failed": res.get("source_failed", 0),
            "item_seen": res.get("item_seen", 0),
            "item_new": res.get("item_new", 0),
            "usage_boundary": "OBSERVATION_ONLY_NOT_AN_INVESTMENT_AUTHORITY",
        }

    def resolve_intel_date_range(self, expression: str, now: datetime | None = None) -> dict[str, Any]:
        """自然语言日期范围解析。"""
        return resolve_intel_date_range(expression, now=now)
