"""Backend test suite for TREND-PARITY Wave 3.

Covers all 24 required scenarios:
1. global freshness disabled -> old RSS eligible
2. global enabled + max_age_days=3 -> 1-day RSS visible, 5-day RSS excluded
3. published_at=NULL -> not dropped/hidden by freshness
4. per-feed NULL -> inherit global
5. per-feed 0 -> old RSS visible (disabled per-feed)
6. per-feed 1 -> old RSS excluded
7. raw intel_items -> excluded old item remains in database
8. AI pending RSS -> expired RSS does not call AI
9. keyword filtered RSS -> freshness evaluated before keyword filter
10. standalone RSS -> bypasses keyword/AI, freshness still respected
11. standalone Hotlist -> rank and state preserved
12. region rss=false -> normal RSS hidden, standalone RSS remains
13. region order persistence
14. all regions disabled -> honest empty configuration state
15. crawler proxy enabled -> hotlist transport receives proxy
16. rss proxy enabled + dedicated URL -> RSS uses dedicated proxy
17. rss proxy enabled + rss URL empty -> RSS falls back to crawler proxy URL
18. proxy disabled -> direct connection
19. proxy failure -> source fails, no silent direct fallback
20. credential-bearing proxy -> logs and error_detail do not leak credentials
21. invalid proxy scheme -> explicit validation failure
22. legacy DB migration -> max_age_days column/config added, old data intact
23. source registry sync -> does not overwrite enabled, does not overwrite max_age_days
24. backup/restore -> Wave 3 config survives
"""

from __future__ import annotations

import http.server
import json
import os
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

import native_intel_freshness as freshness
import native_intel_hotlist as hotlist
import native_intel_router as router
import native_intel_service as service
import native_intel_store as store
import vibe_data_backup


@pytest.fixture
def test_db(tmp_path: Path) -> Path:
    db_file = tmp_path / "test_intel.sqlite3"
    store.initialize_store(db_file)
    return db_file

def _insert_item(
    path: Path,
    source_id: str,
    item_key: str,
    title: str,
    published_at: str | None = None,
    published_ts: int | None = None,
    rank: int | None = None,
    summary: str = "",
    url: str | None = None,
    has_real_rank: bool = False,
) -> int:
    run_id = f"run_{source_id}_{abs(hash(item_key)) % 100000}"
    store.start_run(run_id, "test", 1, path)
    item_dict = {
        "item_key": item_key,
        "canonical_url": url or f"https://example.com/{item_key}",
        "url": url or f"https://example.com/{item_key}",
        "title": title,
        "title_key": title,
        "summary": summary,
        "hint": "macro",
        "published_at": published_at,
        "published_ts": published_ts,
        "rank": rank,
    }
    item_id, _ = store.upsert_observation(
        run_id,
        source_id,
        item_dict,
        observed_at=service.utc_now_iso(),
        has_real_rank=has_real_rank,
        db_path=path,
    )
    store.record_source_run(
        run_id,
        source_id,
        status=store.SOURCE_RUN_OK,
        item_count=1,
        db_path=path,
    )
    store.finish_run(
        run_id,
        status=store.RUN_STATUS_OK,
        source_ok=1,
        source_failed=0,
        item_seen=1,
        item_new=1,
        db_path=path,
    )
    return item_id



@pytest.fixture
def client(test_db: Path, monkeypatch) -> TestClient:
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(router.router)
    monkeypatch.setattr(router, "_db_path", lambda: str(test_db))
    monkeypatch.setattr(service, "db_path", lambda: str(test_db))
    return TestClient(app)


# ---------------------------------------------------------------------------
# Test 1-6: Freshness Evaluator Unit & Combinations
# ---------------------------------------------------------------------------


def test_scenario_01_global_freshness_disabled():
    """1. global freshness disabled -> old RSS eligible."""
    now = datetime(2026, 9, 5, 12, 0, 0, tzinfo=timezone.utc)
    old_time = (now - timedelta(days=10)).isoformat()
    res = freshness.evaluate_freshness(
        source_type="rss",
        published_at=old_time,
        global_enabled=False,
        global_max_age_days=3,
        now=now,
    )
    assert res.eligible is True
    assert res.reason == freshness.REASON_FRESHNESS_DISABLED


