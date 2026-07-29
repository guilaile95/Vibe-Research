"""Tests for trade_ledger_store."""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

import pytest

import trade_ledger_store as store


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "trade_ledger.sqlite3"


@pytest.fixture
def sample_record() -> dict:
    return {
        "trade_id": "abc123",
        "code": "600519",
        "name": "贵州茅台",
        "operation": "buy",
        "execution_status": "full",
        "planned_price": 1500.0,
        "planned_quantity": 100,
        "actual_price": 1498.5,
        "actual_quantity": 100,
        "executed_at": "2026-07-28T01:30:00.000000+00:00",
        "fee": 37.46,
        "other_cost": 0.0,
        "unexecuted_reason": None,
        "note": "测试买入",
        "advice_trade_date": None,
        "advice_generated_at": None,
        "advice_snapshot": None,
        "thesis_id": None,
        "thesis_revision": None,
        "created_at": "2026-07-28T09:31:00.000000+00:00",
    }


class TestInsertAndGet:
    def test_insert_creates_table_and_record(self, db_path, sample_record):
        store.insert_record(db_path, sample_record)
        result = store.get_record(db_path, "abc123")
        assert result is not None
        assert result["trade_id"] == "abc123"
        assert result["code"] == "600519"
        assert result["operation"] == "buy"
        assert result["actual_price"] == 1498.5

    def test_get_missing_returns_none(self, db_path):
        assert store.get_record(db_path, "nonexistent") is None

    def test_insert_multiple(self, db_path, sample_record):
        store.insert_record(db_path, sample_record)
        r2 = dict(sample_record, trade_id="def456", code="000001")
        store.insert_record(db_path, r2)
        assert store.get_record(db_path, "def456")["code"] == "000001"


class TestListRecords:
    def test_list_empty(self, db_path):
        assert store.list_records(db_path) == []

    def test_list_default_excludes_voided(self, db_path, sample_record):
        store.insert_record(db_path, sample_record)
        store.void_record_atomic(db_path, "abc123", "录入错误")
        assert store.list_records(db_path) == []

    def test_list_include_voided(self, db_path, sample_record):
        store.insert_record(db_path, sample_record)
        store.void_record_atomic(db_path, "abc123", "录入错误")
        results = store.list_records(db_path, include_voided=True)
        assert len(results) == 1
        assert results[0]["trade_id"] == "abc123"

    def test_list_filter_by_code(self, db_path, sample_record):
        store.insert_record(db_path, sample_record)
        r2 = dict(sample_record, trade_id="def456", code="000001")
        store.insert_record(db_path, r2)
        results = store.list_records(db_path, code="600519")
        assert len(results) == 1
        assert results[0]["code"] == "600519"

    def test_list_filter_by_operation(self, db_path, sample_record):
        store.insert_record(db_path, sample_record)
        r2 = dict(sample_record, trade_id="def456", operation="sell")
        store.insert_record(db_path, r2)
        results = store.list_records(db_path, operation="sell")
        assert len(results) == 1

    def test_list_filter_by_status(self, db_path, sample_record):
        store.insert_record(db_path, sample_record)
        r2 = dict(sample_record, trade_id="def456", execution_status="partial")
        store.insert_record(db_path, r2)
        results = store.list_records(db_path, execution_status="partial")
        assert len(results) == 1

    def test_list_ordered_by_created_at_desc(self, db_path, sample_record):
        r1 = dict(sample_record, trade_id="abc123", created_at="2026-01-01T00:00:00+00:00")
        store.insert_record(db_path, r1)
        r2 = dict(sample_record, trade_id="def456", created_at="2026-01-02T00:00:00+00:00")
        store.insert_record(db_path, r2)
        results = store.list_records(db_path, include_voided=True)
        assert results[0]["trade_id"] == "def456"
        assert results[1]["trade_id"] == "abc123"

    def test_inclusive_date_filter_by_executed_at(self, db_path, sample_record):
        # Trade executed on 2026-07-28 UTC, but created on 2026-07-29 UTC
        r = dict(
            sample_record,
            executed_at="2026-07-28T01:30:00.000000+00:00",
            created_at="2026-07-29T10:00:00.000000+00:00",
        )
        store.insert_record(db_path, r)

        res = store.list_records(db_path, date_from="2026-07-28", date_to="2026-07-28")
        assert len(res) == 1
        assert res[0]["trade_id"] == "abc123"

        res_miss = store.list_records(db_path, date_from="2026-07-29", date_to="2026-07-29")
        assert len(res_miss) == 0


class TestAtomicVoid:
    def test_void_success(self, db_path, sample_record):
        store.insert_record(db_path, sample_record)
        res = store.void_record_atomic(db_path, "abc123", "录入错误")
        assert res["trade_id"] == "abc123"
        assert res["voided_at"] is not None
        assert res["void_reason"] == "录入错误"

    def test_void_missing_raises_not_found(self, db_path, sample_record):
        store.insert_record(db_path, sample_record)
        with pytest.raises(store.TradeNotFoundError):
            store.void_record_atomic(db_path, "nonexistent", "原因")

    def test_void_already_voided_raises(self, db_path, sample_record):
        store.insert_record(db_path, sample_record)
        store.void_record_atomic(db_path, "abc123", "第一次")
        with pytest.raises(store.TradeAlreadyVoidedError):
            store.void_record_atomic(db_path, "abc123", "第二次")

    def test_concurrent_atomic_void(self, db_path, sample_record):
        store.insert_record(db_path, sample_record)
        results = []
        errors = []

        def worker():
            try:
                r = store.void_record_atomic(db_path, "abc123", "并发作废")
                results.append(r)
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=worker)
        t2 = threading.Thread(target=worker)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert len(results) == 1
        assert len(errors) == 1
        assert isinstance(errors[0], store.TradeAlreadyVoidedError)


class TestReadonlyNoSideEffects:
    def test_get_nonexistent_db_no_side_effects(self, tmp_path):
        db_file = tmp_path / "nonexistent.sqlite3"
        files_before = set(tmp_path.iterdir())

        res_get = store.get_record(db_file, "xyz")
        assert res_get is None

        res_list = store.list_records(db_file)
        assert res_list == []

        files_after = set(tmp_path.iterdir())
        assert files_before == files_after
        assert not db_file.exists()


class TestCorruptedDB:
    def test_get_corrupted_raises(self, db_path, sample_record):
        store.insert_record(db_path, sample_record)
        with open(db_path, "wb") as f:
            f.write(b"this is not a sqlite database")
        with pytest.raises(store.TradeLedgerCorruptedError):
            store.get_record(db_path, "abc123")

    def test_list_corrupted_raises(self, db_path, sample_record):
        store.insert_record(db_path, sample_record)
        with open(db_path, "wb") as f:
            f.write(b"corrupted data")
        with pytest.raises(store.TradeLedgerCorruptedError):
            store.list_records(db_path)
