"""Tests for decision analytics service and API (P2-4A)."""
from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

import decision_analytics_router
import decision_analytics_service as svc
import decision_feedback_store
import decision_feedback_store as store


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_record(
    *,
    code: str = "000001",
    adoption_status: str = "followed",
    outcome_status: str = "better_than_expected",
    created_at: str = "2026-01-01T10:00:00.000000+00:00",
    voided_at: str | None = None,
) -> dict:
    return {
        "feedback_id": f"fb_{uuid.uuid4().hex}",
        "code": code,
        "advice_trade_date": "2026-01-01",
        "advice_generated_at": "2026-01-01T10:00:00+00:00",
        "trade_id": None,
        "adoption_status": adoption_status,
        "outcome_status": outcome_status,
        "note": None,
        "created_at": created_at,
        "voided_at": voided_at,
        "void_reason": None,
    }


def make_app(tmp_db: Path) -> FastAPI:
    app = FastAPI()
    app.include_router(decision_analytics_router.router)

    @app.exception_handler(decision_feedback_store.DecisionFeedbackCorruptedError)
    async def _handle(req, exc):
        return JSONResponse(status_code=500, content={"detail": exc.MESSAGE})

    return app


# ---------------------------------------------------------------------------
# Service-level tests (direct function calls)
# ---------------------------------------------------------------------------


class TestAdoptionSummary:
    def test_adoption_summary_empty_db(self, tmp_path, monkeypatch):
        """No file -> total=0, adoption_rate=None."""
        db = tmp_path / "nonexistent.sqlite3"
        monkeypatch.setenv("VIBE_RESEARCH_DECISION_FEEDBACK_DB", str(db))
        result = svc.get_adoption_summary()
        assert result["total"] == 0
        assert result["adoption_rate"] is None
        assert result["counts"]["followed"] == 0
        assert result["counts"]["not_followed"] == 0

    def test_adoption_summary_with_data(self, tmp_path, monkeypatch):
        """followed x2, not_followed x1 -> total=3, followed=2, rate≈0.667."""
        db = tmp_path / "fb.sqlite3"
        monkeypatch.setenv("VIBE_RESEARCH_DECISION_FEEDBACK_DB", str(db))

        store.insert_record(db, _make_record(adoption_status="followed"))
        store.insert_record(db, _make_record(adoption_status="followed"))
        store.insert_record(db, _make_record(adoption_status="not_followed"))

        result = svc.get_adoption_summary(db_path=db)
        assert result["total"] == 3
        assert result["counts"]["followed"] == 2
        assert result["counts"]["not_followed"] == 1
        assert result["adoption_rate"] == pytest.approx(2 / 3, abs=1e-9)

    def test_adoption_summary_excludes_voided(self, tmp_path):
        """Voided records must not count."""
        db = tmp_path / "fb.sqlite3"
        store.insert_record(db, _make_record(adoption_status="followed"))
        store.insert_record(
            db,
            _make_record(
                adoption_status="followed",
                voided_at="2026-01-02T00:00:00.000000+00:00",
            ),
        )
        result = svc.get_adoption_summary(db_path=db)
        assert result["total"] == 1


