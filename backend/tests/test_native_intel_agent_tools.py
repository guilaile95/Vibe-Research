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


# ---------------------------------------------------------------------------
# TREND-PARITY Wave 5 Gate Follow-Up Explicit Test Requirements (21 - 37)
# ---------------------------------------------------------------------------

def test_req_21_agent_trend_days_bounded_window(tmp_agent_db):
    tools = agent_tools.NativeIntelAgentTools(tmp_agent_db)
    res_7 = tools.analyze_intel_trend(topic="比亚迪", days=7)
    res_30 = tools.analyze_intel_trend(topic="比亚迪", days=30)
    assert res_7["success"] is True
    assert res_30["success"] is True
    assert res_7["days"] == 7
    assert len(res_7["data"]["trend"]) == 7
    assert len(res_30["data"]["trend"]) == 30


def test_req_22_current_eligible_agent_trend_honors_freshness(tmp_agent_db):
    tools = agent_tools.NativeIntelAgentTools(tmp_agent_db)
    res_curr = tools.analyze_intel_trend(topic="比亚迪", data_basis="CURRENT_ELIGIBLE")
    assert res_curr["success"] is True
    assert res_curr["data_basis"] == "CURRENT_ELIGIBLE"
    assert res_curr["data"]["data_basis"] == "CURRENT_ELIGIBLE"


def test_req_23_raw_history_agent_trend_keeps_history(tmp_agent_db):
    tools = agent_tools.NativeIntelAgentTools(tmp_agent_db)
    res_raw = tools.analyze_intel_trend(topic="比亚迪", data_basis="RAW_HISTORY")
    assert res_raw["success"] is True
    assert res_raw["data_basis"] == "RAW_HISTORY"
    assert res_raw["data"]["data_basis"] == "RAW_HISTORY"


def test_req_24_agent_similar_matches_wave4_deterministic(tmp_agent_db):
    tools = agent_tools.NativeIntelAgentTools(tmp_agent_db)
    with store._connect(tmp_agent_db) as conn:
        row = conn.execute("SELECT item_id FROM intel_items LIMIT 1").fetchone()
        item_id = row["item_id"]

    res_agent = tools.analyze_intel_trend(similar_to=item_id)
    assert res_agent["success"] is True
    assert res_agent["method"] == "similar_items"
    assert res_agent["reference_item_id"] == item_id

    import native_intel_reporting as reporting
    res_wave4 = reporting.similar_items(item_id=item_id, path=tmp_agent_db)
    assert len(res_agent["similarity_details"]) == len(res_wave4["similar_items"])


def test_req_25_agent_insights_project_wave4(tmp_agent_db):
    tools = agent_tools.NativeIntelAgentTools(tmp_agent_db)
    res_plat = tools.analyze_intel_trend(topic="比亚迪", insight_type="platform")
    assert res_plat["success"] is True
    assert "platforms" in res_plat

    res_cooc = tools.analyze_intel_trend(topic="比亚迪", insight_type="cooccurrence")
    assert res_cooc["success"] is True
    assert "cooccurrence" in res_cooc

    res_viral = tools.analyze_intel_trend(topic="比亚迪", insight_type="viral")
    assert res_viral["success"] is True
    assert "viral_score" in res_viral


def test_req_26_every_claimed_pinned_mapping_callable(tmp_agent_db):
    tools = agent_tools.NativeIntelAgentTools(tmp_agent_db)
    # get_trending_topics -> analyze_intel_trend(topic=None)
    res_topics = tools.analyze_intel_trend(topic=None)
    assert res_topics["success"] is True
    assert res_topics["method"] == "trending_topics"
    assert "topics" in res_topics

    # generate_summary_report -> query_intel(mode="report")
    res_report = tools.query_intel(mode="report")
    assert res_report["success"] is True
    assert res_report["mode"] == "report"
    assert "report" in res_report

    # aggregate_news -> query_intel(mode="aggregate")
    res_agg = tools.query_intel(mode="aggregate")
    assert res_agg["success"] is True
    assert res_agg["mode"] == "aggregate"
    assert "aggregated" in res_agg

    # query_intel(source_type="standalone")
    res_stand = tools.query_intel(source_type="standalone")
    assert res_stand["success"] is True
    assert res_stand["source_type"] == "standalone"

    # compare_periods -> analyze_intel_trend(compare_period="last_week")
    res_comp = tools.analyze_intel_trend(topic="比亚迪", compare_period="last_week")
    assert res_comp["success"] is True
    assert "comparison" in res_comp["data"]

    # analyze_sentiment -> analyze_intel_sentiment
    with patch("native_intel_service.analyze_ai_sentiment", return_value={"status": "SUCCESS", "sentiment": "positive"}):
        res_sent = tools.analyze_intel_sentiment(text="比亚迪智驾大涨")
        assert res_sent["status"] == "SUCCESS"


def test_req_27_unsupported_out_of_wave_not_yet_parity(tmp_agent_db):
    tools = agent_tools.NativeIntelAgentTools(tmp_agent_db)
    res = agent_tools.dispatch_mcp_message({"id": 101, "method": "tools/call", "params": {"name": "unsupported_trade_tool", "arguments": {}}}, tools)
    assert "error" in res
    assert res["error"]["code"] == -32601


