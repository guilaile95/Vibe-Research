"""Deterministic FastAPI harness for Hotlist Parity real browser E2E tests."""

from __future__ import annotations

import os
from datetime import datetime, timezone

from fastapi import FastAPI

import native_intel_router
import native_intel_service as service
import native_intel_store as store


DB_PATH = os.environ["VIBE_NATIVE_INTEL_DB"]
NOW = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _seed() -> None:
    sources = [
        {
            "source_id": "hotlist-cls-hot",
            "name": "财联社热门",
            "hint": "macro",
            "url": "https://newsnow.busiyi.world/api/s?id=cls-hot&latest",
            "source_type": "hotlist",
            "has_real_rank": True,
            "origin": "system",
        },
        {
            "source_id": "hotlist-wallstreetcn-hot",
            "name": "华尔街见闻",
            "hint": "macro",
            "url": "https://newsnow.busiyi.world/api/s?id=wallstreetcn-hot&latest",
            "source_type": "hotlist",
            "has_real_rank": True,
            "origin": "system",
        },
    ]
    store.upsert_sources(sources, DB_PATH)
    store.start_run("hotlist-parity-e2e", "fixture", 2, DB_PATH)
    item_id, _ = store.upsert_observation(
        "hotlist-parity-e2e",
        "hotlist-cls-hot",
        {
            "item_key": "hotlist-cls-hot:https://www.cls.cn/detail/101",
            "canonical_url": "https://www.cls.cn/detail/101",
            "url": "https://www.cls.cn/detail/101",
            "title": "科技股全线走强",
            "title_key": "科技股全线走强",
            "summary": "半导体与人工智能板块领涨。",
            "hint": "macro",
            "published_at": None,
            "published_ts": 0,
            "rank": 1,
        },
        observed_at=NOW,
        has_real_rank=True,
        db_path=DB_PATH,
    )
    store.record_source_run(
        "hotlist-parity-e2e",
        "hotlist-cls-hot",
        status=store.SOURCE_RUN_OK,
        item_count=1,
        db_path=DB_PATH,
    )
    store.finish_run(
        "hotlist-parity-e2e",
        status=store.RUN_STATUS_OK,
        source_ok=1,
        source_failed=0,
        item_seen=1,
        item_new=1,
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
