"""Tests for trade_ledger API endpoints."""
from __future__ import annotations

import pytest

from fastapi.testclient import TestClient

import app


@pytest.fixture(autouse=True)
def _isolate_trade_db(tmp_path, monkeypatch):
    """Give each test its own isolated trade ledger DB directory."""
    isolated = tmp_path / "trade_db"
    isolated.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("VIBE_RESEARCH_TRADE_LEDGER_DB", str(isolated / "trade_ledger.sqlite3"))
    # Also ensure VR_DATA_DIR points here so resolve_db_path works
    monkeypatch.setenv("VR_DATA_DIR", str(isolated))
    yield


@pytest.fixture
def client():
    return TestClient(app.app)


class TestCreateTrade:
    def test_create_full_buy(self, client):
        resp = client.post("/api/trades", json={
            "code": "600519",
            "name": "贵州茅台",
            "operation": "buy",
            "execution_status": "full",
            "actual_price": 1500.0,
            "actual_quantity": 100,
            "fee": 37.5,
        })
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["code"] == "600519"
        assert data["execution_status"] == "full"
        assert data["gross_amount"] == 150000.0
        assert data["net_cash_flow"] == -150037.5
        assert "trade_id" in data

    def test_create_partial(self, client):
        resp = client.post("/api/trades", json={
            "code": "000001",
            "name": "平安银行",
            "operation": "add",
            "execution_status": "partial",
            "planned_quantity": 500,
            "actual_price": 12.5,
            "actual_quantity": 200,
            "unexecuted_reason": "价格未到位",
        })
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["quantity_completion_pct"] == 40.0

    def test_create_not_executed(self, client):
        resp = client.post("/api/trades", json={
            "code": "000001",
            "name": "平安银行",
            "operation": "buy",
            "execution_status": "not_executed",
            "unexecuted_reason": "取消",
        })
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["actual_price"] is None
        assert data["actual_quantity"] == 0
        assert data["net_cash_flow"] == 0.0

    def test_invalid_code_returns_422(self, client):
        resp = client.post("/api/trades", json={
            "code": "60051",
            "name": "X",
            "operation": "buy",
            "execution_status": "full",
            "actual_price": 100.0,
            "actual_quantity": 100,
        })
        assert resp.status_code == 422

    def test_invalid_operation_returns_422(self, client):
        resp = client.post("/api/trades", json={
            "code": "600519",
            "name": "X",
            "operation": "hold",
            "execution_status": "full",
            "actual_price": 100.0,
            "actual_quantity": 100,
        })
        assert resp.status_code == 422

    def test_unknown_field_returns_422(self, client):
        resp = client.post("/api/trades", json={
            "code": "600519",
            "name": "X",
            "operation": "buy",
            "execution_status": "full",
            "actual_price": 100.0,
            "actual_quantity": 100,
            "unknown_field": "x",
        })
        assert resp.status_code == 422

    def test_negative_fee_returns_422(self, client):
        resp = client.post("/api/trades", json={
            "code": "600519",
            "name": "X",
            "operation": "buy",
            "execution_status": "full",
            "actual_price": 100.0,
            "actual_quantity": 100,
            "fee": -5.0,
        })
        assert resp.status_code == 422

    def test_response_no_path_or_sql(self, client):
        resp = client.post("/api/trades", json={
            "code": "600519",
            "name": "X",
            "operation": "buy",
            "execution_status": "full",
            "actual_price": 100.0,
            "actual_quantity": 100,
        })
        assert resp.status_code == 200
        body = resp.text
        assert "sqlite" not in body.lower()
        assert "traceback" not in body.lower()
        assert "C:\\" not in body