class TestOutcomeSummary:
    def test_outcome_summary_empty(self, tmp_path, monkeypatch):
        """No file -> positive_rate=None."""
        db = tmp_path / "nonexistent.sqlite3"
        monkeypatch.setenv("VIBE_RESEARCH_DECISION_FEEDBACK_DB", str(db))
        result = svc.get_outcome_summary()
        assert result["total"] == 0
        assert result["positive_rate"] is None

    def test_outcome_summary_with_data(self, tmp_path):
        """better x2, worse x1, not_evaluated x1 -> total=4, positive_rate=2/3."""
        db = tmp_path / "fb.sqlite3"
        store.insert_record(db, _make_record(outcome_status="better_than_expected"))
        store.insert_record(db, _make_record(outcome_status="better_than_expected"))
        store.insert_record(db, _make_record(outcome_status="worse_than_expected"))
        store.insert_record(db, _make_record(outcome_status="not_evaluated"))

        result = svc.get_outcome_summary(db_path=db)
        assert result["total"] == 4
        assert result["counts"]["better_than_expected"] == 2
        assert result["counts"]["worse_than_expected"] == 1
        assert result["counts"]["not_evaluated"] == 1
        # evaluated = 3, positive = 2
        assert result["positive_rate"] == pytest.approx(2 / 3, abs=1e-9)

    def test_outcome_summary_filter_adoption(self, tmp_path):
        """Filter by adoption_status='followed'."""
        db = tmp_path / "fb.sqlite3"
        store.insert_record(
            db,
            _make_record(adoption_status="followed", outcome_status="better_than_expected"),
        )
        store.insert_record(
            db,
            _make_record(adoption_status="not_followed", outcome_status="worse_than_expected"),
        )

        result = svc.get_outcome_summary(adoption_status="followed", db_path=db)
        assert result["total"] == 1
        assert result["counts"]["better_than_expected"] == 1
        assert result["counts"]["worse_than_expected"] == 0
        assert result["adoption_status"] == "followed"

    def test_outcome_summary_all_not_evaluated(self, tmp_path):
        """All not_evaluated -> positive_rate=None (denominator=0)."""
        db = tmp_path / "fb.sqlite3"
        store.insert_record(db, _make_record(outcome_status="not_evaluated"))
        result = svc.get_outcome_summary(db_path=db)
        assert result["positive_rate"] is None


class TestStockSummary:
    def test_stock_summary_empty(self, tmp_path, monkeypatch):
        """No file -> empty list."""
        db = tmp_path / "nonexistent.sqlite3"
        monkeypatch.setenv("VIBE_RESEARCH_DECISION_FEEDBACK_DB", str(db))
        result = svc.get_stock_summary()
        assert result == []

    def test_stock_summary_with_data(self, tmp_path):
        """Two stocks, verify code/total/adoption_followed_count."""
        db = tmp_path / "fb.sqlite3"
        # Stock 000001: 3 records, 2 followed
        store.insert_record(db, _make_record(code="000001", adoption_status="followed"))
        store.insert_record(db, _make_record(code="000001", adoption_status="followed"))
        store.insert_record(db, _make_record(code="000001", adoption_status="not_followed"))
        # Stock 000002: 1 record, 1 partially_followed
        store.insert_record(
            db, _make_record(code="000002", adoption_status="partially_followed")
        )

        result = svc.get_stock_summary(db_path=db)
        assert len(result) == 2
        # sorted by total DESC
        assert result[0]["code"] == "000001"
        assert result[0]["total"] == 3
        assert result[0]["adoption_followed_count"] == 2
        assert result[0]["adoption_rate"] == pytest.approx(2 / 3, abs=1e-9)

        assert result[1]["code"] == "000002"
        assert result[1]["total"] == 1
        assert result[1]["adoption_followed_count"] == 1
        assert result[1]["adoption_rate"] == pytest.approx(1.0)

    def test_stock_summary_limit(self, tmp_path):
        """Limit parameter is respected."""
        db = tmp_path / "fb.sqlite3"
        for i in range(5):
            code = f"{i:06d}"
            store.insert_record(db, _make_record(code=code))

        result = svc.get_stock_summary(db_path=db, limit=3)
        assert len(result) == 3


# ---------------------------------------------------------------------------
# API-level tests (TestClient)
# ---------------------------------------------------------------------------


