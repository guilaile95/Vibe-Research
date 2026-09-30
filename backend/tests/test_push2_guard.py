"""Deterministic safety-state tests; all transport responses are synthetic."""
from concurrent.futures import ThreadPoolExecutor
import importlib
from types import SimpleNamespace

import pytest
import astock
import push2_guard as guard


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("VR_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(astock, "_em_last_call", [0.0])


def _transport(monkeypatch, status=200, error=None):
    calls = []
    def get(url, **kwargs):
        calls.append(url)
        if error:
            raise error
        return SimpleNamespace(status_code=status, close=lambda: None)
    monkeypatch.setattr(astock, "_em_session", lambda _: SimpleNamespace(get=get))
    return calls


@pytest.mark.parametrize("status", [403, 429])
def test_refusal_stops_alternate_hosts_and_survives_reload(monkeypatch, status):
    calls = _transport(monkeypatch, status)
    with pytest.raises(guard.Push2Blocked):
        astock.a_share_snapshot()
    assert len(calls) == 1
    importlib.reload(guard)
    for host in ["push2delay", "push2ex", "42.push2"]:
        with pytest.raises(guard.Push2Blocked):
            astock.em_get(f"https://{host}.eastmoney.com/api/test", min_interval=0)
    assert len(calls) == 1
    astock.em_get("https://datacenter-web.eastmoney.com/api/test", min_interval=0)
    assert len(calls) == 2


@pytest.mark.parametrize("error,status", [(None, 503), (ConnectionResetError("reset"), 200)])
def test_repeated_failures_trip_cooldown(monkeypatch, error, status):
    calls = _transport(monkeypatch, status, error)
    for _ in range(3):
        with pytest.raises(Exception):
            astock.em_get("https://push2.eastmoney.com/test", min_interval=0)
    with pytest.raises(guard.Push2Blocked):
        astock.em_get("https://push2delay.eastmoney.com/test", min_interval=0)
    assert len(calls) == 3


def test_budget_atomic_concurrent_and_day_rollover(monkeypatch):
    monkeypatch.setattr(guard, "DAILY_LIMIT", 5)
    now = [1727740790.0]
    monkeypatch.setattr(guard.time, "time", lambda: now[0])
    def reserve(_):
        try:
            guard.reserve()
            return True
        except guard.Push2Blocked:
            return False
    with ThreadPoolExecutor(max_workers=10) as pool:
        assert sum(pool.map(reserve, range(20))) == 5
    now[0] += 86400
    guard.reserve()
    guard.record("refusal")
    now[0] += 20
    with pytest.raises(guard.Push2Blocked):
        guard.reserve()
    now[0] += guard.REFUSAL_COOLDOWN
    guard.reserve()


def test_day_rollover_does_not_clear_refusal(monkeypatch):
    now = [1727740799.0]
    monkeypatch.setattr(guard.time, "time", lambda: now[0])
    guard.reserve()
    guard.record("refusal")
    now[0] += 2
    with pytest.raises(guard.Push2Blocked):
        guard.reserve()


def test_bad_state_blocks_before_network(monkeypatch):
    guard._path().write_bytes(b"not a database")
    calls = _transport(monkeypatch)
    with pytest.raises(guard.Push2Blocked, match="state is unavailable"):
        astock.em_get("https://push2.eastmoney.com/test", min_interval=0)
    assert calls == []


def test_source_matching_is_bounded():
    assert not guard.applies("https://push2.eastmoney.com.evil.test")
    assert not guard.applies("https://datacenter.eastmoney.com")
    assert not guard.applies("https://push2his.eastmoney.com")
    assert guard.applies("https://push2delay.eastmoney.com")


def test_success_resets_consecutive_failures():
    guard.record("failure")
    guard.record("failure")
    guard.record("success")
    guard.record("failure")
    guard.reserve()


def test_budget_wait_cannot_allow_expired_request(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(astock.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(guard, "reserve", lambda: now.__setitem__(0, 102.0))
    calls = _transport(monkeypatch)
    with pytest.raises(RuntimeError, match="budget exhausted"):
        astock.em_get("https://push2.eastmoney.com/test", min_interval=0, deadline=101.0)
    assert calls == []


def test_ai_delay_route_cannot_bypass_source_cooldown(monkeypatch):
    import ai_tools
    calls = _transport(monkeypatch)
    guard.record("refusal")
    with pytest.raises(guard.Push2Blocked):
        ai_tools._fund_flow_today("600519")
    assert calls == []


def test_refused_request_does_not_mutate_persisted_safety_state(monkeypatch):
    guard.record("refusal")
    path = guard._path()
    before = (path.read_bytes(), path.stat().st_mtime_ns)
    calls = _transport(monkeypatch)
    with pytest.raises(guard.Push2Blocked, match="cooldown"):
        astock.em_get("https://push2.eastmoney.com/test", min_interval=0)
    assert calls == []
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before


def test_permitted_request_consumes_persisted_operational_budget(monkeypatch):
    import sqlite3
    calls = _transport(monkeypatch)
    astock.em_get("https://push2.eastmoney.com/test", min_interval=0)
    astock.em_get("https://push2.eastmoney.com/test", min_interval=0)
    assert len(calls) == 2
    with sqlite3.connect(guard._path()) as conn:
        assert conn.execute("SELECT used FROM guard WHERE id=1").fetchone() == (2,)


def test_read_only_blocks_before_storage_and_network(monkeypatch):
    calls = _transport(monkeypatch)
    with guard.read_only(), pytest.raises(guard.Push2Blocked, match="writable"):
        astock.em_get("https://push2.eastmoney.com/test", min_interval=0)
    assert calls == []
    assert not guard._path().exists()
    guard.reserve()
    before = (guard._path().read_bytes(), guard._path().stat().st_mtime_ns)
    with guard.read_only():
        for operation in [guard.reserve, lambda: guard.record("success")]:
            with pytest.raises(guard.Push2Blocked):
                operation()
    assert (guard._path().read_bytes(), guard._path().stat().st_mtime_ns) == before
    assert not guard.is_read_only()


def test_read_only_context_propagates_through_fastapi_threadpool(monkeypatch):
    import asyncio
    from starlette.concurrency import run_in_threadpool
    calls = _transport(monkeypatch)

    async def request():
        with guard.read_only():
            with pytest.raises(guard.Push2Blocked):
                await run_in_threadpool(astock.em_get, "https://push2.eastmoney.com/test", min_interval=0)
    asyncio.run(request())
    assert calls == []
    assert not guard._path().exists()


def test_concurrent_read_only_and_writable_requests_are_isolated(monkeypatch):
    from threading import Barrier
    calls = _transport(monkeypatch)
    barrier = Barrier(2)

    def readonly():
        with guard.read_only():
            barrier.wait()
            with pytest.raises(guard.Push2Blocked):
                astock.em_get("https://push2.eastmoney.com/test", min_interval=0)

    def writable():
        barrier.wait()
        astock.em_get("https://push2.eastmoney.com/test", min_interval=0)

    with ThreadPoolExecutor(max_workers=2) as pool:
        a, b = pool.submit(readonly), pool.submit(writable)
        a.result(); b.result()
    assert len(calls) == 1


def test_read_only_snapshot_reuses_cache_without_poisoning_normal_flight(monkeypatch):
    import market
    monkeypatch.setattr(market, "_CACHE", {})
    monkeypatch.setattr(market, "_A_SHARE_SNAPSHOT_FLIGHT", None)
    calls = []
    monkeypatch.setattr(astock, "a_share_snapshot", lambda: calls.append(True) or [{"code": "600519"}])
    with guard.read_only():
        assert market.get_market_breadth()["status"] == "unavailable"
    assert calls == []
    assert market._A_SHARE_SNAPSHOT_FLIGHT is None
    normal = market.get_a_share_snapshot_observation()
    with guard.read_only():
        cached = market.get_a_share_snapshot_observation()
    assert calls == [True]
    assert cached["rows"] == normal["rows"]
    assert cached["fetched_at"] == normal["fetched_at"]
    assert cached["is_cached"] is True


def test_inbox_assembler_enters_and_restores_read_only_source_context():
    import decision_inbox_runtime_assembler as inbox
    from dataclasses import replace

    def composition():
        assert guard.is_read_only()
        return {"evaluation_status": "NOT_EVALUATED"}
    result = inbox.assemble_current_decision_inbox(
        ports=replace(inbox.PRODUCTION_PORTS, composition_reader=composition))
    assert result["evaluation_status"] == "NOT_EVALUATED"
    assert not guard.is_read_only()


def test_read_only_cold_snapshot_does_not_join_writable_inflight(monkeypatch):
    import market
    from concurrent.futures import Future
    flight = Future()
    monkeypatch.setattr(market, "_CACHE", {})
    monkeypatch.setattr(market, "_A_SHARE_SNAPSHOT_FLIGHT", flight)
    with guard.read_only(), pytest.raises(guard.Push2Blocked):
        market.get_a_share_snapshot_observation()
    assert market._A_SHARE_SNAPSHOT_FLIGHT is flight
    assert not flight.done()
    assert not guard._path().exists()


def test_nested_source_context_remains_blocked_in_explicit_thread_handoff(monkeypatch):
    from contextvars import copy_context
    calls = _transport(monkeypatch)
    with ThreadPoolExecutor(max_workers=1) as outer, ThreadPoolExecutor(max_workers=1) as inner:
        def nested():
            with guard.read_only():
                return inner.submit(copy_context().run, guard.reserve).result()
        with guard.read_only(), pytest.raises(guard.Push2Blocked):
            outer.submit(copy_context().run, nested).result()
    assert calls == []
    assert not guard._path().exists()


def test_inbox_capability_workers_preserve_source_context(monkeypatch):
    import decision_inbox_runtime_assembler as inbox
    import campaign_critical_data_runtime as cdr
    from dataclasses import replace
    calls = _transport(monkeypatch)
    as_of = "2026-09-30T00:00:00Z"
    dependency = cdr.market_sector_adapter.DEPENDENCY_ID
    definition = {"required_dependency_ids": [dependency], "as_of": as_of}

    def evaluator(_lake, definition):
        try:
            astock.em_get("https://push2.eastmoney.com/test", min_interval=0)
            state = "USABLE"
        except guard.Push2Blocked:
            state = "UNKNOWN"
        return {"dependency_id": dependency, "as_of": definition["as_of"], "state": state}

    ports = replace(inbox.PRODUCTION_PORTS, market_sector_evaluator=evaluator)
    with guard.read_only():
        results = inbox._capability_results(definition, lake=None, ports=ports)
    assert results[0]["state"] == "UNKNOWN"
    assert calls == []
    assert not guard._path().exists()
    results = inbox._capability_results(definition, lake=None, ports=ports)
    assert results[0]["state"] == "USABLE"
    assert len(calls) == 1
