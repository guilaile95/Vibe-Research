"""short_term_fact_store 质量单调写入接口测试（v0.2）。"""

from __future__ import annotations

import json
import sqlite3
import sys
import threading

import pytest

sys.path.insert(0, "backend")

import short_term_fact_store as store  # noqa: E402


def _v02(status="normal", trade_date="2026-07-30", content="a"):
    return {
        "schema_version": "short-term-daily-facts-v0.2",
        "trade_date": trade_date,
        "session": "final",
        "is_final": True,
        "source_ids": ["tushare_daily"],
        "fetched_at": "2026-07-31T01:00:00.000000Z",
        "snapshot_at": "2026-07-31T01:00:00.000000Z",
        "status": status,
        "reason_codes": [],
        "warnings": [],
        "limitations": ["fixture"],
        "source_schema_version": "short-term-daily-facts-v0.2",
        "source_status": status,
        "source_reason_codes": [],
        "sections": {
            "facts": {
                "schema_version": "short-term-market-facts-v0.1",
                "status": "normal",
                "facts": {"advance_count": 100, "content": content},
            },
            "ladder": {
                "schema_version": "short-term-limit-up-ladder-v0.1",
                "status": "normal",
                "metrics": {"max_boards": 0, "lianban_count": 0, "ladder": []},
            },
            "gap": {
                "schema_version": "short-term-ladder-gap-v0.1",
                "status": "normal",
                "metrics": {"gap_level_count": 0, "gap_segment_count": 0,
                            "largest_gap_width": 0, "first_gap_board": None,
                            "is_continuous": True},
            },
        },
    }


def _v01():
    env = _v02()
    env["schema_version"] = "short-term-daily-facts-v0.1"
    return env


class TestMonotonic:
    def test_insert_saved(self, tmp_path):
        db = tmp_path / "f.sqlite3"
        result = store.save_daily_facts_monotonic(_v02(), db_path=db)
        assert result["saved"] is True
        assert result["blocked"] is False
        assert result["snapshot"]["schema_version"] == "short-term-daily-facts-v0.2"
        loaded = store.load_daily_facts("2026-07-30", "final", db_path=db)
        assert loaded["schema_version"] == "short-term-daily-facts-v0.2"

    def test_dedupe_same_content(self, tmp_path):
        db = tmp_path / "f.sqlite3"
        store.save_daily_facts_monotonic(_v02(), db_path=db)
        result = store.save_daily_facts_monotonic(_v02(), db_path=db)
        assert result["deduped"] is True
        assert result["saved"] is False

    def test_partial_upgraded_to_normal(self, tmp_path):
        db = tmp_path / "f.sqlite3"
        store.save_daily_facts_monotonic(_v02(status="partial"), db_path=db)
        result = store.save_daily_facts_monotonic(_v02(status="normal"), db_path=db)
        assert result["upgraded"] is True
        loaded = store.load_daily_facts("2026-07-30", "final", db_path=db)
        assert loaded["status"] == "normal"

    def test_normal_not_overwritten_by_partial(self, tmp_path):
        db = tmp_path / "f.sqlite3"
        store.save_daily_facts_monotonic(_v02(status="normal"), db_path=db)
        result = store.save_daily_facts_monotonic(
            _v02(status="partial", content="b"), db_path=db)
        assert result["blocked"] is True
        assert result["reason_code"] == "NORMAL_CONFLICT"
        loaded = store.load_daily_facts("2026-07-30", "final", db_path=db)
        assert loaded["status"] == "normal"

    def test_normal_conflict_not_overwritten(self, tmp_path):
        db = tmp_path / "f.sqlite3"
        store.save_daily_facts_monotonic(_v02(status="normal"), db_path=db)
        result = store.save_daily_facts_monotonic(
            _v02(status="normal", content="different"), db_path=db)
        assert result["blocked"] is True
        assert result["reason_code"] == "NORMAL_CONFLICT"
        loaded = store.load_daily_facts("2026-07-30", "final", db_path=db)
        assert loaded["sections"]["facts"]["facts"]["content"] == "a"

    def test_partial_conflict_not_overwritten(self, tmp_path):
        db = tmp_path / "f.sqlite3"
        store.save_daily_facts_monotonic(_v02(status="partial"), db_path=db)
        result = store.save_daily_facts_monotonic(
            _v02(status="partial", content="b"), db_path=db)
        assert result["blocked"] is True
        assert result["reason_code"] == "PARTIAL_CONFLICT"

    def test_v01_same_key_schema_conflict(self, tmp_path):
        db = tmp_path / "f.sqlite3"
        store.save_daily_facts(_v01(), db_path=db)
        result = store.save_daily_facts_monotonic(_v02(), db_path=db)
        assert result["blocked"] is True
        assert result["reason_code"] == "SCHEMA_CONFLICT_V01"
        loaded = store.load_daily_facts("2026-07-30", "final", db_path=db)
        assert loaded["schema_version"] == "short-term-daily-facts-v0.1"

    def test_unavailable_not_written(self, tmp_path):
        db = tmp_path / "f.sqlite3"
        with pytest.raises(store.FactStoreInvalidEnvelopeError):
            store.save_daily_facts_monotonic(
                _v02(status="unavailable"), db_path=db)
        assert store.load_daily_facts("2026-07-30", "final", db_path=db) is None

    def test_non_final_not_written(self, tmp_path):
        db = tmp_path / "f.sqlite3"
        env = _v02()
        env["session"] = "afternoon_session"
        env["is_final"] = False
        with pytest.raises(store.FactStoreInvalidEnvelopeError):
            store.save_daily_facts_monotonic(env, db_path=db)

    def test_v01_plain_save_still_works(self, tmp_path):
        db = tmp_path / "f.sqlite3"
        store.save_daily_facts(_v01(), db_path=db)
        assert store.load_daily_facts("2026-07-30", "final", db_path=db)["status"] == "normal"

    def test_concurrent_upgrade_no_regression(self, tmp_path):
        db = tmp_path / "f.sqlite3"
        store.save_daily_facts_monotonic(_v02(status="partial"), db_path=db)

        def writer():
            try:
                store.save_daily_facts_monotonic(
                    _v02(status="normal"), db_path=db)
            except Exception:
                pass

        threads = [threading.Thread(target=writer) for _ in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        loaded = store.load_daily_facts("2026-07-30", "final", db_path=db)
        assert loaded["status"] == "normal"

    def test_corrupted_db_fails_closed(self, tmp_path):
        db = tmp_path / "f.sqlite3"
        db.write_bytes(b"this is not sqlite at all")
        with pytest.raises(store.FactStoreCorruptedError):
            store.save_daily_facts_monotonic(_v02(), db_path=db)

    def test_no_sensitive_leak_in_errors(self, tmp_path):
        db = tmp_path / "f.sqlite3"
        db.write_bytes(b"garbage")
        try:
            store.save_daily_facts_monotonic(_v02(), db_path=db)
        except store.FactStoreCorruptedError as exc:
            assert str(tmp_path) not in str(exc)
            assert "Traceback" not in str(exc)