class TestListTrade:
    def test_list_empty(self, client):
        resp = client.get("/api/trades")
        assert resp.status_code == 200
        assert resp.json()["data"] == []

    def test_list_with_records(self, client):
        client.post("/api/trades", json={
            "code": "600519", "name": "X", "operation": "buy",
            "execution_status": "full", "actual_price": 100.0, "actual_quantity": 100,
        })
        client.post("/api/trades", json={
            "code": "000001", "name": "Y", "operation": "sell",
            "execution_status": "full", "actual_price": 50.0, "actual_quantity": 200,
        })
        resp = client.get("/api/trades")
        assert resp.status_code == 200
        assert len(resp.json()["data"]) == 2

    def test_list_filter_code(self, client):
        client.post("/api/trades", json={
            "code": "600519", "name": "X", "operation": "buy",
            "execution_status": "full", "actual_price": 100.0, "actual_quantity": 100,
        })
        client.post("/api/trades", json={
            "code": "000001", "name": "Y", "operation": "buy",
            "execution_status": "full", "actual_price": 50.0, "actual_quantity": 200,
        })
        resp = client.get("/api/trades?code=600519")
        assert len(resp.json()["data"]) == 1
        assert resp.json()["data"][0]["code"] == "600519"

    def test_list_filter_operation(self, client):
        client.post("/api/trades", json={
            "code": "600519", "name": "X", "operation": "buy",
            "execution_status": "full", "actual_price": 100.0, "actual_quantity": 100,
        })
        client.post("/api/trades", json={
            "code": "000001", "name": "Y", "operation": "sell",
            "execution_status": "full", "actual_price": 50.0, "actual_quantity": 200,
        })
        resp = client.get("/api/trades?operation=sell")
        assert len(resp.json()["data"]) == 1

    def test_list_include_voided_param(self, client):
        resp = client.get("/api/trades?include_voided=invalid")
        assert resp.status_code == 422

    def test_list_default_excludes_voided(self, client):
        create_resp = client.post("/api/trades", json={
            "code": "600519", "name": "X", "operation": "buy",
            "execution_status": "full", "actual_price": 100.0, "actual_quantity": 100,
        })
        trade_id = create_resp.json()["data"]["trade_id"]
        client.post(f"/api/trades/{trade_id}/void", json={"reason": "录入错误"})
        resp = client.get("/api/trades")
        assert len(resp.json()["data"]) == 0
        resp2 = client.get("/api/trades?include_voided=true")
        assert len(resp2.json()["data"]) == 1


class TestGetTrade:
    def test_get_detail(self, client):
        create_resp = client.post("/api/trades", json={
            "code": "600519", "name": "X", "operation": "buy",
            "execution_status": "full", "actual_price": 100.0, "actual_quantity": 100,
        })
        trade_id = create_resp.json()["data"]["trade_id"]
        resp = client.get(f"/api/trades/{trade_id}")
        assert resp.status_code == 200
        assert resp.json()["data"]["trade_id"] == trade_id

    def test_get_not_found(self, client):
        resp = client.get("/api/trades/nonexistent-id")
        assert resp.status_code == 404


class TestVoidTrade:
    def test_void_success(self, client):
        create_resp = client.post("/api/trades", json={
            "code": "600519", "name": "X", "operation": "buy",
            "execution_status": "full", "actual_price": 100.0, "actual_quantity": 100,
        })
        trade_id = create_resp.json()["data"]["trade_id"]
        resp = client.post(f"/api/trades/{trade_id}/void", json={"reason": "录入错误"})
        assert resp.status_code == 200
        assert resp.json()["data"]["voided_at"] is not None
        assert resp.json()["data"]["void_reason"] == "录入错误"

    def test_void_not_found(self, client):
        resp = client.post("/api/trades/nonexistent/void", json={"reason": "x"})
        assert resp.status_code == 404

    def test_void_already_voided(self, client):
        create_resp = client.post("/api/trades", json={
            "code": "600519", "name": "X", "operation": "buy",
            "execution_status": "full", "actual_price": 100.0, "actual_quantity": 100,
        })
        trade_id = create_resp.json()["data"]["trade_id"]
        client.post(f"/api/trades/{trade_id}/void", json={"reason": "第一次"})
        resp = client.post(f"/api/trades/{trade_id}/void", json={"reason": "第二次"})
        assert resp.status_code == 409

    def test_void_missing_reason(self, client):
        create_resp = client.post("/api/trades", json={
            "code": "600519", "name": "X", "operation": "buy",
            "execution_status": "full", "actual_price": 100.0, "actual_quantity": 100,
        })
        trade_id = create_resp.json()["data"]["trade_id"]
        resp = client.post(f"/api/trades/{trade_id}/void", json={})
        assert resp.status_code == 422
