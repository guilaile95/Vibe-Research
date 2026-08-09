"""P0 Foundation Router Wiring — main FastAPI app 集成契约测试。

验证已实现但原为 test-only 的 router 已正式挂载到 main app（backend/app.py）：
- account_reality_router（PR65 已挂，这里验证）
- cash_event_router（本 wiring 挂载）
- campaign_router（本 wiring 挂载）

断言使用真实 HTTP 请求（TestClient on app:app）与 OpenAPI schema，而非
test-only FastAPI app；检查路由唯一性、可达性与稳定错误语义。
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from types import SimpleNamespace

import app as app_module
import campaign_service
import position_reality_service


@pytest.fixture(autouse=True)
def _isolate_db(tmp_path, monkeypatch):
    isolated = tmp_path / "wiring_db"
    isolated.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("VIBE_RESEARCH_TRADE_LEDGER_DB", str(isolated / "trade_ledger.sqlite3"))
    monkeypatch.setenv("VIBE_RESEARCH_CAMPAIGN_DB", str(isolated / "campaigns.sqlite3"))
    monkeypatch.setenv("VIBE_RESEARCH_REVIEW_DB", str(isolated / "daily_reviews.sqlite3"))
    monkeypatch.setenv("VIBE_RESEARCH_EVIDENCE_THESIS_DB", str(isolated / "evidence_thesis.db"))
    monkeypatch.setenv("VR_DATA_DIR", str(isolated))
    yield


@pytest.fixture
def client(_isolate_db):
    return TestClient(app_module.app)


@pytest.fixture(autouse=True)
def _bootstrap_default(tmp_path, monkeypatch, _isolate_db):
    position_reality_service.bootstrap_commit({
        "ledger_start_at": "2026-08-01",
        "opening_cash": 100000.0,
        "positions": [],
    })


@pytest.fixture
def fake_evidence_thesis(monkeypatch, tmp_path):
    """fake canonical thesis provider（与 test_campaign_thesis_binding 同一模式）。"""
    theses: dict[str, dict] = {}

    def install(*, thesis_id: str | None = None) -> str:
        tid = thesis_id or "a" * 32
        theses[tid] = {
            "id": tid,
            "subject_type": "stock",
            "subject_id": "600519",
            "market": None,
            "title": "test thesis",
            "summary": "summary",
            "status": "active",
            "core_claims": [],
            "catalysts": [],
            "risks": [],
            "invalidation_conditions": [],
            "created_at": "2026-01-01T00:00:00",
            "updated_at": "2026-01-01T00:00:00",
            "current_revision": 3,
        }
        return tid

    def fake_get_thesis(db_path_arg, thesis_id):
        return theses.get(thesis_id)

    monkeypatch.setattr(
        campaign_service.evidence_thesis_service, "get_thesis", fake_get_thesis
    )
    monkeypatch.setattr(
        campaign_service.evidence_thesis_service,
        "resolve_db_path",
        lambda: tmp_path / "evidence_thesis.db",
    )
    return SimpleNamespace(install=install, theses=theses)


def _openapi_paths(client: TestClient) -> dict:
    """app.openapi() 会展开惰性 _IncludedRouter，得到真实 paths 表。"""
    schema = client.app.openapi()
    return schema["paths"]


class TestAccountRealityWiring:
    def test_account_reality_endpoint_available(self, client):
        response = client.get("/api/account/reality")
        assert response.status_code == 200
        body = response.json()
        assert body["data"]["canonical"] is False
        assert "settled_nav" in body["data"]


class TestCashEventWiring:
    def test_create_and_list_and_get_through_main_app(self, client):
        created = client.post(
            "/api/account/cash-events",
            json={"event_type": "CASH_DEPOSIT", "amount": 1000.0},
        )
        assert created.status_code == 200
        event = created.json()["data"]
        assert event["event_type"] == "CASH_DEPOSIT"

        listed = client.get("/api/account/cash-events")
        assert listed.status_code == 200
        assert [e["event_id"] for e in listed.json()["data"]] == [event["event_id"]]

        fetched = client.get(f"/api/account/cash-events/{event['event_id']}")
        assert fetched.status_code == 200
        assert fetched.json()["data"]["amount"] == 1000.0

    def test_correction_endpoint_through_main_app(self, client):
        created = client.post(
            "/api/account/cash-events",
            json={"event_type": "CASH_DEPOSIT", "amount": 100.0},
        )
        event_id = created.json()["data"]["event_id"]
        corrected = client.post(
            f"/api/account/cash-events/{event_id}/corrections",
            json={"amount": 120.0, "reason": "复核后修正"},
        )
        assert corrected.status_code == 201
        correction = corrected.json()["data"]
        assert correction["status"] == "CORRECTION_RECORDED"

    def test_invalid_reason_still_422_through_main_app(self, client):
        created = client.post(
            "/api/account/cash-events",
            json={"event_type": "CASH_DEPOSIT", "amount": 100.0},
        )
        event_id = created.json()["data"]["event_id"]
        response = client.post(
            f"/api/account/cash-events/{event_id}/corrections",
            json={"amount": 120.0, "reason": 123},
        )
        assert response.status_code == 422

    def test_unknown_event_type_422_through_main_app(self, client):
        response = client.post(
            "/api/account/cash-events",
            json={"event_type": "BOGUS", "amount": 100.0},
        )
        assert response.status_code == 422


class TestCampaignWiring:
    def test_create_and_list_and_get_through_main_app(self, client):
        created = client.post(
            "/api/campaigns",
            json={"security_code": "600519", "strategy": "SWING"},
        )
        assert created.status_code == 201
        campaign = created.json()["data"]
        assert campaign["status"] == "DRAFT"

        listed = client.get("/api/campaigns")
        assert listed.status_code == 200
        data = listed.json()["data"]
        items = data["items"] if isinstance(data, dict) else data
        assert [c["campaign_id"] for c in items] == [campaign["campaign_id"]]

        fetched = client.get(f"/api/campaigns/{campaign['campaign_id']}")
        assert fetched.status_code == 200
        assert fetched.json()["data"]["strategy"] == "SWING"

    def test_transitions_endpoints_through_main_app(self, client):
        created = client.post(
            "/api/campaigns",
            json={"security_code": "600519", "strategy": "SWING"},
        ).json()["data"]
        cid = created["campaign_id"]
        transitioned = client.post(
            f"/api/campaigns/{cid}/transitions",
            json={"expected_status": "DRAFT", "to_status": "RESEARCHING"},
        )
        assert transitioned.status_code == 200
        history = client.get(f"/api/campaigns/{cid}/transitions")
        assert history.status_code == 200
        data = history.json()["data"]
        items = data["items"] if isinstance(data, dict) else data
        assert items

    def test_thesis_binding_endpoints_through_main_app(self, client, fake_evidence_thesis):
        fake_evidence_thesis.install(thesis_id="a" * 32)
        created = client.post(
            "/api/campaigns",
            json={"security_code": "600519", "strategy": "SWING"},
        ).json()["data"]
        cid = created["campaign_id"]
        bound = client.post(
            f"/api/campaigns/{cid}/thesis-binding",
            json={"thesis_id": "a" * 32},
        )
        assert bound.status_code == 201
        fetched = client.get(f"/api/campaigns/{cid}/thesis-binding")
        assert fetched.status_code == 200
        assert fetched.json()["data"]["thesis_id"] == "a" * 32

    def test_invalid_strategy_422_through_main_app(self, client):
        response = client.post(
            "/api/campaigns",
            json={"security_code": "600519", "strategy": "BOGUS"},
        )
        assert response.status_code == 422


class TestMainAppRouteUniqueness:
    TARGET_PATHS = {
        "/api/account/reality",
        "/api/account/cash-events",
        "/api/account/cash-events/{event_id}",
        "/api/account/cash-events/{event_id}/corrections",
        "/api/campaigns",
        "/api/campaigns/{campaign_id}",
        "/api/campaigns/{campaign_id}/transitions",
        "/api/campaigns/{campaign_id}/thesis-binding",
    }

    def test_related_routes_present_and_unique_in_openapi(self, client):
        paths = _openapi_paths(client)
        for target in self.TARGET_PATHS:
            assert target in paths, f"missing route in main app OpenAPI: {target}"
        # OpenAPI 中每个路径只出现一次（无重复注册）
        for target in self.TARGET_PATHS:
            assert len([p for p in paths if p == target]) == 1

    def test_related_routes_not_defined_inline_elsewhere(self, client):
        paths = _openapi_paths(client)
        # cash/campaign 路由必须来自独立 router（非 app.py 内联重复定义）
        assert paths["/api/campaigns"]["post"]["operationId"] != "/api/campaigns"
