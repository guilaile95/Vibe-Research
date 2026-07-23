from __future__ import annotations

import math

import pytest

import ai_result_service as service
import ai_result_store as store


def _review(**overrides):
    review = {
        "trade_date": "2026-07-23",
        "generated_at": "2026-07-23 15:30:00",
        "data_cutoff": "2026-07-23 15:00:00",
        "status": "normal",
    }
    review.update(overrides)
    return review


def _portfolio(holdings=None):
    return {
        "holdings": holdings
        if holdings is not None
        else [
            {"code": "600519", "shares": 100, "cost": 1500.5, "price": 1700},
            {"code": "000001", "shares": 200, "cost": 12.3, "name": "平安银行"},
        ]
    }


def test_provider_normalization_and_model_validation():
    assert service.normalize_provider("") == "api-compatible"
    assert service.normalize_provider("  ") == "api-compatible"
    assert service.normalize_provider("cli-codex") == "cli-codex"
    with pytest.raises(service.AiResultValidationError):
        service.validate_model_info("deepseek", " ")


@pytest.mark.parametrize(
    ("result_type", "trade_date"),
    [("bad", "2026-07-23"), ("daily_review_ai", "2026-2-03"), ("daily_review_ai", "2026-02-30")],
)
def test_result_type_and_date_validation(result_type, trade_date):
    with pytest.raises(service.AiResultValidationError):
        service.validate_result_identity(result_type, trade_date)


def test_fingerprint_is_order_independent_and_uses_only_code_shares_cost():
    holdings = _portfolio()["holdings"]
    reversed_with_noise = [
        {**holdings[1], "price": 99, "name": "ignored"},
        {**holdings[0], "price": 1, "pnl": 123},
    ]
    assert service.compute_portfolio_fingerprint(holdings) == service.compute_portfolio_fingerprint(
        reversed_with_noise
    )
    assert len(service.compute_portfolio_fingerprint(holdings)) == 64
    assert service.compute_portfolio_fingerprint(holdings) == service.compute_portfolio_fingerprint(
        holdings
    ).lower()


@pytest.mark.parametrize(
    "holding",
    [
        {"code": "123", "shares": 1, "cost": 1},
        {"code": "000001", "shares": True, "cost": 1},
        {"code": "000001", "shares": 1.5, "cost": 1},
        {"code": "000001", "shares": 0, "cost": 1},
        {"code": "000001", "shares": 1, "cost": True},
        {"code": "000001", "shares": 1, "cost": math.nan},
        {"code": "000001", "shares": 1, "cost": math.inf},
    ],
)
def test_fingerprint_rejects_invalid_holdings(holding):
    with pytest.raises(service.AiResultValidationError):
        service.compute_portfolio_fingerprint([holding])


def test_daily_review_save_uses_safe_payload_and_no_sensitive_config(tmp_path, monkeypatch):
    db = tmp_path / "daily_reviews.sqlite3"
    monkeypatch.setattr(service.review_history, "resolve_review_db_path", lambda: db)
    cfg = {
        "provider": "",
        "model": "safe-model",
        "apiKey": "sk-secret",
        "baseURL": "https://secret.example/v1",
        "Authorization": "Bearer secret",
    }

    saved = service.save_daily_review_ai(_review(), "# 权威复盘", cfg)

    assert saved["payload"] == {
        "markdown": "# 权威复盘",
        "source_review_generated_at": "2026-07-23 15:30:00",
        "source_data_cutoff": "2026-07-23 15:00:00",
    }
    raw = store.get_result(db, "daily_review_ai", "2026-07-23")
    serialized = repr(raw)
    assert "sk-secret" not in serialized
    assert "secret.example" not in serialized
    assert "Bearer" not in serialized


def test_daily_review_validation_happens_before_old_row_can_be_overwritten(tmp_path, monkeypatch):
    db = tmp_path / "daily_reviews.sqlite3"
    monkeypatch.setattr(service.review_history, "resolve_review_db_path", lambda: db)
    cfg = {"provider": "deepseek", "model": "m"}
    service.save_daily_review_ai(_review(), "old", cfg)

    with pytest.raises(service.AiResultValidationError):
        service.save_daily_review_ai(_review(), "   ", cfg)

    assert store.get_result(db, "daily_review_ai", "2026-07-23")["payload"]["markdown"] == "old"


def test_portfolio_save_and_stale_matrix(tmp_path, monkeypatch):
    db = tmp_path / "daily_reviews.sqlite3"
    monkeypatch.setattr(service.review_history, "resolve_review_db_path", lambda: db)
    original = _portfolio()
    payload = {
        "schema_version": "portfolio-advice-v0.1",
        "generated_at": "2026-07-23 15:40:00",
        "trade_date": "2026-07-23",
        "holdings": [{"code": "600519", "execution_quantity": 100}],
        "account_action": {"action": "hold"},
    }
    service.save_portfolio_advice(original, _review(), payload, {"provider": "cli-codex", "model": "gpt"})

    same_reordered = _portfolio(list(reversed(original["holdings"])))
    restored = service.get_ai_result(
        "portfolio_advice", trade_date="2026-07-23", current_portfolio=same_reordered
    )
    assert restored["payload"] == payload
    assert restored["stale"] is False
    assert "stale_message" not in restored

    mutations = [
        _portfolio([{**original["holdings"][0], "shares": 101}, original["holdings"][1]]),
        _portfolio([{**original["holdings"][0], "cost": 1501}, original["holdings"][1]]),
        _portfolio(original["holdings"] + [{"code": "300750", "shares": 1, "cost": 100}]),
        _portfolio(original["holdings"][:1]),
        _portfolio([]),
    ]
    for changed in mutations:
        result = service.get_ai_result(
            "portfolio_advice", trade_date="2026-07-23", current_portfolio=changed
        )
        assert result["stale"] is True
        assert result["stale_message"] == service.PORTFOLIO_STALE_MESSAGE


def test_get_exact_none_and_latest_without_fresh_aggregation(tmp_path, monkeypatch):
    db = tmp_path / "daily_reviews.sqlite3"
    monkeypatch.setattr(service.review_history, "resolve_review_db_path", lambda: db)
    monkeypatch.setattr(service, "_cached_display_trade_date", lambda: None)
    monkeypatch.setattr(
        service.daily_review,
        "generate_daily_review",
        lambda: (_ for _ in ()).throw(AssertionError("must not aggregate fresh")),
    )
    assert service.get_ai_result("daily_review_ai", trade_date="2026-07-23") is None
    service.save_daily_review_ai(_review(trade_date="2026-07-22"), "old", {"model": "m"})
    service.save_daily_review_ai(_review(trade_date="2026-07-23"), "new", {"model": "m"})
    assert service.get_ai_result("daily_review_ai")["trade_date"] == "2026-07-23"
