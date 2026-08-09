"""P0-S1B-B cash event API tests（test-only FastAPI app，不挂主 app.py）。

按任务书 §十五：MAIN_APP_ROUTER_WIRING = DEFERRED_TO_INTEGRATION；
API 行为在此 test-only app 上验证（含路由唯一性、稳定 4xx、404、脱敏 500）。
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import account_event_store
import cash_event_router
import cash_event_service as svc
import position_reality_service


@pytest.fixture(autouse=True)
def _isolate_db(tmp_path, monkeypatch):
    isolated = tmp_path / "ledger_db"
    isolated.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("VIBE_RESEARCH_TRADE_LEDGER_DB", str(isolated / "trade_ledger.sqlite3"))
    monkeypatch.setenv("VIBE_RESEARCH_REVIEW_DB", str(isolated / "daily_reviews.sqlite3"))
    monkeypatch.setenv("VIBE_RESEARCH_EVIDENCE_THESIS_DB", str(isolated / "evidence_thesis.db"))
    monkeypatch.setenv("VR_DATA_DIR", str(isolated))
    yield


@pytest.fixture
def client():
    test_app = FastAPI()
    test_app.include_router(cash_event_router.router)
    return TestClient(test_app)


@pytest.fixture(autouse=True)
def _bootstrap_default(tmp_path, monkeypatch, _isolate_db):
    # 显式依赖 _isolate_db：保证 env 隔离先于 bootstrap（否则落到 conftest 全局目录）
    position_reality_service.bootstrap_commit({
        "ledger_start_at": "2026-08-01",
        "opening_cash": 100000.0,
        "positions": [],
    })


class TestRouteRegistration:
    def test_routes_registered_exactly_once(self):
        target_paths = {
            ("POST", "/api/account/cash-events"),
            ("GET", "/api/account/cash-events"),
            ("GET", "/api/account/cash-events/{event_id}"),
        }
        found_counts = {t: 0 for t in target_paths}
        for route in cash_event_router.router.routes:
            methods = getattr(route, "methods", set()) or set()
            path = getattr(route, "path", "")
            for m in methods:
                if (m, path) in found_counts:
                    found_counts[(m, path)] += 1
        for target, count in found_counts.items():
            assert count == 1, f"Route {target} registered {count} times (expected 1)"


class TestCashEventApi:
    def test_create_deposit_ok(self, client):
        resp = client.post("/api/account/cash-events", json={"event_type": "CASH_DEPOSIT", "amount": 1000.0})
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["event_type"] == "CASH_DEPOSIT"
        assert data["amount"] == 1000.0

    def test_create_withdrawal_ok(self, client):
        resp = client.post("/api/account/cash-events", json={"event_type": "CASH_WITHDRAWAL", "amount": 200.0})
        assert resp.status_code == 200

    def test_invalid_amount_422(self, client):
        resp = client.post("/api/account/cash-events", json={"event_type": "CASH_DEPOSIT", "amount": -100.0})
        assert resp.status_code == 422
        resp = client.post("/api/account/cash-events", json={"event_type": "CASH_DEPOSIT", "amount": 0})
        assert resp.status_code == 422
        resp = client.post("/api/account/cash-events", json={"event_type": "CASH_DEPOSIT", "amount": "100"})
        assert resp.status_code == 422

    def test_unknown_event_type_422(self, client):
        resp = client.post("/api/account/cash-events", json={"event_type": "CORPORATE_ACTION", "amount": 100.0})
        assert resp.status_code == 422
        resp = client.post("/api/account/cash-events", json={"event_type": "BOGUS", "amount": 100.0})
        assert resp.status_code == 422

    def test_malformed_json_400(self, client):
        resp = client.post("/api/account/cash-events", content="{not json")
        assert resp.status_code == 400

    def test_non_object_422(self, client):
        resp = client.post("/api/account/cash-events", content="[]")
        assert resp.status_code == 422

    def test_list_ok(self, client):
        client.post("/api/account/cash-events", json={"event_type": "CASH_DEPOSIT", "amount": 1000.0})
        client.post("/api/account/cash-events", json={"event_type": "CASH_FEE", "amount": 20.0})
        resp = client.get("/api/account/cash-events")
        assert resp.status_code == 200
        events = resp.json()["data"]
        assert len(events) == 2
        assert events[0]["event_type"] == "CASH_DEPOSIT"
        assert events[1]["event_type"] == "CASH_FEE"

    def test_get_by_id_ok(self, client):
        created = client.post("/api/account/cash-events", json={"event_type": "CASH_TAX", "amount": 10.0}).json()["data"]
        resp = client.get(f"/api/account/cash-events/{created['event_id']}")
        assert resp.status_code == 200
        assert resp.json()["data"]["amount"] == 10.0

    def test_unknown_event_id_404(self, client):
        resp = client.get("/api/account/cash-events/nonexistent")
        assert resp.status_code == 404

    def test_internal_error_sanitized(self, client, monkeypatch):
        """内部异常 → 脱敏 500，不泄漏 SQLite 消息/路径/异常 str。"""
        def _boom(*_args, **_kwargs):
            raise RuntimeError("secret path: /home/user/.vibe-research/x.sqlite3 | sqlite error")

        monkeypatch.setattr(svc, "create_cash_event", _boom)
        resp = client.post("/api/account/cash-events", json={"event_type": "CASH_DEPOSIT", "amount": 100.0})
        assert resp.status_code == 500
        assert "secret path" not in resp.text
        assert "sqlite error" not in resp.text
        assert resp.json()["detail"] == "内部错误"


class TestPersistedCorruptionApi:
    def test_persisted_corruption_sanitized_500(self, client):
        """持久化损坏（NULL amount）→ API 500 脱敏，不泄漏 SQLite/路径/异常 str。"""
        import account_event_store
        account_event_store.insert_event(svc.resolve_db_path(), {
            "event_id": "raw_null_amount",
            "event_type": "CASH_DEPOSIT",
            "code": None, "name": None, "shares": None, "cost_basis": None,
            "opening_cash": None, "ledger_start_at": None, "origin": None,
            "acquired_before_vibe": None, "historical_trades": None,
            "provenance": "MANUAL", "target_event_id": None, "target_event_type": None,
            "before_payload": None, "after_payload": None, "reason": None, "note": None,
            "amount": None, "created_at": "2026-08-09T00:00:00+00:00",
        })
        resp = client.get("/api/account/cash-events")
        assert resp.status_code == 500
        assert "sqlite" not in resp.text.lower()
        assert ".vibe-research" not in resp.text
        assert "traceback" not in resp.text.lower()
        assert resp.json()["detail"] == "内部错误"
