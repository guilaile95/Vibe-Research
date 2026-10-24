from datetime import date

import pytest

import trade_calendar as calendar


@pytest.mark.parametrize("today, expected", [
    (date(2026, 1, 1), "SUPPORTED"),
    (date(2026, 10, 24), "EXPIRING"),
    (date(2026, 12, 31), "EXPIRING"),
    (date(2027, 1, 1), "EXPIRED"),
    (date(2023, 12, 31), "OUT_OF_RANGE"),
])
def test_coverage_is_explicit_without_fabricating_sessions(today, expected):
    result = calendar.coverage_status(today)
    assert result["status"] == expected
    assert result["supported_end"] == "2026-12-31"
    assert result["future_dates_inferred"] is False
    assert calendar.next_trade_date("2026-12-31") is None
    assert calendar.completed_trade_date_at("2027-01-04T08:00:00Z") is None


def test_corrupt_calendar_is_not_reported_as_healthy(monkeypatch):
    monkeypatch.setattr(calendar, "_load_calendar", lambda: None)
    assert calendar.coverage_status(date(2026, 1, 1))["status"] == "INVALID_ARTIFACT"


def test_calendar_endpoint_is_public_metadata_without_provider_probe(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import runtime_info_router
    monkeypatch.setattr(calendar, "_today_shanghai", lambda: date(2027, 1, 1))
    app = FastAPI()
    app.include_router(runtime_info_router.create_router("0.1.3"))
    response = TestClient(app).get("/api/calendar-status")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["data"]["status"] == "EXPIRED"
    assert "path" not in str(response.json()).lower()
