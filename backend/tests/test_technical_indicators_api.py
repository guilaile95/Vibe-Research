"""HTTP 路由测试：TestClient + monkeypatch astock.kline，禁止真实网络。"""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

import app as app_module
import astock
import data_health_event_store

client = TestClient(app_module.app)


def _make_klines(n, base_close=10.0, step=0.1):
    start = date(2026, 1, 1)
    return [
        {
            "datetime": (start + timedelta(days=i)).isoformat(),
            "open": base_close + i * step,
            "close": base_close + i * step,
            "high": base_close + i * step + 0.05,
            "low": base_close + i * step - 0.05,
            "vol": 1000 + i * 100,
            "amount": (base_close + i * step) * (1000 + i * 100),
        }
        for i in range(n)
    ]


@pytest.fixture(autouse=True)
def _clear_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("VR_DATA_DIR", str(tmp_path))
    app_module._DC_CACHE = app_module.TTLCache(max_entries=1024)
    yield
    app_module._DC_CACHE = app_module.TTLCache(max_entries=1024)


# ── 1 normal ──────────────────────────────────────────────────────────


def test_normal_response(monkeypatch):
    klines = _make_klines(70)
    monkeypatch.setattr(astock, "kline", lambda code, category=4, offset=60: list(klines))

    resp = client.get("/api/market/technical-indicators?code=000001&period=daily&days=120")
    assert resp.status_code == 200
    body = resp.json()
    assert "data" in body
    env = body["data"]
    assert env["code"] == "000001"
    assert env["period"] == "daily"
    assert env["status"] == "normal"
    assert env["latest"]["close"] is not None
    assert env["latest"]["sma20"] is not None
    assert env["latest"]["sma60"] is not None
    assert env["latest"]["rsi14"] is not None
    assert isinstance(env["series"], list)
    assert len(env["series"]) <= 60


# ── 2 非法股票代码 ────────────────────────────────────────────────────


def test_invalid_code():
    resp = client.get("/api/market/technical-indicators?code=abc&period=daily")
    assert resp.status_code == 400


def test_invalid_code_short():
    resp = client.get("/api/market/technical-indicators?code=12345&period=daily")
    assert resp.status_code == 400


# ── 3 非法 period ────────────────────────────────────────────────────


def test_invalid_period(monkeypatch):
    klines = _make_klines(70)
    monkeypatch.setattr(astock, "kline", lambda code, category=4, offset=60: list(klines))

    resp = client.get("/api/market/technical-indicators?code=000001&period=weekly")
    assert resp.status_code == 400


# ── 4 days 越界 clamp + warning ──────────────────────────────────────


def test_days_clamp_low(monkeypatch):
    klines = _make_klines(70)
    monkeypatch.setattr(astock, "kline", lambda code, category=4, offset=20: list(klines))

    resp = client.get("/api/market/technical-indicators?code=000001&period=daily&days=5")
    assert resp.status_code == 200
    env = resp.json()["data"]
    assert any("clamp" in w for w in env["warnings"])


def test_days_clamp_high(monkeypatch):
    klines = _make_klines(70)
    monkeypatch.setattr(astock, "kline", lambda code, category=4, offset=240: list(klines))

    resp = client.get("/api/market/technical-indicators?code=000001&period=daily&days=500")
    assert resp.status_code == 200
    env = resp.json()["data"]
    assert any("clamp" in w for w in env["warnings"])


# ── 5 上游异常 → HTTP 200 unavailable ───────────────────────────────


def test_upstream_failure_returns_safe_unavailable_and_records_failure(monkeypatch):
    failures = []
    monkeypatch.setattr(data_health_event_store, "record_failure", lambda *args: failures.append(args))

    def _raise(*args, **kwargs):
        raise RuntimeError("mootdx connection refused")

    monkeypatch.setattr(astock, "kline", _raise)

    resp = client.get("/api/market/technical-indicators?code=000001&period=daily")
    assert resp.status_code == 200
    env = resp.json()["data"]
    assert env["status"] == "unavailable"
    assert all(value is None for value in env["latest"].values())
    assert env["triggers"] == []
    assert env["series"] == []
    assert "mootdx connection refused" not in resp.text
    assert failures == [("technical_indicators", "SOURCE_UNAVAILABLE")]


def test_upstream_failure_is_not_cached_and_retries(monkeypatch):
    calls = 0

    def _raise(*args, **kwargs):
        nonlocal calls
        calls += 1
        raise RuntimeError("private upstream detail")

    monkeypatch.setattr(astock, "kline", _raise)
    assert client.get("/api/market/technical-indicators?code=000001").status_code == 200
    assert client.get("/api/market/technical-indicators?code=000001").status_code == 200
    assert calls == 2


# ── 6 缓存命中不重复调用上游 ──────────────────────────────────────


def test_cache_hit(monkeypatch):
    klines = _make_klines(70)
    call_count = 0

    def _mock_kline(code, category=4, offset=60):
        nonlocal call_count
        call_count += 1
        return list(klines)

    monkeypatch.setattr(astock, "kline", _mock_kline)

    resp1 = client.get("/api/market/technical-indicators?code=000001&period=daily&days=120")
    assert resp1.status_code == 200
    assert call_count == 1

    resp2 = client.get("/api/market/technical-indicators?code=000001&period=daily&days=120")
    assert resp2.status_code == 200
    assert call_count == 1  # 缓存命中，不再调用


# ── 7 partial 状态 ───────────────────────────────────────────────────


def test_partial_status(monkeypatch):
    klines = _make_klines(30)
    monkeypatch.setattr(astock, "kline", lambda code, category=4, offset=30: list(klines))

    resp = client.get("/api/market/technical-indicators?code=000001&period=daily&days=30")
    assert resp.status_code == 200
    env = resp.json()["data"]
    assert env["status"] == "partial"
    assert env["latest"]["sma60"] is None
    assert len(env["limitations"]) > 0


# ── 8 unavailable 不缓存 ─────────────────────────────────────────────


def test_unavailable_not_cached(monkeypatch):
    call_count = 0

    def _mock_kline(code, category=4, offset=60):
        nonlocal call_count
        call_count += 1
        return []

    monkeypatch.setattr(astock, "kline", _mock_kline)

    resp1 = client.get("/api/market/technical-indicators?code=000001&period=daily")
    assert resp1.status_code == 200
    assert resp1.json()["data"]["status"] == "unavailable"
    assert call_count == 1

    resp2 = client.get("/api/market/technical-indicators?code=000001&period=daily")
    assert resp2.status_code == 200
    assert resp2.json()["data"]["status"] == "unavailable"
    assert call_count == 2  # unavailable 不缓存，再次调用


def test_clamp_warning_is_request_scoped_on_cache_hits(monkeypatch):
    klines = _make_klines(70)
    monkeypatch.setattr(astock, "kline", lambda code, category=4, offset=60: list(klines))

    clamped = client.get("/api/market/technical-indicators?code=000001&days=5").json()["data"]
    exact = client.get("/api/market/technical-indicators?code=000001&days=20").json()["data"]
    clamped_again = client.get("/api/market/technical-indicators?code=000001&days=5").json()["data"]

    assert any("clamp" in warning for warning in clamped["warnings"])
    assert not any("clamp" in warning for warning in exact["warnings"])
    assert any("clamp" in warning for warning in clamped_again["warnings"])
