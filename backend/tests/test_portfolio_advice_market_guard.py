"""持仓建议在市场广度不可用时失败关闭（不调模型）。"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import app as app_module
import daily_review
import portfolio_advice_service as svc

client = TestClient(app_module.app)


def _review_breadth_unavailable():
    return {
        "schema_version": "daily-review-v0.1",
        "generated_at": "2026-07-21 12:00:00",
        "trade_date": "2026-07-21",
        "data_cutoff": None,
        "status": "partial",
        "warnings": ["全市场行情数据获取失败，市场广度暂不可用。"],
        "data_health": {
            "components": {
                "indices": "normal",
                "breadth": "unavailable",
                "emotion": "normal",
                "industry_boards": "normal",
                "concept_boards": "normal",
            }
        },
        "market_environment": {
            "breadth": {"status": "unavailable", "data": None, "warnings": []},
        },
        "sector_rotation": {},
        "short_term_emotion": {"status": "normal", "data": {}},
        "capital_activity": {},
    }


def _portfolio():
    return {
        "holdings": [{
            "code": "001896", "name": "豫能控股",
            "shares": 1000, "cost": 5.0, "price": 5.5,
        }],
        "totals": {},
    }


def test_prepare_raises_when_breadth_unavailable_no_model(monkeypatch):
    monkeypatch.setattr(svc.portfolio, "get_portfolio", _portfolio)
    monkeypatch.setattr(daily_review, "generate_daily_review", _review_breadth_unavailable)
    model_called = {"n": 0}

    def boom_model(*a, **k):
        model_called["n"] += 1
        raise AssertionError("model must not be called")

    with pytest.raises(svc.PortfolioAdviceMarketDataError) as ei:
        svc.prepare_portfolio_advice_messages()
    assert "市场核心数据暂不可用" in str(ei.value)

    with pytest.raises(svc.PortfolioAdviceMarketDataError):
        svc.generate_portfolio_advice({"model": "x"}, model_runner=boom_model)
    assert model_called["n"] == 0


def test_api_returns_503_safe_message(monkeypatch):
    monkeypatch.setattr(svc.portfolio, "get_portfolio", _portfolio)
    monkeypatch.setattr(daily_review, "generate_daily_review", _review_breadth_unavailable)

    r = client.post(
        "/api/portfolio/advice",
        json={
            "user_request": None,
            "llm": {
                "provider": "deepseek",
                "baseURL": "https://api.deepseek.com",
                "apiKey": "sk-test",
                "model": "deepseek-chat",
            },
        },
    )
    assert r.status_code == 503
    detail = r.json().get("detail", "")
    assert "市场核心数据暂不可用" in detail
    assert "ProxyError" not in detail
    assert "https://" not in detail


def test_partial_with_valid_breadth_still_prepares(monkeypatch):
    def review_ok_partial():
        rev = _review_breadth_unavailable()
        rev["data_health"]["components"]["breadth"] = "partial"
        rev["market_environment"]["breadth"] = {
            "status": "partial",
            "data": {"stock_count": 5000, "valid_count": 4000, "up_ratio": 0.4},
            "warnings": [],
        }
        rev["status"] = "partial"
        return rev

    monkeypatch.setattr(svc.portfolio, "get_portfolio", _portfolio)
    monkeypatch.setattr(daily_review, "generate_daily_review", review_ok_partial)
    prepared = svc.prepare_portfolio_advice_messages()
    assert prepared["messages"]
    assert prepared["daily_review"]["data_health"]["components"]["breadth"] == "partial"


# ---------------------------------------------------------------------------
# 持仓核心行情缺失时的 Fail-Closed 防护测试
# ---------------------------------------------------------------------------

def test_prepare_raises_when_holding_quote_unavailable_fails_closed(monkeypatch):
    """当持仓价格缺失/为 0/非法时，立即抛出 PortfolioAdviceMarketDataError，且绝不调用 daily_review 或模型。"""
    invalid_portfolios = [
        {"holdings": [{"code": "001896", "name": "豫能控股", "shares": 1000, "cost": 5.0, "price": None}], "totals": {}},
        {"holdings": [{"code": "001896", "name": "豫能控股", "shares": 1000, "cost": 5.0, "price": 0.0}], "totals": {}},
        {"holdings": [{"code": "001896", "name": "豫能控股", "shares": 1000, "cost": 5.0, "price": -1.0}], "totals": {}},
    ]
    for pf in invalid_portfolios:
        monkeypatch.setattr(svc.portfolio, "get_portfolio", lambda: pf)
        review_spy = {"called": False}

        def fake_daily_review():
            review_spy["called"] = True
            return _review_breadth_unavailable()

        monkeypatch.setattr(daily_review, "generate_daily_review", fake_daily_review)
        model_called = {"n": 0}

        def boom_model(*a, **k):
            model_called["n"] += 1
            raise AssertionError("model must not be called")

        with pytest.raises(svc.PortfolioAdviceMarketDataError) as ei:
            svc.prepare_portfolio_advice_messages()
        assert "持仓核心行情暂不可用" in str(ei.value)
        assert review_spy["called"] is False

        with pytest.raises(svc.PortfolioAdviceMarketDataError):
            svc.generate_portfolio_advice({"model": "x"}, model_runner=boom_model)
        assert model_called["n"] == 0


def test_api_returns_503_when_holding_quote_unavailable(monkeypatch):
    """持仓核心行情缺失时，/api/portfolio/advice 返回 HTTP 503 且包含安全业务文案。"""
    pf = {"holdings": [{"code": "001896", "name": "豫能控股", "shares": 1000, "cost": 5.0, "price": None}], "totals": {}}
    monkeypatch.setattr(svc.portfolio, "get_portfolio", lambda: pf)

    r = client.post(
        "/api/portfolio/advice",
        json={
            "user_request": None,
            "llm": {
                "provider": "deepseek",
                "baseURL": "https://api.deepseek.com",
                "apiKey": "sk-test",
                "model": "deepseek-chat",
            },
        },
    )
    assert r.status_code == 503
    detail = r.json().get("detail", "")
    assert "持仓核心行情暂不可用" in detail