def test_scenario_02_global_enabled_fresh_and_expired():
    """2. global enabled + max_age_days=3 -> 1-day RSS visible, 5-day RSS excluded."""
    now = datetime(2026, 9, 5, 12, 0, 0, tzinfo=timezone.utc)
    one_day_ago = (now - timedelta(days=1)).isoformat()
    five_days_ago = (now - timedelta(days=5)).isoformat()

    fresh_res = freshness.evaluate_freshness(
        source_type="rss",
        published_at=one_day_ago,
        global_enabled=True,
        global_max_age_days=3,
        now=now,
    )
    assert fresh_res.eligible is True
    assert fresh_res.reason == freshness.REASON_FRESH

    expired_res = freshness.evaluate_freshness(
        source_type="rss",
        published_at=five_days_ago,
        global_enabled=True,
        global_max_age_days=3,
        now=now,
    )
    assert expired_res.eligible is False
    assert expired_res.reason == freshness.REASON_EXPIRED


def test_scenario_03_published_at_unknown_not_dropped():
    """3. published_at=NULL -> 不因 freshness 被删除/隐藏."""
    now = datetime(2026, 9, 5, 12, 0, 0, tzinfo=timezone.utc)
    res_none = freshness.evaluate_freshness(
        source_type="rss",
        published_at=None,
        published_ts=0,
        global_enabled=True,
        global_max_age_days=3,
        now=now,
    )
    assert res_none.eligible is True
    assert res_none.reason == freshness.REASON_PUBLISHED_AT_UNKNOWN

    res_unparseable = freshness.evaluate_freshness(
        source_type="rss",
        published_at="invalid-date-format-string",
        published_ts=0,
        global_enabled=True,
        global_max_age_days=3,
        now=now,
    )
    assert res_unparseable.eligible is True
    assert res_unparseable.reason == freshness.REASON_PUBLISHED_AT_UNKNOWN


def test_scenario_04_per_feed_null_inherits_global():
    """4. per-feed NULL -> inherit global."""
    now = datetime(2026, 9, 5, 12, 0, 0, tzinfo=timezone.utc)
    two_days_ago = (now - timedelta(days=2)).isoformat()
    four_days_ago = (now - timedelta(days=4)).isoformat()

    # global max_age_days = 3
    res_2d = freshness.evaluate_freshness(
        source_type="rss",
        published_at=two_days_ago,
        source_max_age_days=None,
        global_enabled=True,
        global_max_age_days=3,
        now=now,
    )
    assert res_2d.eligible is True
    assert res_2d.effective_max_age_days == 3

    res_4d = freshness.evaluate_freshness(
        source_type="rss",
        published_at=four_days_ago,
        source_max_age_days=None,
        global_enabled=True,
        global_max_age_days=3,
        now=now,
    )
    assert res_4d.eligible is False
    assert res_4d.effective_max_age_days == 3


def test_scenario_05_per_feed_zero_disables_freshness():
    """5. per-feed 0 -> old RSS visible."""
    now = datetime(2026, 9, 5, 12, 0, 0, tzinfo=timezone.utc)
    thirty_days_ago = (now - timedelta(days=30)).isoformat()
    res = freshness.evaluate_freshness(
        source_type="rss",
        published_at=thirty_days_ago,
        source_max_age_days=0,
        global_enabled=True,
        global_max_age_days=3,
        now=now,
    )
    assert res.eligible is True
    assert res.reason == freshness.REASON_FEED_FRESHNESS_DISABLED


def test_scenario_06_per_feed_positive_overrides_global():
    """6. per-feed 1 -> old RSS excluded even if global is 3."""
    now = datetime(2026, 9, 5, 12, 0, 0, tzinfo=timezone.utc)
    two_days_ago = (now - timedelta(days=2)).isoformat()

    res = freshness.evaluate_freshness(
        source_type="rss",
        published_at=two_days_ago,
        source_max_age_days=1,
        global_enabled=True,
        global_max_age_days=5,
        now=now,
    )
    assert res.eligible is False
    assert res.effective_max_age_days == 1
    assert res.reason == freshness.REASON_EXPIRED


