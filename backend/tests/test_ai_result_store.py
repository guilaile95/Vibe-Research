from __future__ import annotations

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

import ai_result_store as store


def _record(**overrides):
    record = {
        "result_type": "daily_review_ai",
        "trade_date": "2026-07-23",
        "schema_version": "daily_review_ai.v1",
        "payload": {"markdown": "# 复盘", "z": 1, "a": 2},
        "generated_at": "2026-07-23 15:30:00",
        "model_provider": "api-compatible",
        "model_name": "test-model",
        "input_fingerprint": None,
    }
    record.update(overrides)
    return record


def test_init_is_idempotent_and_does_not_touch_snapshot_table(tmp_path):
    db = tmp_path / "daily_reviews.sqlite3"
    store.initialize_store(db)
    store.initialize_store(db)

    with sqlite3.connect(db) as conn:
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE name='ai_generated_results'"
        ).fetchone()[0]
    assert "ai_generated_results" in tables
    assert "daily_review_snapshots" not in tables
    assert "PRIMARY KEY (result_type, trade_date)" in sql


def test_upsert_is_deterministic_and_preserves_created_at(tmp_path, monkeypatch):
    db = tmp_path / "daily_reviews.sqlite3"
    times = iter(["2026-07-23T08:00:00+00:00", "2026-07-23T08:01:00+00:00"])
    monkeypatch.setattr(store, "_utc_now", lambda: next(times))

    first = store.upsert_result(db, _record())
    second = store.upsert_result(db, _record(payload={"markdown": "# 新版", "b": 1}))

    assert first["created_at"] == second["created_at"]
    assert second["updated_at"] > first["updated_at"]
    assert second["payload"] == {"markdown": "# 新版", "b": 1}
    with sqlite3.connect(db) as conn:
        payload_json = conn.execute(
            "SELECT payload_json FROM ai_generated_results"
        ).fetchone()[0]
    assert payload_json == '{"b":1,"markdown":"# 新版"}'


def test_exact_and_latest_reads_are_independent_by_type_and_date(tmp_path):
    db = tmp_path / "daily_reviews.sqlite3"
    store.upsert_result(db, _record(trade_date="2026-07-22"))
    store.upsert_result(db, _record(trade_date="2026-07-23"))
    store.upsert_result(
        db,
        _record(
            result_type="portfolio_advice",
            schema_version="portfolio_advice.v1",
            input_fingerprint="a" * 64,
            payload={"holdings": []},
        ),
    )

    assert store.get_result(db, "daily_review_ai", "2026-07-21") is None
    assert store.get_result(db, "daily_review_ai", "2026-07-22")["trade_date"] == "2026-07-22"
    assert store.get_latest_result(db, "daily_review_ai")["trade_date"] == "2026-07-23"
    assert store.get_latest_result(db, "portfolio_advice")["result_type"] == "portfolio_advice"


def test_bad_payload_raises_dedicated_corruption_error_without_path_or_sql(tmp_path):
    db = tmp_path / "private" / "daily_reviews.sqlite3"
    store.upsert_result(db, _record())
    with sqlite3.connect(db) as conn:
        conn.execute(
            "UPDATE ai_generated_results SET payload_json = ?",
            ("{broken",),
        )
        conn.commit()

    with pytest.raises(store.AiResultPayloadCorruptedError) as exc_info:
        store.get_result(db, "daily_review_ai", "2026-07-23")
    message = str(exc_info.value)
    assert "daily_reviews.sqlite3" not in message
    assert "SELECT" not in message.upper()
    assert "{broken" not in message


def test_serialization_failure_does_not_overwrite_existing_row(tmp_path):
    db = tmp_path / "daily_reviews.sqlite3"
    store.upsert_result(db, _record(payload={"markdown": "old"}))

    with pytest.raises((TypeError, ValueError)):
        store.upsert_result(db, _record(payload={"bad": {1, 2, 3}}))

    assert store.get_result(db, "daily_review_ai", "2026-07-23")["payload"] == {
        "markdown": "old"
    }


def test_repeated_concurrent_upserts_leave_one_valid_row(tmp_path):
    db = tmp_path / "daily_reviews.sqlite3"

    def write(i: int):
        return store.upsert_result(db, _record(payload={"markdown": f"v{i}"}))

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(write, range(12)))

    with sqlite3.connect(db) as conn:
        count = conn.execute("SELECT COUNT(*) FROM ai_generated_results").fetchone()[0]
        payload = json.loads(
            conn.execute("SELECT payload_json FROM ai_generated_results").fetchone()[0]
        )
    assert count == 1
    assert payload["markdown"].startswith("v")
