"""Gate 业务阻断 vs 运行失败事件编码。"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

import data_health_event_store as store
import data_health_service as svc
import portfolio_advice_service as pas


@pytest.fixture()
def events_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("VR_DATA_DIR", str(tmp_path))
    return tmp_path


def test_breadth_unavailable_records_business_block(events_dir, monkeypatch):
    portfolio_data = {
        "holdings": [{"code": "600519", "shares": 100, "cost": 10.0, "price": 20.0}],
        "data_status": "normal",
    }
    monkeypatch.setattr(
        "portfolio.get_portfolio",
        lambda: portfolio_data,
    )
    monkeypatch.setattr(pas.portfolio, "get_portfolio", lambda: portfolio_data)
    monkeypatch.setattr(
        pas.portfolio,
        "_is_valid_price",
        lambda px: isinstance(px, (int, float)) and not isinstance(px, bool) and px > 0,
    )
    monkeypatch.setattr(
        pas.ai_result_service,
        "compute_portfolio_fingerprint",
        lambda holdings: "fp",
    )
    monkeypatch.setattr(
        pas.daily_review,
        "generate_daily_review",
        lambda: {
            "trade_date": "2026-07-28",
            "data_health": {"components": {"breadth": "unavailable"}},
            "market_environment": {"breadth": {"status": "unavailable"}},
        },
    )
    with pytest.raises(pas.PortfolioAdviceMarketDataError):
        pas.prepare_portfolio_advice_messages()
    ev = store.load_events_readonly()["portfolio_advice_gate"]
    assert ev["last_error_code"] == "MARKET_BREADTH_UNAVAILABLE"
    st, blocks, *_ = svc.map_gate_event(ev)
    assert st == "normal"
    assert blocks is True


def test_context_builder_typeerror_is_runtime_failure(events_dir, monkeypatch):
    portfolio_data = {
        "holdings": [{"code": "600519", "shares": 100, "cost": 10.0, "price": 20.0}],
        "data_status": "normal",
    }
    monkeypatch.setattr(pas.portfolio, "get_portfolio", lambda: portfolio_data)
    monkeypatch.setattr(
        pas.portfolio,
        "_is_valid_price",
        lambda px: True,
    )
    monkeypatch.setattr(
        pas.ai_result_service,
        "compute_portfolio_fingerprint",
        lambda holdings: "fp",
    )
    monkeypatch.setattr(
        pas.daily_review,
        "generate_daily_review",
        lambda: {
            "trade_date": "2026-07-28",
            "data_health": {"components": {"breadth": "normal"}},
            "market_environment": {"breadth": {"status": "normal"}},
        },
    )

    def boom(*a, **k):
        raise TypeError("context broken")

    monkeypatch.setattr(
        pas.portfolio_advice_context,
        "build_portfolio_advice_context",
        boom,
    )
    with pytest.raises(pas.PortfolioAdviceMarketDataError):
        pas.prepare_portfolio_advice_messages()
    ev = store.load_events_readonly()["portfolio_advice_gate"]
    assert ev["last_error_code"] == "SOURCE_UNAVAILABLE"
    assert ev["last_success_at"] is None or (
        store.parse_utc(ev["last_error_at"]) is not None
        and (
            ev["last_success_at"] is None
            or store.parse_utc(ev["last_error_at"]) >= store.parse_utc(ev["last_success_at"])
        )
    )
    st, blocks, *_ = svc.map_gate_event(ev)
    assert st == "unavailable"
    assert blocks is False


def test_prompt_builder_valueerror_is_runtime_failure(events_dir, monkeypatch):
    portfolio_data = {
        "holdings": [{"code": "600519", "shares": 100, "cost": 10.0, "price": 20.0}],
        "data_status": "normal",
    }
    monkeypatch.setattr(pas.portfolio, "get_portfolio", lambda: portfolio_data)
    monkeypatch.setattr(pas.portfolio, "_is_valid_price", lambda px: True)
    monkeypatch.setattr(
        pas.ai_result_service, "compute_portfolio_fingerprint", lambda holdings: "fp"
    )
    monkeypatch.setattr(
        pas.daily_review,
        "generate_daily_review",
        lambda: {
            "trade_date": "2026-07-28",
            "data_health": {"components": {"breadth": "normal"}},
            "market_environment": {"breadth": {"status": "normal"}},
        },
    )
    monkeypatch.setattr(
        pas.portfolio_advice_context,
        "build_portfolio_advice_context",
        lambda *a, **k: {"ok": True},
    )

    def boom(*a, **k):
        raise ValueError("prompt broken")

    monkeypatch.setattr(
        pas.portfolio_advice_prompt,
        "build_portfolio_advice_messages",
        boom,
    )
    with pytest.raises(pas.PortfolioAdviceMarketDataError):
        pas.prepare_portfolio_advice_messages()
    ev = store.load_events_readonly()["portfolio_advice_gate"]
    assert ev["last_error_code"] == "SOURCE_UNAVAILABLE"
    st, blocks, *_ = svc.map_gate_event(ev)
    assert st == "unavailable"
    assert blocks is False