# ---------------------------------------------------------------------------
# Test 7-14: Storage Decoupling, AI/Keyword Filtering, Standalone & Display
# ---------------------------------------------------------------------------


def test_scenario_07_raw_intel_items_preserves_expired_item(test_db: Path):
    """7. raw intel_items -> excluded old item remains in database."""
    now = datetime.now(timezone.utc)
    old_time = (now - timedelta(days=10)).isoformat()
    old_ts = int((now - timedelta(days=10)).timestamp())

    # Insert a source
    store.insert_user_source(
        source_id="rss-test-feed",
        name="测试RSS",
        url="https://example.com/rss.xml",
        hint="macro",
        db_path=test_db,
    )
    # Ingest old item into intel_items
    item_key = "rss-test-feed:https://example.com/item1"
    _insert_item(
        test_db,
        source_id="rss-test-feed",
        item_key=item_key,
        title="十天前的宏观研报",
        summary="详细内容",
        published_at=old_time,
        published_ts=old_ts,
        url="https://example.com/item1",
    )

    # Enable global freshness with 3 days
    store.update_native_intel_config(
        {"rss_freshness_enabled": True, "rss_global_max_age_days": 3},
        db_path=test_db,
    )

    # list_filtered_items should exclude the item from display
    filtered = service.list_filtered_items("default", source_type="rss", mode="all", path=str(test_db))
    assert len(filtered["items"]) == 0
    assert filtered["filter_meta"]["freshness_excluded_count"] >= 1

    # But raw items query still has it!
    raw_rows, total = store.query_items(test_db)
    assert total >= 1
    assert any(r["item_key"] == item_key for r in raw_rows)


def test_scenario_08_ai_pending_rss_does_not_call_ai_for_expired(test_db: Path):
    """8. AI pending RSS -> expired RSS does not call AI."""
    now = datetime.now(timezone.utc)
    old_time = (now - timedelta(days=10)).isoformat()
    old_ts = int((now - timedelta(days=10)).timestamp())

    store.insert_user_source(
        source_id="rss-ai-feed",
        name="AI测试源",
        url="https://example.com/ai-rss.xml",
        hint="tech",
        db_path=test_db,
    )
    _insert_item(
        test_db,
        source_id="rss-ai-feed",
        item_key="rss-ai-feed:https://example.com/item-old",
        title="过期旧闻不应调用AI",
        summary="摘要",
        published_at=old_time,
        published_ts=old_ts,
        url="https://example.com/item-old",
    )

    store.update_native_intel_config(
        {"rss_freshness_enabled": True, "rss_global_max_age_days": 3},
        db_path=test_db,
    )

    mock_runner = MagicMock()
    # Configure profile with tags
    service.get_filter_profile("default", str(test_db))
    service.update_filter_profile(
        "default",
        {
            "method": "ai",
            "tags": [{"id": 1, "tag": "半导体", "description": "芯片半导体"}],
        },
        path=str(test_db),
    )

    res = service.classify_items(
        profile_id="default",
        path=str(test_db),
        model_runner=mock_runner,
    )
    # Expired RSS was excluded prior to AI classification, so model_runner was never invoked
    assert mock_runner.call_count == 0


