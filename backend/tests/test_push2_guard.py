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
