"""P0-S1A position reality API tests (offline, deterministic)."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app
import position_reality_service as svc


@pytest.fixture(autouse=True)
def _isolate_trade_db(tmp_path, monkeypatch):
    """Give each test its own isolated trade ledger DB directory."""
    isolated = tmp_path / "trade_db"
    isolated.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("VIBE_RESEARCH_TRADE_LEDGER_DB", str(isolated / "trade_ledger.sqlite3"))
    monkeypatch.setenv("VIBE_RESEARCH_REVIEW_DB", str(isolated / "daily_reviews.sqlite3"))
    monkeypatch.setenv("VIBE_RESEARCH_EVIDENCE_THESIS_DB", str(isolated / "evidence_thesis.db"))
    monkeypatch.setenv("VR_DATA_DIR", str(isolated))
    yield


@pytest.fixture
def client():
    return TestClient(app.app)


_BOOTSTRAP_PAYLOAD = {
    "ledger_start_at": "2026-08-01",
    "opening_cash": 100000.0,
    "positions": [
        {"code": "600519", "name": "贵州茅台", "shares": 100, "cost_basis": 1500.0},
        {"code": "000001", "name": "平安银行", "shares": 200, "cost_basis": 10.0},
    ],
}


class TestRouteRegistration:
    def test_routes_registered_exactly_once(self):
        target_paths = {
            ("POST", "/api/position/bootstrap-preview"),
            ("POST", "/api/position/bootstrap-commit"),
            ("POST", "/api/position/correction"),
            ("GET", "/api/position/derived"),
            ("GET", "/api/position/reconciliation"),
            ("POST", "/api/position/trades/{trade_id}/void"),
        }
        found_counts = {t: 0 for t in target_paths}

        all_routes = []
        for route in app.app.routes:
            if hasattr(route, "original_router"):
                all_routes.extend(route.original_router.routes)
            else:
                all_routes.append(route)

        for route in all_routes:
            methods = getattr(route, "methods", set()) or set()
            path = getattr(route, "path", "")
            for m in methods:
                if (m, path) in found_counts:
                    found_counts[(m, path)] += 1

        for target, count in found_counts.items():
            assert count == 1, f"Route {target} registered {count} times (expected 1)"


class TestBootstrapApi:
    def test_bootstrap_commit_ok(self, client):
        resp = client.post("/api/position/bootstrap-commit", json=_BOOTSTRAP_PAYLOAD)
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["status"] == "BOOTSTRAPPED"
        assert data["opening"]["event_type"] == "ACCOUNT_OPENING"
        assert len(data["positions"]) == 2
        assert data["positions"][0]["origin"] == "PRE_VIBE"

    def test_bootstrap_preview_not_written(self, client):
        resp = client.post("/api/position/bootstrap-preview", json=_BOOTSTRAP_PAYLOAD)
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["preview"] is True
        # 未落库：derived 显示未 bootstrap
        derived_resp = client.get("/api/position/derived")
        assert derived_resp.status_code == 200
        assert derived_resp.json()["data"]["ledger_start"] is None
        assert derived_resp.json()["data"]["positions"] == []

    def test_bootstrap_invalid_payload_422(self, client):
        # 缺 ledger_start_at
        resp = client.post("/api/position/bootstrap-commit", json={
            "positions": [{"code": "600519", "shares": 100, "cost_basis": 1500.0}],
        })
        assert resp.status_code == 422
        # shares <= 0
        resp = client.post("/api/position/bootstrap-commit", json={
            "ledger_start_at": "2026-08-01",
            "positions": [{"code": "600519", "shares": 0, "cost_basis": 1500.0}],
        })
        assert resp.status_code == 422
        # 重复 code
        resp = client.post("/api/position/bootstrap-commit", json={
            "ledger_start_at": "2026-08-01",
            "positions": [
                {"code": "600519", "shares": 100, "cost_basis": 1500.0},
                {"code": "600519", "shares": 200, "cost_basis": 1500.0},
            ],
        })
        assert resp.status_code == 422

    def test_bootstrap_duplicate_409(self, client):
        assert client.post("/api/position/bootstrap-commit", json=_BOOTSTRAP_PAYLOAD).status_code == 200
        resp = client.post("/api/position/bootstrap-commit", json=_BOOTSTRAP_PAYLOAD)
        assert resp.status_code == 409

    def test_bootstrap_after_trade_409(self, client):
        resp = client.post("/api/trades", json={
            "code": "600519",
            "name": "贵州茅台",
            "operation": "buy",
            "execution_status": "full",
            "actual_price": 1500.0,
            "actual_quantity": 100,
            "executed_at": "2026-07-28T09:30:00+08:00",
        })
        assert resp.status_code == 200
        resp = client.post("/api/position/bootstrap-commit", json=_BOOTSTRAP_PAYLOAD)
        assert resp.status_code == 409


class TestCorrectionApi:
    def test_correction_ok(self, client):
        client.post("/api/position/bootstrap-commit", json=_BOOTSTRAP_PAYLOAD)
        import account_event_store
        events = account_event_store.list_events(svc.resolve_db_path())
        target = next(e for e in events if e["event_type"] == "LEGACY_POSITION_OPENING")
        code = target["code"]
        resp = client.post("/api/position/correction", json={
            "target_event_id": target["event_id"],
            "target_event_type": "account_event",
            "after_payload": {"shares": 120},
            "reason": "期初数量修正",
        })
        assert resp.status_code == 200
        assert resp.json()["data"]["status"] == "CORRECTION_RECORDED"
        derived = client.get("/api/position/derived").json()["data"]
        pos = next(p for p in derived["positions"] if p["code"] == code)
        assert pos["shares"] == 120

    def test_correction_target_not_found_404(self, client):
        resp = client.post("/api/position/correction", json={
            "target_event_id": "missing",
            "target_event_type": "trade",
            "after_payload": {"actual_quantity": 10},
        })
        assert resp.status_code == 404

    def test_correction_unknown_field_422(self, client):
        client.post("/api/position/bootstrap-commit", json=_BOOTSTRAP_PAYLOAD)
        import account_event_store
        events = account_event_store.list_events(svc.resolve_db_path())
        target = next(e for e in events if e["event_type"] == "LEGACY_POSITION_OPENING")
        resp = client.post("/api/position/correction", json={
            "target_event_id": target["event_id"],
            "target_event_type": "account_event",
            "after_payload": {"shares": 120, "name": "改名"},
        })
        assert resp.status_code == 422


class TestDerivedApi:
    def test_derived_structure(self, client):
        client.post("/api/position/bootstrap-commit", json=_BOOTSTRAP_PAYLOAD)
        resp = client.get("/api/position/derived")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["derivation_status"] == "OK"
        assert data["bootstrap_status"] == "BOOTSTRAPPED"
        assert data["canonical"] is True
        assert data["ledger_start"]["pre_vibe_history"] == "UNKNOWN"
        codes = {p["code"] for p in data["positions"]}
        assert codes == {"600519", "000001"}

    def test_derived_empty_before_bootstrap(self, client):
        resp = client.get("/api/position/derived")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["ledger_start"] is None
        assert data["bootstrap_status"] == "NOT_BOOTSTRAPPED"
        assert data["canonical"] is False
        assert data["positions"] == []

    def test_bootstrap_invalid_ledger_start_422(self, client):
        resp = client.post("/api/position/bootstrap-commit", json={
            "ledger_start_at": "not-a-date",
            "positions": [],
        })
        assert resp.status_code == 422


class TestReconciliationApi:
    def _write_portfolio(self, tmp_path: Path, monkeypatch, holdings: list[dict]) -> None:
        import json
        import portfolio
        pf = tmp_path / "portfolio.json"
        pf.write_text(json.dumps({"holdings": holdings, "last_refresh": None}), encoding="utf-8")
        monkeypatch.setattr(portfolio, "PF_FILE", str(pf))

    def test_reconciliation_structure(self, client, tmp_path, monkeypatch):
        client.post("/api/position/bootstrap-commit", json=_BOOTSTRAP_PAYLOAD)
        self._write_portfolio(tmp_path, monkeypatch, [
            {"code": "600519", "shares": 100, "cost": 1500.0},
            {"code": "000001", "shares": 200, "cost": 10.0},
        ])
        resp = client.get("/api/position/reconciliation")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["derivation_status"] == "OK"
        assert data["summary"]["match"] == 2
        assert all(item["status"] == "MATCH" for item in data["items"])

    def test_reconciliation_mismatch(self, client, tmp_path, monkeypatch):
        client.post("/api/position/bootstrap-commit", json=_BOOTSTRAP_PAYLOAD)
        self._write_portfolio(tmp_path, monkeypatch, [
            {"code": "600519", "shares": 90, "cost": 1500.0},
        ])
        resp = client.get("/api/position/reconciliation")
        assert resp.status_code == 200
        data = resp.json()["data"]
        by_code = {item["code"]: item for item in data["items"]}
        assert by_code["600519"]["status"] == "MISMATCH"
        assert by_code["600519"]["reason"] == "shares mismatch"
        assert by_code["000001"]["status"] == "MISSING_IN_PORTFOLIO"


class TestVoidCascadeApi:
    def test_void_trade_cascades_correction(self, client):
        client.post("/api/position/bootstrap-commit", json=_BOOTSTRAP_PAYLOAD)
        trade_resp = client.post("/api/trades", json={
            "code": "600519",
            "name": "贵州茅台",
            "operation": "buy",
            "execution_status": "full",
            "actual_price": 10.0,
            "actual_quantity": 100,
            "executed_at": "2026-08-03T09:30:00+08:00",
        })
        trade_id = trade_resp.json()["data"]["trade_id"]
        corr_resp = client.post("/api/position/correction", json={
            "target_event_id": trade_id,
            "target_event_type": "trade",
            "after_payload": {"actual_quantity": 50},
        })
        assert corr_resp.status_code == 200
        void_resp = client.post(f"/api/position/trades/{trade_id}/void", json={"reason": "录入错误"})
        assert void_resp.status_code == 200
        data = void_resp.json()["data"]
        assert data["status"] == "VOIDED"
        assert data["cascade_voided"] == 1
        # derivation 不再失败
        derived = client.get("/api/position/derived").json()["data"]
        assert derived["derivation_status"] == "OK"

    def test_void_trade_missing_404(self, client):
        resp = client.post("/api/position/trades/missing/void", json={"reason": "x"})
        assert resp.status_code == 404

    def test_void_trade_missing_reason_422(self, client):
        resp = client.post("/api/position/trades/abc/void", json={})
        assert resp.status_code == 422

    def test_void_already_voided_recovery_200(self, client):
        """already-voided + 孤儿 correction：恢复成功返回 200（非 409），derivation 恢复。"""
        client.post("/api/position/bootstrap-commit", json=_BOOTSTRAP_PAYLOAD)
        trade_resp = client.post("/api/trades", json={
            "code": "600519",
            "name": "贵州茅台",
            "operation": "buy",
            "execution_status": "full",
            "actual_price": 10.0,
            "actual_quantity": 100,
            "executed_at": "2026-08-03T09:30:00+08:00",
        })
        trade_id = trade_resp.json()["data"]["trade_id"]
        client.post("/api/position/correction", json={
            "target_event_id": trade_id,
            "target_event_type": "trade",
            "after_payload": {"actual_quantity": 50},
        })
        # 既有端点作废（不级联）→ 制造孤儿
        client.post(f"/api/trades/{trade_id}/void", json={"reason": "既有 void"})
        derived_before = client.get("/api/position/derived")
        assert derived_before.status_code == 500
        # 新端点恢复 → 200 ALREADY_VOIDED_RECOVERED
        resp = client.post(f"/api/position/trades/{trade_id}/void", json={"reason": "恢复路径"})
        assert resp.status_code == 200
        assert resp.json()["data"]["status"] == "ALREADY_VOIDED_RECOVERED"
        assert resp.json()["data"]["cascade_voided"] == 1
        derived_after = client.get("/api/position/derived")
        assert derived_after.status_code == 200
        assert derived_after.json()["data"]["derivation_status"] == "OK"

    def test_void_already_voided_no_orphan_409(self, client):
        """already-voided + 无孤儿：保持 409 Already Voided，零副作用。"""
        client.post("/api/position/bootstrap-commit", json=_BOOTSTRAP_PAYLOAD)
        trade_resp = client.post("/api/trades", json={
            "code": "600519",
            "name": "贵州茅台",
            "operation": "buy",
            "execution_status": "full",
            "actual_price": 10.0,
            "actual_quantity": 100,
            "executed_at": "2026-08-03T09:30:00+08:00",
        })
        trade_id = trade_resp.json()["data"]["trade_id"]
        assert client.post(f"/api/position/trades/{trade_id}/void", json={"reason": "首次"}).status_code == 200
        resp = client.post(f"/api/position/trades/{trade_id}/void", json={"reason": "再次"})
        assert resp.status_code == 409


class TestJsonContractApi:
    """P2-1：JSON 解析错误必须原样返回 400/422，不得变成 500。"""

    def test_bootstrap_commit_malformed_json_400(self, client):
        resp = client.post("/api/position/bootstrap-commit", content="{not json")
        assert resp.status_code == 400

    def test_bootstrap_commit_non_object_422(self, client):
        resp = client.post("/api/position/bootstrap-commit", content="[]")
        assert resp.status_code == 422

    def test_correction_malformed_json_400(self, client):
        resp = client.post("/api/position/correction", content="{not json")
        assert resp.status_code == 400

    def test_correction_non_object_422(self, client):
        resp = client.post("/api/position/correction", content="[]")
        assert resp.status_code == 422