def test_scenario_09_keyword_filtered_rss_freshness_first(test_db: Path):
    """9. keyword filtered RSS -> freshness precedes display filter."""
    now = datetime.now(timezone.utc)
    old_time = (now - timedelta(days=10)).isoformat()
    old_ts = int((now - timedelta(days=10)).timestamp())

    store.insert_user_source(
        source_id="rss-kw-feed",
        name="关键词源",
        url="https://example.com/kw.xml",
        hint="tech",
        db_path=test_db,
    )
    _insert_item(
        test_db,
        source_id="rss-kw-feed",
        item_key="rss-kw-feed:https://example.com/item-kw",
        title="人形机器人取得重大突破",
        summary="技术突破",
        published_at=old_time,
        published_ts=old_ts,
        url="https://example.com/item-kw",
    )

    # Enable keyword rule matching "机器人"
    service.get_filter_profile("default", str(test_db))
    service.update_filter_profile(
        "default",
        {
            "method": "keyword",
            "keyword_rules": {
                "groups": [{"name": "具身智能", "includes": ["机器人"]}],
            },
        },
        path=str(test_db),
    )

    # With freshness enabled (max_age=3), 10-day article is excluded despite matching keyword
    store.update_native_intel_config(
        {"rss_freshness_enabled": True, "rss_global_max_age_days": 3},
        db_path=test_db,
    )

    out = service.list_filtered_items("default", source_type="rss", mode="my_interests", path=str(test_db))
    assert len(out["items"]) == 0
    assert out["filter_meta"]["freshness_excluded_count"] >= 1


def test_scenario_10_standalone_rss_bypasses_filter_respects_freshness(test_db: Path):
    """10. standalone RSS -> bypass keyword/AI, freshness still applies."""
    now = datetime.now(timezone.utc)
    one_day_ago = (now - timedelta(days=1)).isoformat()
    one_day_ts = int((now - timedelta(days=1)).timestamp())
    ten_days_ago = (now - timedelta(days=10)).isoformat()
    ten_days_ts = int((now - timedelta(days=10)).timestamp())

    store.insert_user_source(
        source_id="rss-standalone-feed",
        name="重点独立RSS",
        url="https://example.com/st.xml",
        hint="macro",
        db_path=test_db,
    )
    _insert_item(
        test_db,
        source_id="rss-standalone-feed",
        item_key="rss-standalone-feed:https://example.com/st-fresh",
        title="完全不含敏感词的新鲜宏观文章",
        summary="摘要",
        published_at=one_day_ago,
        published_ts=one_day_ts,
        url="https://example.com/st-fresh",
    )
    _insert_item(
        test_db,
        source_id="rss-standalone-feed",
        item_key="rss-standalone-feed:https://example.com/st-old",
        title="完全不含敏感词的十天前宏观文章",
        summary="摘要",
        published_at=ten_days_ago,
        published_ts=ten_days_ts,
        url="https://example.com/st-old",
    )

    # Config: standalone enabled, selecting rss-standalone-feed
    store.update_native_intel_config(
        {
            "rss_freshness_enabled": True,
            "rss_global_max_age_days": 3,
            "standalone_enabled": True,
            "standalone_source_ids": ["rss-standalone-feed"],
            "standalone_max_items": 20,
        },
        db_path=test_db,
    )

    # Keyword filter for "机器人"
    service.update_filter_profile(
        "default",
        {
            "method": "keyword",
            "keyword_rules": {
                "groups": [{"name": "具身智能", "includes": ["机器人"]}],
            },
        },
        path=str(test_db),
    )

    # 1. Normal "my_interests" view filters out fresh article because it does not match "机器人"
    my_interests = service.list_filtered_items("default", source_type="rss", mode="my_interests", path=str(test_db))
    assert len(my_interests["items"]) == 0

    # 2. Standalone view bypasses keyword filter -> fresh article appears!
    # But respects freshness -> 10-day article is excluded!
    st_res = service.get_standalone_items(str(test_db))
    assert st_res["status"] == "normal"
    assert len(st_res["items"]) == 1
    assert st_res["items"][0]["title"] == "完全不含敏感词的新鲜宏观文章"
    assert st_res["freshness_excluded_count"] == 1


