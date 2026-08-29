"""get_cached_board_ranking / get_board_ranking 离线测试（Mock board_ranking，不联网）。"""
from __future__ import annotations

import pytest

import market

_ENVELOPE_KEYS = {
    "status", "source", "trade_date", "data_time",
    "fetched_at", "is_stale", "warnings", "data",
}


def _raw(
    *,
    board_type="industry",
    total=90,
    ranked_count=90,
    unknown_count=0,
    top_n=30,
):
    top = [
        {"code": f"T{i:03d}", "name": f"强{i}", "change_pct": float(30 - i),
         "up_count": 10, "down_count": 5, "up_ratio": 0.6667,
         "turnover_pct": 1.0, "market_cap": 1e10, "leader": "L", "leader_change_pct": 1.0}
        for i in range(top_n)
    ]
    bottom = [
        {"code": f"B{i:03d}", "name": f"弱{i}", "change_pct": float(-30 + i),
         "up_count": 5, "down_count": 10, "up_ratio": 0.3333,
         "turnover_pct": 1.0, "market_cap": 1e10, "leader": "L", "leader_change_pct": -1.0}
        for i in range(top_n)
    ]
    return {
        "type": board_type,
        "total": total,
        "ranked_count": ranked_count,
        "unknown_count": unknown_count,
        "top": top,
        "bottom": bottom,
    }


def _assert_envelope(env: dict):
    assert set(env.keys()) == _ENVELOPE_KEYS
    assert env["source"] == "eastmoney_push2"
    assert env["trade_date"] is None
    assert env["data_time"] is None
    assert isinstance(env["fetched_at"], str)
    assert isinstance(env["warnings"], list)
    assert env["status"] in ("normal", "partial", "unavailable")


# ── 1–2 缓存 ────────────────────────────────────────────────────────

def test_cached_board_ranking_reuses_cache(monkeypatch):
    market._CACHE.clear()
    calls = {"n": 0, "args": []}

    def fake(bt, top_n=20):
        calls["n"] += 1
        calls["args"].append((bt, top_n))
        return _raw(board_type=bt)

    monkeypatch.setattr(market.astock, "board_ranking", fake)
    a = market.get_cached_board_ranking("industry")
    b = market.get_cached_board_ranking("industry")
    assert calls["n"] == 1
    assert calls["args"][0] == ("industry", 100)
    assert a["total"] == b["total"] == 90
    market._CACHE.clear()


def test_three_board_types_independent_cache(monkeypatch):
    market._CACHE.clear()
    calls = {"types": []}

    def fake(bt, top_n=20):
        calls["types"].append(bt)
        return _raw(board_type=bt)

    monkeypatch.setattr(market.astock, "board_ranking", fake)
    market.get_cached_board_ranking("industry")
    market.get_cached_board_ranking("concept")
    market.get_cached_board_ranking("region")
    # 再各取一次，应仍只 3 次底层
    market.get_cached_board_ranking("industry")
    market.get_cached_board_ranking("concept")
    market.get_cached_board_ranking("region")
    assert calls["types"] == ["industry", "concept", "region"]
    market._CACHE.clear()


# ── 3 normal ────────────────────────────────────────────────────────

def test_get_board_ranking_normal(monkeypatch):
    market._CACHE.clear()
    raw = _raw(total=90, ranked_count=90, unknown_count=0)
    monkeypatch.setattr(market.astock, "board_ranking", lambda bt, top_n=20: raw)
    env = market.get_board_ranking("industry", top_n=20)
    _assert_envelope(env)
    assert env["status"] == "normal"
    assert env["trade_date"] is None
    assert env["data_time"] is None
    assert any("交易日期" in w or "行情时间" in w for w in env["warnings"])
    assert env["data"]["total"] == 90
    assert env["data"]["ranked_count"] == 90
    assert env["data"]["unknown_count"] == 0
    assert env["data"]["type"] == "industry"
    # 数值未改写
    assert env["data"]["top"][0]["code"] == raw["top"][0]["code"]
    assert env["data"]["top"][0]["change_pct"] == raw["top"][0]["change_pct"]
    market._CACHE.clear()


# ── 4 top_n 切片 ────────────────────────────────────────────────────

def test_get_board_ranking_slices_top_n(monkeypatch):
    market._CACHE.clear()
    calls = {"n": 0}
    raw = _raw(top_n=30)

    def fake(bt, top_n=20):
        calls["n"] += 1
        return raw

    monkeypatch.setattr(market.astock, "board_ranking", fake)
    env1 = market.get_board_ranking("industry", top_n=10)
    env2 = market.get_board_ranking("industry", top_n=10)
    assert calls["n"] == 1  # 切片不触发再抓
    assert len(env1["data"]["top"]) == 10
    assert len(env1["data"]["bottom"]) == 10
    assert env1["data"]["total"] == 90
    assert env1["data"]["ranked_count"] == 90
    assert env2["data"]["top"][0]["code"] == raw["top"][0]["code"]
    market._CACHE.clear()


