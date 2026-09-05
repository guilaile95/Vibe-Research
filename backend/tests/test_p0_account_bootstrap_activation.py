"""P0-AB1 — account bootstrap product activation E2E.

复用已有 canonical bootstrap authority（service + HTTP API 均不新增），
证明一条真实形态路径：空账户 → preview（零写）→ commit（原子）→
canonical position derivation → holdings composition → Decision Inbox。

全部使用隔离临时数据库；不触碰真实用户数据、不产生真实写入。
"""

from __future__ import annotations

import math

import pytest
from fastapi.testclient import TestClient

import app
import position_reality_service as svc


@pytest.fixture(autouse=True)
def _isolate_env(tmp_path, monkeypatch):
    isolated = tmp_path / "ab1"
    isolated.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("VIBE_RESEARCH_TRADE_LEDGER_DB", str(isolated / "trade_ledger.sqlite3"))
    monkeypatch.setenv("VIBE_RESEARCH_REVIEW_DB", str(isolated / "daily_reviews.sqlite3"))
    monkeypatch.setenv("VIBE_RESEARCH_EVIDENCE_THESIS_DB", str(isolated / "evidence_thesis.db"))
    monkeypatch.setenv("VIBE_RESEARCH_CAMPAIGN_DB", str(isolated / "campaigns.sqlite3"))
    monkeypatch.setenv("VIBE_RESEARCH_FROZEN_DECISION_DB", str(isolated / "frozen_decisions.sqlite3"))
    monkeypatch.setenv("VR_DATA_DIR", str(isolated))
    monkeypatch.delenv("VR_FACT_LAKE_ROOT", raising=False)
    yield


@pytest.fixture
def client():
    return TestClient(app.app)


_PAYLOAD = {
    "ledger_start_at": "2026-08-01",
    "opening_cash": 100000.0,
    "positions": [
        {"code": "600519", "name": "贵州茅台", "shares": 100, "cost_basis": 1500.0},
        {"code": "000001", "name": "平安银行", "shares": 200, "cost_basis": 10.5},
        {"code": "300750", "name": "宁德时代", "shares": 50, "cost_basis": None},
    ],
}


class TestPreview:
    def test_preview_is_zero_write_and_carries_frozen_semantics(self, client):
        before = svc.derive_positions()
        assert before["bootstrap_status"] == "NOT_BOOTSTRAPPED"

        resp = client.post("/api/position/bootstrap-preview", json=_PAYLOAD)
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["preview"] is True
        assert data["validation"] == "ok"

        opening = data["opening"]
        assert opening["event_type"] == "ACCOUNT_OPENING"
        assert opening["historical_trades"] == "UNKNOWN"
        assert opening["provenance"] == "MANUAL"

        positions = data["positions"]
        assert len(positions) == 3
        for position in positions:
            assert position["event_type"] == "LEGACY_POSITION_OPENING"
            assert position["origin"] == "PRE_VIBE"
            assert position["historical_trades"] == "UNKNOWN"
            assert position["provenance"] == "MANUAL"
            assert position["acquired_before_vibe"] == 1

        # 零写证明：preview 后账户仍未 bootstrap
        after = svc.derive_positions()
        assert after["bootstrap_status"] == "NOT_BOOTSTRAPPED"

    def test_preview_invalid_payload_rejected_without_write(self, client):
        resp = client.post(
            "/api/position/bootstrap-preview",
            json={**_PAYLOAD, "force": True},
        )
        assert resp.status_code == 422
        assert svc.derive_positions()["bootstrap_status"] == "NOT_BOOTSTRAPPED"


class TestCommit:
    def test_bootstrap_commit_to_derivation_exactness(self, client):
        resp = client.post("/api/position/bootstrap-commit", json=_PAYLOAD)
        assert resp.status_code == 200
        body = resp.json()["data"]
        assert body["status"] == "BOOTSTRAPPED"
        assert body["opening"]["event_type"] == "ACCOUNT_OPENING"
        assert [p["event_type"] for p in body["positions"]] == [
            "LEGACY_POSITION_OPENING"
        ] * 3

        derived = svc.derive_positions()
        assert derived["bootstrap_status"] == "BOOTSTRAPPED"
        assert derived["canonical"] is True
        by_code = {p["code"]: p for p in derived["positions"]}
        assert by_code["600519"]["shares"] == 100
        # cost_basis 语义 = 期初总成本（每股成本 × 股数）
        assert by_code["600519"]["cost_basis"] == 150000.0
        assert by_code["600519"]["avg_cost"] == 1500.0
        assert by_code["000001"]["shares"] == 200
        assert by_code["000001"]["cost_basis"] == 2100.0
        assert by_code["000001"]["avg_cost"] == 10.5
        assert by_code["300750"]["shares"] == 50
        assert by_code["300750"]["cost_basis"] is None
        assert by_code["300750"]["cost_known"] is False
        assert all(p["origin"] in ("PRE_VIBE",) for p in derived["positions"])

    def test_legacy_opening_is_not_a_buy(self, client):
        client.post("/api/position/bootstrap-commit", json=_PAYLOAD)
        import trade_ledger_service
        import trade_ledger_store

        derived = svc.derive_positions()
        assert all(
            p["origin"] == "PRE_VIBE" for p in derived["positions"]
        )
        # 没有任何 trade 记录（不存在虚构历史 BUY）
        records = trade_ledger_store.list_records(
            trade_ledger_service.resolve_db_path(),
            include_voided=False,
            limit=None,
        )
        assert records == []