def test_scenario_11_standalone_hotlist_preserves_rank_and_state(test_db: Path):
    """11. standalone Hotlist -> rank/state preserved."""
    # Insert a hotlist item with rank
    store.upsert_sources(
        [
            {
                "source_id": "cls-hot",
                "name": "财联社热门",
                "hint": "macro",
                "url": "https://example.com/cls",
                "source_type": "hotlist",
                "has_real_rank": True,
            }
        ],
        test_db,
    )
    item_id = _insert_item(
        test_db,
        source_id="cls-hot",
        item_key="cls-hot:item-1",
        title="A股全线大涨创阶段新高",
        summary="",
        published_at=None,
        published_ts=0,
        rank=1,
        url="https://cls.cn/1",
        has_real_rank=True,
    )

    store.update_native_intel_config(
        {
            "standalone_enabled": True,
            "standalone_source_ids": ["cls-hot"],
            "standalone_max_items": 20,
        },
        db_path=test_db,
    )

    st_res = service.get_standalone_items(str(test_db))
    assert st_res["status"] == "normal"
    assert len(st_res["items"]) >= 1
    item = st_res["items"][0]
    assert item["rank"] == 1
    assert item["current_state"] == "ON_LIST"


def test_scenario_12_region_rss_false_preserves_standalone_rss(client: TestClient, test_db: Path):
    """12. region rss=false -> normal RSS hidden, standalone RSS remains."""
    now = datetime.now(timezone.utc)
    fresh_time = (now - timedelta(hours=2)).isoformat()
    fresh_ts = int((now - timedelta(hours=2)).timestamp())

    store.insert_user_source(
        source_id="rss-standalone-source",
        name="重点RSS源",
        url="https://example.com/rss-s.xml",
        hint="macro",
        db_path=test_db,
    )
    _insert_item(
        test_db,
        source_id="rss-standalone-source",
        item_key="rss-standalone-source:https://example.com/s-1",
        title="重要宏观产业规划发布",
        summary="",
        published_at=fresh_time,
        published_ts=fresh_ts,
        url="https://example.com/s-1",
    )

    # Put config: regions_enabled rss=False, standalone=True
    cfg_res = client.put(
        "/api/native-intel/config",
        json={
            "standalone_enabled": True,
            "standalone_source_ids": ["rss-standalone-source"],
            "regions_enabled": {"rss": False, "standalone": True, "hotlist": True},
        },
    )
    assert cfg_res.status_code == 200

    # Standalone endpoint returns the RSS item
    st_res = client.get("/api/native-intel/standalone").json()
    assert st_res["status"] == "normal"
    assert len(st_res["items"]) == 1
    assert st_res["items"][0]["title"] == "重要宏观产业规划发布"

    # Display status reflects rss is disabled
    stat = client.get("/api/native-intel/status").json()
    assert stat["display"]["regions_enabled"]["rss"] is False
    assert stat["display"]["regions_enabled"]["standalone"] is True


def test_scenario_13_region_order_persistence(client: TestClient):
    """13. region order persistence."""
    custom_order = ["standalone", "rss", "hotlist"]
    res = client.put("/api/native-intel/config", json={"region_order": custom_order})
    assert res.status_code == 200
    assert res.json()["region_order"] == custom_order

    # Read back via GET
    get_res = client.get("/api/native-intel/config")
    assert get_res.status_code == 200
    assert get_res.json()["region_order"] == custom_order


def test_scenario_14_all_regions_disabled_honest_state(client: TestClient):
    """14. all regions disabled -> honest empty configuration state."""
    res = client.put(
        "/api/native-intel/config",
        json={
            "regions_enabled": {
                "hotlist": False,
                "rss": False,
                "standalone": False,
            }
        },
    )
    assert res.status_code == 200
    re = res.json()["regions_enabled"]
    assert re["hotlist"] is False
    assert re["rss"] is False
    assert re["standalone"] is False

    stat = client.get("/api/native-intel/status").json()
    assert stat["display"]["regions_enabled"]["hotlist"] is False
    assert stat["display"]["regions_enabled"]["rss"] is False
    assert stat["display"]["regions_enabled"]["standalone"] is False


# ---------------------------------------------------------------------------
# Test 15-21: Proxy Resolver, Transport Wiring, Redaction & Validation
# ---------------------------------------------------------------------------