# ── 5 partial ───────────────────────────────────────────────────────

def test_get_board_ranking_partial(monkeypatch):
    market._CACHE.clear()
    raw = _raw(total=100, ranked_count=95, unknown_count=5)
    monkeypatch.setattr(market.astock, "board_ranking", lambda bt, top_n=20: raw)
    env = market.get_board_ranking("concept", top_n=15)
    _assert_envelope(env)
    assert env["status"] == "partial"
    assert env["data"] is not None
    assert env["data"]["unknown_count"] == 5
    assert any("5" in w and "缺少有效涨跌幅" in w for w in env["warnings"])
    assert len(env["data"]["top"]) == 15
    market._CACHE.clear()


# ── 6–7 unavailable ─────────────────────────────────────────────────

def test_get_board_ranking_total_zero(monkeypatch):
    market._CACHE.clear()
    raw = {
        "type": "industry", "total": 0, "ranked_count": 0, "unknown_count": 0,
        "top": [], "bottom": [],
    }
    monkeypatch.setattr(market.astock, "board_ranking", lambda bt, top_n=20: raw)
    env = market.get_board_ranking("industry")
    assert env["status"] == "unavailable"
    assert env["data"] is None
    market._CACHE.clear()


def test_get_board_ranking_ranked_zero(monkeypatch):
    market._CACHE.clear()
    raw = {
        "type": "industry", "total": 10, "ranked_count": 0, "unknown_count": 10,
        "top": [], "bottom": [],
    }
    monkeypatch.setattr(market.astock, "board_ranking", lambda bt, top_n=20: raw)
    env = market.get_board_ranking("industry")
    assert env["status"] == "unavailable"
    assert env["data"] is None
    market._CACHE.clear()


# ── 8 数据源异常 ────────────────────────────────────────────────────

def test_get_board_ranking_source_error(monkeypatch):
    market._CACHE.clear()

    def boom(bt, top_n=20):
        raise RuntimeError("timeout")

    monkeypatch.setattr(market.astock, "board_ranking", boom)
    env = market.get_board_ranking("industry")  # 不向外抛
    assert env["status"] == "unavailable"
    assert env["data"] is None
    assert any("timeout" in w for w in env["warnings"])
    market._CACHE.clear()


# ── 9–10 参数校验 ───────────────────────────────────────────────────

def test_get_board_ranking_invalid_type():
    with pytest.raises(ValueError, match="不支持的板块类型"):
        market.get_board_ranking("invalid")


@pytest.mark.parametrize("n", [0, 101])
def test_get_board_ranking_invalid_top_n(n):
    with pytest.raises(ValueError, match="top_n"):
        market.get_board_ranking("industry", top_n=n)


# ── 11 信封键一致 ───────────────────────────────────────────────────

def test_envelope_keys_all_statuses(monkeypatch):
    market._CACHE.clear()
    cases = []

    monkeypatch.setattr(
        market.astock, "board_ranking",
        lambda bt, top_n=20: _raw(total=90, ranked_count=90, unknown_count=0),
    )
    cases.append(market.get_board_ranking("industry"))

    market._CACHE.clear()
    monkeypatch.setattr(
        market.astock, "board_ranking",
        lambda bt, top_n=20: _raw(total=100, ranked_count=95, unknown_count=5),
    )
    cases.append(market.get_board_ranking("industry"))

    market._CACHE.clear()
    monkeypatch.setattr(
        market.astock, "board_ranking",
        lambda bt, top_n=20: (_ for _ in ()).throw(RuntimeError("x")),
    )
    cases.append(market.get_board_ranking("industry"))

    assert [c["status"] for c in cases] == ["normal", "partial", "unavailable"]
    for c in cases:
        _assert_envelope(c)
    market._CACHE.clear()


# ── 12 空结果不缓存 ─────────────────────────────────────────────────

def test_empty_result_not_cached(monkeypatch):
    market._CACHE.clear()
    calls = {"n": 0}
    seq = [
        {"type": "industry", "total": 0, "ranked_count": 0, "unknown_count": 0, "top": [], "bottom": []},
        _raw(total=50, ranked_count=50, unknown_count=0),
    ]

    def fake(bt, top_n=20):
        i = calls["n"]
        calls["n"] += 1
        return seq[min(i, len(seq) - 1)]

    monkeypatch.setattr(market.astock, "board_ranking", fake)
    # 第一次：底层空 → 不缓存
    r1 = market.get_cached_board_ranking("industry")
    assert r1["total"] == 0
    # 第二次：应再打底层，得到正常
    r2 = market.get_cached_board_ranking("industry")
    assert calls["n"] == 2
    assert r2["total"] == 50
    # 第三次：命中缓存
    r3 = market.get_cached_board_ranking("industry")
    assert calls["n"] == 2
    assert r3["total"] == 50
    market._CACHE.clear()


