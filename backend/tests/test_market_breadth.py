"""市场广度 calculate_market_breadth / get_market_breadth 信封契约离线测试（Mock 快照，不联网）。"""
from __future__ import annotations

import pytest

import market

_ENVELOPE_KEYS = {
    "status", "source", "trade_date", "data_time",
    "fetched_at", "is_stale", "warnings", "data",
}


def _s(
    code="600519",
    name="测试股",
    *,
    price=10.0,
    change_pct=1.0,
    amount=1e8,
    turnover_pct=5.0,
    market_cap=1e10,
    **extra,
):
    row = {
        "code": code,
        "name": name,
        "market": 1,
        "price": price,
        "change_pct": change_pct,
        "change": None,
        "volume": None,
        "amount": amount,
        "amplitude_pct": None,
        "turnover_pct": turnover_pct,
        "high": None,
        "low": None,
        "open": None,
        "prev_close": None,
        "market_cap": market_cap,
        "float_market_cap": None,
    }
    row.update(extra)
    return row


def _assert_envelope(env: dict):
    assert set(env.keys()) == _ENVELOPE_KEYS
    assert env["source"] == "eastmoney_push2"
    assert env["trade_date"] is None
    assert env["data_time"] is None
    assert isinstance(env["fetched_at"], str) and len(env["fetched_at"]) >= 10
    assert isinstance(env["is_stale"], bool)
    assert isinstance(env["warnings"], list)
    assert env["status"] in ("normal", "partial", "unavailable")


# ── 纯计算 ─────────────────────────────────────────────────────────

def test_breadth_up_down_flat_partition():
    snap = [
        _s("000001", change_pct=2.0),
        _s("000002", change_pct=-1.0),
        _s("000003", change_pct=0.0),
        _s("000004", change_pct=3.5),
        _s("000005", change_pct=-3.0),
        _s("000006", change_pct=None),
        _s("000007", change_pct=None),
    ]
    b = market.calculate_market_breadth(snap)
    assert b["stock_count"] == 7
    assert b["valid_count"] == 5
    assert b["up_count"] == 2
    assert b["down_count"] == 2
    assert b["flat_count"] == 1
    assert b["up_count"] + b["down_count"] + b["flat_count"] == b["valid_count"]
    assert b["up_ratio"] == pytest.approx(0.4)
    assert b["up_3pct_count"] == 1
    assert b["down_3pct_count"] == 1


def test_breadth_empty_and_all_invalid_pct():
    b0 = market.calculate_market_breadth([])
    assert b0["stock_count"] == 0
    assert b0["valid_count"] == 0
    assert b0["up_ratio"] is None
    assert b0["total_amount"] is None

    b1 = market.calculate_market_breadth([
        _s(change_pct=None, amount=None, turnover_pct=None),
        _s("000002", change_pct=None, amount=None, turnover_pct=None),
    ])
    assert b1["valid_count"] == 0
    assert b1["up_ratio"] is None


def test_breadth_total_amount_skips_missing():
    snap = [
        _s("000001", amount=100.0),
        _s("000002", amount=None),
        _s("000003", amount=50.0),
        _s("000004", amount=-1.0),
    ]
    b = market.calculate_market_breadth(snap)
    assert b["amount_valid_count"] == 2
    assert b["total_amount"] == pytest.approx(150.0)


def test_breadth_amount_top_order_and_fields():
    snap = [
        _s("000001", name="小", amount=10.0),
        _s("000002", name="大", amount=100.0),
        _s("000003", name="中", amount=50.0),
        _s("000004", name="无额", amount=None),
    ]
    b = market.calculate_market_breadth(snap, amount_top_n=2)
    top = b["amount_top"]
    assert [x["code"] for x in top] == ["000002", "000003"]
    assert set(top[0].keys()) == {
        "code", "name", "price", "change_pct", "amount", "turnover_pct", "market_cap",
    }


def test_breadth_high_turnover_threshold_and_order():
    snap = [
        _s("000001", turnover_pct=20.0),
        _s("000002", turnover_pct=15.0),
        _s("000003", turnover_pct=14.9),
        _s("000004", turnover_pct=None),
        _s("000005", turnover_pct=30.0),
    ]
    b = market.calculate_market_breadth(snap, high_turnover_n=10, high_turnover_min=15.0)
    ht = b["high_turnover"]
    assert [x["code"] for x in ht] == ["000005", "000001", "000002"]


# ── 缓存 ────────────────────────────────────────────────────────────

def test_get_a_share_snapshot_caches(monkeypatch):
    market._CACHE.clear()
    calls = {"n": 0}
    data = [_s("600519"), _s("000001")]

    def fake():
        calls["n"] += 1
        return list(data)

    monkeypatch.setattr(market.astock, "a_share_snapshot", fake)
    a = market.get_a_share_snapshot()
    b = market.get_a_share_snapshot()
    assert calls["n"] == 1
    assert len(a) == 2
    market._CACHE.clear()


def test_get_a_share_snapshot_empty_not_cached(monkeypatch):
    market._CACHE.clear()
    calls = {"n": 0}

    def fake():
        calls["n"] += 1
        return []

    monkeypatch.setattr(market.astock, "a_share_snapshot", fake)
    assert market.get_a_share_snapshot() == []
    assert market.get_a_share_snapshot() == []
    assert calls["n"] == 2
    market._CACHE.clear()


def test_get_a_share_snapshot_propagates_error(monkeypatch):
    market._CACHE.clear()

    def boom():
        raise RuntimeError("upstream failed")

    monkeypatch.setattr(market.astock, "a_share_snapshot", boom)
    with pytest.raises(RuntimeError, match="upstream failed"):
        market.get_a_share_snapshot()
    market._CACHE.clear()