def test_scenario_15_crawler_proxy_enabled_transport_wiring(test_db: Path, monkeypatch):
    """15. crawler proxy enabled -> hotlist transport receives proxy."""
    store.update_native_intel_config(
        {
            "crawler_proxy_enabled": True,
            "crawler_proxy_url": "http://127.0.0.1:8899",
        },
        db_path=test_db,
    )
    cfg = store.get_native_intel_config(test_db)
    resolved = store.resolve_crawler_proxy(cfg)
    assert resolved == "http://127.0.0.1:8899"

    # Verify that hotlist.fetch_hotlist_items passes proxy_url to _http_get_json
    mock_get = MagicMock(return_value={"status": "success", "items": []})
    monkeypatch.setattr(hotlist, "_http_get_json", mock_get)

    src = {
        "source_id": "cls-hot",
        "name": "财联社热门",
        "url": "https://newsnow.busiyi.world/api/s?id=cls-hot&latest",
        "source_type": "hotlist",
    }
    hotlist.fetch_hotlist_items(src, timeout=5, redline=[], proxy_url=resolved)
    mock_get.assert_called_once()
    assert mock_get.call_args[1]["proxy_url"] == "http://127.0.0.1:8899"


def test_scenario_16_rss_proxy_enabled_dedicated_url(test_db: Path):
    """16. rss proxy enabled + dedicated URL -> RSS uses dedicated proxy."""
    store.update_native_intel_config(
        {
            "crawler_proxy_enabled": True,
            "crawler_proxy_url": "http://127.0.0.1:7001",
            "rss_proxy_enabled": True,
            "rss_proxy_url": "http://127.0.0.1:7002",
        },
        db_path=test_db,
    )
    cfg = store.get_native_intel_config(test_db)
    resolved = store.resolve_rss_proxy(cfg)
    assert resolved == "http://127.0.0.1:7002"


def test_scenario_17_rss_proxy_fallback_to_crawler(test_db: Path):
    """17. rss proxy enabled + rss URL empty -> uses crawler proxy URL."""
    store.update_native_intel_config(
        {
            "crawler_proxy_enabled": True,
            "crawler_proxy_url": "http://127.0.0.1:8080",
            "rss_proxy_enabled": True,
            "rss_proxy_url": "",
        },
        db_path=test_db,
    )
    cfg = store.get_native_intel_config(test_db)
    resolved = store.resolve_rss_proxy(cfg)
    assert resolved == "http://127.0.0.1:8080"


def test_scenario_18_proxy_disabled_returns_none(test_db: Path):
    """18. proxy disabled -> direct (resolved is None)."""
    store.update_native_intel_config(
        {
            "crawler_proxy_enabled": False,
            "crawler_proxy_url": "http://127.0.0.1:8080",
            "rss_proxy_enabled": False,
            "rss_proxy_url": "http://127.0.0.1:8081",
        },
        db_path=test_db,
    )
    cfg = store.get_native_intel_config(test_db)
    assert store.resolve_crawler_proxy(cfg) is None
    assert store.resolve_rss_proxy(cfg) is None


def test_scenario_19_proxy_failure_isolation_and_no_silent_fallback(test_db: Path, monkeypatch):
    """19. proxy failure -> source fails, no silent direct fallback."""
    # Point proxy to a non-existent port on localhost
    bad_proxy = "http://127.0.0.1:59999"
    src = {
        "source_id": "rss-proxy-fail",
        "name": "代理失败源",
        "url": "http://example.com/rss.xml",
        "source_type": "rss",
    }
    # When proxy fails to connect, urllib raises URLError
    items, kind, detail = service._fetch_source_items(
        src, per=5, cutoff=None, redline=[], proxy_url=bad_proxy
    )
    # Must record network error kind, empty items, and NEVER secretly fallback to direct!
    assert len(items) == 0
    assert kind == store.ERROR_KIND_NETWORK
    assert "URLError" in str(detail) or "OSError" in str(detail) or "TimeoutError" in str(detail)


def test_scenario_20_credential_bearing_proxy_redaction(test_db: Path):
    """20. credential-bearing proxy -> logs / error_detail do not leak credentials."""
    raw_proxy = "http://admin:SecretPassword123@proxy.internal.corp:8080"
    redacted = store.redact_proxy_url(raw_proxy)
    assert "SecretPassword123" not in redacted
    assert redacted == "http://admin:***@proxy.internal.corp:8080"

    store.update_native_intel_config(
        {
            "crawler_proxy_enabled": True,
            "crawler_proxy_url": raw_proxy,
        },
        db_path=test_db,
    )
    stat = service.status(str(test_db))
    # /status exposes redacted proxy URL
    c_info = stat["proxies"]["crawler_proxy"]
    assert c_info["configured"] is True
    assert "SecretPassword123" not in c_info["url"]
    assert "***" in c_info["url"]


