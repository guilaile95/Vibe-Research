"""P0-DI2A holdings-to-Campaign composition HTTP contract.

The router is tested on an isolated FastAPI application and its composition
entrypoint is always replaced.  No production ledger, Campaign database, or
other user data authority is read by this module.
"""
from __future__ import annotations

from copy import deepcopy

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import account_event_store
import campaign_service
import holdings_campaign_composition as composition
import holdings_campaign_composition_router as composition_router
import position_reality_service
import trade_ledger_store


PATH = "/api/holdings/campaign-composition"
POSITION_UNAVAILABLE = "持仓事实不可用，无法生成持仓-Campaign 组成"
ACCOUNT_CORRUPTED = "账户事件数据损坏，已停止读写"
TRADE_CORRUPTED = "交易流水数据损坏，已停止读写"
CAMPAIGN_UNAVAILABLE = "Campaign 服务暂不可用"
COMPOSITION_UNAVAILABLE = "持仓-Campaign 组成暂不可用"
INVALID_QUERY = "持仓-Campaign 组成查询参数无效"


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(composition_router.router)
    return app


@pytest.fixture
def client() -> TestClient:
    # raise_server_exceptions=False proves unexpected errors are translated at
    # the HTTP boundary rather than escaping into the process.
    return TestClient(_make_app(), raise_server_exceptions=False)


@pytest.fixture
def evaluated_payload() -> dict:
    return {
        "schema_version": "holdings-campaign-composition.v0.1",
        "evaluation_status": "EVALUATED",
        "canonical": True,
        "reason_codes": [],
        "items": [
            {
                "item_kind": "HOLDING_COMPOSITION",
                "security_code": "600519",
                "security_name": "贵州茅台",
                "holding": {
                    "status": "OPEN",
                    "shares": 100,
                    "cost_basis": 150000.0,
                    "avg_cost": 1500.0,
                    "cost_known": True,
                    "origin": "PRE_VIBE",
                },
                "composition_status": "UNASSIGNED_HOLDING",
                "campaigns": [],
                "allocation_status": "NOT_APPLICABLE",
            }
        ],
        "total_holdings": 1,
    }


def _install_result(monkeypatch, payload: dict):
    calls: list[tuple[tuple, dict]] = []

    def fake_assemble(*args, **kwargs):
        calls.append((args, kwargs))
        return deepcopy(payload)

    monkeypatch.setattr(
        composition_router.service,
        "assemble_holdings_campaign_composition",
        fake_assemble,
    )
    return calls


def _install_error(monkeypatch, error: Exception) -> None:
    def fail_closed(*args, **kwargs):
        raise error

    monkeypatch.setattr(
        composition_router.service,
        "assemble_holdings_campaign_composition",
        fail_closed,
    )


def test_get_returns_exact_data_envelope(
    client, monkeypatch, evaluated_payload
):
    calls = _install_result(monkeypatch, evaluated_payload)

    response = client.get(PATH)

    assert response.status_code == 200
    assert response.json() == {"data": evaluated_payload}
    assert calls == [((), {})]


def test_noncanonical_is_200_not_evaluated_without_fake_items(
    client, monkeypatch
):
    not_evaluated = {
        "schema_version": "holdings-campaign-composition.v0.1",
        "evaluation_status": "NOT_EVALUATED",
        "canonical": False,
        "reason_codes": ["POSITION_LEDGER_NOT_BOOTSTRAPPED"],
        "items": [],
        "total_holdings": 0,
    }
    calls = _install_result(monkeypatch, not_evaluated)

    response = client.get(PATH)

    assert response.status_code == 200
    assert response.json() == {"data": not_evaluated}
    assert calls == [((), {})]


@pytest.mark.parametrize(
    ("error", "safe_detail"),
    [
        (
            position_reality_service.PositionDerivationError(
                "C:\\Users\\private\\trade_ledger.sqlite3 SELECT secret"
            ),
            POSITION_UNAVAILABLE,
        ),
        (
            composition.HoldingsCampaignCompositionIntegrityError(
                "invalid internal position payload token=secret"
            ),
            POSITION_UNAVAILABLE,
        ),
        (
            account_event_store.AccountEventCorruptedError(),
            ACCOUNT_CORRUPTED,
        ),
        (
            trade_ledger_store.TradeLedgerCorruptedError(),
            TRADE_CORRUPTED,
        ),
        (
            campaign_service.CampaignServiceError(
                "SELECT * FROM campaigns WHERE token='secret'"
            ),
            CAMPAIGN_UNAVAILABLE,
        ),
    ],
)
def test_typed_errors_are_fixed_sanitized_500(
    client, monkeypatch, error, safe_detail
):
    _install_error(monkeypatch, error)

    response = client.get(PATH)

    assert response.status_code == 500
    assert response.json() == {"detail": safe_detail}
    body = response.text
    for leaked in (
        "private",
        "sqlite3",
        "SELECT",
        "secret",
        "token=",
        "Traceback",
        type(error).__name__,
    ):
        assert leaked not in body


def test_unexpected_error_is_fixed_sanitized_500(client, monkeypatch):
    _install_error(
        monkeypatch,
        RuntimeError(
            "ProxyError https://provider.invalid/token=secret "
            "C:\\Users\\private\\lake.sqlite3"
        ),
    )

    response = client.get(PATH)

    assert response.status_code == 500
    assert response.json() == {"detail": COMPOSITION_UNAVAILABLE}
    for leaked in (
        "ProxyError",
        "provider.invalid",
        "token=secret",
        "Users",
        "sqlite3",
        "Traceback",
    ):
        assert leaked not in response.text


@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
def test_endpoint_exposes_no_write_route(client, method):
    response = client.request(method.upper(), PATH, json={})
    assert response.status_code == 405


def test_openapi_exposes_exactly_get_for_path(client):
    operation = client.app.openapi()["paths"][PATH]
    assert set(operation) == {"get"}


def test_unknown_query_parameter_is_fixed_422_without_service_call(
    client, monkeypatch, evaluated_payload
):
    calls = _install_result(monkeypatch, evaluated_payload)

    response = client.get(PATH, params={"limit": "10"})

    assert response.status_code == 422
    assert response.json() == {"detail": INVALID_QUERY}
    assert calls == []
