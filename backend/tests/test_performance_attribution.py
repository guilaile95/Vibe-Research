"""Tests for performance attribution store/service/API (P2-4B)."""
from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import performance_attribution_router
import performance_attribution_service as svc
import performance_attribution_store as store
import trade_ledger_store as tl_store


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _trade(
    *,
    code: str = "000001",
    name: str = "平安银行",
    operation: str = "buy",
    price: float = 10.0,
    quantity: int = 1000,
    fee: float = 5.0,
    other_cost: float = 0.0,
    executed_at: str = "2026-01-05T02:00:00+00:00",
    execution_status: str = "full",
) -> dict:
    return {
        "trade_id": f"tr_{uuid.uuid4().hex}",
        "code": code,
        "name": name,
        "operation": operation,
        "execution_status": execution_status,
        "planned_price": price,
        "planned_quantity": quantity,
        "actual_price": price,
        "actual_quantity": quantity,
        "executed_at": executed_at,
        "fee": fee,
        "other_cost": other_cost,
        "created_at": executed_at,
    }


@pytest.fixture()
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    trade_db = tmp_path / "trade_ledger.sqlite3"
    attr_db = tmp_path / "performance_attribution.sqlite3"
    monkeypatch.setenv("VIBE_RESEARCH_TRADE_LEDGER_DB", str(trade_db))
    monkeypatch.setenv("VIBE_RESEARCH_PERFORMANCE_ATTRIBUTION_DB", str(attr_db))
    return {"trade_db": trade_db, "attr_db": attr_db}


def _insert(env, *records: dict) -> None:
    for rec in records:
        tl_store.insert_record(env["trade_db"], rec)


def _void(env, trade_id: str) -> None:
    tl_store.void_record_atomic(env["trade_db"], trade_id, "test")


def _by_code(result: dict, code: str) -> dict:
    for pos in result["positions"]:
        if pos["code"] == code:
            return pos
    raise AssertionError(f"position {code} not found")


def make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(performance_attribution_router.router)
    return app


# ---------------------------------------------------------------------------
# Service: computation
# ---------------------------------------------------------------------------

def test_empty_db_returns_empty_result(env):
    result = svc.compute_attribution()
    assert result["positions"] == []
    assert result["totals"] == {
        "total_realized_pnl": 0.0,
        "total_unrealized_pnl": None,
        "total_fees": 0.0,
        "total_cost_basis": 0.0,
        "position_count": 0,
    }


def test_single_buy_cost_includes_fee(env):
    _insert(env, _trade(price=10.0, quantity=1000, fee=5.0, other_cost=1.0))
    pos = _by_code(svc.compute_attribution(), "000001")
    assert pos["remaining_quantity"] == 1000
    assert pos["cost_basis"] == 10006.0
    assert pos["realized_pnl"] == 0.0
    assert pos["closed_quantity"] == 0
    assert pos["total_fees"] == 6.0
    assert pos["avg_cost"] == 10.01


def test_buy_then_full_sell_realized_pnl(env):
    _insert(
        env,
        _trade(price=10.0, quantity=1000, fee=5.0, executed_at="2026-01-05T02:00:00+00:00"),
        _trade(
            operation="sell",
            price=12.0,
            quantity=1000,
            fee=6.0,
            executed_at="2026-01-06T02:00:00+00:00",
        ),
    )
    pos = _by_code(svc.compute_attribution(), "000001")
    # cost 10005, proceeds 12000-6=11994 -> 1989
    assert pos["realized_pnl"] == 1989.0
    assert pos["remaining_quantity"] == 0
    assert pos["cost_basis"] == 0.0
    assert pos["avg_cost"] is None
    assert pos["closed_quantity"] == 1000


def test_weighted_average_cost_after_add_and_partial_sell(env):
    _insert(
        env,
        _trade(price=10.0, quantity=1000, fee=0.0, executed_at="2026-01-05T02:00:00+00:00"),
        _trade(
            operation="add",
            price=12.0,
            quantity=1000,
            fee=0.0,
            executed_at="2026-01-06T02:00:00+00:00",
        ),
        _trade(
            operation="reduce",
            price=15.0,
            quantity=500,
            fee=0.0,
            executed_at="2026-01-07T02:00:00+00:00",
        ),
    )
    pos = _by_code(svc.compute_attribution(), "000001")
    # avg cost 11.0; sell 500 @15 -> realized 2000; remaining 1500 cost 16500
    assert pos["avg_cost"] == 11.0
    assert pos["realized_pnl"] == 2000.0
    assert pos["remaining_quantity"] == 1500
    assert pos["cost_basis"] == 16500.0