def test_scenario_21_invalid_proxy_scheme_rejected(client: TestClient):
    """21. invalid proxy scheme -> explicit validation failure."""
    res_socks = client.put(
        "/api/native-intel/config",
        json={"crawler_proxy_url": "socks5://127.0.0.1:1080"},
    )
    assert res_socks.status_code == 422
    assert "UNSUPPORTED_PROXY_SCHEME" in res_socks.text

    res_ftp = client.put(
        "/api/native-intel/config",
        json={"rss_proxy_url": "ftp://127.0.0.1:21"},
    )
    assert res_ftp.status_code == 422
    assert "UNSUPPORTED_PROXY_SCHEME" in res_ftp.text


# ---------------------------------------------------------------------------
# Test 22-24: Legacy DB Migration, Sync Registry & Backup/Restore
# ---------------------------------------------------------------------------


def test_scenario_22_legacy_db_migration(tmp_path: Path):
    """22. legacy DB migration -> max_age_days column/config added, old data intact."""
    legacy_db = tmp_path / "legacy_intel.sqlite3"
    # Create DB with legacy schema without max_age_days
    with sqlite3.connect(str(legacy_db)) as conn:
        conn.executescript(
            """
            CREATE TABLE intel_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE intel_sources (
                source_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                hint TEXT NOT NULL,
                url TEXT NOT NULL,
                source_type TEXT NOT NULL,
                has_real_rank INTEGER NOT NULL DEFAULT 0,
                enabled INTEGER NOT NULL DEFAULT 1,
                origin TEXT NOT NULL DEFAULT 'system',
                updated_at TEXT NOT NULL,
                deleted_at TEXT,
                re_enabled_at TEXT,
                re_enabled_after_run_id TEXT
            );
            CREATE TABLE intel_items (
                item_id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_key TEXT NOT NULL UNIQUE,
                canonical_url TEXT NOT NULL,
                url TEXT NOT NULL,
                title TEXT NOT NULL,
                title_key TEXT NOT NULL,
                summary TEXT,
                source_id TEXT NOT NULL,
                hint TEXT NOT NULL,
                published_at TEXT,
                published_ts INTEGER NOT NULL DEFAULT 0,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                observation_count INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            );
            INSERT INTO intel_sources (source_id, name, hint, url, source_type, updated_at)
            VALUES ('legacy-src', '遗留老源', 'macro', 'https://example.com/feed', 'rss', '2026-09-01T00:00:00Z');
            INSERT INTO intel_items (item_key, canonical_url, url, title, title_key, source_id, hint, first_seen_at, last_seen_at, created_at)
            VALUES ('k1', 'https://example.com/1', 'https://example.com/1', '遗留老文章', '遗留老文章', 'legacy-src', 'macro', '2026-09-01T00:00:00Z', '2026-09-01T00:00:00Z', '2026-09-01T00:00:00Z');
            """
        )

    # Initialize / migrate
    store.initialize_store(legacy_db)

    # Verify column exists and old data intact
    with sqlite3.connect(str(legacy_db)) as conn:
        conn.row_factory = sqlite3.Row
        cols = {str(r["name"]) for r in conn.execute("PRAGMA table_info(intel_sources)")}
        assert "max_age_days" in cols

        src = conn.execute("SELECT * FROM intel_sources WHERE source_id = 'legacy-src'").fetchone()
        assert src is not None
        assert src["name"] == "遗留老源"
        assert src["max_age_days"] is None

        it = conn.execute("SELECT * FROM intel_items WHERE item_key = 'k1'").fetchone()
        assert it is not None
        assert it["title"] == "遗留老文章"


