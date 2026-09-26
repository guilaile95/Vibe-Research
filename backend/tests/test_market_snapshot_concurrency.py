"""全 A 快照 single-flight：离线、小 fixture、事件控制并发顺序。"""
from concurrent.futures import Future, ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace

import pytest

import market


@pytest.fixture
def snapshot_state(monkeypatch):
    monkeypatch.setattr(market, "_CACHE", {})
    monkeypatch.setattr(market, "_A_SHARE_SNAPSHOT_FLIGHT", None)
    joined = Event()

    class ObservedFuture(Future):
        def result(self, timeout=None):
            joined.set()
            return super().result(timeout=timeout)

    monkeypatch.setattr(market, "Future", ObservedFuture)
    return joined


@pytest.mark.parametrize("outcome", ["success", "failure", "empty"])
def test_concurrent_snapshot_shares_one_fetch(monkeypatch, snapshot_state, outcome):
    started, release = Event(), Event()
    snapshot = [{"code": "600001", "name": "测试股"}]
    failure = RuntimeError("incomplete snapshot")
    calls = 0

    def fetch():
        nonlocal calls
        calls += 1
        if calls == 1:
            started.set()
            assert release.wait(5), "test did not release fetch"
            if outcome == "failure":
                raise failure
            if outcome == "empty":
                return []
        return snapshot

    monkeypatch.setattr(market.astock, "a_share_snapshot", fetch)
    with ThreadPoolExecutor(max_workers=2) as pool:
        leader = pool.submit(market.get_a_share_snapshot)
        try:
            assert started.wait(5)
            follower = pool.submit(market.get_a_share_snapshot)
            assert snapshot_state.wait(5), "follower did not join flight"
            assert calls == 1
        finally:
            release.set()

        if outcome == "failure":
            for result in (leader, follower):
                with pytest.raises(RuntimeError, match="incomplete snapshot") as caught:
                    result.result(timeout=5)
                assert caught.value is failure
        else:
            first = leader.result(timeout=5)
            assert follower.result(timeout=5) is first
            assert first == (snapshot if outcome == "success" else [])

    assert calls == 1
    if outcome != "success":
        assert "a_share_snapshot" not in market._CACHE
    assert market.get_a_share_snapshot() is snapshot
    assert calls == (1 if outcome == "success" else 2)


def test_snapshot_ttl_starts_at_fetch_completion(monkeypatch, snapshot_state):
    clock = SimpleNamespace(now=1000.0)
    monkeypatch.setattr(market, "time", SimpleNamespace(time=lambda: clock.now))
    calls = 0
    snapshot = [{"code": "600001", "name": "测试股"}]

    def fetch():
        nonlocal calls
        calls += 1
        clock.now += 120
        return snapshot

    monkeypatch.setattr(market.astock, "a_share_snapshot", fetch)
    assert market.get_a_share_snapshot() is snapshot
    assert market._CACHE["a_share_snapshot"][0] == 1120
    clock.now = 1120 + market._TTL - 1
    assert market.get_a_share_snapshot() is snapshot
    assert calls == 1
    clock.now += 1
    assert market.get_a_share_snapshot() is snapshot
    assert calls == 2


def test_waiter_timeout_keeps_leader_and_expired_cache(monkeypatch, snapshot_state):
    started, release = Event(), Event()
    old = [{"code": "600001", "name": "旧快照"}]
    new = [{"code": "600001", "name": "新快照"}]
    stale = (market.time.time() - market._TTL - 1, old)
    market._CACHE["a_share_snapshot"] = stale
    monkeypatch.setattr(market, "_A_SHARE_SNAPSHOT_WAIT_SECONDS", 0.01)
    calls = 0

    def fetch():
        nonlocal calls
        calls += 1
        started.set()
        assert release.wait(5), "test did not release fetch"
        return new

    monkeypatch.setattr(market.astock, "a_share_snapshot", fetch)
    with ThreadPoolExecutor(max_workers=2) as pool:
        leader = pool.submit(market.get_a_share_snapshot)
        try:
            assert started.wait(5)
            # 超时后另一请求仍加入原 flight，不另起抓取、不刷新旧值。
            for _ in range(2):
                follower = pool.submit(market.get_a_share_snapshot)
                with pytest.raises(TimeoutError):
                    follower.result(timeout=5)
                assert follower.done()
                assert not leader.done()
                assert calls == 1
                assert market._CACHE["a_share_snapshot"] is stale
        finally:
            release.set()
        assert leader.result(timeout=5) is new

    assert market.get_a_share_snapshot() is new
    assert calls == 1
