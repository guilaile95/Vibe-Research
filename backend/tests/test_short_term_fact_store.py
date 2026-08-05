"""BK-11 Slice 3a 短线事实快照存储层测试。

全部使用临时目录（tmp_path），不触碰真实 VR_DATA_DIR / 用户目录。
"""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timezone

import pytest

sys.path.insert(0, "backend")

import short_term_fact_store as store  # noqa: E402


def _envelope(trade_date="2026-07-31", session="final", status="normal",
              **overrides):
    envelope = {
        "schema_version": "short-term-daily-facts-v0.1",
        "trade_date": trade_date,
        "session": session,
        "is_final": session == "final",
        "source_ids": ["eastmoney_getTopicZTPool"],
        "fetched_at": "2026-07-31T15:10:00.000000Z",
        "snapshot_at": "2026-07-31T15:10:00.000000Z",
        "status": status,
        "reason_codes": [],
        "warnings": [],
        "limitations": [
            "composed from approved BK-11 pure calculators",
            "does not validate upstream consecutive-limit-up semantics",
            "does not compute layered promotion rates",
            "production integration not authorized",
        ],
        "source_schema_version": "short-term-limit-up-final-snapshot-v0.1",
        "source_status": "normal",
        "source_reason_codes": [],
        "sections": {
            "facts": {"schema_version": "short-term-market-facts-v0.1",
                      "status": "normal"},
            "ladder": {"schema_version": "short-term-limit-up-ladder-v0.1",
                       "status": "normal"},
            "gap": {"schema_version": "short-term-ladder-gap-v0.1",
                    "status": "normal"},
        },
    }
    envelope.update(overrides)
    return envelope


# ---------------------------------------------------------------------------
# 1. 公开合同与路径解析
# ---------------------------------------------------------------------------

class TestPublicContract:
    def test_constants(self):
        assert store.SCHEMA_VERSION == "short-term-fact-store-v0.1"
        assert store.STORED_SCHEMA_VERSION == "short-term-daily-facts-v0.1"

    def test_explicit_path_wins(self, tmp_path):
        explicit = tmp_path / "explicit" / "f.sqlite3"
        assert store.resolve_db_path(explicit) == explicit

    def test_vr_data_dir_used(self, monkeypatch, tmp_path):
        monkeypatch.setenv("VR_DATA_DIR", str(tmp_path / "data"))
        assert store.resolve_db_path() == (
            tmp_path / "data" / "short_term_facts.sqlite3")

    def test_default_path(self, monkeypatch):
        monkeypatch.delenv("VR_DATA_DIR", raising=False)
        path = store.resolve_db_path()
        assert path.name == "short_term_facts.sqlite3"
        assert ".vibe-research" in path.parts


# ---------------------------------------------------------------------------
# 2. 初始化与保存/加载
# ---------------------------------------------------------------------------

