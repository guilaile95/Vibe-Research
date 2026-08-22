"""P1-PAA1 Portfolio Advice 与 Position Reality Holding authority 对齐验收。"""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

import ai_result_service
import app as app_module
import astock
import portfolio
import portfolio_advice_context
import portfolio_advice_prompt
import portfolio_advice_service as advice_service
import position_reality_service as position_service


client = TestClient(app_module.app)

_LEDGER_ENV = "VIBE_RESEARCH_TRADE_LEDGER_DB"
_REVIEW_ENV = "VIBE_RESEARCH_REVIEW_DB"
_BOOTSTRAP = {
    "ledger_start_at": "2026-08-01",
    "opening_cash": 100000.0,
    "positions": [{"code": "600519", "name": "贵州茅台", "shares": 100, "cost_basis": 8.0}],
}


def _review() -> dict:
    return {
        "schema_version": "daily-review-v0.1",
        "generated_at": "2026-08-23 15:30:00",
        "trade_date": "2026-08-23",
        "data_cutoff": None,
        "status": "normal",
        "data_health": {"components": {"breadth": "normal"}},
        "market_environment": {"breadth": {"status": "normal"}},
    }


def _advice_payload() -> dict:
    return {
        "schema_version": "portfolio-advice-v0.1",
        "generated_at": "2026-08-23 16:00:00",
        "trade_date": "2026-08-23",
        "market_status": "normal",
        "portfolio_summary": {
            "holding_count": 1,
            "market_value": 1000.0,
            "cost": 800.0,
            "pnl": 200.0,
            "pnl_pct": 25.0,
        },
        "account_action": {
            "action": "hold",
            "reason": "仅用于 authority vertical",
            "confidence": "medium",
        },
        "holdings": [
            {
                "code": "600519",
                "name": "贵州茅台",
                "shares": 100,
                "cost_price": 8.0,
                "current_price": 10.0,
                "market_value": 1000.0,
                "pnl_amount": 200.0,
                "pnl_pct": 25.0,
                "holding_weight_pct": 100.0,
                "action": "hold",
                "execution_size_pct_of_holding": None,
                "execution_quantity": None,
                "trigger_conditions": [],
                "price_conditions": [],
                "execution_plan": [],
                "risk_conditions": [],
                "invalidation_conditions": [],
                "confidence": "medium",
                "data_limitations": [],
            }
        ],
        "warnings": [],
        "data_limitations": [],
    }


