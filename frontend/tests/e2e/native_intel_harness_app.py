"""Deterministic FastAPI harness for the Native Intel rendered vertical."""

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
        {"source_id": "official-rss", "name": "官方 RSS", "hint": "a-share", "url": "https://example.test/official.xml", "source_type": "rss", "has_real_rank": False},
        {"source_id": "failed-rss", "name": "失败测试源", "hint": "macro", "url": "https://example.test/failed.xml", "source_type": "rss", "has_real_rank": False},
    ]
    store.upsert_sources(sources, DB_PATH)
    store.replace_entity_terms(
        "300750",
        [{"term": "固态电池", "term_kind": store.TERM_CONCEPT, "source_ref": "fixture"}],
        DB_PATH,
    )
    store.start_run("native-intel-e2e", "fixture", 2, DB_PATH)
    item_id, _ = store.upsert_observation(
        "native-intel-e2e",
        "official-rss",
        {
            "item_key": "native-e2e-item",
            "canonical_url": "https://example.test/native-intel-item",
            "url": "https://example.test/native-intel-item",
            "title": "固态电池产业化进展加速",
            "title_key": "固态电池产业化进展加速",
            "summary": "宁德时代等产业链公司持续推进固态电池研发。",
            "hint": "a-share",
            "published_at": NOW,
            "published_ts": int(datetime.now(timezone.utc).timestamp()),
            "rank": None,
        },
        observed_at=NOW,
        db_path=DB_PATH,
    )
    service.link_entities_for_items([item_id], DB_PATH)
    store.record_source_run("native-intel-e2e", "official-rss", status=store.SOURCE_RUN_OK, item_count=1, db_path=DB_PATH)
    store.record_source_run("native-intel-e2e", "failed-rss", status=store.SOURCE_RUN_FAILED, error_kind=store.ERROR_KIND_NETWORK, error_detail="URLError", db_path=DB_PATH)
    store.finish_run("native-intel-e2e", status=store.RUN_STATUS_PARTIAL, source_ok=1, source_failed=1, item_seen=1, item_new=1, db_path=DB_PATH)


_seed()
service.ensure_directory = lambda _path=None, **_kwargs: {  # type: ignore[assignment]
    "status": service.STATUS_NORMAL,
    "size": 3,
    "synced_at": NOW,
    "note": None,
}

app = FastAPI(title="Native Intel E2E harness")
app.include_router(native_intel_router.router)
