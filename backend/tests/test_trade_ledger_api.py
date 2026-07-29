"""Tests for trade_ledger API endpoints."""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import ai_result_store
import app
import evidence_thesis_service
import trade_ledger_store as store


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


class TestSingleRouterRegistration:
    def test_routes_registered_exactly_once(self):
        target_paths = {
            ("POST", "/api/trades"),
            ("GET", "/api/trades"),
            ("GET", "/api/trades/{trade_id}"),
            ("POST", "/api/trades/{trade_id}/void"),
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


class TestCreateTrade:
    def test_create_full_buy(self, client):
        resp = client.post("/api/trades", json={
            "code": "600519",
            "name": "贵州茅台",
            "operation": "buy",
            "execution_status": "full",
            "actual_price": 1500.0,
            "actual_quantity": 100,
            "executed_at": "2026-07-28T09:30:00+08:00",
            "fee": 37.5,
        })
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["code"] == "600519"
        assert data["execution_status"] == "full"
        assert data["executed_at"] == "2026-07-28T01:30:00.000000+00:00"
        assert data["gross_amount"] == 150000.0
        assert data["total_cost"] == 37.5
        assert data["net_cash_flow"] == -150037.5
        assert "trade_id" in data

    def test_missing_required_fields_returns_422(self, client):
        for req in ("code", "name", "operation", "execution_status"):
            payload = {
                "code": "600519",
                "name": "贵州茅台",
                "operation": "buy",
                "execution_status": "full",
                "actual_price": 1500.0,
                "actual_quantity": 100,
                "executed_at": "2026-07-28T09:30:00+08:00",
            }
            del payload[req]
            resp = client.post("/api/trades", json=payload)
            assert resp.status_code == 422

    def test_response_no_path_or_sql(self, client):
        resp = client.post("/api/trades", json={
            "code": "600519",
            "name": "X",
            "operation": "buy",
            "execution_status": "full",
            "actual_price": 100.0,
            "actual_quantity": 100,
            "executed_at": "2026-07-28T09:30:00+08:00",
        })
        assert resp.status_code == 200
        body = resp.text
        assert "sqlite" not in body.lower()
        assert "traceback" not in body.lower()
        assert "C:\\" not in body


class TestCreateTradeWithAdviceRef:
    def _seed_advice(self, trade_date="2026-07-28", generated_at="2026-07-28 09:00:00"):
        review_db = Path(os.environ["VIBE_RESEARCH_REVIEW_DB"])
        payload = {
            "trade_date": trade_date,
            "generated_at": generated_at,
            "holdings": [
                {
                    "code": "600519",
                    "action": "add",
                    "execution_quantity": 100,
                    "price_conditions": ["低于1500"],
                    "execution_plan": ["分批建仓"],
                    "risk_conditions": ["止损点1400"],
                    "invalidation_conditions": ["基本面恶化"],
                    "confidence": "high",
                }
            ],
        }
        record = {
            "result_type": "portfolio_advice",
            "trade_date": trade_date,
            "schema_version": "portfolio_advice.v1",
            "payload": payload,
            "generated_at": generated_at,
            "model_provider": "api-compatible",
            "model_name": "gpt-4",
        }
        ai_result_store.upsert_result(review_db, record)

    def test_advice_ref_success_returns_object_snapshot(self, client):
        self._seed_advice()
        resp = client.post("/api/trades", json={
            "code": "600519",
            "name": "贵州茅台",
            "operation": "buy",
            "execution_status": "full",
            "actual_price": 1500.0,
            "actual_quantity": 100,
            "executed_at": "2026-07-28T09:30:00+08:00",
            "advice_ref": {
                "trade_date": "2026-07-28",
                "generated_at": "2026-07-28 09:00:00",
            },
        })
        assert resp.status_code == 200
        data = resp.json()["data"]
        snapshot = data["advice_snapshot"]
        assert isinstance(snapshot, dict)
        assert snapshot["action"] == "add"

        # Also GET detail returns dict snapshot
        trade_id = data["trade_id"]
        get_resp = client.get(f"/api/trades/{trade_id}")
        assert isinstance(get_resp.json()["data"]["advice_snapshot"], dict)

    def test_advice_ref_not_found_returns_404(self, client):
        resp = client.post("/api/trades", json={
            "code": "600519",
            "name": "贵州茅台",
            "operation": "buy",
            "execution_status": "full",
            "actual_price": 1500.0,
            "actual_quantity": 100,
            "executed_at": "2026-07-28T09:30:00+08:00",
            "advice_ref": {
                "trade_date": "2026-07-28",
                "generated_at": "2026-07-28 09:00:00",
            },
        })
        assert resp.status_code == 404

    def test_advice_ref_conflict_returns_409(self, client):
        self._seed_advice(generated_at="2026-07-28 09:00:00")
        resp = client.post("/api/trades", json={
            "code": "600519",
            "name": "贵州茅台",
            "operation": "buy",
            "execution_status": "full",
            "actual_price": 1500.0,
            "actual_quantity": 100,
            "executed_at": "2026-07-28T09:30:00+08:00",
            "advice_ref": {
                "trade_date": "2026-07-28",
                "generated_at": "2026-07-28 10:00:00",
            },
        })
        assert resp.status_code == 409

    def test_advice_ref_invalid_calendar_date_returns_422(self, client):
        resp = client.post("/api/trades", json={
            "code": "600519",
            "name": "贵州茅台",
            "operation": "buy",
            "execution_status": "full",
            "actual_price": 1500.0,
            "actual_quantity": 100,
            "executed_at": "2026-07-28T09:30:00+08:00",
            "advice_ref": {
                "trade_date": "2026-02-30",
                "generated_at": "2026-07-28 09:00:00",
            },
        })
        assert resp.status_code == 422


class TestCreateTradeWithThesisRef:
    def test_thesis_ref_success(self, client):
        thesis_db = Path(os.environ["VIBE_RESEARCH_EVIDENCE_THESIS_DB"])
        created = evidence_thesis_service.create_thesis(thesis_db, {
            "subject_type": "stock",
            "subject_id": "600519",
            "title": "茅台逻辑",
            "summary": "龙头",
            "core_claims": ["核心主张"],
            "catalysts": ["催化剂"],
            "risks": ["风险点"],
            "invalidation_conditions": ["证伪条件"],
        })
        thesis_id = created["thesis"]["id"]

        resp = client.post("/api/trades", json={
            "code": "600519",
            "name": "贵州茅台",
            "operation": "buy",
            "execution_status": "full",
            "actual_price": 1500.0,
            "actual_quantity": 100,
            "executed_at": "2026-07-28T09:30:00+08:00",
            "thesis_ref": {
                "thesis_id": thesis_id,
                "revision_number": 1,
            },
        })
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["thesis_id"] == thesis_id
        assert data["thesis_revision"] == 1

    def test_thesis_ref_not_found_returns_404(self, client):
        resp = client.post("/api/trades", json={
            "code": "600519",
            "name": "贵州茅台",
            "operation": "buy",
            "execution_status": "full",
            "actual_price": 1500.0,
            "actual_quantity": 100,
            "executed_at": "2026-07-28T09:30:00+08:00",
            "thesis_ref": {
                "thesis_id": "nonexistent-id",
                "revision_number": 1,
            },
        })
        assert resp.status_code == 404


class TestListTradeFiltering:
    def test_strict_include_voided_param(self, client):
        for invalid_val in ("1", "0", "yes", "no", "on", "off", "true,false"):
            resp = client.get(f"/api/trades?include_voided={invalid_val}")
            assert resp.status_code == 422, f"Expected 422 for include_voided={invalid_val}"

        assert client.get("/api/trades?include_voided=true").status_code == 200
        assert client.get("/api/trades?include_voided=false").status_code == 200

    def test_strict_filter_validations(self, client):
        assert client.get("/api/trades?code=123").status_code == 422
        assert client.get("/api/trades?operation=invalid").status_code == 422
        assert client.get("/api/trades?execution_status=invalid").status_code == 422
        assert client.get("/api/trades?date_from=2026-02-30").status_code == 422
        assert client.get("/api/trades?date_from=2026-07-29&date_to=2026-07-28").status_code == 422


class TestVoidTrade:
    def test_void_success(self, client):
        create_resp = client.post("/api/trades", json={
            "code": "600519", "name": "X", "operation": "buy",
            "execution_status": "full", "actual_price": 100.0, "actual_quantity": 100,
            "executed_at": "2026-07-28T09:30:00+08:00",
        })
        trade_id = create_resp.json()["data"]["trade_id"]
        resp = client.post(f"/api/trades/{trade_id}/void", json={"reason": "录入错误"})
        assert resp.status_code == 200
        assert resp.json()["data"]["voided_at"] is not None
        assert resp.json()["data"]["void_reason"] == "录入错误"

    def test_void_already_voided_returns_409(self, client):
        create_resp = client.post("/api/trades", json={
            "code": "600519", "name": "X", "operation": "buy",
            "execution_status": "full", "actual_price": 100.0, "actual_quantity": 100,
            "executed_at": "2026-07-28T09:30:00+08:00",
        })
        trade_id = create_resp.json()["data"]["trade_id"]
        client.post(f"/api/trades/{trade_id}/void", json={"reason": "第一次"})
        resp = client.post(f"/api/trades/{trade_id}/void", json={"reason": "第二次"})
        assert resp.status_code == 409


class TestCorruptedDBFailClosed:
    def test_corrupted_db_returns_safe_500(self, client, monkeypatch):
        db_path = Path(os.environ["VIBE_RESEARCH_TRADE_LEDGER_DB"])
        db_path.parent.mkdir(parents=True, exist_ok=True)

        client.post("/api/trades", json={
            "code": "600519", "name": "X", "operation": "buy",
            "execution_status": "full", "actual_price": 100.0, "actual_quantity": 100,
            "executed_at": "2026-07-28T09:30:00+08:00",
        })

        with open(db_path, "wb") as f:
            f.write(b"CORRUPTED DB DATA")

        resp = client.get("/api/trades")
        assert resp.status_code == 500
        assert resp.json()["detail"] == "交易流水数据损坏，已停止读写"
        assert "CORRUPTED" not in resp.text
        assert "sqlite" not in resp.text.lower()