@pytest.fixture()
def isolated(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setattr(portfolio, "CACHE_DIR", str(data_dir))
    monkeypatch.setattr(portfolio, "PF_FILE", str(data_dir / "portfolio.json"))
    monkeypatch.setenv("VR_DATA_DIR", str(data_dir))
    monkeypatch.setenv(_LEDGER_ENV, str(data_dir / "trade_ledger.sqlite3"))
    monkeypatch.setenv(_REVIEW_ENV, str(data_dir / "review_history.sqlite3"))
    monkeypatch.setattr(
        astock,
        "tencent_quote",
        lambda codes: {code: {"name": f"股{code}", "price": 10.0} for code in codes},
    )
    return data_dir


def _bootstrap(payload: dict | None = None) -> dict:
    response = client.post("/api/position/bootstrap-commit", json=payload or _BOOTSTRAP)
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _canonical_portfolio() -> dict:
    derived = position_service.derive_positions()
    return portfolio.get_portfolio(derived_positions=derived)


def test_pre_bootstrap_advice_keeps_legacy_portfolio_path(isolated, monkeypatch):
    legacy = {
        "holdings": [{"code": "600519", "name": "archive", "shares": 12, "cost": 7.0}],
        "last_refresh": None,
    }
    (isolated / "portfolio.json").write_text(json.dumps(legacy), encoding="utf-8")
    monkeypatch.setattr(advice_service.daily_review, "generate_daily_review", _review)
    monkeypatch.setattr(
        advice_service.portfolio_advice_context,
        "build_portfolio_advice_context",
        lambda p, r: {"holdings": p["holdings"]},
    )
    monkeypatch.setattr(
        advice_service.portfolio_advice_prompt,
        "build_portfolio_advice_messages",
        lambda context_json, *, user_request: [],
    )

    prepared = advice_service.prepare_portfolio_advice_messages()

    assert position_service.get_holding_authority_state() == "LEGACY"
    assert prepared["portfolio"]["holdings"][0]["shares"] == 12


def test_canonical_advice_ignores_legacy_archive_holdings(isolated, monkeypatch):
    _bootstrap()
    (isolated / "portfolio.json").write_text(
        json.dumps(
            {
                "holdings": [{"code": "600519", "name": "poisoned", "shares": 999, "cost": 1.0}],
                "last_refresh": None,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(advice_service.daily_review, "generate_daily_review", _review)
    monkeypatch.setattr(
        advice_service.portfolio_advice_context,
        "build_portfolio_advice_context",
        lambda p, r: {"holdings": p["holdings"]},
    )
    monkeypatch.setattr(
        advice_service.portfolio_advice_prompt,
        "build_portfolio_advice_messages",
        lambda context_json, *, user_request: [],
    )

    prepared = advice_service.prepare_portfolio_advice_messages()
    api_portfolio = client.get("/api/portfolio")

    assert api_portfolio.status_code == 200
    canonical = api_portfolio.json()["data"]
    assert canonical["holding_authority"] == "LEDGER_DERIVED"
    assert prepared["portfolio"]["holdings"] == canonical["holdings"]
    assert prepared["portfolio"]["holdings"][0]["shares"] == 100
    assert prepared["portfolio"]["holdings"][0]["shares"] != 999


def test_pre_bootstrap_stale_restore_keeps_legacy_snapshot_semantics(isolated):
    legacy = {"holdings": [{"code": "600519", "shares": 12, "cost": 7.0}]}
    (isolated / "portfolio.json").write_text(json.dumps(legacy), encoding="utf-8")
    snapshot = portfolio.get_portfolio_holdings_snapshot()
    advice_service.ai_result_service.save_portfolio_advice(
        snapshot,
        _review(),
        _advice_payload(),
        {"provider": "test", "model": "legacy-test"},
    )

    initial = client.get("/api/ai-results/portfolio_advice", params={"trade_date": "2026-08-23"})
    assert initial.status_code == 200, initial.text
    assert initial.json()["data"]["stale"] is False

    (isolated / "portfolio.json").write_text(
        json.dumps({"holdings": [{"code": "600519", "shares": 13, "cost": 7.0}]}),
        encoding="utf-8",
    )
    changed = client.get("/api/ai-results/portfolio_advice", params={"trade_date": "2026-08-23"})
    assert changed.status_code == 200, changed.text
    assert changed.json()["data"]["stale"] is True


def test_real_fastapi_advice_restore_becomes_stale_after_trade_and_correction(isolated):
    _bootstrap()
    (isolated / "portfolio.json").write_text(
        json.dumps({"holdings": [], "last_refresh": None}),
        encoding="utf-8",
    )
    canonical = _canonical_portfolio()
    saved = advice_service.ai_result_service.save_portfolio_advice(
        canonical,
        _review(),
        _advice_payload(),
        {"provider": "test", "model": "authority-test"},
    )
    assert saved["input_fingerprint"] == ai_result_service.compute_portfolio_fingerprint(
        canonical["holdings"]
    )

    initial = client.get("/api/ai-results/portfolio_advice", params={"trade_date": "2026-08-23"})
    assert initial.status_code == 200, initial.text
    assert initial.json()["data"]["stale"] is False

    trade = client.post(
        "/api/trades",
        json={
            "code": "600519",
            "name": "贵州茅台",
            "operation": "buy",
            "execution_status": "full",
            "actual_price": 10.0,
            "actual_quantity": 50,
            "executed_at": "2026-08-05T10:00:00Z",
        },
    )
    assert trade.status_code == 200, trade.text

    after_trade = client.get("/api/ai-results/portfolio_advice", params={"trade_date": "2026-08-23"})
    assert after_trade.status_code == 200, after_trade.text
    assert after_trade.json()["data"]["stale"] is True

    trade_id = trade.json()["data"]["trade_id"]
    correction = client.post(
        "/api/position/correction",
        json={
            "target_event_type": "trade",
            "target_event_id": trade_id,
            "after_payload": {"actual_quantity": 80},
            "reason": "PAA1 authority vertical",
        },
    )
    assert correction.status_code == 200, correction.text

    after_correction = client.get(
        "/api/ai-results/portfolio_advice", params={"trade_date": "2026-08-23"}
    )
    assert after_correction.status_code == 200, after_correction.text
    assert after_correction.json()["data"]["stale"] is True
    assert client.get("/api/portfolio").json()["data"]["holdings"][0]["shares"] == 180


def test_authority_read_failure_does_not_fallback_for_advice_or_restore(isolated, monkeypatch):
    _bootstrap()
    canonical = _canonical_portfolio()
    advice_service.ai_result_service.save_portfolio_advice(
        canonical,
        _review(),
        _advice_payload(),
        {"provider": "test", "model": "authority-test"},
    )
    (isolated / "portfolio.json").write_text(
        json.dumps({"holdings": [{"code": "600519", "shares": 99, "cost": 1.0}]}),
        encoding="utf-8",
    )
    (isolated / "trade_ledger.sqlite3").write_bytes(b"not sqlite")
    fallback = MagicMock(side_effect=AssertionError("legacy fallback is forbidden"))
    monkeypatch.setattr(advice_service.portfolio, "get_portfolio", fallback)

    with pytest.raises(advice_service.PortfolioAdviceMarketDataError, match="持仓权威暂不可用"):
        advice_service.prepare_portfolio_advice_messages()
    fallback.assert_not_called()

    restore = client.get("/api/ai-results/portfolio_advice")
    assert restore.status_code == 503
    assert restore.json()["detail"] == "持仓权威暂不可用，AI结果新鲜度无法确认"


def test_canonical_snapshot_has_no_quote_io(isolated, monkeypatch):
    _bootstrap()
    monkeypatch.setattr(astock, "tencent_quote", MagicMock(side_effect=AssertionError("quote I/O")))

    snapshot = portfolio.get_portfolio_holdings_snapshot(
        derived_positions=position_service.derive_positions()
    )

    assert snapshot["holdings"] == [
        {"code": "600519", "shares": 100, "cost": 8.0, "cost_known": True}
    ]


def test_canonical_save_rejects_generation_snapshot_change(isolated, monkeypatch):
    initial = {"holdings": [{"code": "600519", "shares": 100, "cost": 8.0}]}
    changed = {"holdings": [{"code": "600519", "shares": 120, "cost": 8.0}]}
    monkeypatch.setattr(
        ai_result_service.position_reality_service,
        "read_holding_authority",
        lambda: (
            "CANONICAL",
            {
                "canonical": True,
                "positions": [
                    {
                        "code": "600519",
                        "shares": 120,
                        "avg_cost": 8.0,
                        "status": "OPEN",
                        "cost_known": True,
                    }
                ],
            },
        ),
    )
    monkeypatch.setattr(
        ai_result_service.portfolio,
        "get_portfolio_holdings_snapshot",
        lambda *, derived_positions=None: changed,
    )

    with pytest.raises(ai_result_service.AiResultValidationError, match="生成期间持仓快照发生变化"):
        ai_result_service.save_portfolio_advice(
            initial,
            {"trade_date": "2026-08-23"},
            _advice_payload(),
            {"provider": "cli-codex", "model": "test-model"},
            input_fingerprint=ai_result_service.compute_portfolio_fingerprint(initial["holdings"]),
        )