def test_oversell_limits_to_available_quantity(env):
    _insert(
        env,
        _trade(price=10.0, quantity=500, fee=0.0, executed_at="2026-01-05T02:00:00+00:00"),
        _trade(
            operation="sell",
            price=12.0,
            quantity=800,
            fee=0.0,
            executed_at="2026-01-06T02:00:00+00:00",
        ),
    )
    pos = _by_code(svc.compute_attribution(), "000001")
    assert svc.OVERSELL_LIMITATION in pos["data_limitations"]
    assert pos["closed_quantity"] == 500
    assert pos["realized_pnl"] == 1000.0
    assert pos["remaining_quantity"] == 0


def test_sell_without_position_produces_limitation_only(env):
    _insert(
        env,
        _trade(
            operation="sell",
            price=12.0,
            quantity=500,
            fee=0.0,
            executed_at="2026-01-06T02:00:00+00:00",
        ),
    )
    pos = _by_code(svc.compute_attribution(), "000001")
    assert svc.NO_POSITION_LIMITATION in pos["data_limitations"]
    assert pos["realized_pnl"] == 0.0
    assert pos["closed_quantity"] == 0


def test_voided_records_excluded(env):
    rec = _trade(price=10.0, quantity=1000, fee=0.0)
    _insert(env, rec)
    _void(env, rec["trade_id"])
    assert svc.compute_attribution()["positions"] == []


def test_not_executed_records_excluded(env):
    rec = _trade(execution_status="not_executed", quantity=0)
    rec["actual_quantity"] = 0
    _insert(env, rec)
    assert svc.compute_attribution()["positions"] == []


def test_unrealized_pnl_with_price_map(env):
    _insert(env, _trade(price=10.0, quantity=1000, fee=0.0))
    result = svc.compute_attribution(price_map={"000001": 11.5})
    pos = _by_code(result, "000001")
    assert pos["unrealized_pnl"] == 1500.0
    assert result["totals"]["total_unrealized_pnl"] == 1500.0
    assert svc.NO_PRICE_LIMITATION not in result["data_limitations"]


def test_unrealized_none_without_price_map(env):
    _insert(env, _trade(price=10.0, quantity=1000, fee=0.0))
    result = svc.compute_attribution()
    assert _by_code(result, "000001")["unrealized_pnl"] is None
    assert result["totals"]["total_unrealized_pnl"] is None
    assert svc.NO_PRICE_LIMITATION in result["data_limitations"]


def test_date_range_filter(env):
    _insert(
        env,
        _trade(code="000001", price=10.0, quantity=1000, fee=0.0,
               executed_at="2026-01-05T02:00:00+00:00"),
        _trade(code="000002", name="万科A", price=20.0, quantity=500, fee=0.0,
               executed_at="2026-02-10T02:00:00+00:00"),
    )
    result = svc.compute_attribution(date_from="2026-02-01", date_to="2026-02-28")
    assert [p["code"] for p in result["positions"]] == ["000002"]
    assert result["date_from"] == "2026-02-01"
    assert result["date_to"] == "2026-02-28"


def test_invalid_date_raises_value_error(env):
    with pytest.raises(ValueError):
        svc.compute_attribution(date_from="2026/01/01")
    with pytest.raises(ValueError):
        svc.compute_attribution(date_to="20260101")


def test_positions_sorted_by_realized_pnl_desc(env):
    _insert(
        env,
        _trade(code="000001", price=10.0, quantity=100, fee=0.0,
               executed_at="2026-01-05T02:00:00+00:00"),
        _trade(code="000001", operation="sell", price=11.0, quantity=100, fee=0.0,
               executed_at="2026-01-06T02:00:00+00:00"),
        _trade(code="000002", name="万科A", price=10.0, quantity=100, fee=0.0,
               executed_at="2026-01-05T03:00:00+00:00"),
        _trade(code="000002", name="万科A", operation="sell", price=20.0, quantity=100,
               fee=0.0, executed_at="2026-01-06T03:00:00+00:00"),
    )
    result = svc.compute_attribution()
    assert [p["code"] for p in result["positions"]] == ["000002", "000001"]


