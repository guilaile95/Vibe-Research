"""Deterministic FastAPI harness for Native Intel Wave 3 Display Controls and Freshness real browser E2E tests."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

_backend_dir = str(Path(__file__).resolve().parents[3] / "backend")
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

from fastapi import FastAPI

import native_intel_filter as filter_engine
import native_intel_router
import native_intel_service as service
import native_intel_store as store

DB_PATH = os.environ.get("VIBE_NATIVE_INTEL_DB", str(Path(__file__).resolve().parents[3] / "vibe_data" / "native_intel.sqlite3"))
now_dt = datetime.now(timezone.utc)
NOW = now_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
ONE_DAY_AGO = (now_dt - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
ONE_DAY_TS = int((now_dt - timedelta(days=1)).timestamp())
FIVE_DAYS_AGO = (now_dt - timedelta(days=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
FIVE_DAYS_TS = int((now_dt - timedelta(days=5)).timestamp())


def _seed() -> None:
    store.initialize_store(DB_PATH)

    # Hotlist source
    store.upsert_sources(
        [
            {
                "source_id": "hotlist-cls-hot",
                "name": "财联社热门",
                "hint": "macro",
                "url": "https://cls.cn/hot",
                "source_type": "hotlist",
                "has_real_rank": True,
                "enabled": True,
            }
        ],
        DB_PATH,
    )

    # RSS sources
    store.insert_user_source(
        source_id="rss-feed-a",
        name="RSS源A",
        url="https://example.com/feed-a.xml",
        hint="macro",
        enabled=True,
        max_age_days=None,
        db_path=DB_PATH,
    )
    store.insert_user_source(
        source_id="rss-feed-b",
        name="RSS源B",
        url="https://example.com/feed-b.xml",
        hint="macro",
        enabled=True,
        max_age_days=None,
        db_path=DB_PATH,
    )
    store.insert_user_source(
        source_id="rss-feed-c",
        name="RSS源C",
        url="https://example.com/feed-c.xml",
        hint="macro",
        enabled=True,
        max_age_days=None,
        db_path=DB_PATH,
    )
    store.insert_user_source(
        source_id="rss-feed-standalone",
        name="重点独立研报",
        url="https://example.com/standalone.xml",
        hint="macro",
        enabled=True,
        max_age_days=None,
        db_path=DB_PATH,
    )

    # Seed observations and items
    run_id = "seed-wave3-run"
    store.start_run(run_id, "fixture", 5, DB_PATH)

    # Hotlist item
    hot_item = {
        "item_key": "hotlist-cls-hot:https://cls.cn/101",
        "canonical_url": "https://cls.cn/101",
        "url": "https://cls.cn/101",
        "title": "A股全天冲高震荡大涨",
        "title_key": "A股全天冲高震荡大涨",
        "summary": "热榜摘要",
        "hint": "macro",
        "published_at": None,
        "published_ts": 0,
        "rank": 1,
    }
    store.upsert_observation(run_id, "hotlist-cls-hot", hot_item, observed_at=NOW, has_real_rank=True, db_path=DB_PATH)
    store.record_source_run(run_id, "hotlist-cls-hot", status=store.SOURCE_RUN_OK, item_count=1, db_path=DB_PATH)

    # RSS items
    rss_items = [
        # Feed A: 1 day ago (fresh under 3-day global)
        ("rss-feed-a", "新鲜宏观动态：科技与产业进展", "https://example.com/a1", ONE_DAY_AGO, ONE_DAY_TS),
        # Feed B: 5 days ago (expired under 3-day global)
        ("rss-feed-b", "五天前宏观简讯：市场回顾", "https://example.com/b1", FIVE_DAYS_AGO, FIVE_DAYS_TS),
        # Feed C: published_at=None (unknown, must not be dropped)
        ("rss-feed-c", "未标注日期的特别快讯", "https://example.com/c1", None, 0),
        # Standalone fresh: 1 day ago, no "机器人" keyword
        ("rss-feed-standalone", "新鲜宏观深度分析报告", "https://example.com/st-fresh", ONE_DAY_AGO, ONE_DAY_TS),
        # Standalone old: 5 days ago, expired under 3-day
        ("rss-feed-standalone", "五天前过期独立文章", "https://example.com/st-old", FIVE_DAYS_AGO, FIVE_DAYS_TS),
    ]

    for sid, title, url, pub_at, pub_ts in rss_items:
        it = {
            "item_key": f"{sid}:{url}",
            "canonical_url": url,
            "url": url,
            "title": title,
            "title_key": title,
            "summary": "详细摘要内容",
            "hint": "macro",
            "published_at": pub_at,
            "published_ts": pub_ts,
            "rank": None,
        }
        store.upsert_observation(run_id, sid, it, observed_at=NOW, has_real_rank=False, db_path=DB_PATH)
        store.record_source_run(run_id, sid, status=store.SOURCE_RUN_OK, item_count=1, db_path=DB_PATH)

    store.finish_run(
        run_id,
        status=store.RUN_STATUS_OK,
        source_ok=5,
        source_failed=0,
        item_seen=len(rss_items) + 1,
        item_new=len(rss_items) + 1,
        db_path=DB_PATH,
    )

    # Initial Wave 3 configuration
    store.update_native_intel_config(
        {
            "rss_freshness_enabled": True,
            "rss_global_max_age_days": 3,
            "standalone_enabled": True,
            "standalone_source_ids": ["rss-feed-standalone"],
            "standalone_max_items": 20,
            "regions_enabled": {"hotlist": True, "rss": True, "standalone": True},
            "region_order": ["hotlist", "rss", "standalone"],
        },
        db_path=DB_PATH,
    )

    # Seed keyword filter with "机器人"
    service.update_filter_profile(
        "default",
        {
            "method": "keyword",
            "keyword_rules": {
                "groups": [{"name": "具身智能", "includes": ["机器人"]}],
            },
        },
        path=DB_PATH,
    )


app = FastAPI(title="Wave3 Display Controls E2E Test Harness")
app.include_router(native_intel_router.router)


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@app.on_event("startup")
def startup() -> None:
    _seed()
