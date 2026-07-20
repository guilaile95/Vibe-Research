"""_sentiment() 全 A 快照广度替换乐咕/AKShare 的离线测试（全部 Mock，不联网）。"""
from __future__ import annotations

import pytest

import astock
import market


def _breadth_env(
    *,
    status="normal",
    up=3000,
    down=1800,
    flat=100,
    up_ratio=0.6122,
    stock_count=4900,
    valid_count=4900,
    up_3pct=500,
    down_3pct=260,
    total_amount=1.25e12,
    warnings=None,
):
    data = None
    if status != "unavailable":
        data = {
            "stock_count": stock_count,
            "valid_count": valid_count,
            "up_count": up,
            "down_count": down,
            "flat_count": flat,
            "up_ratio": up_ratio,
            "up_3pct_count": up_3pct,
            "down_3pct_count": down_3pct,
            "total_amount": total_amount,
            "amount_valid_count": valid_count,
            "amount_top": [],
            "high_turnover": [],
        }
    return {
        "status": status,
        "source": "eastmoney_push2",
        "trade_date": None,
        "data_time": None,
        "fetched_at": "2026-07-21 15:30:00",
        "is_stale": False,
        "warnings": list(warnings or []),
        "data": data,
    }


def _emotion(zt=80, dt=12, date="2026-07-21"):
    return {
        "date": date,
        "zt_count": zt,
        "dt_count": dt,
        "zb_count": 10,
        "max_boards": 5,
        "lianban_count": 20,
        "ladder": [],
        "lianban_stocks": [],
        "seal_rate": 0.8,
        "break_rate": 0.2,
        "promotion_rate": 0.3,
        "yzt_count": 50,
    }


# ── 1. 不再调用 AKShare ─────────────────────────────────────────────

def test_sentiment_does_not_call_akshare(monkeypatch):
    calls = {"n": 0}

    def boom():
        calls["n"] += 1
        raise RuntimeError("akshare should not be called")

    monkeypatch.setattr(astock, "_akshare", boom)
    monkeypatch.setattr(market, "get_market_breadth", lambda: _breadth_env())
    monkeypatch.setattr(market, "get_short_term_emotion", lambda: _emotion())
    out = market._sentiment()
    assert calls["n"] == 0
    assert out["status"] == "normal"
    assert out["up"] == 3000


# ── 2. 正常数据映射 ─────────────────────────────────────────────────

def test_sentiment_normal_mapping(monkeypatch):
    monkeypatch.setattr(market, "get_market_breadth", lambda: _breadth_env(up_ratio=0.5678))
    monkeypatch.setattr(market, "get_short_term_emotion", lambda: _emotion(zt=80, dt=12))
    out = market._sentiment()
    assert out["status"] == "normal"
    assert out["source"] == "eastmoney_push2"
    assert out["up"] == 3000
    assert out["down"] == 1800
    assert out["flat"] == 100
    assert out["zt"] == 80
    assert out["dt"] == 12
    assert out["zt_real"] == out["zt"] == 80
    assert out["dt_real"] == out["dt"] == 12
    assert out["up_ratio"] == pytest.approx(0.5678)
    assert out["total_amount"] == pytest.approx(1.25e12)
    assert out["limit_count_source"] == "eastmoney_limit_pool"
    assert out["date"] == "2026-07-21"


# ── 3. 宽度标签边界 ─────────────────────────────────────────────────

@pytest.mark.parametrize(
    "ratio,label",
    [
        (None, None),
        (0.2499, "冰点"),
        (0.25, "偏弱"),
        (0.3999, "偏弱"),
        (0.40, "中性"),
        (0.60, "中性"),
        (0.6001, "偏强"),
        (0.75, "偏强"),
        (0.7501, "普涨"),
    ],
)
def test_breadth_label_boundaries(ratio, label):
    assert market._breadth_label(ratio) == label


# ── 4. 投机标签边界 ─────────────────────────────────────────────────

@pytest.mark.parametrize(
    "zt,label",
    [
        (None, None),
        (29, "冰点"),
        (30, "普通"),
        (59, "普通"),
        (60, "活跃"),
        (99, "活跃"),
        (100, "亢奋"),
    ],
)
def test_speculation_label_boundaries(zt, label):
    assert market._speculation_label(zt) == label


