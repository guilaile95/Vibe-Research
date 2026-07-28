"""data_health_event_store 单元测试。"""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

import data_health_event_store as store


@pytest.fixture()
def events_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("VR_DATA_DIR", str(tmp_path))
    return tmp_path


def test_first_create_success(events_dir):
    rec = store.record_success("quotes")
    assert rec["source_id"] == "quotes"
    assert rec["last_success_at"] is not None
    assert rec["last_error_at"] is None
    path = store.events_path()
    assert os.path.isfile(path)
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    assert data["schema_version"] == store.SCHEMA_VERSION
    assert set(data.keys()) == {"schema_version", "events"}
    assert set(data["events"]["quotes"].keys()) == {
        "source_id", "last_success_at", "last_error_at", "last_error_code",
    }


def test_success_partial_degraded_failure_transitions(events_dir):
    store.record_success("quotes")
    p = store.record_partial("quotes")
    assert p["last_success_at"] == p["last_error_at"]
    assert p["last_error_code"] == "SOURCE_PARTIAL"
    d = store.record_degraded("announcements")
    assert d["last_error_code"] == "SOURCE_DEGRADED"
    f = store.record_failure("financials", "SOURCE_UNAVAILABLE")
    assert f["last_error_at"] is not None
    assert f["last_success_at"] is None


def test_monotonic_time_same_clock(events_dir):
    frozen = datetime(2026, 7, 28, 12, 0, 0, tzinfo=timezone.utc)
    a = store.record_success("quotes", now=frozen)
    b = store.record_partial("quotes", now=frozen)
    ta = store.parse_utc(a["last_success_at"])
    tb = store.parse_utc(b["last_success_at"])
    assert tb is not None and ta is not None
    assert tb > ta
    # partial 同一 observation 的 success/error 相等
    assert b["last_success_at"] == b["last_error_at"]


def test_partial_then_success_recovers(events_dir):
    frozen = datetime(2026, 7, 28, 12, 0, 0, tzinfo=timezone.utc)
    store.record_partial("quotes", now=frozen)
    s = store.record_success("quotes", now=frozen)
    events = store.load_events_readonly()
    q = events["quotes"]
    assert store.parse_utc(q["last_success_at"]) > store.parse_utc(q["last_error_at"])
    assert q["last_error_code"] == "SOURCE_PARTIAL"  # 历史保留


def test_degraded_then_success(events_dir):
    frozen = datetime(2026, 7, 28, 12, 0, 0, tzinfo=timezone.utc)
    store.record_degraded("sector_research", now=frozen)
    store.record_success("sector_research", now=frozen)
    e = store.load_events_readonly()["sector_research"]
    assert store.parse_utc(e["last_success_at"]) > store.parse_utc(e["last_error_at"])


def test_gate_blocked_allow_blocked(events_dir):
    frozen = datetime(2026, 7, 28, 12, 0, 0, tzinfo=timezone.utc)
    b = store.record_gate_blocked("NO_HOLDINGS", now=frozen)
    assert b["last_success_at"] == b["last_error_at"]
    assert b["last_error_code"] == "NO_HOLDINGS"
    a = store.record_gate_allowed(now=frozen)
    assert store.parse_utc(a["last_success_at"]) > store.parse_utc(a["last_error_at"])
    b2 = store.record_gate_blocked("HOLDING_QUOTES_UNAVAILABLE", now=frozen)
    assert b2["last_success_at"] == b2["last_error_at"]
    assert b2["last_error_code"] == "HOLDING_QUOTES_UNAVAILABLE"


def test_gate_failure_then_allow_or_block(events_dir):
    frozen = datetime(2026, 7, 28, 12, 0, 0, tzinfo=timezone.utc)
    store.record_gate_failure("SOURCE_TIMEOUT", now=frozen)
    e = store.load_events_readonly()["portfolio_advice_gate"]
    assert e["last_success_at"] is None
    store.record_gate_allowed(now=frozen)
    e = store.load_events_readonly()["portfolio_advice_gate"]
    assert e["last_success_at"] is not None
    store.record_gate_failure("SOURCE_UNAVAILABLE", now=frozen)
    store.record_gate_blocked("MARKET_BREADTH_UNAVAILABLE", now=frozen)
    e = store.load_events_readonly()["portfolio_advice_gate"]
    assert e["last_error_code"] == "MARKET_BREADTH_UNAVAILABLE"
    assert e["last_success_at"] == e["last_error_at"]