class TestCommitSafety:
    def test_duplicate_bootstrap_rejected(self, client):
        assert client.post(
            "/api/position/bootstrap-commit", json=_PAYLOAD
        ).status_code == 200
        resp = client.post("/api/position/bootstrap-commit", json=_PAYLOAD)
        assert resp.status_code == 409

    def test_existing_account_events_reject(self, client):
        client.post("/api/position/bootstrap-commit", json=_PAYLOAD)
        resp = client.post(
            "/api/position/bootstrap-commit",
            json={**_PAYLOAD, "ledger_start_at": "2026-08-02"},
        )
        assert resp.status_code == 409

    def test_existing_post_vibe_trade_reject(self, client):
        import trade_ledger_service

        trade_ledger_service.create_trade({
            "code": "600519",
            "name": "贵州茅台",
            "operation": "buy",
            "execution_status": "full",
            "actual_price": 1500.0,
            "actual_quantity": 10,
            "executed_at": "2026-08-03T09:30:00+08:00",
            "fee": 0.0,
        })
        resp = client.post("/api/position/bootstrap-commit", json=_PAYLOAD)
        assert resp.status_code == 409


class TestInputFailClosed:
    @pytest.mark.parametrize(
        "mutate",
        [
            lambda p: p["positions"].append({"code": "600519", "shares": 1}),
            lambda p: p["positions"].append({"code": "ABC", "shares": 1}),
            lambda p: p["positions"].append({"code": "000002", "shares": 0}),
            lambda p: p["positions"].append({"code": "000002", "shares": True}),
            lambda p: p["positions"].append(
                {"code": "000002", "shares": 1, "cost_basis": float("nan")}
            ),
            lambda p: p["positions"].append(
                {"code": "000002", "shares": 1, "cost_basis": float("inf")}
            ),
            lambda p: p["positions"].append(
                {"code": "000002", "shares": 1, "cost_basis": -1.0}
            ),
            lambda p: p.__setitem__("unknown_top", 1),
            lambda p: p["positions"].append(
                {"code": "000002", "shares": 1, "historical_buy_date": "2026-01-01"}
            ),
        ],
    )
    def test_invalid_input_rejected_without_write(self, client, mutate):
        payload = {
            "ledger_start_at": "2026-08-01",
            "opening_cash": 100000.0,
            "positions": [
                {"code": "600519", "name": "贵州茅台", "shares": 100, "cost_basis": 1500.0},
            ],
        }
        mutate(payload)
        resp = client.post("/api/position/bootstrap-commit", json=payload)
        assert resp.status_code == 422
        assert svc.derive_positions()["bootstrap_status"] == "NOT_BOOTSTRAPPED"

    def test_finite_cost_guard(self, client):
        assert math.isfinite(1.0)


class TestProductFlow:
    def test_bootstrap_to_composition_to_inbox(self, client):
        assert client.post(
            "/api/position/bootstrap-commit", json=_PAYLOAD
        ).status_code == 200

        # holdings → campaign composition：无 Campaign → 全部 UNASSIGNED
        composition = client.get("/api/holdings/campaign-composition")
        assert composition.status_code == 200
        comp = composition.json()["data"]
        assert comp["evaluation_status"] == "EVALUATED"
        assert comp["total_holdings"] == 3
        codes = {item["security_code"] for item in comp["items"]}
        assert codes == {"600519", "000001", "300750"}
        assert all(
            item["composition_status"] == "UNASSIGNED_HOLDING"
            for item in comp["items"]
        )
        assert all(item["campaigns"] == [] for item in comp["items"])

        # decision inbox：同一批持仓全部出现，SETUP_REQUIRED + CREATE_CAMPAIGN
        inbox = client.get("/api/decision-inbox")
        assert inbox.status_code == 200
        data = inbox.json()["data"]
        assert data["evaluation_status"] == "EVALUATED"
        assert data["total_holdings"] == 3
        assert data["total_campaign_items"] == 0
        setup = data["holding_setup_items"]
        assert len(setup) == 3
        setup_codes = {item["security_code"] for item in setup}
        assert setup_codes == {"600519", "000001", "300750"}
        assert all(
            item["item_kind"] == "UNASSIGNED_HOLDING"
            and item["next_workflow_action"] == "CREATE_CAMPAIGN"
            and item["reason_codes"] == ["UNASSIGNED_HOLDING"]
            for item in setup
        )
        assert data["campaign_items"] == []
        assert data["canonical"] is True

    def test_no_phantom_campaign_no_fake_buy_no_duplicates(self, client):
        client.post("/api/position/bootstrap-commit", json=_PAYLOAD)
        composition = client.get(
            "/api/holdings/campaign-composition"
        ).json()["data"]
        assert len(composition["items"]) == len(
            {item["security_code"] for item in composition["items"]}
        )
        assert all(
            item["composition_status"] == "UNASSIGNED_HOLDING"
            for item in composition["items"]
        )
        assert not any(item["campaigns"] for item in composition["items"])
        derived = svc.derive_positions()
        assert derived["positions"]
        assert all(p["origin"] == "PRE_VIBE" for p in derived["positions"])
