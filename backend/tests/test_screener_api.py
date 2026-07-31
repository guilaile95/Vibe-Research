"""API contract tests for POST /api/screener/evaluate."""

from __future__ import annotations

import math
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import app as app_module
import screener_service as svc
from screener_models import FORBIDDEN_RESPONSE_KEYS

client = TestClient(app_module.app)


def _valid_body(**overrides):
    body = {
        "codes": ["000001", "600519"],
        "conditions": [{"id": "price_gt_sma20"}],
    }
    body.update(overrides)
    return body


def _mock_env(close=12.0, sma20=11.0, sma60=10.0, status="normal"):
    return {
        "status": status,
        "trade_date": "2026-07-30",
        "limitations": [],
        "latest": {
            "close": close,
            "sma20": sma20,
            "sma60": sma60,
            "rsi14": 55.0,
            "macd_histogram": 0.2,
            "volume_ratio_5_20": 1.1,
        },
        "triggers": [],
    }


@pytest.fixture
def mock_eval_ok(monkeypatch):
    def kline_fn(code, days):
        return [{"datetime": "2026-07-01", "close": 10, "high": 11, "low": 9, "volume": 1}]

    def compute_fn(raw, **kwargs):
        # 000001 match, 600519 reject
        if kwargs["code"] == "000001":
            return _mock_env(close=12, sma20=11)
        return _mock_env(close=10, sma20=11)

    monkeypatch.setattr(svc, "evaluate_screener", lambda body, **kw: svc.evaluate_screener(
        body, kline_fn=kline_fn, compute_fn=compute_fn, now_iso="2026-07-31T12:00:00.000000Z", **{k: v for k, v in kw.items() if k not in ("kline_fn", "compute_fn", "now_iso")}
    ))
    # Actually simpler: patch at evaluate_one_stock path via evaluate_screener kwargs by patching astock
    monkeypatch.setattr("screener_service.astock.kline", lambda code, category=4, offset=120: [
        {"datetime": "2026-07-01", "close": 10, "high": 11, "low": 9, "volume": 1}
    ])

    def compute(raw, **kwargs):
        if kwargs["code"] == "000001":
            return _mock_env(close=12, sma20=11)
        if kwargs["code"] == "000002":
            raise RuntimeError("boom")
        return _mock_env(close=10, sma20=11)

    monkeypatch.setattr("screener_service.ti.compute_indicators", compute)