class TestAnalyticsAPI:
    @pytest.fixture
    def tmp_db(self, tmp_path) -> Path:
        return tmp_path / "fb.sqlite3"

    @pytest.fixture
    def client(self, tmp_db, monkeypatch) -> TestClient:
        monkeypatch.setenv("VIBE_RESEARCH_DECISION_FEEDBACK_DB", str(tmp_db))
        app = make_app(tmp_db)
        return TestClient(app)

    @pytest.fixture
    def client_with_data(self, tmp_db, monkeypatch) -> TestClient:
        monkeypatch.setenv("VIBE_RESEARCH_DECISION_FEEDBACK_DB", str(tmp_db))
        store.insert_record(tmp_db, _make_record(adoption_status="followed"))
        store.insert_record(tmp_db, _make_record(adoption_status="not_followed"))
        app = make_app(tmp_db)
        return TestClient(app)

    def test_api_get_adoption(self, client):
        """GET /api/decision-analytics/adoption -> 200."""
        resp = client.get("/api/decision-analytics/adoption")
        assert resp.status_code == 200
        body = resp.json()
        assert "data" in body
        assert "total" in body["data"]
        assert "counts" in body["data"]
        assert "adoption_rate" in body["data"]

    def test_api_get_outcome(self, client):
        """GET /api/decision-analytics/outcome -> 200."""
        resp = client.get("/api/decision-analytics/outcome")
        assert resp.status_code == 200
        body = resp.json()
        assert "data" in body
        assert "positive_rate" in body["data"]

    def test_api_get_stocks(self, client):
        """GET /api/decision-analytics/stocks -> 200."""
        resp = client.get("/api/decision-analytics/stocks")
        assert resp.status_code == 200
        body = resp.json()
        assert "data" in body
        assert isinstance(body["data"], list)

    def test_api_invalid_date(self, client):
        """GET adoption?date_from=not-a-date -> 422."""
        resp = client.get("/api/decision-analytics/adoption?date_from=not-a-date")
        assert resp.status_code == 422

    def test_api_invalid_adoption_status(self, client):
        """GET outcome?adoption_status=invalid -> 422."""
        resp = client.get("/api/decision-analytics/outcome?adoption_status=invalid_status")
        assert resp.status_code == 422

    def test_api_valid_adoption_status_filter(self, client_with_data):
        """GET outcome?adoption_status=followed -> 200."""
        resp = client_with_data.get(
            "/api/decision-analytics/outcome?adoption_status=followed"
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["adoption_status"] == "followed"

    def test_api_stocks_with_limit(self, client_with_data):
        """GET stocks?limit=1 -> 200, at most 1 item."""
        resp = client_with_data.get("/api/decision-analytics/stocks?limit=1")
        assert resp.status_code == 200
        assert len(resp.json()["data"]) <= 1

    def test_api_stocks_limit_over_100(self, client):
        """GET stocks?limit=200 -> 422 (FastAPI Query ge/le)."""
        resp = client.get("/api/decision-analytics/stocks?limit=200")
        assert resp.status_code == 422

    def test_api_adoption_with_date_range(self, client_with_data):
        """GET adoption?date_from=2026-01-01&date_to=2026-12-31 -> 200."""
        resp = client_with_data.get(
            "/api/decision-analytics/adoption?date_from=2026-01-01&date_to=2026-12-31"
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["date_from"] == "2026-01-01"
        assert body["data"]["date_to"] == "2026-12-31"

    def test_api_adoption_data_correct(self, tmp_db, monkeypatch):
        """Verify adoption summary numbers via API."""
        monkeypatch.setenv("VIBE_RESEARCH_DECISION_FEEDBACK_DB", str(tmp_db))
        store.insert_record(tmp_db, _make_record(adoption_status="followed"))
        store.insert_record(tmp_db, _make_record(adoption_status="followed"))
        store.insert_record(tmp_db, _make_record(adoption_status="not_followed"))

        app = make_app(tmp_db)
        client = TestClient(app)
        resp = client.get("/api/decision-analytics/adoption")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["total"] == 3
        assert data["counts"]["followed"] == 2
        assert data["adoption_rate"] == pytest.approx(2 / 3, abs=1e-9)