class TestSaveLoad:
    def test_init_idempotent(self, tmp_path):
        db = tmp_path / "facts.sqlite3"
        store.init_db(db)
        store.init_db(db)
        assert db.exists()
        conn = sqlite3.connect(db)
        tables = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        conn.close()
        assert "fact_snapshots" in tables
        assert "schema_meta" in tables

    def test_roundtrip(self, tmp_path):
        db = tmp_path / "facts.sqlite3"
        envelope = _envelope()
        meta = store.save_daily_facts(envelope, db)
        assert meta["trade_date"] == "2026-07-31"
        assert meta["session"] == "final"
        assert meta["schema_version"] == "short-term-daily-facts-v0.1"
        loaded = store.load_daily_facts("2026-07-31", "final", db)
        assert loaded == envelope

    def test_load_by_date_latest_session(self, tmp_path):
        db = tmp_path / "facts.sqlite3"
        store.save_daily_facts(
            _envelope(session="afternoon_session"), db)
        store.save_daily_facts(_envelope(session="final"), db)
        loaded = store.load_daily_facts("2026-07-31", db_path=db)
        assert loaded["session"] == "final"

    def test_load_not_found(self, tmp_path):
        db = tmp_path / "facts.sqlite3"
        assert store.load_daily_facts("2026-07-30", db_path=db) is None

    def test_upsert_replaces(self, tmp_path):
        db = tmp_path / "facts.sqlite3"
        store.save_daily_facts(_envelope(reason_codes=["OLD"]), db)
        store.save_daily_facts(_envelope(reason_codes=["NEW"]), db)
        loaded = store.load_daily_facts("2026-07-31", "final", db)
        assert loaded["reason_codes"] == ["NEW"]
        assert len(store.list_snapshots(db)) == 1

    def test_list_trade_dates_sorted(self, tmp_path):
        db = tmp_path / "facts.sqlite3"
        for day in ["2026-07-30", "2026-07-29", "2026-07-31"]:
            store.save_daily_facts(
                _envelope(trade_date=day, session="final"), db)
        assert store.list_trade_dates(db) == [
            "2026-07-29", "2026-07-30", "2026-07-31"]

    def test_list_snapshots(self, tmp_path):
        db = tmp_path / "facts.sqlite3"
        store.save_daily_facts(_envelope(), db)
        snapshots = store.list_snapshots(db)
        assert len(snapshots) == 1
        assert snapshots[0]["trade_date"] == "2026-07-31"
        assert snapshots[0]["session"] == "final"
        assert snapshots[0]["schema_version"] == "short-term-daily-facts-v0.1"
        assert "stored_at" in snapshots[0]

    def test_roundtrip_preserves_sections(self, tmp_path):
        db = tmp_path / "facts.sqlite3"
        envelope = _envelope()
        store.save_daily_facts(envelope, db)
        loaded = store.load_daily_facts("2026-07-31", "final", db)
        assert loaded["sections"]["ladder"]["status"] == "normal"


# ---------------------------------------------------------------------------
# 3. 非法 envelope 拒绝（失败关闭，不写入）
# ---------------------------------------------------------------------------

class TestInvalidEnvelope:
    def _assert_rejected(self, envelope, tmp_path):
        db = tmp_path / "facts.sqlite3"
        with pytest.raises(store.FactStoreInvalidEnvelopeError):
            store.save_daily_facts(envelope, db)
        assert store.list_trade_dates(db) == []

    def test_non_dict(self, tmp_path):
        self._assert_rejected("x", tmp_path)

    def test_dict_subclass(self, tmp_path):
        class D(dict):
            pass
        self._assert_rejected(D(_envelope()), tmp_path)

    def test_wrong_schema(self, tmp_path):
        envelope = _envelope()
        envelope["schema_version"] = "wrong"
        self._assert_rejected(envelope, tmp_path)

    def test_extra_key(self, tmp_path):
        envelope = _envelope()
        envelope["extra"] = 1
        self._assert_rejected(envelope, tmp_path)

    def test_missing_key(self, tmp_path):
        envelope = _envelope()
        del envelope["sections"]
        self._assert_rejected(envelope, tmp_path)

    @pytest.mark.parametrize("bad", ["2026-7-31", "20260731",
                                     "2026-02-30", 20260731, None])
    def test_bad_trade_date(self, tmp_path, bad):
        self._assert_rejected(_envelope(trade_date=bad), tmp_path)

    @pytest.mark.parametrize("bad", ["draft", 1, None])
    def test_bad_session(self, tmp_path, bad):
        self._assert_rejected(_envelope(session=bad), tmp_path)

    @pytest.mark.parametrize("bad", ["weird", 1, None])
    def test_bad_status(self, tmp_path, bad):
        self._assert_rejected(_envelope(status=bad), tmp_path)

    def test_is_final_non_bool(self, tmp_path):
        self._assert_rejected(_envelope(is_final=1), tmp_path)

    def test_source_ids_non_list(self, tmp_path):
        self._assert_rejected(_envelope(source_ids="x"), tmp_path)

    def test_sections_wrong_keys(self, tmp_path):
        envelope = _envelope()
        envelope["sections"] = {"facts": {}}
        self._assert_rejected(envelope, tmp_path)

    def test_nan_rejected(self, tmp_path):
        envelope = _envelope()
        envelope["warnings"] = [float("nan")]
        self._assert_rejected(envelope, tmp_path)


# ---------------------------------------------------------------------------
# 4. 损坏与异常
# ---------------------------------------------------------------------------