# ── 5. active 字段 ──────────────────────────────────────────────────

def test_sentiment_active_from_up_ratio(monkeypatch):
    monkeypatch.setattr(market, "get_market_breadth", lambda: _breadth_env(up_ratio=0.5678))
    monkeypatch.setattr(market, "get_short_term_emotion", lambda: _emotion())
    out = market._sentiment()
    assert out["active"] == "56.8%"
    assert out["active_metric"] == "up_ratio"
    assert out["breadth"] == "中性"  # 0.5678 in (0.40, 0.60]


# ── 6. 广度 partial ─────────────────────────────────────────────────

def test_sentiment_breadth_partial(monkeypatch):
    env = _breadth_env(status="partial", warnings=["涨跌幅字段有效比例偏低"])
    monkeypatch.setattr(market, "get_market_breadth", lambda: env)
    monkeypatch.setattr(market, "get_short_term_emotion", lambda: _emotion())
    out = market._sentiment()
    assert out["status"] == "partial"
    assert out["up"] == 3000
    assert any("涨跌幅" in w for w in out["warnings"])


# ── 7. 广度 unavailable ─────────────────────────────────────────────

def test_sentiment_breadth_unavailable_keeps_emotion(monkeypatch):
    env = _breadth_env(status="unavailable", warnings=["全市场快照获取失败：timeout"])
    monkeypatch.setattr(market, "get_market_breadth", lambda: env)
    monkeypatch.setattr(market, "get_short_term_emotion", lambda: _emotion(zt=55, dt=8))
    out = market._sentiment()
    assert out["status"] == "unavailable"
    assert out["up"] is None
    assert out["down"] is None
    assert out["flat"] is None
    assert out["up"] is not 0  # 不返回全 0
    assert out["zt"] == 55
    assert out["dt"] == 8
    assert out["zt_real"] == 55
    assert out["speculation"] == "普通"  # 55
    assert any("timeout" in w for w in out["warnings"])


# ── 8. 情绪池缺失 ───────────────────────────────────────────────────

def test_sentiment_emotion_missing_partial(monkeypatch):
    monkeypatch.setattr(market, "get_market_breadth", lambda: _breadth_env())
    monkeypatch.setattr(market, "get_short_term_emotion", lambda: {})
    out = market._sentiment()
    assert out["status"] == "partial"
    assert out["up"] == 3000
    assert out["zt"] is None
    assert out["dt"] is None
    assert out["speculation"] is None
    assert any("涨跌停池数据不可用" in w for w in out["warnings"])


# ── 9. 情绪池异常 ───────────────────────────────────────────────────

def test_sentiment_emotion_exception_partial(monkeypatch):
    monkeypatch.setattr(market, "get_market_breadth", lambda: _breadth_env())

    def boom():
        raise RuntimeError("pool timeout")

    monkeypatch.setattr(market, "get_short_term_emotion", boom)
    out = market._sentiment()  # 不向外抛
    assert out["status"] == "partial"
    assert out["up"] == 3000
    assert out["zt"] is None
    assert any("pool timeout" in w for w in out["warnings"])


# ── 10. overview 兼容 ───────────────────────────────────────────────

def test_overview_top_level_shape(monkeypatch):
    market._CACHE.clear()
    monkeypatch.setattr(market, "_sentiment", lambda: {"status": "normal", "up": 1})
    monkeypatch.setattr(market, "_sectors", lambda: [{"name": "电子", "pct": 1.0, "net": 1.0}])
    out = market.get_overview()
    assert set(out.keys()) == {"sentiment", "sectors", "updated"}
    assert out["sentiment"]["up"] == 1
    assert out["sectors"][0]["name"] == "电子"
    assert isinstance(out["updated"], str)
    market._CACHE.clear()


def test_sentiment_breadth_exception_unavailable(monkeypatch):
    def boom():
        raise RuntimeError("unexpected breadth")

    monkeypatch.setattr(market, "get_market_breadth", boom)
    monkeypatch.setattr(market, "get_short_term_emotion", lambda: _emotion())
    out = market._sentiment()
    assert out["status"] == "unavailable"
    assert out["up"] is None
    assert any("unexpected breadth" in w for w in out["warnings"])