def test_concurrent_different_source_ids(events_dir):
    errors = []

    def worker(sid):
        try:
            for _ in range(20):
                store.record_success(sid)
        except Exception as e:
            errors.append(e)

    threads = [
        threading.Thread(target=worker, args=("quotes",)),
        threading.Thread(target=worker, args=("announcements",)),
        threading.Thread(target=worker, args=("financials",)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    events = store.load_events_readonly()
    assert "quotes" in events
    assert "announcements" in events
    assert "financials" in events


def test_corrupted_file_refuses_overwrite(events_dir):
    path = Path(store.events_path())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")
    st = path.stat()
    with pytest.raises(store.DataHealthEventStoreError):
        store.record_success("quotes")
    st2 = path.stat()
    assert st2.st_size == st.st_size
    assert st2.st_mtime_ns == st.st_mtime_ns
    assert path.read_text(encoding="utf-8") == "{not json"


def test_high_schema_refuses_write(events_dir):
    path = Path(store.events_path())
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"schema_version": "data-health-events.v99", "events": {}}
    path.write_text(json.dumps(payload), encoding="utf-8")
    before = path.read_text(encoding="utf-8")
    st = path.stat()
    with pytest.raises(store.DataHealthEventStoreError):
        store.record_success("quotes")
    assert path.read_text(encoding="utf-8") == before
    assert path.stat().st_mtime_ns == st.st_mtime_ns


def test_extra_fields_refuses_sanitize(events_dir):
    path = Path(store.events_path())
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": store.SCHEMA_VERSION,
        "events": {},
        "extra": True,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    before = path.read_text(encoding="utf-8")
    with pytest.raises(store.DataHealthEventStoreError):
        store.record_success("quotes")
    assert path.read_text(encoding="utf-8") == before

    # 记录级额外字段
    payload2 = {
        "schema_version": store.SCHEMA_VERSION,
        "events": {
            "quotes": {
                "source_id": "quotes",
                "last_success_at": "2026-07-28T00:00:00.000000Z",
                "last_error_at": None,
                "last_error_code": None,
                "traceback": "secret",
            }
        },
    }
    path.write_text(json.dumps(payload2), encoding="utf-8")
    before2 = path.read_text(encoding="utf-8")
    with pytest.raises(store.DataHealthEventStoreError):
        store.record_success("quotes")
    assert path.read_text(encoding="utf-8") == before2


def test_write_failure_does_not_change_business_semantics(events_dir, monkeypatch):
    """safe_call 吞掉写入失败。"""
    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(store, "record_success", boom)
    out = store.safe_call(store.record_success, "quotes")
    assert out is None


def test_load_readonly_missing_is_empty(events_dir):
    assert store.load_events_readonly() == {}
    # 不创建文件
    assert not os.path.exists(store.events_path())


def test_rejects_source_not_initialized_persist(events_dir):
    with pytest.raises(store.DataHealthEventStoreError):
        store.record_failure("quotes", "SOURCE_NOT_INITIALIZED")


def test_unknown_source_rejected(events_dir):
    with pytest.raises(store.DataHealthEventStoreError):
        store.record_success("daily_review")


def test_same_source_monotonic_under_concurrency(events_dir):
    times = []
    lock = threading.Lock()

    def worker():
        for _ in range(15):
            rec = store.record_success("quotes")
            with lock:
                times.append(store.parse_utc(rec["last_success_at"]))

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(times) == 60
    assert times == sorted(times)
    assert len(set(times)) == 60


def _write_raw(events_dir, payload: dict):
    path = Path(store.events_path())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_cross_source_error_code_rejected(events_dir):
    with pytest.raises(store.DataHealthEventStoreError):
        store.record_failure("quotes", "NO_HOLDINGS")
    with pytest.raises(store.DataHealthEventStoreError):
        store.record_failure("portfolio_advice_gate", "SOURCE_PARTIAL")


def test_unpaired_error_fields_rejected(events_dir):
    path = _write_raw(events_dir, {
        "schema_version": store.SCHEMA_VERSION,
        "events": {
            "quotes": {
                "source_id": "quotes",
                "last_success_at": "2026-07-28T01:00:00.000000Z",
                "last_error_at": None,
                "last_error_code": "SOURCE_PARTIAL",
            }
        },
    })
    before = path.read_text(encoding="utf-8")
    st = path.stat()
    with pytest.raises(store.DataHealthEventStoreError):
        store.record_success("quotes")
    assert path.read_text(encoding="utf-8") == before
    assert path.stat().st_size == st.st_size
    assert path.stat().st_mtime_ns == st.st_mtime_ns

    path2 = _write_raw(events_dir, {
        "schema_version": store.SCHEMA_VERSION,
        "events": {
            "quotes": {
                "source_id": "quotes",
                "last_success_at": "2026-07-28T01:00:00.000000Z",
                "last_error_at": "2026-07-28T01:00:00.000000Z",
                "last_error_code": None,
            }
        },
    })
    before2 = path2.read_text(encoding="utf-8")
    st2 = path2.stat()
    with pytest.raises(store.DataHealthEventStoreError):
        store.record_success("announcements")
    assert path2.read_text(encoding="utf-8") == before2
    assert path2.stat().st_mtime_ns == st2.st_mtime_ns


def test_non_canonical_utc_rejected(events_dir):
    bad_times = [
        "2026-07-28 09:30:00",
        "2026-07-28T09:30:00",
        "2026-07-28T01:00:00+08:00",
        "2026-07-28T01:00:00Z",  # 无微秒
        "",
        "not-a-date",
    ]
    for bad in bad_times:
        path = _write_raw(events_dir, {
            "schema_version": store.SCHEMA_VERSION,
            "events": {
                "quotes": {
                    "source_id": "quotes",
                    "last_success_at": bad,
                    "last_error_at": None,
                    "last_error_code": None,
                }
            },
        })
        before = path.read_text(encoding="utf-8")
        st = path.stat()
        with pytest.raises(store.DataHealthEventStoreError):
            store.record_success("quotes")
        assert path.read_text(encoding="utf-8") == before
        assert path.stat().st_size == st.st_size
        assert path.stat().st_mtime_ns == st.st_mtime_ns
