"""GitHub Trending + HF Daily Papers: parse, history, failure != empty."""

from __future__ import annotations

import json
from pathlib import Path

import native_intel_ext_sources as ext
import native_intel_store as store

FIXTURES = Path(__file__).parent / "fixtures"
GH_SOURCE = {
    "source_id": "tech-github-trending",
    "name": "GitHub Trending",
    "hint": "tech",
    "url": "https://github.com/trending?since=daily",
    "source_type": "hotlist",
    "has_real_rank": True,
}
HF_SOURCE = {
    "source_id": "ai-hugging-face-daily-papers",
    "name": "Hugging Face Daily Papers",
    "hint": "ai",
    "url": "https://huggingface.co/api/daily_papers",
    "source_type": "rss",
    "has_real_rank": False,
}


def test_github_trending_parses_repos_filters_sponsored_and_ranks():
    html = (FIXTURES / "github_trending_sample.html").read_text(encoding="utf-8")
    items, kind, detail = ext.parse_github_trending_html(html, GH_SOURCE, redline=[])
    assert kind is None and detail is None
    assert [it["title"] for it in items] == ["openai/whisper", "vercel/next.js"]
    assert [it["rank"] for it in items] == [1, 2]
    facts = items[0]["source_facts"]
    assert facts["stars_period"] == 1234
    assert facts["stars_total"] == 80123
    assert facts["language"] == "Python"
    assert "ads/not-a-repo" not in [it["title"] for it in items]

    bad, kind, detail = ext.parse_github_trending_html("<html><body>nope</body></html>", GH_SOURCE, [])
    assert bad == []
    assert kind == store.ERROR_KIND_PARSE
    assert kind != store.SOURCE_RUN_EMPTY


def test_hf_daily_papers_parses_identity_facts_and_null_rank():
    payload = json.loads((FIXTURES / "hf_daily_papers_sample.json").read_text(encoding="utf-8"))
    items, kind, detail = ext.parse_hf_daily_papers(payload, HF_SOURCE, redline=[])
    assert kind is None and detail is None
    assert len(items) == 1
    item = items[0]
    assert item["rank"] is None
    assert item["title"] == "Scaling Laws for Neural Language Models"
    assert "2001.08361" in item["item_key"]
    assert "Jared Kaplan" in item["summary"]
    facts = item["source_facts"]
    assert facts["upvotes"] == 42
    assert facts["num_comments"] == 7
    assert facts["github_repo"] == "openai/scaling-laws"
    assert "ai_summary" not in facts

    bad, kind, detail = ext.parse_hf_daily_papers({"not": "a list"}, HF_SOURCE, [])
    assert bad == []
    assert kind == store.ERROR_KIND_PARSE


def test_source_facts_history_preserves_observations(tmp_path: Path):
    db = tmp_path / "facts.sqlite3"
    store.initialize_store(db)
    store.upsert_sources([GH_SOURCE], db)
    item = {
        "item_key": "tech-github-trending:https://github.com/openai/whisper",
        "canonical_url": "https://github.com/openai/whisper",
        "url": "https://github.com/openai/whisper",
        "title": "openai/whisper",
        "title_key": "openai/whisper",
        "summary": "speech",
        "hint": "tech",
        "published_at": None,
        "published_ts": 0,
        "rank": 1,
        "source_facts": {"stars_total": 100, "stars_period": 10, "language": "Python"},
    }
    store.start_run("run-a", "test", 1, db, started_at="2026-01-01T00:00:00Z")
    store.upsert_observation("run-a", GH_SOURCE["source_id"], item, observed_at="2026-01-01T00:00:00Z", has_real_rank=True, db_path=db)
    store.finish_run("run-a", status=store.RUN_STATUS_OK, source_ok=1, source_failed=0, item_seen=1, item_new=1, db_path=db)

    item_b = dict(item)
    item_b["source_facts"] = {"stars_total": 150, "stars_period": 12, "language": "Python"}
    store.start_run("run-b", "test", 1, db, started_at="2026-01-02T00:00:00Z")
    store.upsert_observation("run-b", GH_SOURCE["source_id"], item_b, observed_at="2026-01-02T00:00:00Z", has_real_rank=True, db_path=db)
    store.finish_run("run-b", status=store.RUN_STATUS_OK, source_ok=1, source_failed=0, item_seen=1, item_new=0, db_path=db)

    store.start_run("run-legacy", "test", 1, db, started_at="2025-12-01T00:00:00Z")
    legacy = dict(item)
    legacy.pop("source_facts")
    legacy["item_key"] = "tech-github-trending:https://github.com/legacy/null-facts"
    legacy["canonical_url"] = "https://github.com/legacy/null-facts"
    legacy["url"] = "https://github.com/legacy/null-facts"
    legacy["title"] = "legacy/null-facts"
    store.upsert_observation("run-legacy", GH_SOURCE["source_id"], legacy, observed_at="2025-12-01T00:00:00Z", has_real_rank=True, db_path=db)
    store.finish_run("run-legacy", status=store.RUN_STATUS_OK, source_ok=1, source_failed=0, item_seen=1, item_new=1, db_path=db)

    rows, _ = store.query_items(db, source_id=GH_SOURCE["source_id"], limit=10)
    whisper = next(r for r in rows if r["title"] == "openai/whisper")
    assert whisper["source_facts"]["stars_total"] == 150
    legacy_row = next(r for r in rows if r["title"] == "legacy/null-facts")
    assert legacy_row["source_facts"] is None

    with store._connect(db) as conn:
        facts = [
            r["source_facts_json"]
            for r in conn.execute(
                "SELECT source_facts_json FROM intel_observations WHERE item_id = ? ORDER BY observed_at",
                (whisper["item_id"],),
            ).fetchall()
        ]
    assert len(facts) == 2
    assert json.loads(facts[0])["stars_total"] == 100
    assert json.loads(facts[1])["stars_total"] == 150