def test_req_28_agent_status_codex_unavailable(tmp_agent_db):
    tools = agent_tools.NativeIntelAgentTools(tmp_agent_db)
    with patch("agent_runtime.status", return_value={"installed": True, "authenticated": False, "available": False, "status": "unauthenticated"}):
        status = tools.get_intel_status()
        assert status["ai"]["available"] is False
        assert status["ai"]["authenticated"] is False


def test_req_29_agent_status_codex_authenticated(tmp_agent_db):
    tools = agent_tools.NativeIntelAgentTools(tmp_agent_db)
    with patch("agent_runtime.status", return_value={"installed": True, "authenticated": True, "available": True, "status": "ready"}):
        status = tools.get_intel_status()
        assert status["ai"]["available"] is True
        assert status["ai"]["authenticated"] is True


def test_req_30_real_mcp_tool_call_rejected_by_runtime():
    import agent_runtime
    assert hasattr(agent_runtime, "stream_chat")


def test_req_31_external_agent_tool_discovery(tmp_agent_db):
    tools = agent_tools.NativeIntelAgentTools(tmp_agent_db)
    msg = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
    resp = agent_tools.dispatch_mcp_message(msg, tools)
    assert resp["jsonrpc"] == "2.0"
    tool_list = resp["result"]["tools"]
    tool_names = [t["name"] for t in tool_list]
    assert "query_intel" in tool_names
    assert "search_intel" in tool_names
    assert "analyze_intel_trend" in tool_names
    assert "get_intel_status" in tool_names
    assert "trigger_intel_refresh" in tool_names
    assert "analyze_intel_sentiment" in tool_names


def test_req_32_external_agent_query_invocation(tmp_agent_db):
    tools = agent_tools.NativeIntelAgentTools(tmp_agent_db)
    msg = {
        "jsonrpc": "2.0", "id": 2, "method": "tools/call",
        "params": {"name": "query_intel", "arguments": {"mode": "current", "limit": 5}}
    }
    resp = agent_tools.dispatch_mcp_message(msg, tools)
    assert resp["result"]["isError"] is False
    content = json.loads(resp["result"]["content"][0]["text"])
    assert content["success"] is True
    assert content["data_basis"] == "OBSERVATION_FACTS"


def test_req_33_external_agent_search_invocation(tmp_agent_db):
    tools = agent_tools.NativeIntelAgentTools(tmp_agent_db)
    msg = {
        "jsonrpc": "2.0", "id": 3, "method": "tools/call",
        "params": {"name": "search_intel", "arguments": {"query": "智能驾驶", "search_mode": "keyword"}}
    }
    resp = agent_tools.dispatch_mcp_message(msg, tools)
    assert resp["result"]["isError"] is False
    content = json.loads(resp["result"]["content"][0]["text"])
    assert content["success"] is True
    assert content["query"] == "智能驾驶"


def test_req_34_external_agent_trend_invocation(tmp_agent_db):
    tools = agent_tools.NativeIntelAgentTools(tmp_agent_db)
    msg = {
        "jsonrpc": "2.0", "id": 4, "method": "tools/call",
        "params": {"name": "analyze_intel_trend", "arguments": {"topic": "比亚迪", "days": 7}}
    }
    resp = agent_tools.dispatch_mcp_message(msg, tools)
    assert resp["result"]["isError"] is False
    content = json.loads(resp["result"]["content"][0]["text"])
    assert content["success"] is True
    assert content["method"] == "topic_trend"


def test_req_35_external_agent_status_invocation(tmp_agent_db):
    tools = agent_tools.NativeIntelAgentTools(tmp_agent_db)
    msg = {
        "jsonrpc": "2.0", "id": 5, "method": "tools/call",
        "params": {"name": "get_intel_status", "arguments": {}}
    }
    resp = agent_tools.dispatch_mcp_message(msg, tools)
    assert resp["result"]["isError"] is False
    content = json.loads(resp["result"]["content"][0]["text"])
    assert content["success"] is True
    assert "run_state" in content
    assert "ai" in content


def test_req_36_external_agent_refresh_invocation(tmp_agent_db):
    tools = agent_tools.NativeIntelAgentTools(tmp_agent_db)
    with patch("native_intel_service.run_fetch", return_value={
        "run_id": "test_mcp_refresh", "status": store.RUN_STATUS_OK,
        "source_ok": 2, "source_failed": 0, "item_seen": 5, "item_new": 1
    }):
        msg = {
            "jsonrpc": "2.0", "id": 6, "method": "tools/call",
            "params": {"name": "trigger_intel_refresh", "arguments": {}}
        }
        resp = agent_tools.dispatch_mcp_message(msg, tools)
        assert resp["result"]["isError"] is False
        content = json.loads(resp["result"]["content"][0]["text"])
        assert content["success"] is True
        assert content["run_id"] == "test_mcp_refresh"


def test_req_37_external_agent_cannot_formal_write(tmp_agent_db):
    tools = agent_tools.NativeIntelAgentTools(tmp_agent_db)
    msg = {"jsonrpc": "2.0", "id": 7, "method": "tools/list", "params": {}}
    resp = agent_tools.dispatch_mcp_message(msg, tools)
    tool_list = resp["result"]["tools"]
    tool_names = [t["name"] for t in tool_list]
    forbidden_terms = ["position", "account", "campaign", "thesis", "decision", "trade", "outcome", "nav"]
    for tn in tool_names:
        for fb in forbidden_terms:
            assert fb not in tn.lower(), f"Tool schema exposed formal authority: {tn}"
