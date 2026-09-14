from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import astock
import stock_valuation_context as context
import stock_valuation_context_router as router


def _snapshot() -> list[dict[str, Any]]:
    return [
        {"code": "000001", "name": "甲", "industry": "电子", "pe_ttm": 10.0, "pb": 1.0, "market_cap": 100.0},
        {"code": "000002", "name": "乙", "industry": "电子", "pe_ttm": 20.0, "pb": 2.0, "market_cap": 200.0},
        {"code": "000003", "name": "丙", "industry": "电子", "pe_ttm": 0.0, "pb": 0.0, "market_cap": 0.0},
        {"code": "000004", "name": "丁", "industry": "电子", "pe_ttm": -5.0, "pb": -2.0, "market_cap": 50.0},
        {"code": "000005", "name": "戊", "industry": "医药", "pe_ttm": 5.0, "pb": 1.0, "market_cap": 100.0},
        {"code": "000006", "name": "己", "industry": None, "pe_ttm": 8.0, "pb": 3.0, "market_cap": 80.0},
    ]


def test_stock_uses_current_member_positive_median_without_fabricating_zero():
    result = context.build_stock_valuation_context("000001", snapshot_reader=_snapshot)

    assert result["schema_version"] == "stock-valuation-context.v0.1"
    assert result["status"] == "normal"
    assert result["industry_name"] == "电子"
    assert result["industry_status"] == "normal"
    assert result["industry_membership_semantics"] == "CURRENT_MEMBERSHIP_SNAPSHOT"
    assert result["valuation_semantics"] == "CURRENT_MEMBER_VALUATION_DISTRIBUTION_ONLY"
    assert result["pe_source"] == "eastmoney_clist_f115"
    assert result["pb_source"] == "eastmoney_clist_f23"
    assert result["provenance"]["dynamic_pe_used"] is False
    assert result["pe_ttm"]["stock_value"] == pytest.approx(10.0)
    assert result["pe_ttm"]["industry_positive_median"] == pytest.approx(15.0)
    assert result["pe_ttm"]["vs_industry_positive_median"] == pytest.approx(-5.0)
    assert result["pe_ttm"]["rank_among_positive"] == 1
    assert result["pe_ttm"]["positive_sample_count"] == 2
    assert result["pe_ttm"]["industry_zero_count"] == 1
    assert result["pe_ttm"]["industry_negative_count"] == 1
    assert result["pb"]["stock_value"] == pytest.approx(1.0)
    assert result["pb"]["industry_positive_median"] == pytest.approx(1.5)
    assert result["pb"]["vs_industry_positive_median"] == pytest.approx(-0.5)


def test_zero_and_negative_stock_values_stay_visible_without_median_comparison():
    zero = context.build_stock_valuation_context("000003", snapshot_reader=_snapshot)
    assert zero["status"] == "partial"
    assert zero["pe_ttm"]["stock_value"] == pytest.approx(0.0)
    assert zero["pe_ttm"]["stock_sign"] == "zero"
    assert zero["pe_ttm"]["vs_industry_positive_median"] is None
    assert zero["pe_ttm"]["rank_among_positive"] is None
    assert zero["pe_ttm"]["industry_positive_median"] == pytest.approx(15.0)

    negative = context.build_stock_valuation_context("000004", snapshot_reader=_snapshot)
    assert negative["pe_ttm"]["stock_value"] == pytest.approx(-5.0)
    assert negative["pe_ttm"]["stock_sign"] == "negative"
    assert negative["pe_ttm"]["vs_industry_positive_median"] is None
    assert negative["pe_ttm"]["rank_among_positive"] is None


def test_unknown_industry_keeps_stock_values_and_isolates_industry_median():
    result = context.build_stock_valuation_context("000006", snapshot_reader=_snapshot)
    assert result["industry_name"] == "UNKNOWN"
    assert result["industry_status"] == "unknown"
    assert result["status"] == "partial"
    assert result["pe_ttm"]["stock_value"] == pytest.approx(8.0)
    assert result["pe_ttm"]["industry_positive_median"] is None
    assert result["pe_ttm"]["vs_industry_positive_median"] is None
    assert result["pb"]["stock_value"] == pytest.approx(3.0)
    assert result["pb"]["industry_positive_median"] is None


def test_missing_stock_and_snapshot_failure_are_unavailable_not_zero():
    missing = context.build_stock_valuation_context("000999", snapshot_reader=_snapshot)
    assert missing["status"] == "unavailable"
    assert missing["pe_ttm"]["stock_value"] is None
    assert missing["pe_ttm"]["industry_positive_median"] is None

    failed = context.build_stock_valuation_context(
        "000001",
        snapshot_reader=lambda: (_ for _ in ()).throw(RuntimeError("fixture")),
    )
    assert failed["status"] == "unavailable"
    assert failed["industry_status"] == "unavailable"
    assert failed["pe_ttm"]["stock_value"] is None
    assert failed["pb"]["stock_value"] is None


def test_raw_provider_fields_use_f115_not_dynamic_f9():
    raw_rows = [
        {"f12": "000001", "f14": "甲", "f13": 0, "f9": 100.0, "f115": 10.0, "f20": 100.0, "f23": 1.0, "f100": "电子"},
        {"f12": "000002", "f14": "乙", "f13": 0, "f9": 200.0, "f115": 20.0, "f20": 200.0, "f23": 2.0, "f100": "电子"},
        {"f12": "000003", "f14": "丙", "f13": 0, "f9": 50.0, "f115": None, "f20": 50.0, "f23": 3.0, "f100": "电子"},
    ]

    def snapshot():
        return [mapped for raw in raw_rows if (mapped := astock._map_a_share_row(raw)) is not None]

    result = context.build_stock_valuation_context("000001", snapshot_reader=snapshot)
    assert result["pe_ttm"]["stock_value"] == pytest.approx(10.0)
    assert result["pe_ttm"]["industry_positive_median"] == pytest.approx(15.0)
    assert result["pe_ttm"]["industry_missing_count"] == 1
    assert result["provenance"]["dynamic_pe_used"] is False

    missing_ttm = context.build_stock_valuation_context("000003", snapshot_reader=snapshot)
    assert missing_ttm["pe_ttm"]["stock_value"] is None
    assert missing_ttm["pe_ttm"]["stock_sign"] == "missing"
    assert missing_ttm["pe_ttm"]["vs_industry_positive_median"] is None


def test_http_route_validates_code_and_keeps_read_only_envelope(monkeypatch):
    payload = {"schema_version": context.SCHEMA_VERSION, "status": "unavailable"}
    monkeypatch.setattr(router.service, "build_stock_valuation_context", lambda code: payload)
    app = FastAPI()
    app.include_router(router.router)
    client = TestClient(app)

    assert client.get("/api/stock-valuation-context?code=000001").json() == payload
    assert client.get("/api/stock-valuation-context?code=ABC").status_code == 422
    assert "BUY" not in str(payload)
    assert "SELL" not in str(payload)
