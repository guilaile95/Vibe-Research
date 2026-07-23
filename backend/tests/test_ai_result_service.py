from __future__ import annotations

import math
import json
import re
from unittest.mock import MagicMock

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


def _advice_payload(**overrides):
    payload = {
        "schema_version": "portfolio-advice-v0.1",
        "generated_at": "2026-07-23 15:40:00",
        "trade_date": "2026-07-23",
        "market_status": "normal",
        "portfolio_summary": {
            "holding_count": 1,
            "market_value": 170000.0,
            "cost": 150050.0,
            "pnl": 19950.0,
            "pnl_pct": 13.3,
        },
        "account_action": {
            "action": "hold",
            "reason": "继续观察",
            "confidence": "medium",
        },
        "holdings": [
            {
                "code": "600519",
                "name": "贵州茅台",
                "shares": 100,
                "cost_price": 1500.5,
                "current_price": 1700.0,
                "market_value": 170000.0,
                "pnl_amount": 19950.0,
                "pnl_pct": 13.3,
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
    payload.update(overrides)
    return payload


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


def test_daily_review_record_generated_at_is_ai_completion_time_not_source_review_time(
    tmp_path,
    monkeypatch,
):
    db = tmp_path / "daily_reviews.sqlite3"
    monkeypatch.setattr(service.review_history, "resolve_review_db_path", lambda: db)
    review = _review(generated_at="2026-07-22 09:00:00", data_cutoff="2026-07-22 15:00:00")

    saved = service.save_daily_review_ai(review, "# 权威复盘", {"model": "safe-model"})

    assert saved["payload"]["source_review_generated_at"] == "2026-07-22 09:00:00"
    assert saved["payload"]["source_data_cutoff"] == "2026-07-22 15:00:00"
    assert saved["generated_at"] != saved["payload"]["source_review_generated_at"]
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", saved["generated_at"])
    restored = service.get_ai_result("daily_review_ai", trade_date="2026-07-23")
    assert restored["generated_at"] == saved["generated_at"]
    assert restored["payload"]["source_review_generated_at"] == "2026-07-22 09:00:00"


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
    payload = _advice_payload()
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


def test_portfolio_advice_restore_uses_static_holdings_snapshot_without_quotes(
    tmp_path,
    monkeypatch,
):
    db = tmp_path / "daily_reviews.sqlite3"
    pf_file = tmp_path / "portfolio.json"
    monkeypatch.setattr(service.review_history, "resolve_review_db_path", lambda: db)
    monkeypatch.setattr(service.portfolio, "PF_FILE", str(pf_file))
    monkeypatch.setattr(service.portfolio, "CACHE_DIR", str(tmp_path))
    portfolio_data = _portfolio([{"code": "600519", "shares": 100, "cost": 1500.5}])
    pf_file.write_text(
        json.dumps({"holdings": portfolio_data["holdings"], "last_refresh": "old"}),
        encoding="utf-8",
    )
    service.save_portfolio_advice(
        portfolio_data,
        _review(),
        _advice_payload(),
        {"provider": "cli-codex", "model": "gpt"},
    )

    def boom_quote(*_args, **_kwargs):
        raise AssertionError("restore must not request live quotes")

    monkeypatch.setattr(service.portfolio.astock, "tencent_quote", boom_quote)

    restored = service.get_ai_result("portfolio_advice", trade_date="2026-07-23")

    assert restored["stale"] is False
    assert json.loads(pf_file.read_text(encoding="utf-8"))["last_refresh"] == "old"


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


@pytest.mark.parametrize(
    ("result_type", "schema_version", "payload", "fingerprint"),
    [
        (
            "daily_review_ai",
            "daily_review_ai.v1",
            {
                "source_review_generated_at": "2026-07-23 15:30:00",
                "source_data_cutoff": "2026-07-23 15:00:00",
            },
            None,
        ),
        (
            "portfolio_advice",
            "portfolio_advice.v1",
            {
                "markdown": "cross-type payload",
                "source_review_generated_at": "2026-07-23 15:30:00",
                "source_data_cutoff": None,
            },
            "a" * 64,
        ),
        (
            "portfolio_advice",
            "portfolio_advice.v1",
            {
                "schema_version": "portfolio-advice-v0.1",
                "generated_at": "2026-07-23 15:40:00",
                "trade_date": "2026-07-23",
                "market_status": "normal",
                "portfolio_summary": {},
                "account_action": {},
                "holdings": "not-a-list",
                "warnings": [],
                "data_limitations": [],
            },
            "a" * 64,
        ),
    ],
)
def test_restore_rejects_result_type_specific_payload_corruption_safely(
    tmp_path,
    monkeypatch,
    result_type,
    schema_version,
    payload,
    fingerprint,
):
    db = tmp_path / "private" / "daily_reviews.sqlite3"
    monkeypatch.setattr(service.review_history, "resolve_review_db_path", lambda: db)
    store.upsert_result(
        db,
        {
            "result_type": result_type,
            "trade_date": "2026-07-23",
            "schema_version": schema_version,
            "payload": payload,
            "generated_at": "2026-07-23 15:40:00",
            "model_provider": "api-compatible",
            "model_name": "safe-model",
            "input_fingerprint": fingerprint,
        },
    )

    kwargs = {"trade_date": "2026-07-23"}
    if result_type == "portfolio_advice":
        kwargs["current_portfolio"] = _portfolio()
    with pytest.raises(service.AiResultCorruptedError) as exc_info:
        service.get_ai_result(result_type, **kwargs)

    message = str(exc_info.value)
    assert "private" not in message
    assert "holdings" not in message
    assert "markdown" not in message


@pytest.mark.parametrize(
    "broken_field",
    ["portfolio_summary", "account_action", "holding"],
)
def test_restore_rejects_nested_portfolio_payload_corruption(
    tmp_path,
    monkeypatch,
    broken_field,
):
    db = tmp_path / "daily_reviews.sqlite3"
    monkeypatch.setattr(service.review_history, "resolve_review_db_path", lambda: db)
    payload = _advice_payload()
    if broken_field == "holding":
        payload["holdings"] = [{}]
    else:
        payload[broken_field] = {}
    store.upsert_result(
        db,
        {
            "result_type": "portfolio_advice",
            "trade_date": "2026-07-23",
            "schema_version": "portfolio_advice.v1",
            "payload": payload,
            "generated_at": "2026-07-23 15:40:00",
            "model_provider": "api-compatible",
            "model_name": "safe-model",
            "input_fingerprint": service.compute_portfolio_fingerprint(
                _portfolio()["holdings"]
            ),
        },
    )

    with pytest.raises(service.AiResultCorruptedError):
        service.get_ai_result(
            "portfolio_advice",
            trade_date="2026-07-23",
            current_portfolio=_portfolio(),
        )


def test_save_portfolio_uses_same_strict_payload_contract(tmp_path, monkeypatch):
    db = tmp_path / "daily_reviews.sqlite3"
    monkeypatch.setattr(service.review_history, "resolve_review_db_path", lambda: db)
    upsert = MagicMock()
    monkeypatch.setattr(service.ai_result_store, "upsert_result", upsert)
    payload = _advice_payload(account_action={})

    with pytest.raises(service.AiResultValidationError):
        service.save_portfolio_advice(
            _portfolio(),
            _review(),
            payload,
            {"provider": "api-compatible", "model": "safe-model"},
        )

    upsert.assert_not_called()
