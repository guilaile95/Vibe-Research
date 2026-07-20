"""市场广度 calculate_market_breadth / get_a_share_snapshot 离线测试（Mock 快照，不联网）。"""
from __future__ import annotations

import pytest

import market


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


# ── 纯计算：涨跌互斥与 up_ratio ─────────────────────────────────────

def test_breadth_up_down_flat_partition():
    snap = [
        _s("000001", change_pct=2.0),
        _s("000002", change_pct=-1.0),
        _s("000003", change_pct=0.0),
        _s("000004", change_pct=3.5),
        _s("000005", change_pct=-3.0),
        _s("000006", change_pct=None),  # 无效，不计入 valid
        _s("000007", change_pct=None),
    ]

    b = market.calculate_market_breadth(snap)
    assert b["stock_count"] == 7
    assert b["valid_count"] == 5
    assert b["up_count"] == 2      # 2.0, 3.5
    assert b["down_count"] == 2    # -1.0, -3.0
    assert b["flat_count"] == 1    # 0.0
    assert b["up_count"] + b["down_count"] + b["flat_count"] == b["valid_count"]
    assert b["up_ratio"] == pytest.approx(0.4)  # 2/5
    assert b["up_3pct_count"] == 1   # 3.5
    assert b["down_3pct_count"] == 1  # -3.0


def test_breadth_empty_and_all_invalid_pct():
    b0 = market.calculate_market_breadth([])
    assert b0["stock_count"] == 0
    assert b0["valid_count"] == 0
    assert b0["up_ratio"] is None
    assert b0["total_amount"] is None
    assert b0["amount_valid_count"] == 0
    assert b0["amount_top"] == []
    assert b0["high_turnover"] == []

    b1 = market.calculate_market_breadth([
        _s(change_pct=None, amount=None, turnover_pct=None),
        _s("000002", change_pct=None, amount=None, turnover_pct=None),
    ])
    assert b1["valid_count"] == 0
    assert b1["up_ratio"] is None
    assert b1["total_amount"] is None


def test_breadth_total_amount_skips_missing():
    snap = [
        _s("000001", amount=100.0),
        _s("000002", amount=None),
        _s("000003", amount=50.0),
        _s("000004", amount=-1.0),  # 负值不计入
    ]
    b = market.calculate_market_breadth(snap)
    assert b["amount_valid_count"] == 2
    assert b["total_amount"] == pytest.approx(150.0)


def test_breadth_amount_top_order_and_fields():
    snap = [
        _s("000001", name="小", amount=10.0, change_pct=1.0, turnover_pct=1.0),
        _s("000002", name="大", amount=100.0, change_pct=-0.5, turnover_pct=2.0),
        _s("000003", name="中", amount=50.0, change_pct=0.0, turnover_pct=3.0),
        _s("000004", name="无额", amount=None, change_pct=1.0),
    ]
    b = market.calculate_market_breadth(snap, amount_top_n=2)
    top = b["amount_top"]
    assert len(top) == 2
    assert [x["code"] for x in top] == ["000002", "000003"]
    assert top[0]["amount"] == pytest.approx(100.0)
    assert set(top[0].keys()) == {
        "code", "name", "price", "change_pct", "amount", "turnover_pct", "market_cap",
    }


def test_breadth_high_turnover_threshold_and_order():
    snap = [
        _s("000001", turnover_pct=20.0, amount=1.0),
        _s("000002", turnover_pct=15.0, amount=2.0),
        _s("000003", turnover_pct=14.9, amount=3.0),  # 不进榜
        _s("000004", turnover_pct=None, amount=4.0),
        _s("000005", turnover_pct=30.0, amount=5.0),
    ]
    b = market.calculate_market_breadth(snap, high_turnover_n=10, high_turnover_min=15.0)
    ht = b["high_turnover"]
    assert [x["code"] for x in ht] == ["000005", "000001", "000002"]
    assert all(x["turnover_pct"] >= 15 for x in ht)
    assert set(ht[0].keys()) == {
        "code", "name", "price", "change_pct", "amount", "turnover_pct", "market_cap",
    }


# ── 共享缓存 get_a_share_snapshot ───────────────────────────────────

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
    assert a is b or a == b
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
    assert calls["n"] == 2  # 空列表不缓存，每次重抓
    market._CACHE.clear()


def test_get_a_share_snapshot_propagates_error(monkeypatch):
    market._CACHE.clear()

    def boom():
        raise RuntimeError("upstream failed")

    monkeypatch.setattr(market.astock, "a_share_snapshot", boom)
    with pytest.raises(RuntimeError, match="upstream failed"):
        market.get_a_share_snapshot()
    market._CACHE.clear()


def test_get_market_breadth_uses_shared_snapshot(monkeypatch):
    market._CACHE.clear()
    calls = {"n": 0}
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
    # 两次 get_market_breadth 应复用同一缓存快照
    assert calls["n"] == 1
    assert b1["up_count"] == 1
    assert b1["down_count"] == 1
    assert b1["flat_count"] == 1
    assert b1["valid_count"] == 3
    assert b1["stock_count"] == 3
    assert b2["total_amount"] == pytest.approx(150.0)
    assert b1["amount_top"][0]["code"] == "000001"
    assert b1["high_turnover"][0]["code"] == "000001"
    market._CACHE.clear()