def test_scenario_23_source_registry_sync_preserves_overrides(test_db: Path):
    """23. source registry sync -> does not overwrite enabled, does not overwrite max_age_days."""
    # Seed a source
    seed_sources = [
        {
            "source_id": "seed-feed-1",
            "name": "种子源",
            "hint": "tech",
            "url": "https://example.com/seed.xml",
            "source_type": "rss",
        }
    ]
    store.upsert_sources(seed_sources, test_db)

    # User modifies enabled and max_age_days
    store.update_source("seed-feed-1", enabled=False, max_age_days=5, db_path=test_db)
    src_before = store.get_source("seed-feed-1", test_db)
    assert src_before["enabled"] == 0
    assert src_before["max_age_days"] == 5

    # Re-sync sources
    store.upsert_sources(seed_sources, test_db)

    # Must NOT overwrite user overrides!
    src_after = store.get_source("seed-feed-1", test_db)
    assert src_after["enabled"] == 0
    assert src_after["max_age_days"] == 5


def test_scenario_24_backup_restore_preserves_wave3_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """24. backup/restore -> Wave 3 config survives."""
    import sqlite3

    data = tmp_path / "data"
    data.mkdir()
    review = tmp_path / "review" / "daily_reviews.sqlite3"
    reports = tmp_path / "reports"
    fact = tmp_path / "fact-lake"
    research = data / "research_data_plane"

    reports.mkdir()
    (reports / "report.md").write_text("report", encoding="utf-8")
    research.mkdir()
    (research / "manifest.json").write_text('{"schema_version": 1}', encoding="utf-8")
    (fact / "raw").mkdir(parents=True)
    (fact / "canonical").mkdir()
    (fact / "raw" / "item.json").write_text('{"ok": true}', encoding="utf-8")

    db_file = data / "native_intel.sqlite3"
    store.initialize_store(db_file)

    for p in (review, fact / "control.sqlite3"):
        p.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(p) as conn:
            conn.execute("CREATE TABLE records (value TEXT)")

    # Set Wave 3 config and source max_age_days
    store.insert_user_source(
        source_id="backup-rss",
        name="待备份源",
        url="https://example.com/b.xml",
        hint="macro",
        max_age_days=7,
        db_path=db_file,
    )
    store.update_native_intel_config(
        {
            "rss_freshness_enabled": True,
            "rss_global_max_age_days": 4,
            "crawler_proxy_enabled": True,
            "crawler_proxy_url": "http://127.0.0.1:9999",
            "standalone_enabled": True,
            "standalone_source_ids": ["backup-rss"],
            "region_order": ["standalone", "hotlist", "rss"],
        },
        db_path=db_file,
    )

    monkeypatch.setenv("VR_DATA_DIR", str(data))
    monkeypatch.setenv("VIBE_RESEARCH_REVIEW_DB", str(review))
    monkeypatch.setenv("VR_REPORTS_DIR", str(reports))
    monkeypatch.setenv("VR_FACT_LAKE_ROOT", str(fact))
    monkeypatch.setenv("VIBE_NATIVE_INTEL_DB", str(db_file))

    archive = tmp_path / "complete.zip"
    res = vibe_data_backup.create_bundle(archive, quiescent_probe=lambda: vibe_data_backup.QUIESCENT)
    assert res["status"] == "OK"

    restored = tmp_path / "restored"
    restore_res = vibe_data_backup.restore_bundle(archive, restored)
    assert restore_res["status"] == "OK"

    restored_db = restored / "data" / "native_intel.sqlite3"
    assert restored_db.exists()

    # Read back config and source
    cfg = store.get_native_intel_config(restored_db)
    assert cfg["rss_freshness_enabled"] is True
    assert cfg["rss_global_max_age_days"] == 4
    assert cfg["crawler_proxy_enabled"] is True
    assert cfg["crawler_proxy_url"] == "http://127.0.0.1:9999"
    assert cfg["standalone_source_ids"] == ["backup-rss"]
    assert cfg["region_order"] == ["standalone", "hotlist", "rss"]

    src = store.get_source("backup-rss", restored_db)
    assert src is not None
    assert src["max_age_days"] == 7
