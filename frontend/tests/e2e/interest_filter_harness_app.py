"""Deterministic FastAPI harness for Personal Interest Filter real browser E2E tests (TREND-PARITY Wave 2)."""

from __future__ import annotations

import os
from datetime import datetime, timezone

from fastapi import FastAPI

import native_intel_filter as filter_engine
import native_intel_router
import native_intel_service as service
import native_intel_store as store


DB_PATH = os.environ["VIBE_NATIVE_INTEL_DB"]
NOW = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _seed() -> None:
    reg = service.load_registry()
    hotlists = [s for s in reg["sources"] if s["source_type"] == "hotlist"]
    store.upsert_sources(hotlists, DB_PATH)

    run_id = "interest-filter-e2e"
    store.start_run(run_id, "fixture", len(hotlists), DB_PATH)

    seed_items = [
        ("hotlist-cls-hot", "科技突破：先进制程半导体量产", "https://cls.cn/detail/201", "半导体芯片制造取得重大进展。", 1),
        ("hotlist-weibo", "微博热议大模型前沿算法发布", "https://weibo.com/ai-202", "新一代AI人工智能大模型推理框架开源。", 2),
        ("hotlist-zhihu", "娱乐圈八卦明星动态", "https://zhihu.com/question/star-203", "当红演员参加巡回演出盛况分享。", 3),
        ("hotlist-baidu", "独家广告赞助大促销活动", "https://baidu.com/s?wd=ad-204", "电商平台年中大促领券优惠活动。", 4),
        ("hotlist-cls-hot", "英伟达发布新一代GPU硬件", "https://cls.cn/detail/205", "英伟达GPU算力硬件正式发布。", 5),
        ("hotlist-cls-hot", "英伟达高管减持股票公告", "https://cls.cn/detail/206", "英伟达最新股东权益变动公告。", 6),
    ]

    for sid, title, url, summary, rank in seed_items:
        store.upsert_observation(
            run_id,
            sid,
            {
                "item_key": f"{sid}:{url}",
                "canonical_url": url,
                "url": url,
                "title": title,
                "title_key": title,
                "summary": summary,
                "hint": "macro",
                "published_at": None,
                "published_ts": 0,
                "rank": rank,
            },
            observed_at=NOW,
            has_real_rank=True,
            db_path=DB_PATH,
        )
        store.record_source_run(
            run_id,
            sid,
            status=store.SOURCE_RUN_OK,
            item_count=1,
            db_path=DB_PATH,
        )

    store.finish_run(
        run_id,
        status=store.RUN_STATUS_OK,
        source_ok=len(seed_items),
        source_failed=0,
        item_seen=len(seed_items),
        item_new=len(seed_items),
        db_path=DB_PATH,
    )

    # Seed RSS source and RSS item
    store.upsert_sources([
        {
            "source_id": "rss-semi-tech",
            "name": "半导体产业快讯",
            "hint": "macro",
            "url": "https://rss.example/semi",
            "source_type": "rss",
            "origin": "user",
            "enabled": True,
            "has_real_rank": False,
        }
    ], DB_PATH)

    with store._connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO intel_items (item_key, canonical_url, url, title, title_key, summary, source_id, hint, published_at, published_ts, first_seen_at, last_seen_at, observation_count, created_at)
            VALUES ('rss-item-1', 'https://rss.example/1', 'https://rss.example/1', 'RSS简讯：半导体芯片智算中心交付', 'rss-item-1', '半导体算力基础设施建设加速', 'rss-semi-tech', 'macro', ?, 0, ?, ?, 1, ?)
            """,
            (NOW, NOW, NOW, NOW),
        )

    # Seed initial keyword profile
    init_profile = {
        "profile_id": "default",
        "name": "default",
        "method": "keyword",
        "interests_text": "专注半导体和AI算力产业链",
        "min_score": 0.6,
        "reclassify_threshold": 0.3,
        "keyword_rules": {
            "groups": [
                {"name": "半导体芯片", "includes": ["半导体", "芯片"], "excludes": []},
                {"name": "AI大模型", "includes": ["大模型", "人工智能"], "excludes": []},
            ],
            "global_excludes": ["广告", "促销"],
        },
        "tags": [
            {"id": 1, "tag": "芯片制造", "description": "先进制程与制造"},
            {"id": 2, "tag": "AI技术", "description": "前沿算法与大模型"},
        ],
    }
    store.upsert_filter_profile(init_profile, DB_PATH)


_seed()
service.ensure_directory = lambda _path=None, **_kwargs: {
    "status": service.STATUS_NORMAL,
    "size": 4,
    "synced_at": NOW,
    "note": None,
}

# Deterministic AI extraction & classification mock for harness (synchronous)
def _mock_extract_interest_tags(interests_text: str, cfg=None, model_runner=None):
    return [
        {"id": 1, "tag": "智能算力", "description": "GPU与智算集群"},
        {"id": 2, "tag": "芯片制造", "description": "先进制程工艺"},
    ]

def _mock_update_interest_tags(old_tags, new_interests_text, cfg=None, model_runner=None):
    new_tags = list(old_tags or []) + [{"id": len(old_tags or []) + 1, "tag": "具身智能", "description": "人形机器人驱动"}]
    return {
        "keep": [t.get("tag") for t in (old_tags or [])],
        "add": [{"tag": "具身智能", "description": "人形机器人驱动"}],
        "remove": [],
        "new_tags": new_tags,
        "change_ratio": 0.25,
    }

def _mock_classify_items_batch(items, tags, interests_text="", cfg=None, batch_size=15, model_runner=None):
    results = []
    not_relevant_ids = []
    for item in items:
        text = f"{item.get('title', '')} {item.get('summary', '')}"
        if "半导体" in text or "芯片" in text:
            results.append({
                "item_id": item["item_id"],
                "relevance_score": 0.92,
                "primary_tag": "芯片制造",
            })
        elif "大模型" in text or "人工智能" in text:
            results.append({
                "item_id": item["item_id"],
                "relevance_score": 0.88,
                "primary_tag": "AI技术",
            })
        else:
            not_relevant_ids.append(item["item_id"])
    return results, not_relevant_ids, []

filter_engine.extract_interest_tags = _mock_extract_interest_tags
filter_engine.update_interest_tags = _mock_update_interest_tags
filter_engine.classify_items_batch = _mock_classify_items_batch

app = FastAPI(title="Interest Filter Parity E2E harness")
app.include_router(native_intel_router.router)