# ── get_market_breadth 状态信封 ─────────────────────────────────────

def test_get_market_breadth_normal_envelope(monkeypatch):
    """完整覆盖快照 → normal；含元数据缺失 warning。"""
    market._CACHE.clear()
    # 3500 只、涨跌幅与成交额齐全 → 覆盖充分
    snap = [
        _s(f"{i:06d}", change_pct=1.0 if i % 2 == 0 else -0.5, amount=1e7)
        for i in range(3500)
    ]
    monkeypatch.setattr(market, "get_a_share_snapshot", lambda: snap)
    env = market.get_market_breadth()
    _assert_envelope(env)
    assert env["status"] == "normal"
    assert env["data"] is not None
    assert env["data"]["stock_count"] == 3500
    assert env["data"]["valid_count"] == 3500
    assert any("交易日期" in w or "行情时间" in w for w in env["warnings"])
    market._CACHE.clear()


def test_get_market_breadth_partial_low_valid_pct(monkeypatch):
    """股票数足够，但有效涨跌幅比例 < 0.8 → partial。"""
    market._CACHE.clear()
    # 3200 只；仅 50% 有 change_pct
    snap = []
    for i in range(3200):
        pct = 1.0 if i < 1600 else None
        snap.append(_s(f"{i:06d}", change_pct=pct, amount=1e7))
    monkeypatch.setattr(market, "get_a_share_snapshot", lambda: snap)
    env = market.get_market_breadth()
    _assert_envelope(env)
    assert env["status"] == "partial"
    assert env["data"] is not None
    assert env["data"]["stock_count"] == 3200
    assert env["data"]["valid_count"] == 1600
    assert any("涨跌幅" in w for w in env["warnings"])
    market._CACHE.clear()


def test_get_market_breadth_partial_low_amount_ratio(monkeypatch):
    """股票数足够，成交额有效比例 < 0.8 → partial。"""
    market._CACHE.clear()
    snap = []
    for i in range(3200):
        amt = 1e7 if i < 1000 else None  # ~31% 有成交额
        snap.append(_s(f"{i:06d}", change_pct=0.5, amount=amt))
    monkeypatch.setattr(market, "get_a_share_snapshot", lambda: snap)
    env = market.get_market_breadth()
    _assert_envelope(env)
    assert env["status"] == "partial"
    assert env["data"] is not None
    assert any("成交额" in w for w in env["warnings"])
    market._CACHE.clear()


def test_get_market_breadth_empty_snapshot_unavailable(monkeypatch):
    market._CACHE.clear()
    monkeypatch.setattr(market, "get_a_share_snapshot", lambda: [])
    env = market.get_market_breadth()
    _assert_envelope(env)
    assert env["status"] == "unavailable"
    assert env["data"] is None
    assert any("空" in w for w in env["warnings"])
    # 不返回全 0 统计
    assert env["data"] is None
    market._CACHE.clear()


def test_get_market_breadth_snapshot_error_unavailable(monkeypatch):
    market._CACHE.clear()

    def boom():
        raise RuntimeError("timeout")

    monkeypatch.setattr(market, "get_a_share_snapshot", boom)
    env = market.get_market_breadth()  # 不向外抛
    _assert_envelope(env)
    assert env["status"] == "unavailable"
    assert env["data"] is None
    assert any("timeout" in w for w in env["warnings"])
    market._CACHE.clear()


def test_get_market_breadth_envelope_keys_all_statuses(monkeypatch):
    """三种状态顶层键一致。"""
    market._CACHE.clear()
    cases = []

    # normal
    snap_ok = [
        _s(f"{i:06d}", change_pct=1.0, amount=1e7) for i in range(3500)
    ]
    monkeypatch.setattr(market, "get_a_share_snapshot", lambda: snap_ok)
    cases.append(market.get_market_breadth())

    # partial (count < 3000)
    snap_few = [_s(f"{i:06d}", change_pct=1.0, amount=1e7) for i in range(100)]
    monkeypatch.setattr(market, "get_a_share_snapshot", lambda: snap_few)
    market._CACHE.clear()
    cases.append(market.get_market_breadth())

    # unavailable
    monkeypatch.setattr(market, "get_a_share_snapshot", lambda: [])
    market._CACHE.clear()
    cases.append(market.get_market_breadth())

    assert [c["status"] for c in cases] == ["normal", "partial", "unavailable"]
    for c in cases:
        _assert_envelope(c)
    market._CACHE.clear()


def test_get_market_breadth_uses_shared_snapshot(monkeypatch):
    """两次 get_market_breadth 复用同一缓存快照（经 get_a_share_snapshot）。"""
    market._CACHE.clear()
    calls = {"n": 0}
    # 小样本 → partial，但两次应只抓一次底层快照
    snap = [
        _s("000001", change_pct=1.0, amount=100.0, turnover_pct=20.0),
        _s("000002", change_pct=-1.0, amount=50.0, turnover_pct=5.0),
        _s("000003", change_pct=0.0, amount=None, turnover_pct=None),
    ]

    def fake():
        calls["n"] += 1
        return snap

    monkeypatch.setattr(market.astock, "a_share_snapshot", fake)
    b1 = market.get_market_breadth()
    b2 = market.get_market_breadth()
    assert calls["n"] == 1
    assert b1["status"] == b2["status"] == "partial"
    assert b1["data"]["up_count"] == 1
    assert b1["data"]["down_count"] == 1
    assert b1["data"]["flat_count"] == 1
    market._CACHE.clear()
