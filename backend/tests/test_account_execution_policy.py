"""Unit tests for account execution policy service and REST router (P2-3)."""

from __future__ import annotations

import json

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
    assert _svc.get_account_execution_policy_status(db_file=db_file) == {
        "status": "default",
        "data": _svc.DEFAULT_POLICY,
        "reason_code": None,
    }


def test_corrupted_policy_is_explicit_and_read_only(tmp_path):
    db_file = tmp_path / "account_execution_policy.json"
    original = b"{broken"
    db_file.write_bytes(original)

    status = _svc.get_account_execution_policy_status(db_file=db_file)

    assert status == {
        "status": "corrupted",
        "data": None,
        "reason_code": _svc.ACCOUNT_EXECUTION_POLICY_CORRUPTED_REASON,
    }
    with pytest.raises(_svc.AccountExecutionPolicyCorruptedError):
        _svc.get_account_execution_policy(db_file=db_file)
    assert db_file.read_bytes() == original
    assert not list(tmp_path.glob("*.tmp"))


def test_save_explicitly_recovers_corrupted_policy(tmp_path):
    db_file = tmp_path / "account_execution_policy.json"
    db_file.write_text("{broken", encoding="utf-8")

    saved = _svc.save_account_execution_policy(VALID_POLICY, db_file=db_file)

    assert _svc.get_account_execution_policy_status(db_file=db_file) == {
        "status": "configured",
        "data": saved,
        "reason_code": None,
    }
    assert json.loads(db_file.read_text(encoding="utf-8")) == saved


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
    assert body["status"] == "default"
    assert body["reason_code"] is None
    assert body["data"] == VALID_POLICY


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
    assert body["status"] == "configured"
    assert body["reason_code"] is None
    assert body["data"]["lot_size"] == 50
    assert body["data"]["tie_breaker_order"] == "code_desc"
    assert body["data"]["allow_partial_execution"] is False


def test_api_put_policy_invalid(tmp_path, monkeypatch):
    monkeypatch.setenv("VR_DATA_DIR", str(tmp_path))
    client = TestClient(make_app())
    payload = dict(VALID_POLICY, lot_size=0)
    resp = client.put("/api/account-execution-policy", json=payload)
    assert resp.status_code == 400
