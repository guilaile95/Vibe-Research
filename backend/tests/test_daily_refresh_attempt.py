"""Offline daily-refresh deadline and attempt-versus-success contracts."""
import multiprocessing
from datetime import datetime, timezone
import socket
import time
import threading

import pytest
from fastapi.testclient import TestClient

import app
import daily_review as dr
import daily_review_cache as cache
import data_health_adapters as health
import public_data_budget as budget
from test_daily_review_refresh import _packet


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("VR_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(dr, "_latest_attempt", None)
    monkeypatch.setattr(dr, "_review_cache", {})
    monkeypatch.setattr(dr, "_build_flight", None)
    monkeypatch.setattr(dr, "_build_generation", 0)
    monkeypatch.setattr(dr, "_committed_generation", 0)
    monkeypatch.setattr(dr, "_explicit_refresh_current", None)
    monkeypatch.setattr(dr, "_review_session_current", lambda *args: True)
    monkeypatch.setattr(budget, "_CACHE", {})
    monkeypatch.setattr(budget, "_INFLIGHT", set())
    dr._clear_refresh_failure()
    def denied(*args, **kwargs):
        raise AssertionError("external network forbidden")
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket, "getaddrinfo", denied)


def slow_success(path, operation, code):
    # Deliberately longer than the former default12 / follower14 second bounds.
    time.sleep(15)
    budget._write_result(path, {"sources": {}, "reason_code": None})


def test_daily_default_allows_slow_success_and_reaps_child(monkeypatch):
    before = {p.pid for p in multiprocessing.active_children()}
    entered = threading.Event()
    calls, results = [], []
    def build():
        calls.append(1)
        entered.set()
        return budget.run("daily_review", _target=slow_success)
    monkeypatch.setattr(dr, "_build_daily_review", build)
    leader = threading.Thread(target=lambda: results.append(dr._shared_build()))
    leader.start()
    assert entered.wait(2)
    # This joins the actual running build and must not retain the old14s timeout.
    results.append(dr._shared_build())
    leader.join(2)
    assert not leader.is_alive() and len(calls) == 1
    assert len(results) == 2 and results[0] == results[1]
    assert results[0][1]["reason_code"] is None
    assert {p.pid for p in multiprocessing.active_children()} == before
    assert dr._REFRESH_JOIN_TIMEOUT > budget.DAILY_REVIEW_TIMEOUT >= 120
    assert budget.TIMEOUT == 12


def test_default_budget_dispatch_is_operation_specific(monkeypatch):
    calls = []
    monkeypatch.setattr(budget, "_run_process", lambda op, code, **kw: calls.append((op, kw["timeout"])) or {})
    budget.run("daily_review")
    budget.run("financials", "000001")
    assert calls == [("daily_review", budget.DAILY_REVIEW_TIMEOUT), ("financials", 12)]


def test_failure_exposes_timeout_and_source_without_replacing_last_success(monkeypatch):
    old = _packet()
    assert cache.save_latest_review(old, saved_at=old["generated_at"])
    old_bytes = open(cache.cache_path(), "rb").read()
    candidate = _packet("2026-07-25 11:00:00", status="partial", critical_bad=True)
    candidate["collection"] = {"failed": [], "pending": ["breadth"], "reason_code": "SOURCE_TIMEOUT"}
    monkeypatch.setattr(dr, "_build_daily_review", lambda: candidate)
    response = TestClient(app.app).post("/api/daily-review/refresh")
    assert response.status_code == 503
    attempt = response.json()["refresh_attempt"]
    assert attempt["state"] == "failed" and attempt["reason_code"] == "SOURCE_TIMEOUT"
    assert attempt["pending_sources"] == ["breadth"]
    assert attempt["failed_sources"] == ["indices", "emotion"]
    assert attempt["started_at"] and attempt["finished_at"]
    assert open(cache.cache_path(), "rb").read() == old_bytes
    ctx = health.HealthReadContext(now_utc=datetime.now(timezone.utc))
    record = health.DailyReviewAdapter().read(ctx)
    assert record["refresh_attempt"] == attempt
    assert record["status"] == "normal" and record["is_stale"] is True
    assert record["last_success_at"] != attempt["finished_at"]


@pytest.mark.parametrize("corrupt", [False, True])
def test_health_missing_or_corrupt_snapshot_still_reports_failed_attempt(corrupt):
    if corrupt:
        from pathlib import Path
        Path(cache.cache_path()).write_text("invalid json")
    dr._start_refresh_attempt(1)
    dr._finish_refresh_attempt(1, reason="SOURCE_BUSY")
    rec = health.DailyReviewAdapter().read(health.HealthReadContext(now_utc=datetime.now(timezone.utc)))
    assert rec["last_success_at"] is None
    assert rec["refresh_attempt"]["reason_code"] == "SOURCE_BUSY"


def test_persistence_failure_is_not_collection_success(monkeypatch):
    monkeypatch.setattr(dr, "_build_daily_review", lambda: _packet())
    monkeypatch.setattr(cache, "save_latest_review", lambda *args, **kwargs: False)
    with pytest.raises(dr.DailyReviewRefreshError):
        dr.refresh_daily_review_for_display()
    assert dr.latest_refresh_attempt()["reason_code"] == "persist_failed"
    assert not dr._review_cache