class TestCorruption:
    def test_corrupted_json_raises(self, tmp_path):
        db = tmp_path / "facts.sqlite3"
        store.init_db(db)
        conn = sqlite3.connect(db)
        conn.execute(
            "INSERT INTO fact_snapshots "
            "(trade_date, session, schema_version, stored_at, envelope_json) "
            "VALUES (?, ?, ?, ?, ?)",
            ("2026-07-31", "final", "short-term-daily-facts-v0.1",
             "2026-08-05T00:00:00Z", "{not-json"))
        conn.commit()
        conn.close()
        with pytest.raises(store.FactStoreCorruptedError):
            store.load_daily_facts("2026-07-31", "final", db)

    def test_corrupted_db_file_raises(self, tmp_path):
        db = tmp_path / "facts.sqlite3"
        db.write_bytes(b"not-a-sqlite-db")
        with pytest.raises(store.FactStoreCorruptedError):
            store.list_trade_dates(db)


# ---------------------------------------------------------------------------
# 5. VR_DATA_DIR 隔离与集成
# ---------------------------------------------------------------------------

class TestEnvironment:
    def test_vr_data_dir_not_touched(self, monkeypatch, tmp_path):
        monkeypatch.setenv("VR_DATA_DIR", str(tmp_path / "vr"))
        db = store.resolve_db_path()
        store.save_daily_facts(_envelope(), db)
        assert (tmp_path / "vr" / "short_term_facts.sqlite3").exists()
        assert store.load_daily_facts("2026-07-31", "final", db) == _envelope()

    def test_real_daily_facts_envelope_roundtrip(self, tmp_path):
        # 用 2K 组合层真实输出做端到端（纯内存计算，无网络）
        import short_term_daily_facts as daily
        producer = {
            "schema_version": "short-term-limit-up-final-snapshot-v0.1",
            "requested_trade_date": "2026-07-31",
            "observed_at": "2026-07-31T15:10:00.000000Z",
            "status": "normal", "reason_codes": [], "session": "final",
            "is_final": True,
            "finality_basis": "three_identical_normal_observations",
            "required_observations": 3, "completed_observations": 3,
            "stable_observation_count": 3,
            "observation_interval_seconds": 2.2,
            "required_stability_window_seconds": 4.4,
            "actual_stability_window_seconds": 104.4 - 100.0,
            "first_observation_monotonic": 100.0,
            "last_observation_monotonic": 104.4,
            "snapshot": {
                "schema_version": "short-term-limit-up-pool-adapter-v0.1",
                "source_id": "eastmoney_getTopicZTPool",
                "endpoint": "getTopicZTPool",
                "requested_trade_date": "2026-07-31",
                "observed_at": "2026-07-31T15:05:00.000000Z",
                "status": "normal", "reason_codes": [],
                "rows": [{"stock_code": "600001", "lbc": 2}],
                "transport_success": True, "parse_success": True,
                "required_field_present": True, "data_array_present": True,
                "trade_date_match": True, "row_count": 1,
                "legal_zero": False, "upstream_null": False,
                "unexplained_empty": False, "coverage_warning": False,
                "target_universe_empty_after_filter": False,
                "source_pool_row_count": 1, "http_status": 200,
                "error_class": "NONE", "excluded_universe_count": 0,
                "invalid_row_count": 0, "duplicate_code_count": 0,
            },
            "warnings": [],
        }
        envelope = daily.compute_daily_facts({
            "final_snapshot": producer,
            "breadth": {"advance_count": 1, "decline_count": 1,
                        "flat_count": 0, "suspended_count": 0,
                        "eligible_count": 2},
            "limit_activity": {"limit_up_count": 1, "limit_down_count": 0,
                               "failed_limit_up_count": 0},
            "facts_data_health": {
                "transport_success": True, "parse_success": True,
                "required_field_present": True, "data_array_present": True,
                "trade_date_match": True, "row_count": 1,
                "legal_zero": False, "upstream_null": False,
                "unexplained_empty": False, "coverage_warning": False},
        })
        assert envelope["status"] == "normal"
        db = tmp_path / "facts.sqlite3"
        store.save_daily_facts(envelope, db)
        loaded = store.load_daily_facts("2026-07-31", "final", db)
        assert loaded == envelope
        assert loaded["sections"]["gap"]["metrics"]["is_continuous"] is True