def _assert_no_forbidden(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            assert k not in FORBIDDEN_RESPONSE_KEYS, f"forbidden key {k}"
            _assert_no_forbidden(v)
    elif isinstance(obj, list):
        for it in obj:
            _assert_no_forbidden(it)


def test_happy_path_match_and_reject(monkeypatch):
    monkeypatch.setattr(
        "screener_service.astock.kline",
        lambda code, category=4, offset=120: [
            {"datetime": "2026-07-01", "close": 10, "high": 11, "low": 9, "volume": 1}
        ],
    )

    def compute(raw, **kwargs):
        if kwargs["code"] == "000001":
            return _mock_env(close=12, sma20=11)
        return _mock_env(close=10, sma20=11)

    monkeypatch.setattr("screener_service.ti.compute_indicators", compute)

    r = client.post("/api/screener/evaluate", json=_valid_body())
    assert r.status_code == 200
    data = r.json()
    assert data["logic"] == "AND"
    assert data["schema_version"] == "screener-v0.1"
    assert [s["code"] for s in data["matched"]] == ["000001"]
    assert [s["code"] for s in data["rejected"]] == ["600519"]
    assert data["unavailable"] == []
    assert data["status"] == "normal"
    _assert_no_forbidden(data)


def test_kline_exception_isolated(monkeypatch):
    def kline(code, category=4, offset=120):
        if code == "000002":
            raise RuntimeError("down")
        return [{"datetime": "2026-07-01", "close": 10, "high": 11, "low": 9, "volume": 1}]

    monkeypatch.setattr("screener_service.astock.kline", kline)
    monkeypatch.setattr(
        "screener_service.ti.compute_indicators",
        lambda raw, **kw: _mock_env(close=12, sma20=11),
    )

    r = client.post(
        "/api/screener/evaluate",
        json={"codes": ["000001", "000002"], "conditions": [{"id": "price_gt_sma20"}]},
    )
    assert r.status_code == 200
    data = r.json()
    assert [s["code"] for s in data["matched"]] == ["000001"]
    assert [s["code"] for s in data["unavailable"]] == ["000002"]
    assert data["status"] == "partial"
    assert data["unavailable"][0]["matched"] is None


def test_missing_sma60_unavailable(monkeypatch):
    monkeypatch.setattr(
        "screener_service.astock.kline",
        lambda *a, **k: [{"datetime": "2026-07-01", "close": 10, "high": 11, "low": 9, "volume": 1}],
    )
    monkeypatch.setattr(
        "screener_service.ti.compute_indicators",
        lambda raw, **kw: _mock_env(close=12, sma20=11, sma60=None, status="partial"),
    )
    r = client.post(
        "/api/screener/evaluate",
        json={"codes": ["600519"], "conditions": [{"id": "price_gt_sma60"}]},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["matched"] == []
    assert data["rejected"] == []
    assert len(data["unavailable"]) == 1
    assert data["unavailable"][0]["bucket"] == "unavailable"


def test_code_dedupe_sort(monkeypatch):
    seen = []

    def kline(code, category=4, offset=120):
        seen.append(code)
        return [{"datetime": "2026-07-01", "close": 10, "high": 11, "low": 9, "volume": 1}]

    monkeypatch.setattr("screener_service.astock.kline", kline)
    monkeypatch.setattr(
        "screener_service.ti.compute_indicators",
        lambda raw, **kw: _mock_env(close=12, sma20=11),
    )
    r = client.post(
        "/api/screener/evaluate",
        json={
            "codes": ["600519", "000001", "600519"],
            "conditions": [{"id": "price_gt_sma20"}],
        },
    )
    assert r.status_code == 200
    assert seen == ["000001", "600519"]


def test_empty_codes_422():
    r = client.post("/api/screener/evaluate", json={"codes": [], "conditions": [{"id": "price_gt_sma20"}]})
    assert r.status_code == 422


def test_too_many_codes_422():
    codes = [f"{i:06d}" for i in range(31)]
    r = client.post("/api/screener/evaluate", json={"codes": codes, "conditions": [{"id": "price_gt_sma20"}]})
    assert r.status_code == 422


def test_invalid_code_422():
    r = client.post(
        "/api/screener/evaluate",
        json={"codes": ["ABC"], "conditions": [{"id": "price_gt_sma20"}]},
    )
    assert r.status_code == 422


def test_duplicate_condition_id_422():
    r = client.post(
        "/api/screener/evaluate",
        json={
            "codes": ["000001"],
            "conditions": [{"id": "price_gt_sma20"}, {"id": "price_gt_sma20"}],
        },
    )
    assert r.status_code == 422


def test_unknown_condition_422():
    r = client.post(
        "/api/screener/evaluate",
        json={"codes": ["000001"], "conditions": [{"id": "not_a_real_condition"}]},
    )
    assert r.status_code == 422


def test_missing_params_422():
    r = client.post(
        "/api/screener/evaluate",
        json={"codes": ["000001"], "conditions": [{"id": "rsi_between"}]},
    )
    assert r.status_code == 422


def test_extra_params_field_422():
    r = client.post(
        "/api/screener/evaluate",
        json={
            "codes": ["000001"],
            "conditions": [
                {"id": "rsi_between", "params": {"min": 30, "max": 70, "extra": 1}}
            ],
        },
    )
    assert r.status_code == 422


def test_extra_top_level_field_422():
    r = client.post(
        "/api/screener/evaluate",
        json={
            "codes": ["000001"],
            "conditions": [{"id": "price_gt_sma20"}],
            "days": 120,
        },
    )
    assert r.status_code == 422


def test_min_gt_max_422():
    r = client.post(
        "/api/screener/evaluate",
        json={
            "codes": ["000001"],
            "conditions": [{"id": "rsi_between", "params": {"min": 80, "max": 20}}],
        },
    )
    assert r.status_code == 422


def test_threshold_le_zero_422():
    r = client.post(
        "/api/screener/evaluate",
        json={
            "codes": ["000001"],
            "conditions": [{"id": "volume_ratio_gte", "params": {"threshold": 0}}],
        },
    )
    assert r.status_code == 422


def test_nan_infinity_422():
    r = client.post(
        "/api/screener/evaluate",
        json={
            "codes": ["000001"],
            "conditions": [{"id": "rsi_between", "params": {"min": "NaN", "max": 70}}],
        },
    )
    assert r.status_code == 422

    r2 = client.post(
        "/api/screener/evaluate",
        json={
            "codes": ["000001"],
            "conditions": [
                {"id": "volume_ratio_gte", "params": {"threshold": "Infinity"}}
            ],
        },
    )
    assert r2.status_code == 422


def test_determinism_excluding_evaluated_at(monkeypatch):
    monkeypatch.setattr(
        "screener_service.astock.kline",
        lambda *a, **k: [{"datetime": "2026-07-01", "close": 10, "high": 11, "low": 9, "volume": 1}],
    )
    monkeypatch.setattr(
        "screener_service.ti.compute_indicators",
        lambda raw, **kw: _mock_env(close=12, sma20=11),
    )
    body = {"codes": ["600519", "000001"], "conditions": [{"id": "price_gt_sma20"}]}
    a = client.post("/api/screener/evaluate", json=body).json()
    b = client.post("/api/screener/evaluate", json=body).json()
    for key in ("matched", "rejected", "unavailable", "status", "logic", "schema_version"):
        assert a[key] == b[key]
