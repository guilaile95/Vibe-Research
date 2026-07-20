"""a_share_snapshot 分页完整性离线测试（Mock 网络，不打真实东财）。

覆盖：上游每页强制 100 条、多页合并、去重、重复页保护、失败不返回半截数据。
"""
from __future__ import annotations

import json

import pytest

import astock
import market


def _row(code: str, name: str | None = None, **extra):
    d = {
        "f2": 10.0, "f3": 1.0, "f4": 0.1, "f5": 1000.0, "f6": 1e7, "f7": 1.0, "f8": 1.0,
        "f12": code, "f13": 1, "f14": name if name is not None else f"股{code}",
        "f15": 11.0, "f16": 9.0, "f17": 10.0, "f18": 9.9,
        "f20": 1e9, "f21": 1e9,
    }
    d.update(extra)
    return d


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


def _install(monkeypatch, handler):
    calls: list[dict] = []

    def fake_em_get(url, params=None, headers=None, timeout=15):
        calls.append({"url": url, "params": dict(params or {})})
        return _FakeResp(handler(url, params or {}))

    monkeypatch.setattr(astock, "em_get", fake_em_get)
    monkeypatch.setattr(astock, "_EM_MIN_INTERVAL", 0)
    monkeypatch.setattr(astock, "_em_last_call", [0.0])
    return calls


def _codes(n: int, start: int = 0) -> list[dict]:
    """生成 n 条合法 6 位代码。"""
    rows = []
    for i in range(start, start + n):
        code = f"{i % 1000000:06d}"
        rows.append(_row(code, f"N{code}"))
    return rows


# ---------------------------------------------------------------------------
# 1–3 多页 / 上游限 100 / 末页不足
# ---------------------------------------------------------------------------

def test_multi_page_complete_250(monkeypatch):
    """total=250, page_size=100 → 3 页 100+100+50。"""
    def handler(url, params):
        pn = int(params["pn"])
        assert params["pz"] == "100"
        if pn == 1:
            return {"data": {"total": 250, "diff": _codes(100, 0)}}
        if pn == 2:
            return {"data": {"total": 250, "diff": _codes(100, 100)}}
        if pn == 3:
            return {"data": {"total": 250, "diff": _codes(50, 200)}}
        raise AssertionError(f"unexpected page {pn}")

    calls = _install(monkeypatch, handler)
    out = astock.a_share_snapshot(page_size=100)
    assert len(calls) == 3
    assert [c["params"]["pn"] for c in calls] == ["1", "2", "3"]
    assert len(out) == 250
    assert len({x["code"] for x in out}) == 250


def test_upstream_caps_at_100_despite_larger_pz(monkeypatch):
    """请求 pz=200，上游每页仍只回 100；total=250 时必须继续翻页。"""
    def handler(url, params):
        pn = int(params["pn"])
        assert params["pz"] == "200"
        # 上游强制最多 100
        if pn == 1:
            return {"data": {"total": 250, "diff": _codes(100, 0)}}
        if pn == 2:
            return {"data": {"total": 250, "diff": _codes(100, 100)}}
        if pn == 3:
            return {"data": {"total": 250, "diff": _codes(50, 200)}}
        raise AssertionError(f"unexpected page {pn}")

    calls = _install(monkeypatch, handler)
    out = astock.a_share_snapshot(page_size=200)
    assert len(calls) == 3
    assert len(out) == 250
    # 回归：旧 bug 会在第 1 页 100 < 200 时提前结束
    assert len(out) != 100


def test_last_page_short_ok(monkeypatch):
    def handler(url, params):
        pn = int(params["pn"])
        if pn == 1:
            return {"data": {"total": 5, "diff": _codes(3, 0)}}
        if pn == 2:
            return {"data": {"total": 5, "diff": _codes(2, 3)}}
        raise AssertionError(f"unexpected page {pn}")

    calls = _install(monkeypatch, handler)
    out = astock.a_share_snapshot(page_size=3)
    assert len(calls) == 2
    assert len(out) == 5


