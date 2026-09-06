"""
TREND-PARITY Wave 5 Vertical Proof: Real AI & Agent Tools Integration.
Verifies:
1. Real AI calls via local Codex Subscription runtime (127.0.0.1:8911)
2. 6-module structured report generation and artifact persistence
3. Translation, entity extraction, and sentiment analysis
4. Agent Tools 6-function suite verification
5. Strictly zero writes to formal investment authority tables
"""
import os
import json
import sqlite3
import pytest
from datetime import datetime, timezone, timedelta
from pathlib import Path

import native_intel_store as store
import native_intel_service as service
import native_intel_ai as ai
import native_intel_agent_tools as agent_tools


@pytest.fixture
def proof_db(tmp_path):
    db_file = str(tmp_path / "vertical_proof_intel.sqlite3")
    store.initialize_store(db_file)

    # Seed directory for deterministic resolution
    store.upsert_security_directory([
        {"code": "688981", "name": "中芯国际", "industry": "半导体"},
    ], db_path=db_file)

    # Seed sources
    store.upsert_sources(
        [
            {
                "source_id": "cls-hot",
                "name": "财联社热门",
                "hint": "macro",
                "url": "https://cls.cn/hot",
                "source_type": "hotlist",
                "has_real_rank": True,
                "enabled": True,
            },
            {
                "source_id": "rss-semi",
                "name": "半导体产业周报",
                "hint": "tech",
                "url": "https://example.com/rss.xml",
                "source_type": "rss",
                "has_real_rank": False,
                "enabled": True,
            },
            {
                "source_id": "standalone-deep",
                "name": "深度专栏",
                "hint": "exclusive",
                "url": "https://example.com/deep.xml",
                "source_type": "rss",
                "has_real_rank": False,
                "enabled": True,
                "standalone_display": True,
            },
        ],
        db_path=db_file,
    )

    # Seed observations
    run_id = "proof-run-001"
    now_dt = datetime.now(timezone.utc)
    now = now_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    store.start_run(run_id, "proof", 3, db_path=db_file, started_at=now)

    item1 = {
        "item_key": "cls:1", "canonical_url": "https://cls.cn/hot/1", "url": "https://cls.cn/hot/1",
        "title": "中芯国际先进制程产能突破与供应链扩产", "title_key": "中芯国际先进制程产能突破与供应链扩产",
        "summary": "国内晶圆代工龙头中芯国际推进先进制程研发与设备国产化适配。",
        "published_at": now, "published_ts": int(now_dt.timestamp()), "rank": 1
    }
    item2 = {
        "item_key": "semi:1", "canonical_url": "https://example.com/semi/1", "url": "https://example.com/semi/1",
        "title": "液冷技术在高密算力中心大规模部署", "title_key": "液冷技术在高密算力中心大规模部署",
        "summary": "液冷CDU与冷板式散热成为智算中心标准配置。",
        "published_at": now, "published_ts": int(now_dt.timestamp()), "rank": None
    }
    item3 = {
        "item_key": "deep:1", "canonical_url": "https://example.com/deep/1", "url": "https://example.com/deep/1",
        "title": "自主可控算力底座：从芯片到系统", "title_key": "自主可控算力底座：从芯片到系统",
        "summary": "独家深度解析算力基础设施国产化演进路径与投资逻辑。",
        "published_at": now, "published_ts": int(now_dt.timestamp()), "rank": None
    }

    store.upsert_observation(run_id, "cls-hot", item1, observed_at=now, has_real_rank=True, db_path=db_file)
    store.upsert_observation(run_id, "rss-semi", item2, observed_at=now, has_real_rank=False, db_path=db_file)
    store.upsert_observation(run_id, "standalone-deep", item3, observed_at=now, has_real_rank=False, db_path=db_file)
    store.record_source_run(run_id, "cls-hot", status="ok", item_count=1, db_path=db_file)
    store.record_source_run(run_id, "rss-semi", status="ok", item_count=1, db_path=db_file)
    store.record_source_run(run_id, "standalone-deep", status="ok", item_count=1, db_path=db_file)
    store.finish_run(run_id, status=store.RUN_STATUS_OK, source_ok=3, source_failed=0, item_seen=3, item_new=3, db_path=db_file)

    # Set AI config to cli-codex
    store.update_native_intel_config({
        "ai_analysis_provider": "cli-codex",
        "ai_analysis_model": "gpt-5-codex",
        "ai_analysis_region_enabled": True,
    }, db_file)

    return db_file


def _check_codex_available() -> bool:
    try:
        import agent_runtime
        st = agent_runtime.status()
        return bool(st.get("available") and st.get("authenticated"))
    except Exception:
        return False