def test_generation_fencing_and_fixed_public_vocabulary():
    dr._start_refresh_attempt(1)
    dr._start_refresh_attempt(2)
    dr._finish_refresh_attempt(2, _packet())
    success = dr.latest_refresh_attempt()
    dr._finish_refresh_attempt(1, reason="SOURCE_TIMEOUT")
    assert dr.latest_refresh_attempt() == success
    dr._start_refresh_attempt(3)
    dr._finish_refresh_attempt(3, {"collection": {"failed": ["https://private/token"],
        "pending": ["password"], "reason_code": "https://private/token"}}, reason="secret exception")
    result = dr.latest_refresh_attempt()
    assert result["reason_code"] == "build_exception"
    assert result["failed_sources"] == result["pending_sources"] == []
    assert "private" not in str(result) and "secret" not in str(result)
    result["state"] = "altered"
    assert dr.latest_refresh_attempt()["state"] == "failed"


def test_persistence_reason_is_not_masked_by_optional_timeout():
    dr._start_refresh_attempt(1)
    value = _packet()
    value["collection"] = {"reason_code": "SOURCE_TIMEOUT", "pending": ["region"]}
    dr._finish_refresh_attempt(1, value, reason="persist_failed")
    attempt = dr.latest_refresh_attempt()
    assert attempt["reason_code"] == "persist_failed"
    assert attempt["stage"] == "persistence"


def test_unexpected_post_collection_error_finishes_attempt_safely(monkeypatch):
    monkeypatch.setattr(dr, "_build_daily_review", lambda: _packet())
    def broken(*args, **kwargs):
        raise RuntimeError("https://private/token")
    monkeypatch.setattr(dr, "_store_review_on_refresh", broken)
    with pytest.raises(dr.DailyReviewRefreshError):
        dr.refresh_daily_review_for_display()
    attempt = dr.latest_refresh_attempt()
    assert attempt["state"] == "failed" and attempt["reason_code"] == "build_exception"
    assert "private" not in str(attempt)


def test_health_rejects_unsafe_attempt_shape():
    adapter = health.DailyReviewAdapter()
    record = adapter.read(health.HealthReadContext(now_utc=datetime.now(timezone.utc)))
    record["refresh_attempt"] = {"url": "https://private/token"}
    with pytest.raises(RuntimeError, match="refresh_attempt"):
        health.validate_data_health_record(adapter, record)


def test_swallowed_cooldown_preserves_safe_source_reason_without_reset(monkeypatch):
    import market
    import astock
    import daily_review_sources as sources
    import push2_guard
    from pathlib import Path
    # Entirely synthetic guard database under tmp VR_DATA_DIR.
    push2_guard.record("refusal")
    before = Path(push2_guard._path()).read_bytes()
    monkeypatch.setattr(market, "get_a_share_snapshot_observation", push2_guard.reserve)
    monkeypatch.setattr(astock, "index_quote", lambda: [{"code": "fixture"}])
    monkeypatch.setattr(market, "get_global_indices", lambda: [])
    monkeypatch.setattr(market, "get_short_term_emotion", lambda: {"zt_count": 1})
    monkeypatch.setattr(market, "get_turnover_top", lambda: {"stocks": []})
    monkeypatch.setattr(market, "get_board_ranking", lambda *args, **kwargs: {"status": "normal", "data": {}})
    packet = sources.collect(lambda value: None)
    breadth = packet["sources"]["breadth"]
    # The provider caught the block: task complete does not mean data usable.
    assert breadth["status"] == "complete" and breadth["value"]["status"] == "unavailable"
    assert breadth["reason_code"] == "SOURCE_COOLDOWN"
    assert "reason_code" not in packet["sources"]["indices"]
    monkeypatch.setattr(budget, "run", lambda *args, **kwargs: packet)
    with pytest.raises(dr.DailyReviewRefreshError):
        dr.refresh_daily_review_for_display()
    attempt = dr.latest_refresh_attempt()
    assert attempt["source_errors"] == {"breadth": "SOURCE_COOLDOWN"}
    assert attempt["reason_code"] == "SOURCE_COOLDOWN" and attempt["stage"] == "collection"
    assert Path(push2_guard._path()).read_bytes() == before


def test_legacy_block_exception_is_unknown_not_guessed_cooldown():
    import push2_guard
    with push2_guard.observe_blocks() as codes:
        old = push2_guard.Push2Blocked("https://private/token")
        invalid = push2_guard.Push2Blocked("secret", code="https://private/token")
    assert old.code == invalid.code == "SOURCE_BLOCKED"
    assert codes == ["SOURCE_BLOCKED", "SOURCE_BLOCKED"]
    assert str(old) == "https://private/token"  # exception compatibility, not public projection
    with push2_guard.observe_blocks() as independent:
        pass
    assert independent == []


def test_optional_cooldown_does_not_explain_unknown_critical_failure():
    dr._start_refresh_attempt(1)
    value = _packet(status="partial", critical_bad=True)
    value["data_health"]["components"]["region_boards"] = "unavailable"
    value["collection"] = {"source_errors": {"region": "SOURCE_COOLDOWN"}}
    dr._finish_refresh_attempt(1, value, reason="critical_unavailable")
    attempt = dr.latest_refresh_attempt()
    assert attempt["reason_code"] == "critical_unavailable"
    assert attempt["source_errors"] == {"region": "SOURCE_COOLDOWN"}
