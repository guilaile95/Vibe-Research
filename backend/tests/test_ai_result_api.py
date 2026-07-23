from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

import ai_result_service
import ai_result_store
import app as app_module


client = TestClient(app_module.app)


def _result(result_type="daily_review_ai", stale=False):
    payload = (
        {"markdown": "# 复盘", "source_review_generated_at": "2026-07-23 15:30:00", "source_data_cutoff": None}
        if result_type == "daily_review_ai"
        else {"schema_version": "portfolio-advice-v0.1", "holdings": [], "account_action": {}}
    )
    return {
        "result_type": result_type,
        "trade_date": "2026-07-23",
        "schema_version": f"{result_type}.v1",
        "payload": payload,
        "generated_at": "2026-07-23 15:30:00",
        "model_provider": "api-compatible",
        "model_name": "model-x",
        "stale": stale,
        **({"stale_message": ai_result_service.PORTFOLIO_STALE_MESSAGE} if stale else {}),
    }


def test_get_exact_result_passes_explicit_date(monkeypatch):
    get_result = MagicMock(return_value=_result())
    monkeypatch.setattr(app_module.ai_result_service, "get_ai_result", get_result)

    response = client.get("/api/ai-results/daily_review_ai?trade_date=2026-07-23")

    assert response.status_code == 200
    assert response.json() == {"data": _result()}
    get_result.assert_called_once_with("daily_review_ai", trade_date="2026-07-23")


def test_get_without_date_and_empty_are_normal_200(monkeypatch):
    get_result = MagicMock(return_value=None)
    monkeypatch.setattr(app_module.ai_result_service, "get_ai_result", get_result)

    response = client.get("/api/ai-results/portfolio_advice")

    assert response.status_code == 200
    assert response.json() == {"data": None}
    get_result.assert_called_once_with("portfolio_advice", trade_date=None)


def test_stale_response_keeps_fixed_message(monkeypatch):
    saved = _result("portfolio_advice", stale=True)
    monkeypatch.setattr(app_module.ai_result_service, "get_ai_result", lambda **_k: saved)
    monkeypatch.setattr(
        app_module.ai_result_service,
        "get_ai_result",
        lambda result_type, trade_date=None: saved,
    )
    response = client.get("/api/ai-results/portfolio_advice?trade_date=2026-07-23")
    assert response.status_code == 200
    assert response.json()["data"]["stale"] is True
    assert response.json()["data"]["stale_message"] == ai_result_service.PORTFOLIO_STALE_MESSAGE


@pytest.mark.parametrize(
    "url",
    [
        "/api/ai-results/not-allowed",
        "/api/ai-results/daily_review_ai?trade_date=2026-02-30",
    ],
)
def test_invalid_type_or_date_returns_stable_422(monkeypatch, url):
    monkeypatch.setattr(
        app_module.ai_result_service,
        "get_ai_result",
        MagicMock(side_effect=ai_result_service.AiResultValidationError("private detail")),
    )
    response = client.get(url)
    assert response.status_code == 422
    assert response.json() == {"detail": "AI结果查询参数无效"}


@pytest.mark.parametrize(
    "error",
    [
        ai_result_store.AiResultPayloadCorruptedError(),
        RuntimeError(r"SQL failed at C:\Users\private\daily_reviews.sqlite3"),
    ],
)
def test_storage_errors_are_safe_500(monkeypatch, error):
    monkeypatch.setattr(
        app_module.ai_result_service,
        "get_ai_result",
        MagicMock(side_effect=error),
    )
    response = client.get("/api/ai-results/daily_review_ai")
    assert response.status_code == 500
    assert response.json() == {"detail": "AI结果读取失败"}
    assert "SQL" not in response.text
    assert "private" not in response.text