def test_vertical_proof_real_ai_and_agent_tools(proof_db):
    codex_ready = _check_codex_available()
    print(f"\n[VERTICAL PROOF] Codex Subscription Runtime Ready: {codex_ready}")

    if not codex_ready:
        pytest.skip("Codex Subscription runtime (http://127.0.0.1:8911) is not running or available")

    # 1. Real AI Deep Analysis
    print("\n--- 1. Testing Real AI Deep Analysis ---")
    analysis_res = service.analyze_ai_report(
        mode="CURRENT",
        scope="all",
        max_news=10,
        include_rss=True,
        include_standalone=True,
        path=proof_db,
    )

    print(f"Artifact ID: {analysis_res.get('artifact_id')}")
    print(f"Status: {analysis_res.get('status')}")
    print(f"Provider: {analysis_res.get('provider')}")
    print(f"Model: {analysis_res.get('model')}")
    print(f"Counts: {analysis_res.get('counts')}")
    assert analysis_res["status"] in ("SUCCESS", "PARTIAL")
    assert analysis_res["artifact_id"].startswith("ai_analysis_")
    assert analysis_res["provider"] == "cli-codex"
    assert "disclaimer" in analysis_res

    # Check persistence in intel_ai_artifacts
    saved = store.get_ai_artifact(analysis_res["artifact_id"], proof_db)
    assert saved is not None
    assert saved["input_fingerprint"] is not None
    assert saved["artifact_kind"] == "analysis"

    # 2. Real AI Translation
    print("\n--- 2. Testing Real AI Translation ---")
    trans_res = service.translate_ai_text(
        text="Data center liquid cooling architecture is evolving rapidly.",
        target_language="Chinese",
        path=proof_db,
    )
    print(f"Translation: {trans_res.get('translated_text')}")
    assert trans_res["status"] == "SUCCESS"
    assert len(trans_res["translated_text"]) > 0
    assert trans_res["original_text"] == "Data center liquid cooling architecture is evolving rapidly."

    # 3. Real AI Entity Extraction
    print("\n--- 3. Testing Real AI Entity Extraction ---")
    entity_res = service.extract_ai_entities(
        text="中芯国际发布财报，先进制程晶圆代工业务稳步提升。",
        path=proof_db,
    )
    print(f"Entities: {entity_res.get('entities')}")
    assert entity_res["status"] == "SUCCESS"
    entities = entity_res.get("entities", [])
    assert len(entities) > 0
    matched_codes = [e.get("resolved_security_code") for e in entities if e.get("name") == "中芯国际"]
    if matched_codes:
        assert "688981" in matched_codes
        print(f"Resolved Security Code: {matched_codes}")

    # 4. Real AI Sentiment Analysis
    print("\n--- 4. Testing Real AI Sentiment Analysis ---")
    sentiment_res = service.analyze_ai_sentiment(
        text="算力需求高景气持续带动供应链订单，核心厂商毛利率超出预期。",
        topic="算力产业链",
        path=proof_db,
    )
    print(f"Sentiment: {sentiment_res.get('sentiment')}, Confidence: {sentiment_res.get('confidence')}")
    assert sentiment_res["status"] == "SUCCESS"
    assert sentiment_res["sentiment"] in ("positive", "negative", "neutral", "controversial", "uncertain")

    # 5. Controlled Agent Tools
    print("\n--- 5. Testing Controlled Agent Tools ---")
    tools = service.get_agent_tools(proof_db)

    # 5a. get_intel_status
    status = tools.get_intel_status()
    assert status["status"] in ("ok", "normal")
    assert "ai" in status
    assert status["ai"]["provider"] == "cli-codex"
    print(f"Agent Tool Status: OK (AI Provider={status['ai']['provider']})")

    # 5b. query_intel
    q_res = tools.query_intel(limit=5)
    assert len(q_res["items"]) >= 3
    print(f"Agent Tool Query Items: {len(q_res['items'])}")

    # 5c. search_intel
    s_res = tools.search_intel("中芯国际")
    assert len(s_res["items"]) >= 1
    assert "中芯国际" in s_res["items"][0]["title"]
    print(f"Agent Tool Search: Found {len(s_res['items'])} items for '中芯国际'")

    # 5d. analyze_intel_trend
    t_res = tools.analyze_intel_trend(keyword="液冷")
    assert t_res["success"] is True
    assert t_res["topic"] == "液冷"
    total_mentions = sum(b["mention_count"] for b in t_res["data"]["trend"])
    assert total_mentions >= 1
    print(f"Agent Tool Trend: Mentions={total_mentions}")

    # 5e. resolve_intel_date_range
    r_res = tools.resolve_intel_date_range("最近7天")
    assert r_res["success"] is True
    assert "start" in r_res["date_range"] and "end" in r_res["date_range"]
    print(f"Agent Tool Resolve Date Range: {r_res['date_range']['start']} to {r_res['date_range']['end']}")

    # 5f. trigger_intel_refresh
    trig_res = tools.trigger_intel_refresh()
    assert trig_res["success"] is True
    assert "run_id" in trig_res
    print(f"Agent Tool Trigger Refresh: run_id={trig_res['run_id']}, status={trig_res['status']}")

    # 6. Verification of ZERO writes to formal investment authority tables
    print("\n--- 6. Verifying ZERO Writes to Formal Investment Authority ---")
    with sqlite3.connect(proof_db) as conn:
        # Check formal entity terms
        cur = conn.cursor()
        cur.execute("SELECT count(*) FROM intel_entity_terms")
        terms_count = cur.fetchone()[0]
        assert terms_count == 0, f"intel_entity_terms should have 0 records, got {terms_count}"

        # Verify no thesis/decision tables were touched (if tables exist)
        tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        for formal_table in ("theses", "thesis_revisions", "trade_records", "positions", "decision_inbox", "watchlists"):
            if formal_table in tables:
                cnt = cur.execute(f"SELECT count(*) FROM {formal_table}").fetchone()[0]
                assert cnt == 0, f"Formal table {formal_table} was written to! Count: {cnt}"

    print("[VERTICAL PROOF] ALL REAL AI & AGENT TOOLS VERIFICATIONS PASSED CLEANLY!")
