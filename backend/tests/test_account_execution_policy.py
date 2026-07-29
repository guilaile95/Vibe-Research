"""Unit tests for account execution policy service and REST router (P2-3)."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import account_execution_policy as _svc
import account_execution_policy_router


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(account_execution_policy_router.router)
    return app


VALID_POLICY = {
    "lot_size": 100,
    "min_cash_reserve_pct": 0.10,
    "max_single_stock_allocation_pct": 0.30,
    "tie_breaker_order": "code_asc",
    "allow_partial_execution": True,
}


# ---------------------------------------------------------------------------
# Service-layer tests
# ---------------------------------------------------------------------------


def test_default_policy_returned_when_no_file(tmp_path):
    db_file = tmp_path / "account_execution_policy.json"
    result = _svc.get_account_execution_policy(db_file=db_file)
    assert result == _svc.DEFAULT_POLICY


def test_save_and_reload(tmp_path):
    db_file = tmp_path / "account_execution_policy.json"
    data = {
        "lot_size": 200,
        "min_cash_reserve_pct": 0.05,
        "max_single_stock_allocation_pct": 0.20,
        "tie_breaker_order": "proportional",
        "allow_partial_execution": False,
    }
    saved = _svc.save_account_execution_policy(data, db_file=db_file)
    assert db_file.exists()
    reloaded = _svc.get_account_execution_policy(db_file=db_file)
    assert reloaded == saved
    assert reloaded["lot_size"] == 200
    assert reloaded["tie_breaker_order"] == "proportional"


def test_validate_lot_size_zero_raises():
    bad = dict(VALID_POLICY, lot_size=0)
    with pytest.raises(ValueError, match="lot_size"):
        _svc.validate_policy_data(bad)


def test_validate_lot_size_negative_raises():
    bad = dict(VALID_POLICY, lot_size=-1)
    with pytest.raises(ValueError, match="lot_size"):
        _svc.validate_policy_data(bad)


def test_validate_reserve_pct_ge_1_raises():
    bad = dict(VALID_POLICY, min_cash_reserve_pct=1.0)
    with pytest.raises(ValueError, match="min_cash_reserve_pct"):
        _svc.validate_policy_data(bad)


def test_validate_reserve_pct_negative_raises():
    bad = dict(VALID_POLICY, min_cash_reserve_pct=-0.1)
    with pytest.raises(ValueError, match="min_cash_reserve_pct"):
        _svc.validate_policy_data(bad)


def test_validate_invalid_tie_breaker_raises():
    bad = dict(VALID_POLICY, tie_breaker_order="random")
    with pytest.raises(ValueError, match="tie_breaker_order"):
        _svc.validate_policy_data(bad)


def test_validate_single_cap_zero_raises():
    bad = dict(VALID_POLICY, max_single_stock_allocation_pct=0)
    with pytest.raises(ValueError, match="max_single_stock_allocation_pct"):
        _svc.validate_policy_data(bad)


# ---------------------------------------------------------------------------
# API tests (TestClient)
# ---------------------------------------------------------------------------


def test_api_get_policy(tmp_path, monkeypatch):
    monkeypatch.setenv("VR_DATA_DIR", str(tmp_path))
    client = TestClient(make_app())
    resp = client.get("/api/account-execution-policy")
    assert resp.status_code == 200
    body = resp.json()
    for key in VALID_POLICY:
        assert key in body


def test_api_put_policy_valid(tmp_path, monkeypatch):
    monkeypatch.setenv("VR_DATA_DIR", str(tmp_path))
    client = TestClient(make_app())
    payload = {
        "lot_size": 50,
        "min_cash_reserve_pct": 0.15,
        "max_single_stock_allocation_pct": 0.25,
        "tie_breaker_order": "code_desc",
        "allow_partial_execution": False,
    }
    resp = client.put("/api/account-execution-policy", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["lot_size"] == 50
    assert body["tie_breaker_order"] == "code_desc"
    assert body["allow_partial_execution"] is False


def test_api_put_policy_invalid(tmp_path, monkeypatch):
    monkeypatch.setenv("VR_DATA_DIR", str(tmp_path))
    client = TestClient(make_app())
    payload = dict(VALID_POLICY, lot_size=0)
    resp = client.put("/api/account-execution-policy", json=payload)
    assert resp.status_code == 400
