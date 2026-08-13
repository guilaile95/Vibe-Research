"""P0-DI2 — Decision Inbox runtime HTTP contract tests.

独立 FastAPI 实例 + monkeypatch service；不访问真实数据库、不产生写入。
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import account_event_store
import campaign_service
import decision_inbox_runtime_assembler as service
import decision_inbox_runtime_router as router_module
import holdings_campaign_composition as composition
import position_reality_service
import trade_ledger_store


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(router_module.router)
    return app


@pytest.fixture
def client() -> TestClient:
    return TestClient(_app())


_EXPECTED = {
    "schema_version": "decision_inbox_runtime.v0.1",
    "as_of": "2026-08-13T04:00:00.000000Z",
    "evaluation_status": "EVALUATED",
    "canonical": True,
    "reason_codes": [],
    "holding_setup_items": [],
    "campaign_items": [],
    "total_holdings": 0,
    "total_campaign_items": 0,
}


def test_get_returns_exact_data_envelope(client, monkeypatch):
    monkeypatch.setattr(
        service, "assemble_current_decision_inbox", lambda: _EXPECTED
    )
    response = client.get("/api/decision-inbox")
    assert response.status_code == 200
    assert response.json() == {"data": _EXPECTED}


def test_noncanonical_is_200_not_evaluated_without_fake_rows(
    client, monkeypatch
):
    payload = {
        **_EXPECTED,
        "evaluation_status": "NOT_EVALUATED",
        "canonical": False,
        "reason_codes": ["POSITION_LEDGER_NOT_BOOTSTRAPPED"],
    }
    monkeypatch.setattr(
        service, "assemble_current_decision_inbox", lambda: payload
    )
    response = client.get("/api/decision-inbox")
    assert response.status_code == 200
    body = response.json()["data"]
    assert body["evaluation_status"] == "NOT_EVALUATED"
    assert body["holding_setup_items"] == []
    assert body["campaign_items"] == []


@pytest.mark.parametrize(
    "exc_factory",
    [
        lambda: composition.HoldingsCampaignCompositionError("x"),
        lambda: position_reality_service.PositionDerivationError("x"),
        lambda: account_event_store.AccountEventCorruptedError(),
        lambda: trade_ledger_store.TradeLedgerCorruptedError(),
        lambda: campaign_service.CampaignServiceError("x"),
        lambda: service.DecisionInboxRuntimeIntegrityError("x"),
    ],
)
def test_typed_errors_are_fixed_sanitized_500(
    client, monkeypatch, exc_factory
):
    def broken():
        raise exc_factory()

    monkeypatch.setattr(service, "assemble_current_decision_inbox", broken)
    response = client.get("/api/decision-inbox")
    assert response.status_code == 500
    assert response.json() == {"detail": response.json()["detail"]}
    assert response.json()["detail"] not in ("x",)


def test_unexpected_error_is_fixed_sanitized_500(client, monkeypatch):
    def broken():
        raise RuntimeError("secret-detail")

    monkeypatch.setattr(service, "assemble_current_decision_inbox", broken)
    response = client.get("/api/decision-inbox")
    assert response.status_code == 500
    assert response.json() == {"detail": "Decision Inbox 暂不可用"}


@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
def test_endpoint_exposes_no_write_route(client, method):
    response = client.request(method.upper(), "/api/decision-inbox", json={})
    assert response.status_code == 405


def test_openapi_exposes_exactly_get_for_path(client):
    paths = client.get("/openapi.json").json()["paths"]
    assert "/api/decision-inbox" in paths
    assert set(paths["/api/decision-inbox"]) == {"get"}


def test_unknown_query_parameter_is_fixed_422_without_service_call(
    client, monkeypatch
):
    calls = []
    monkeypatch.setattr(
        service,
        "assemble_current_decision_inbox",
        lambda: calls.append(True) or _EXPECTED,
    )
    response = client.get("/api/decision-inbox?as_of=2026-08-01")
    assert response.status_code == 422
    assert response.json() == {"detail": "Decision Inbox 查询参数无效"}
    assert calls == []


def test_route_returns_no_write_side_effect(client, monkeypatch):
    monkeypatch.setattr(
        service, "assemble_current_decision_inbox", lambda: _EXPECTED
    )
    assert client.get("/api/decision-inbox").status_code == 200
    assert client.get("/api/decision-inbox").json() == {"data": _EXPECTED}
