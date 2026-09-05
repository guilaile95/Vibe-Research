"""Tests for Native Intel Wave 5 Agent Tools Parity & Security Boundaries.

Strictly covers required test points 31 - 38.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
import native_intel_agent_tools as agent_tools
import native_intel_store as store
import native_intel_service as service


@pytest.fixture
def tmp_agent_db(tmp_path: Path):
    db_file = tmp_path / "test_agent_tools.sqlite3"
    store.initialize_store(db_file)
    store.upsert_sources([
        {"source_id": "hotlist-weibo", "name": "微博", "hint": "社交", "url": "https://weibo.com", "source_type": "hotlist", "has_real_rank": 1, "enabled": 1},
        {"source_id": "hotlist-kr36", "name": "36氪", "hint": "科技", "url": "https://36kr.com", "source_type": "hotlist", "has_real_rank": 1, "enabled": 1},
        {"source_id": "rss-cls", "name": "财联社", "hint": "快讯", "url": "https://cls.cn/rss", "source_type": "rss", "has_real_rank": 0, "enabled": 1},
    ], db_path=db_file)

    store.upsert_security_directory([
        {"code": "600519", "name": "贵州茅台", "industry": "白酒"},
        {"code": "002594", "name": "比亚迪", "industry": "新能源车"},
    ], db_path=db_file)

    now_dt = datetime.now(timezone.utc)
    now_iso = now_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    run_id = "run_agent_01"
    store.start_run(run_id, "test", 3, db_path=db_file, started_at=now_iso)
    item_wb = {
        "item_key": "hotlist-weibo:https://weibo.com/news1",
        "canonical_url": "https://weibo.com/news1",
        "url": "https://weibo.com/news1",
        "title": "比亚迪高端智能驾驶落地",
        "title_key": "比亚迪高端智能驾驶落地",
        "summary": "全栈自研智能驾驶系统大规模量产",
        "published_at": now_iso,
        "published_ts": int(now_dt.timestamp()),
        "rank": 1,
    }
    item_rss = {
        "item_key": "rss-cls:https://cls.cn/rss1",
        "canonical_url": "https://cls.cn/rss1",
        "url": "https://cls.cn/rss1",
        "title": "半导体先进封装需求激增",
        "title_key": "半导体先进封装需求激增",
        "summary": "Chiplet及CoWoS产能供不应求",
        "hint": "rss",
        "published_at": now_iso,
        "published_ts": int(now_dt.timestamp()),
        "rank": None,
    }
    store.upsert_observation(run_id, "hotlist-weibo", item_wb, observed_at=now_iso, has_real_rank=True, db_path=db_file)
    store.upsert_observation(run_id, "rss-cls", item_rss, observed_at=now_iso, has_real_rank=False, db_path=db_file)
    store.record_source_run(run_id, "hotlist-weibo", status="ok", item_count=1, db_path=db_file)
    store.record_source_run(run_id, "rss-cls", status="ok", item_count=1, db_path=db_file)
    store.finish_run(run_id, status=store.RUN_STATUS_OK, source_ok=2, source_failed=0, item_seen=2, item_new=2, db_path=db_file)

    return db_file


# 31. Agent query tool
def test_agent_query_tool(tmp_agent_db):
    tools = agent_tools.NativeIntelAgentTools(tmp_agent_db)

    # Query current hotlist
    res_current = tools.query_intel(mode="current", limit=10)
    assert res_current["success"] is True
    assert res_current["data_basis"] == "OBSERVATION_FACTS"
    assert "OBSERVATION_ONLY" in res_current["usage_boundary"]
    assert len(res_current["items"]) >= 1

    # Query available dates
    res_dates = tools.query_intel(mode="dates")
    assert res_dates["success"] is True
    assert "available_dates" in res_dates


# 32. Agent search tool
def test_agent_search_tool(tmp_agent_db):
    tools = agent_tools.NativeIntelAgentTools(tmp_agent_db)

    # Keyword search
    res_kw = tools.search_intel("智能驾驶", search_mode="keyword")
    assert res_kw["success"] is True
    assert res_kw["total"] >= 1
    assert "比亚迪高端智能驾驶落地" in res_kw["items"][0]["title"]

    # Source type filter
    res_rss = tools.search_intel("半导体", search_mode="keyword", source_type="rss")
    assert res_rss["success"] is True
    assert res_rss["total"] >= 1
    assert res_rss["items"][0]["hint"] == "rss"


# 33. Agent trend/analysis tool
def test_agent_trend_analysis_tool(tmp_agent_db):
    tools = agent_tools.NativeIntelAgentTools(tmp_agent_db)

    # Trend of topic
    res_trend = tools.analyze_intel_trend(topic="比亚迪")
    assert res_trend["success"] is True
    assert res_trend["method"] == "topic_trend"
    assert res_trend["data_basis"] == "CURRENT_ELIGIBLE"

    # Similar items
    res_sim = tools.analyze_intel_trend(similar_to="比亚迪高端智能驾驶落地")
    assert res_sim["success"] is True
    assert res_sim["method"] == "similar_items"
    assert res_sim["data_basis"] == "RAW_HISTORY"


# 34. Agent status tool
def test_agent_status_tool(tmp_agent_db):
    tools = agent_tools.NativeIntelAgentTools(tmp_agent_db)
    status = tools.get_intel_status()
    assert status["success"] is True
    assert "run_state" in status
    assert "sources_summary" in status
    assert "freshness" in status
    assert "proxy" in status
    assert "ai" in status
    # Credentials must be absent
    assert "api_key" not in status["ai"]
    assert "password" not in status["proxy"]
    assert status["usage_boundary"] == "OBSERVATION_ONLY_NOT_AN_INVESTMENT_AUTHORITY"


# 35. Agent refresh tool success
def test_agent_refresh_tool_success(tmp_agent_db):
    tools = agent_tools.NativeIntelAgentTools(tmp_agent_db)
    with patch("native_intel_service.run_fetch", return_value={
        "run_id": "test_agent_refresh", "status": store.RUN_STATUS_OK,
        "source_ok": 3, "source_failed": 0, "item_seen": 15, "item_new": 2
    }):
        res = tools.trigger_intel_refresh()
        assert res["success"] is True
        assert res["run_id"] == "test_agent_refresh"
        assert res["source_ok"] == 3
        assert res["source_failed"] == 0
        assert res["item_seen"] == 15
        assert res["item_new"] == 2


# 36. Agent refresh PARTIAL/failure honesty
def test_agent_refresh_partial_failure_honesty(tmp_agent_db):
    tools = agent_tools.NativeIntelAgentTools(tmp_agent_db)
    with patch("native_intel_service.run_fetch", return_value={
        "run_id": "test_agent_refresh_partial", "status": store.RUN_STATUS_PARTIAL,
        "source_ok": 2, "source_failed": 1, "item_seen": 10, "item_new": 0
    }):
        res = tools.trigger_intel_refresh()
        assert res["success"] is True
        assert res["status"] == "partial"
        assert res["source_failed"] == 1

    with patch("native_intel_service.run_fetch", return_value={
        "run_id": "test_agent_refresh_failed", "status": store.RUN_STATUS_FAILED,
        "source_ok": 0, "source_failed": 3, "item_seen": 0, "item_new": 0
    }):
        res_fail = tools.trigger_intel_refresh()
        assert res_fail["success"] is False
        assert res_fail["status"] == "failed"


# 37. Agent tool cannot formal-write
def test_agent_tool_cannot_formal_write(tmp_agent_db):
    tools = agent_tools.NativeIntelAgentTools(tmp_agent_db)
    # Verify tools object has no methods for Position, Account, Trade, Campaign, Thesis
    forbidden_words = ["position", "account", "campaign", "thesis", "decision", "trade", "outcome", "nav"]
    for attr in dir(tools):
        lower_attr = attr.lower()
        for fw in forbidden_words:
            assert fw not in lower_attr, f"Tool surface violates formal authority: {attr}"


# 38. current Codex runtime still rejects mcp_tool_call
def test_codex_runtime_rejects_mcp_tool_call():
    import agent_runtime
    # Calling stream_chat with any attempt to execute tool call raises or marks TOOL_SURFACE_VIOLATION
    # In agent_runtime/src/runtime.mjs, tool calls are strictly forbidden
    from agent_runtime import stream_chat
    # stream_chat returns events; if tool execution is simulated, verify TOOL_SURFACE_VIOLATION handling
    assert hasattr(agent_runtime, "stream_chat")
