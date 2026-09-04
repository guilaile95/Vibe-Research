"""Deterministic FastAPI harness for Hotlist Parity real browser E2E tests."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI

import native_intel_router
import native_intel_service as service
import native_intel_store as store


DB_PATH = os.environ["VIBE_NATIVE_INTEL_DB"]
NOW = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _seed() -> None:
    reg = service.load_registry()
    hotlists = [s for s in reg["sources"] if s["source_type"] == "hotlist"]
    store.upsert_sources(hotlists, DB_PATH)

    run_id = "hotlist-parity-e2e"
    store.start_run(run_id, "fixture", len(hotlists), DB_PATH)

    seed_items = [
        ("hotlist-cls-hot", "科技股全线走强", "https://cls.cn/detail/101", "半导体与人工智能板块领涨。", 1),
        ("hotlist-weibo", "微博热议人工智能", "https://weibo.com/ai-trend", "全网热议新一代大模型突破。", 2),
        ("hotlist-zhihu", "知乎深度解析芯片突破", "https://zhihu.com/question/semi-breakthrough", "行业专家深度拆解先进制程工艺。", 3),
        ("hotlist-baidu", "百度热搜机器人产业", "https://baidu.com/s?wd=robotics", "智能人形机器人落地进展迅速。", 4),
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


_seed()
service.ensure_directory = lambda _path=None, **_kwargs: {
    "status": service.STATUS_NORMAL,
    "size": 2,
    "synced_at": NOW,
    "note": None,
}

app = FastAPI(title="Hotlist Parity E2E harness")
app.include_router(native_intel_router.router)


@app.post("/api/test/make-stale")
def _make_stale():
    with store._LOCK:
        with store._connect(DB_PATH) as conn:
            with conn:
                old_time = (datetime.now(timezone.utc) - timedelta(hours=8)).strftime("%Y-%m-%dT%H:%M:%SZ")
                conn.execute("UPDATE intel_fetch_runs SET started_at = ?", (old_time,))
    return {"status": "ok"}


@app.post("/api/test/make-fresh")
def _make_fresh():
    with store._LOCK:
        with store._connect(DB_PATH) as conn:
            with conn:
                now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                conn.execute("UPDATE intel_fetch_runs SET started_at = ?", (now,))
    return {"status": "ok"}