# ---------------------------------------------------------------------------
# 4. 空最后一页
# ---------------------------------------------------------------------------

def test_empty_trailing_page_stops(monkeypatch):
    """total 偏大时，空页安全结束。"""
    def handler(url, params):
        pn = int(params["pn"])
        if pn == 1:
            return {"data": {"total": 9999, "diff": _codes(2, 0)}}
        if pn == 2:
            return {"data": {"total": 9999, "diff": []}}
        raise AssertionError(f"unexpected page {pn}")

    calls = _install(monkeypatch, handler)
    out = astock.a_share_snapshot(page_size=2)
    assert len(calls) == 2
    assert len(out) == 2


# ---------------------------------------------------------------------------
# 5. 基于 total 而非固定数量
# ---------------------------------------------------------------------------

def test_uses_response_total_not_fixed(monkeypatch):
    totals_seen = []

    def handler(url, params):
        pn = int(params["pn"])
        totals_seen.append(77)
        if pn == 1:
            return {"data": {"total": 77, "diff": _codes(50, 0)}}
        if pn == 2:
            return {"data": {"total": 77, "diff": _codes(27, 50)}}
        raise AssertionError(f"unexpected page {pn}")

    calls = _install(monkeypatch, handler)
    out = astock.a_share_snapshot(page_size=50)
    assert len(out) == 77
    assert len(calls) == 2


# ---------------------------------------------------------------------------
# 6–7 去重 / 缺 code
# ---------------------------------------------------------------------------

def test_dedupe_by_code_stable_order(monkeypatch):
    page1 = [_row("600001", "甲"), _row("600002", "乙")]
    page2 = [_row("600002", "乙-重复"), _row("600003", "丙")]

    def handler(url, params):
        pn = int(params["pn"])
        if pn == 1:
            return {"data": {"total": 4, "diff": page1}}
        if pn == 2:
            return {"data": {"total": 4, "diff": page2}}
        return {"data": {"total": 4, "diff": []}}

    _install(monkeypatch, handler)
    out = astock.a_share_snapshot(page_size=2)
    assert [x["code"] for x in out] == ["600001", "600002", "600003"]
    assert out[1]["name"] == "乙"  # 首次出现


def test_missing_code_skipped(monkeypatch):
    rows = [
        _row("600001", "甲"),
        {"f12": "", "f14": "无代码", "f2": 1, "f3": 1},
        _row("600002", "乙"),
    ]

    def handler(url, params):
        return {"data": {"total": 3, "diff": rows}}

    _install(monkeypatch, handler)
    out = astock.a_share_snapshot()
    assert [x["code"] for x in out] == ["600001", "600002"]


# ---------------------------------------------------------------------------
# 8. 重复页面
# ---------------------------------------------------------------------------

def test_repeated_page_raises(monkeypatch):
    same = _codes(3, 0)

    def handler(url, params):
        pn = int(params["pn"])
        # 每页相同 3 条，total 很大 → 应在第 2 页报重复
        return {"data": {"total": 30, "diff": same}}

    _install(monkeypatch, handler)
    with pytest.raises(RuntimeError, match="repeated page"):
        astock.a_share_snapshot(page_size=3)


# ---------------------------------------------------------------------------
# 9–10 失败与结构异常
# ---------------------------------------------------------------------------

def test_mid_page_failure_raises_not_partial(monkeypatch):
    def handler(url, params):
        pn = int(params["pn"])
        if pn == 1:
            return {"data": {"total": 10, "diff": _codes(5, 0)}}
        raise ConnectionError("page2 down")

    _install(monkeypatch, handler)
    with pytest.raises(RuntimeError, match="request failed"):
        astock.a_share_snapshot(page_size=5)


