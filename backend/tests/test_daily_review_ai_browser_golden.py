"""Saved-result browser fixtures are real SQLite restores, never model output tests."""
import json
from pathlib import Path

import pytest
import ai_result_service as service
import daily_review_basis as basis
import daily_review_context
from test_short_term_seal_quality_service import http_get, tree

DAY = "2026-07-31"
GOLDEN = Path(__file__).resolve().parents[2] / "frontend/tests/fixtures/daily-review-ai-basis.json"


def seed_saved_result(monkeypatch, root, version):
    monkeypatch.setenv("VR_DATA_DIR", str(root))
    monkeypatch.setattr(service.review_history, "resolve_review_db_path", lambda: root / "synthetic-ai.sqlite3")
    monkeypatch.setattr(service, "_now_beijing_timestamp", lambda: DAY + " 16:00:00")
    review = {"schema_version": "daily-review-v0.1", "trade_date": DAY, "generated_at": DAY + " 15:30:00",
        "data_cutoff": DAY + " 15:00:00", "status": "partial", "warnings": ["Synthetic unavailable source"],
        "data_health": {"components": {"breadth": "partial"}}, "market_environment": {}}
    captured = basis.capture_basis(daily_review_context.render_daily_review_ai_context(review), review)
    service.save_daily_review_ai(review, "SYNTHETIC_SAVED_REVIEW_" + version, {"provider": "fixture", "model": "fixture"},
                                input_basis=captured if version == "v2" else None)
    return service.get_ai_result("daily_review_ai", trade_date=DAY)


@pytest.fixture
def saved_result(monkeypatch, tmp_path, request):
    seed_saved_result(monkeypatch, tmp_path, request.param)
    return tmp_path, request.param


@pytest.mark.parametrize("saved_result", ["v1", "v2"], indirect=True)
def test_browser_saved_basis_equals_actual_registered_restore(saved_result, http_get):
    root, version = saved_result
    before = tree(root)
    response = http_get("/api/ai-results/daily_review_ai?trade_date=" + DAY)
    assert response.status_code == 200
    assert response.json()["data"] == json.loads(GOLDEN.read_text(encoding="utf-8"))[version]
    assert tree(root) == before