# ---------------------------------------------------------------------------
# Service: snapshot persistence
# ---------------------------------------------------------------------------

def test_save_and_get_snapshot_roundtrip(env):
    _insert(env, _trade(price=10.0, quantity=1000, fee=5.0))
    result = svc.compute_attribution(price_map={"000001": 11.0})
    snapshot = svc.save_attribution_snapshot(result)
    assert snapshot["snapshot_id"].startswith("attr_")

    fetched = svc.get_attribution_snapshot(snapshot["snapshot_id"])
    assert fetched is not None
    assert fetched["snapshot"]["snapshot_id"] == snapshot["snapshot_id"]
    assert len(fetched["positions"]) == 1
    assert fetched["positions"][0]["code"] == "000001"
    assert fetched["snapshot"]["payload"]["totals"]["position_count"] == 1


def test_get_missing_snapshot_returns_none(env):
    assert svc.get_attribution_snapshot("attr_missing") is None


def test_list_snapshots_pagination(env):
    _insert(env, _trade(price=10.0, quantity=1000, fee=0.0))
    result = svc.compute_attribution()
    ids = [svc.save_attribution_snapshot(result)["snapshot_id"] for _ in range(3)]
    assert len(ids) == 3

    page1 = svc.list_attribution_snapshots(limit=2)
    page2 = svc.list_attribution_snapshots(limit=2, offset=2)
    assert len(page1) == 2
    assert len(page2) == 1
    assert "payload_json" not in page1[0]
    all_ids = {r["snapshot_id"] for r in page1 + page2}
    assert all_ids == set(ids)


def test_store_reads_on_missing_db_are_empty(env):
    assert store.get_snapshot(env["attr_db"], "attr_x") is None
    assert store.list_snapshots(env["attr_db"]) == []


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

def test_api_get_attribution_200(env):
    _insert(env, _trade(price=10.0, quantity=1000, fee=0.0))
    client = TestClient(make_app())
    resp = client.get("/api/performance-attribution")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["totals"]["position_count"] == 1


def test_api_post_snapshot_200(env):
    _insert(env, _trade(price=10.0, quantity=1000, fee=0.0))
    client = TestClient(make_app())
    resp = client.post(
        "/api/performance-attribution/snapshot",
        json={"price_map": {"000001": 12.0}},
    )
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["snapshot"]["snapshot_id"].startswith("attr_")
    assert body["attribution"]["totals"]["total_unrealized_pnl"] == 2000.0


def test_api_list_snapshots_200(env):
    _insert(env, _trade(price=10.0, quantity=1000, fee=0.0))
    client = TestClient(make_app())
    client.post("/api/performance-attribution/snapshot", json={})
    resp = client.get("/api/performance-attribution/snapshots", params={"limit": 10})
    assert resp.status_code == 200
    assert len(resp.json()["data"]["items"]) == 1


def test_api_get_snapshot_404(env):
    client = TestClient(make_app())
    resp = client.get("/api/performance-attribution/snapshots/attr_nope")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "收益归因快照不存在"


def test_api_invalid_date_from_422(env):
    client = TestClient(make_app())
    resp = client.get("/api/performance-attribution", params={"date_from": "2026-1-1"})
    assert resp.status_code == 422


def test_api_invalid_price_map_422(env):
    client = TestClient(make_app())
    bad_code = client.post(
        "/api/performance-attribution/snapshot", json={"price_map": {"abc": 10.0}}
    )
    assert bad_code.status_code == 422
    bad_price = client.post(
        "/api/performance-attribution/snapshot", json={"price_map": {"000001": -1.0}}
    )
    assert bad_price.status_code == 422


def test_api_extra_field_rejected(env):
    client = TestClient(make_app())
    resp = client.post("/api/performance-attribution/snapshot", json={"foo": 1})
    assert resp.status_code == 422