# ── 13 成交额字段（enrichment via stock/get）与 amount_top ─────────────────────────


def test_map_board_row_sets_amount_none_by_default():
    """_map_board_row 应将 amount 初始化为 None（fail-closed，不伪造 0）。"""
    import astock

    row = astock._map_board_row({
        "f12": "BK0447", "f14": "电子", "f3": 1.5,
        "f8": 2.0, "f20": 1e12, "f104": 50, "f105": 30, "f128": "领涨股", "f136": 5.0,
    })
    assert row is not None
    assert row["amount"] is None, "amount should be None before enrichment"
    assert row["change_pct"] == 1.5


def test_enrich_board_amounts_populates_amount(monkeypatch):
    """_enrich_board_amounts 应通过 stock/get 补充成交额，失败保留 None。"""
    import astock

    fake_amounts = {"BK001": 1e8, "BK002": 5e8}

    def fake_fetch_single(code):
        return code, fake_amounts.get(code)

    monkeypatch.setattr(astock, "_fetch_board_amount_single", fake_fetch_single)

    boards = [
        {"code": "BK001", "name": "小成交额", "amount": None},
        {"code": "BK002", "name": "大成交额", "amount": None},
        {"code": "BK003", "name": "无成交额", "amount": None},
    ]
    astock._enrich_board_amounts(boards)

    assert boards[0]["amount"] == 1e8
    assert boards[1]["amount"] == 5e8
    assert boards[2]["amount"] is None, "failed fetch should keep None (fail-closed)"


def test_board_ranking_amount_top_sorted_by_amount(monkeypatch):
    """astock.board_ranking 应返回按成交额降序的 amount_top，null amount 不进入。"""
    import astock

    raw_pages = [
        {
            "data": {
                "total": 3,
                "diff": [
                    {"f12": "BK001", "f14": "小成交额", "f3": 5.0, "f8": 1.0, "f20": 1e10, "f104": 10, "f105": 5},
                    {"f12": "BK002", "f14": "大成交额", "f3": -2.0, "f8": 2.0, "f20": 1e10, "f104": 5, "f105": 10},
                    {"f12": "BK003", "f14": "无成交额", "f3": 1.0, "f8": 1.0, "f20": 1e10, "f104": 8, "f105": 7},
                ],
            },
        },
    ]

    def fake_em_get(url, params=None, headers=None, timeout=15):
        class _Resp:
            def json(self_inner):
                return raw_pages[0]
        return _Resp()

    # Mock amount enrichment: BK001=1e8, BK002=5e8, BK003=None
    fake_amounts = {"BK001": 1e8, "BK002": 5e8}

    def fake_enrich(boards):
        for b in boards:
            b["amount"] = fake_amounts.get(b["code"])

    monkeypatch.setattr(astock, "em_get", fake_em_get)
    monkeypatch.setattr(astock, "_enrich_board_amounts", fake_enrich)

    result = astock.board_ranking("industry", top_n=10)

    assert result["total"] == 3
    assert len(result["amount_top"]) == 2, "null amount should be excluded from amount_top"
    # 按成交额降序
    assert result["amount_top"][0]["code"] == "BK002"
    assert result["amount_top"][0]["amount"] == 5e8
    assert result["amount_top"][1]["code"] == "BK001"
    assert result["amount_top"][1]["amount"] == 1e8


def test_get_board_ranking_passes_amount_top(monkeypatch):
    """market.get_board_ranking 应透传 amount_top 并按 top_n 切片。"""
    market._CACHE.clear()
    amount_top = [
        {"code": f"A{i}", "name": f"板块{i}", "change_pct": 1.0, "amount": float(100 - i) * 1e6,
         "turnover_pct": 1.0, "market_cap": 1e10, "up_count": 10, "down_count": 5,
         "up_ratio": 0.6667, "leader": None, "leader_change_pct": None}
        for i in range(50)
    ]
    raw = {
        "type": "industry", "total": 50, "ranked_count": 50, "unknown_count": 0,
        "top": amount_top[:20], "bottom": amount_top[-20:], "amount_top": amount_top,
    }
    monkeypatch.setattr(market, "get_cached_board_ranking", lambda bt: raw)
    env = market.get_board_ranking("industry", top_n=10)

    assert env["status"] == "normal"
    assert env["data"] is not None
    assert len(env["data"]["amount_top"]) == 10, "amount_top should be sliced by top_n"
    assert env["data"]["amount_top"][0]["code"] == "A0"
    assert env["data"]["amount_top"][0]["amount"] == 100e6
    market._CACHE.clear()