def test_invalid_structures(monkeypatch):
    def handler_missing(url, params):
        return {"rc": 0}

    _install(monkeypatch, handler_missing)
    with pytest.raises(RuntimeError, match="missing data"):
        astock.a_share_snapshot()

    def handler_diff_bad(url, params):
        return {"data": {"total": 1, "diff": "not-list"}}

    _install(monkeypatch, handler_diff_bad)
    with pytest.raises(RuntimeError, match="diff"):
        astock.a_share_snapshot()

    def handler_total_bad(url, params):
        return {"data": {"total": "x", "diff": [_row("600001")]}}

    _install(monkeypatch, handler_total_bad)
    with pytest.raises(RuntimeError, match="invalid total"):
        astock.a_share_snapshot()


# ---------------------------------------------------------------------------
# 11–12 市场广度
# ---------------------------------------------------------------------------

def test_breadth_uses_full_snapshot():
    snap = []
    for i, pct in enumerate([1.0, -1.0, 0.0, 3.5, -3.0, None, 0.5] * 20):
        snap.append({
            "code": f"{i:06d}",
            "name": f"s{i}",
            "price": 10.0,
            "change_pct": pct,
            "amount": 100.0 if pct is not None else None,
            "turnover_pct": 1.0,
            "market_cap": 1e9,
        })
    # 补足超过 100 条
    assert len(snap) == 140
    b = market.calculate_market_breadth(snap)
    assert b["stock_count"] == 140
    # None 不计入 valid
    assert b["valid_count"] == 120  # 140 * 6/7
    assert b["up_count"] + b["down_count"] + b["flat_count"] == b["valid_count"]
    assert b["up_ratio"] == pytest.approx(b["up_count"] / b["valid_count"], rel=1e-4)
    assert b["amount_valid_count"] == 120
    assert b["total_amount"] == pytest.approx(120 * 100.0)


def test_breadth_zero_and_none():
    snap = [
        {"code": "000001", "name": "a", "change_pct": 0, "amount": 0, "turnover_pct": 0, "price": 1, "market_cap": 1},
        {"code": "000002", "name": "b", "change_pct": None, "amount": None, "turnover_pct": None, "price": 1, "market_cap": 1},
        {"code": "000003", "name": "c", "change_pct": 1.0, "amount": 10.0, "turnover_pct": 20.0, "price": 1, "market_cap": 1},
    ]
    b = market.calculate_market_breadth(snap)
    assert b["stock_count"] == 3
    assert b["valid_count"] == 2
    assert b["flat_count"] == 1
    assert b["up_count"] == 1
    assert b["amount_valid_count"] == 2  # 0 计入
    assert b["total_amount"] == pytest.approx(10.0)


# ---------------------------------------------------------------------------
# 13–14 缓存
# ---------------------------------------------------------------------------

def test_cache_stores_full_multi_page(monkeypatch):
    market._CACHE.clear()
    n_calls = {"n": 0}

    def fake_snap():
        n_calls["n"] += 1
        return [{"code": f"{i:06d}", "name": f"s{i}", "change_pct": 1.0, "amount": 1.0}
                for i in range(250)]

    monkeypatch.setattr(market.astock, "a_share_snapshot", fake_snap)
    a = market.get_a_share_snapshot()
    b = market.get_a_share_snapshot()
    assert n_calls["n"] == 1
    assert len(a) == 250
    assert a is b or a == b
    assert len(a) != 100
    market._CACHE.clear()


def test_failure_does_not_cache_partial(monkeypatch):
    market._CACHE.clear()
    full = [{"code": f"{i:06d}", "name": f"s{i}", "change_pct": 1.0, "amount": 1.0}
            for i in range(200)]
    state = {"fail": False}

    def fake_snap():
        if state["fail"]:
            raise RuntimeError("boom")
        return full

    monkeypatch.setattr(market.astock, "a_share_snapshot", fake_snap)
    ok = market.get_a_share_snapshot()
    assert len(ok) == 200
    state["fail"] = True
    # 缓存命中成功结果，失败刷新不会发生除非清缓存
    still = market.get_a_share_snapshot()
    assert len(still) == 200
    market._CACHE.clear()
    with pytest.raises(RuntimeError, match="boom"):
        market.get_a_share_snapshot()
    # 失败后缓存不应变成 100 条伪完整
    assert "a_share_snapshot" not in market._CACHE
