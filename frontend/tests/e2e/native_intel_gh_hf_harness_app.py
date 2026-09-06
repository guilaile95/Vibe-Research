"""Deterministic harness for GitHub Trending + HF Daily Papers Intel display."""
from __future__ import annotations

import os
from datetime import datetime, timezone

import native_intel_router
import native_intel_store as store
from fastapi import FastAPI

DB_PATH = os.environ["VIBE_NATIVE_INTEL_DB"]
NOW = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _seed() -> None:
    store.initialize_store(DB_PATH)
    store.upsert_sources(
        [
            {
                "source_id": "tech-github-trending",
                "name": "GitHub Trending",
                "hint": "tech",
                "url": "https://github.com/trending?since=daily",
                "source_type": "hotlist",
                "has_real_rank": True,
            },
            {
                "source_id": "ai-hugging-face-daily-papers",
                "name": "Hugging Face Daily Papers",
                "hint": "ai",
                "url": "https://huggingface.co/api/daily_papers",
                "source_type": "rss",
                "has_real_rank": False,
            },
            {
                "source_id": "tech-hacker-news",
                "name": "Hacker News",
                "hint": "tech",
                "url": "https://hnrss.org/frontpage",
                "source_type": "rss",
                "has_real_rank": False,
            },
        ],
        DB_PATH,
    )
    store.start_run("gh-hf-e2e", "fixture", 3, DB_PATH)
    store.upsert_observation(
        "gh-hf-e2e",
        "tech-github-trending",
        {
            "item_key": "tech-github-trending:https://github.com/openai/whisper",
            "canonical_url": "https://github.com/openai/whisper",
            "url": "https://github.com/openai/whisper",
            "title": "openai/whisper",
            "title_key": "openai/whisper",
            "summary": "speech recognition",
            "hint": "tech",
            "published_at": None,
            "published_ts": 0,
            "rank": 1,
            "source_facts": {
                "stars_total": 80123,
                "stars_period": 1234,
                "language": "Python",
            },
        },
        observed_at=NOW,
        has_real_rank=True,
        db_path=DB_PATH,
    )
    store.upsert_observation(
        "gh-hf-e2e",
        "ai-hugging-face-daily-papers",
        {
            "item_key": "ai-hugging-face-daily-papers:hf-paper:2001.08361",
            "canonical_url": "https://huggingface.co/papers/2001.08361",
            "url": "https://huggingface.co/papers/2001.08361",
            "title": "Scaling Laws for Neural Language Models",
            "title_key": "scaling laws for neural language models",
            "summary": "We study empirical scaling laws.",
            "hint": "ai",
            "published_at": NOW,
            "published_ts": int(datetime.now(timezone.utc).timestamp()),
            "rank": None,
            "source_facts": {"upvotes": 42, "num_comments": 7},
        },
        observed_at=NOW,
        has_real_rank=False,
        db_path=DB_PATH,
    )
    store.upsert_observation(
        "gh-hf-e2e",
        "tech-hacker-news",
        {
            "item_key": "tech-hacker-news:hn:123456",
            "canonical_url": "https://example.com/article",
            "url": "https://example.com/article",
            "title": "Show HN: Example",
            "title_key": "show hn example",
            "summary": "An example story",
            "hint": "tech",
            "published_at": NOW,
            "published_ts": int(datetime.now(timezone.utc).timestamp()),
            "rank": None,
            "source_facts": {
                "hn_story_id": 123456,
                "score": 321,
                "num_comments": 87,
                "author": "pg",
                "discussion_url": "https://news.ycombinator.com/item?id=123456",
            },
        },
        observed_at=NOW,
        has_real_rank=False,
        db_path=DB_PATH,
    )
    store.record_source_run(
        "gh-hf-e2e", "tech-github-trending", status=store.SOURCE_RUN_OK, item_count=1, db_path=DB_PATH
    )
    store.record_source_run(
        "gh-hf-e2e",
        "ai-hugging-face-daily-papers",
        status=store.SOURCE_RUN_OK,
        item_count=1,
        db_path=DB_PATH,
    )
    store.record_source_run(
        "gh-hf-e2e", "tech-hacker-news", status=store.SOURCE_RUN_OK, item_count=1, db_path=DB_PATH
    )
    store.finish_run(
        "gh-hf-e2e",
        status=store.RUN_STATUS_OK,
        source_ok=3,
        source_failed=0,
        item_seen=3,
        item_new=3,
        db_path=DB_PATH,
    )


_seed()
app = FastAPI(title="Native Intel GH/HF E2E harness")
app.include_router(native_intel_router.router)
