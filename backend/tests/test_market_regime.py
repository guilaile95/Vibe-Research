"""Market Regime v0.1 专项测试（全部 Mock，不联网）。

覆盖：RISK_ON / RISK_OFF / STRESSED / NEUTRAL / UNKNOWN /
部分缺失降级 / stale 降级 / 强冲突不激进 / 确定性重复执行 /
reason codes 与规则一致 / API contract / 数据截止时间。
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

import app as app_module
import market
import market_regime
from market_regime import BEIJING, derive_market_regime

client = TestClient(app_module.app)

_NOW = datetime(2026, 8, 7, 16, 0, 0, tzinfo=BEIJING)  # 15:30 收盘后 30 分钟
_FRESH_FETCHED_AT = "2026-08-07 15:30:00"


def _recent_fetched_at() -> str:
    """相对真实当前时间的新鲜获取时间（API 路径用真实 now，避免误判 stale）。"""
    return (datetime.now(BEIJING) - timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")


def _breadth_env(
    status: str = "normal",
    *,
    up_ratio=0.50,
    total_amount=1.0e12,
    amount_valid_count=4900,
    fetched_at: str | None = _FRESH_FETCHED_AT,
    data: dict | None = None,
) -> dict:
    if data is None and status != "unavailable":
        data = {
            "stock_count": 5000,
            "valid_count": 4900,
            "up_count": 2500,
            "down_count": 2300,
            "flat_count": 100,
            "up_ratio": up_ratio,
            "up_3pct_count": 300,
            "down_3pct_count": 200,
            "total_amount": total_amount,
            "amount_valid_count": amount_valid_count,
            "amount_top": [],
            "high_turnover": [],
        }
    return {
        "status": status,
        "source": "eastmoney_push2",
        "trade_date": None,
        "data_time": None,
        "fetched_at": fetched_at,
        "is_stale": False,
        "warnings": [],
        "data": data,
    }


def _emotion(
    *,
    zt: int | None = 50,
    dt: int | None = 8,
    break_rate: float | None = 0.3,
    seal_rate: float | None = 0.7,
    promotion_rate: float | None = 0.2,
    max_boards: int = 5,
    date: str | None = "2026-08-07",
) -> dict:
    return {
        "date": date,
        "zt_count": zt,
        "dt_count": dt,
        "zb_count": 20,
        "max_boards": max_boards,
        "lianban_count": 8,
        "ladder": [],
        "lianban_stocks": [],
        "seal_rate": seal_rate,
        "break_rate": break_rate,
        "promotion_rate": promotion_rate,
        "yzt_count": 40,
    }


def _codes(payload: dict) -> list[str]:
    return [r["code"] for r in payload["reasons"]]


# ---------------------------------------------------------------------------
# 1. 明显 RISK_ON
# ---------------------------------------------------------------------------
def test_risk_on_clear():
    payload = derive_market_regime(
        _breadth_env(up_ratio=0.72, total_amount=1.5e12),
        _emotion(zt=150),
        now=_NOW,
    )
    assert payload["market_regime"] == "RISK_ON"
    assert payload["risk_appetite"] == "HIGH"
    assert payload["confidence"] == "HIGH"
    assert payload["is_stale"] is False
    assert payload["trade_date"] == "2026-08-07"
    assert payload["data_cutoff"] == _FRESH_FETCHED_AT
    codes = _codes(payload)
    assert "BREADTH_STRONG" in codes
    assert "RISK_APPETITE_HIGH" in codes
    assert "LIQUIDITY_STRONG" in codes
    assert "EMOTION_NORMAL" in codes
    assert "SIGNAL_CONFLICT" not in codes


# ---------------------------------------------------------------------------
# 2. 明显 RISK_OFF
# ---------------------------------------------------------------------------
def test_risk_off_clear():
    payload = derive_market_regime(
        _breadth_env(up_ratio=0.30, total_amount=7.0e11),
        _emotion(zt=12),
        now=_NOW,
    )
    assert payload["market_regime"] == "RISK_OFF"
    assert payload["risk_appetite"] == "LOW"
    assert payload["confidence"] == "HIGH"
    codes = _codes(payload)
    assert "BREADTH_WEAK" in codes
    assert "RISK_APPETITE_LOW" in codes
    assert "LIQUIDITY_WEAK" in codes


def test_risk_off_two_weak_signals_without_appetite():
    """宽度弱 + 流动性弱（投机数据缺失）→ 仍可形成 RISK_OFF，但 Confidence 降级。"""
    payload = derive_market_regime(
        _breadth_env(up_ratio=0.30, total_amount=7.0e11),
        _emotion(zt=None, dt=None, break_rate=None, date=None),
        now=_NOW,
    )
    assert payload["market_regime"] == "RISK_OFF"
    assert payload["risk_appetite"] == "UNKNOWN"
    assert payload["confidence"] == "LOW"  # 两个组件缺失 → LOW
    assert "DATA_PARTIAL" in _codes(payload)


# ---------------------------------------------------------------------------
# 3. STRESSED
# ---------------------------------------------------------------------------
def test_stressed_high_limit_down():
    payload = derive_market_regime(
        _breadth_env(up_ratio=0.30),
        _emotion(zt=12, dt=45, break_rate=0.6),
        now=_NOW,
    )
    assert payload["market_regime"] == "STRESSED"
    assert "EMOTION_STRESSED" in _codes(payload)
    assert "BREADTH_WEAK" in _codes(payload)


def test_stressed_high_break_rate():
    payload = derive_market_regime(
        _breadth_env(up_ratio=0.30),
        _emotion(zt=12, dt=8, break_rate=0.7),
        now=_NOW,
    )
    assert payload["market_regime"] == "STRESSED"


# ---------------------------------------------------------------------------
# 4. 混合信号 → NEUTRAL（不强行给激进状态）
# ---------------------------------------------------------------------------
def test_mixed_neutral_high_confidence():
    payload = derive_market_regime(
        _breadth_env(up_ratio=0.50, total_amount=1.0e12),
        _emotion(zt=45),
        now=_NOW,
    )
    assert payload["market_regime"] == "NEUTRAL"
    assert payload["confidence"] == "HIGH"  # 中性本身是合法状态，不是低置信
    codes = _codes(payload)
    assert "BREADTH_NEUTRAL" in codes
    assert "RISK_APPETITE_MEDIUM" in codes
    assert "LIQUIDITY_NEUTRAL" in codes


def test_neutral_single_strong_signal_not_enough():
    """只有宽度强、投机与流动性普通 → 不因单一指标强行 RISK_ON。"""
    payload = derive_market_regime(
        _breadth_env(up_ratio=0.72, total_amount=1.0e12),
        _emotion(zt=45),
        now=_NOW,
    )
    assert payload["market_regime"] == "NEUTRAL"
    assert "RISK_ON" not in payload["market_regime"]


# ---------------------------------------------------------------------------
# 5. 核心数据完全缺失 → UNKNOWN
# ---------------------------------------------------------------------------
def test_core_unavailable_unknown_even_with_emotion():
    payload = derive_market_regime(
        _breadth_env("unavailable", data=None),
        _emotion(zt=150, dt=3, break_rate=0.1),
        now=_NOW,
    )
    assert payload["market_regime"] == "UNKNOWN"
    assert payload["risk_appetite"] == "HIGH"  # 情绪仍可读，但不替代核心
    assert payload["confidence"] == "LOW"
    assert "DATA_UNAVAILABLE" in _codes(payload)
    assert "BREADTH_UNAVAILABLE" in _codes(payload)


def test_core_up_ratio_missing_unknown():
    """广度信封 normal 但无 up_ratio → 无法形成方向 → UNKNOWN（不伪造）。"""
    payload = derive_market_regime(
        _breadth_env(data={**_breadth_env()["data"], "up_ratio": None, "valid_count": 0}),
        _emotion(),
        now=_NOW,
    )
    assert payload["market_regime"] == "UNKNOWN"
    assert payload["confidence"] == "LOW"


# ---------------------------------------------------------------------------
# 6. 部分数据缺失 → 允许方向但 Confidence 降级
# ---------------------------------------------------------------------------
def test_partial_missing_liquidity_keeps_direction_lower_confidence():
    payload = derive_market_regime(
        _breadth_env(up_ratio=0.72, total_amount=None, amount_valid_count=0),
        _emotion(zt=150),
        now=_NOW,
    )
    assert payload["market_regime"] == "RISK_ON"  # 方向可形成
    assert payload["confidence"] == "MEDIUM"      # 缺失 → 降级
    assert payload["components"]["liquidity"]["available"] is False
    assert "LIQUIDITY_UNAVAILABLE" in _codes(payload)
    assert "DATA_PARTIAL" in _codes(payload)


def test_breadth_partial_envelope_lower_confidence():
    payload = derive_market_regime(
        _breadth_env("partial", up_ratio=0.50),
        _emotion(zt=45),
        now=_NOW,
    )
    assert payload["market_regime"] == "NEUTRAL"
    assert payload["confidence"] == "MEDIUM"
    assert "DATA_PARTIAL" in _codes(payload)


# ---------------------------------------------------------------------------
# 7. stale → is_stale + Confidence 降级；freshness 缺失 → fail-closed stale
# ---------------------------------------------------------------------------
def test_stale_downgrades_confidence():
    payload = derive_market_regime(
        _breadth_env(up_ratio=0.72, total_amount=1.5e12, fetched_at="2026-08-06 09:00:00"),
        _emotion(zt=150),
        now=_NOW,
    )
    assert payload["is_stale"] is True
    assert payload["confidence"] == "MEDIUM"  # HIGH → MEDIUM
    assert "DATA_STALE" in _codes(payload)
    assert payload["data_cutoff"] == "2026-08-06 09:00:00"  # 不伪装实时


def test_stale_with_other_downgrades_stays_low():
    payload = derive_market_regime(
        _breadth_env(up_ratio=0.30, total_amount=7.0e11, fetched_at="2026-08-06 09:00:00"),
        _emotion(zt=12),
        now=_NOW,
    )
    assert payload["market_regime"] == "RISK_OFF"
    assert payload["is_stale"] is True
    assert payload["confidence"] == "MEDIUM"


def test_missing_fetched_at_fail_closed_stale():
    payload = derive_market_regime(
        _breadth_env(up_ratio=0.72, total_amount=1.5e12, fetched_at=None),
        _emotion(zt=150),
        now=_NOW,
    )
    assert payload["is_stale"] is True
    assert "DATA_STALE" in _codes(payload)


def test_fresh_data_not_stale():
    payload = derive_market_regime(
        _breadth_env(up_ratio=0.72, total_amount=1.5e12),
        _emotion(zt=150),
        now=_NOW,
    )
    assert payload["is_stale"] is False


# ---------------------------------------------------------------------------
# 8. 强冲突 → NEUTRAL / LOW Confidence，不激进
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("up_ratio", "zt"),
    [
        (0.72, 12),   # 宽度强 + 投机冰点
        (0.30, 150),  # 宽度弱 + 投机亢奋
    ],
)
def test_strong_conflict_neutral_low_confidence(up_ratio, zt):
    payload = derive_market_regime(
        _breadth_env(up_ratio=up_ratio, total_amount=1.5e12),
        _emotion(zt=zt),
        now=_NOW,
    )
    assert payload["market_regime"] == "NEUTRAL"
    assert payload["confidence"] == "LOW"
    assert "SIGNAL_CONFLICT" in _codes(payload)


# ---------------------------------------------------------------------------
# 9. 相同输入 → 完全相同输出（确定性）
# ---------------------------------------------------------------------------
def test_deterministic_repeat_same_output():
    inputs = (
        _breadth_env(up_ratio=0.72, total_amount=1.5e12),
        _emotion(zt=150, dt=8, break_rate=0.3),
    )
    first = derive_market_regime(*inputs, now=_NOW)
    second = derive_market_regime(*inputs, now=_NOW)
    assert first == second


# ---------------------------------------------------------------------------
# 10. reason codes 与实际规则一致（固定顺序可审计）
# ---------------------------------------------------------------------------
def test_reason_codes_exact_for_unknown_core():
    payload = derive_market_regime(
        _breadth_env("unavailable", data=None),
        _emotion(zt=None, dt=None, break_rate=None, date=None),
        now=_NOW,
    )
    assert _codes(payload) == [
        "DATA_UNAVAILABLE",
        "BREADTH_UNAVAILABLE",
        "RISK_APPETITE_UNAVAILABLE",
        "LIQUIDITY_UNAVAILABLE",
        "EMOTION_UNAVAILABLE",
        "TRADE_DATE_UNKNOWN",
    ]


def test_reason_codes_exact_for_risk_on():
    payload = derive_market_regime(
        _breadth_env(up_ratio=0.72, total_amount=1.5e12),
        _emotion(zt=150),
        now=_NOW,
    )
    assert _codes(payload) == [
        "BREADTH_STRONG",
        "RISK_APPETITE_HIGH",
        "LIQUIDITY_STRONG",
        "EMOTION_NORMAL",
    ]


# ---------------------------------------------------------------------------
# 11. API contract
# ---------------------------------------------------------------------------
def test_api_contract_normal(monkeypatch):
    monkeypatch.setattr(
        market, "get_market_breadth",
        lambda: _breadth_env(up_ratio=0.72, total_amount=1.5e12, fetched_at=_recent_fetched_at()),
    )
    monkeypatch.setattr(market, "get_short_term_emotion", lambda: _emotion(zt=150))
    r = client.get("/api/market/regime")
    assert r.status_code == 200
    data = r.json()["data"]
    assert set(data) >= {
        "market_regime", "risk_appetite", "confidence", "is_stale",
        "trade_date", "data_cutoff", "components", "reasons",
    }
    assert data["market_regime"] == "RISK_ON"
    assert data["risk_appetite"] == "HIGH"
    assert data["confidence"] == "HIGH"
    assert set(data["components"]) == {"breadth", "speculation", "liquidity", "emotion"}
    for comp in data["components"].values():
        assert set(comp) >= {"state", "available", "fresh", "raw"}
    assert all({"code", "message"} <= set(r) for r in data["reasons"])


def test_api_contract_unavailable(monkeypatch):
    monkeypatch.setattr(market, "get_market_breadth", lambda: _breadth_env("unavailable", data=None))
    monkeypatch.setattr(market, "get_short_term_emotion", lambda: _emotion())
    r = client.get("/api/market/regime")
    assert r.status_code == 200  # 状态在 body，不抛 5xx
    data = r.json()["data"]
    assert data["market_regime"] == "UNKNOWN"
    assert data["confidence"] == "LOW"


def test_api_unexpected_error_502(monkeypatch):
    def boom():
        raise RuntimeError("unexpected")

    monkeypatch.setattr(market_regime, "get_market_regime", boom)
    r = client.get("/api/market/regime")
    assert r.status_code == 502
    assert "市场状态异常" in r.json()["detail"]
    assert "unexpected" in r.json()["detail"]


def test_api_emotion_exception_falls_back(monkeypatch):
    monkeypatch.setattr(
        market, "get_market_breadth",
        lambda: _breadth_env(up_ratio=0.50, total_amount=1.0e12, fetched_at=_recent_fetched_at()),
    )

    def boom():
        raise RuntimeError("emotion boom")

    monkeypatch.setattr(market, "get_short_term_emotion", boom)
    r = client.get("/api/market/regime")
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["components"]["speculation"]["available"] is False
    assert data["components"]["emotion"]["available"] is False
    assert data["risk_appetite"] == "UNKNOWN"
    assert "DATA_PARTIAL" in _codes(data)


# ---------------------------------------------------------------------------
# 12. trade_date / data_cutoff 诚实性
# ---------------------------------------------------------------------------
def test_trade_date_from_emotion():
    payload = derive_market_regime(
        _breadth_env(up_ratio=0.72, total_amount=1.5e12),
        _emotion(zt=150, date="2026-08-07"),
        now=_NOW,
    )
    assert payload["trade_date"] == "2026-08-07"


def test_trade_date_unknown_when_no_date():
    payload = derive_market_regime(
        _breadth_env(up_ratio=0.72, total_amount=1.5e12),
        _emotion(zt=150, date=None),
        now=_NOW,
    )
    assert payload["trade_date"] is None
    assert "TRADE_DATE_UNKNOWN" in _codes(payload)


def test_data_cutoff_missing_not_fabricated():
    payload = derive_market_regime(
        _breadth_env(up_ratio=0.72, total_amount=1.5e12, fetched_at=None),
        _emotion(zt=150),
        now=_NOW,
    )
    assert payload["data_cutoff"] is None
