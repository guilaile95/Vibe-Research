from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import app as app_module
import sector_market_context as context


def _history(count: int = 90) -> list[dict]:
    return [
        {"date": f"2026-01-{index + 1:02d}", "date_ms": index, "close": 100.0 + index, "turnover": 1000.0 + index}
        for index in range(count)
    ]


def _observation(
    thscode: str,
    *,
    constituents: list[dict] | None = None,
    snapshots: list[dict] | None = None,
) -> dict:
    return {
        "thscode": thscode,
        "history": _history(),
        "constituents_as_of_ms": 1787542767000 if constituents is not None else None,
        "constituents": constituents,
        "constituent_snapshot_as_of_ms": 1787542768000 if snapshots is not None else None,
        "constituent_snapshots": snapshots,
    }


def test_history_metrics_keep_windows_and_formula_explicit():
    metrics = context._history_metrics(_history(61))
    assert metrics["return_5d_pct"] == pytest.approx((160 / 155 - 1) * 100, abs=1e-4)
    assert metrics["return_20d_pct"] == pytest.approx((160 / 140 - 1) * 100, abs=1e-4)
    assert metrics["return_60d_pct"] == 60.0
    expected_delta = ((160 / 155 - 1) - (155 / 150 - 1)) * 100
    assert metrics["return_5d_delta_vs_previous_5d_pct"] == pytest.approx(expected_delta, abs=1e-4)
    short = context._history_metrics(_history(20))
    assert short["return_5d_pct"] is not None
    assert short["return_20d_pct"] is None
    assert short["return_60d_pct"] is None


def test_current_breadth_is_current_constituent_intersection_and_preserves_missing():
    breadth = context._current_breadth(
        [
            {"ticker": "000001", "name": "甲"},
            {"ticker": "000002", "name": "乙"},
            {"ticker": "000003", "name": "丙"},
        ],
        {
            "000001": {"change_pct": 2.0},
            "000002": {"change_pct": -1.0},
            "000003": {"change_pct": None},
        },
    )
    assert breadth["constituents_total"] == 3
    assert breadth["snapshot_valid_count"] == 2
    assert breadth["up_count"] == breadth["down_count"] == 1
    assert breadth["up_ratio"] == 0.5
    assert breadth["equal_weight_change_pct"] == 0.5
    assert breadth["constituents_sample"][2]["change_pct"] is None
    assert breadth["constituent_semantics"] == "CURRENT_CONSTITUENTS_ONLY"


def test_unmapped_detail_is_unavailable_without_provider_calls():
    def forbidden(*_args, **_kwargs):
        raise AssertionError("provider must not be called for an unmapped sector")

    result = context.build_sector_market_context(
        sector_key="ai-computing", index_reader=forbidden
    )
    assert result["status"] == "unavailable"
    assert result["items"][0]["mapping_status"] == "unavailable"
    assert result["items"][0]["metrics"] is None


def test_mapped_detail_adds_current_breadth_without_historical_backfill():
    members = [
        {"thscode": "002463.SZ", "ticker": "002463", "name": "沪电股份"},
        {"thscode": "002916.SZ", "ticker": "002916", "name": "深南电路"},
    ]
    result = context.build_sector_market_context(
        sector_key="pcb",
        index_reader=lambda thscode: _observation(
            thscode,
            constituents=members,
            snapshots=[
                {"ticker": "002463", "change_pct": 1.2},
                {"ticker": "002916", "change_pct": -0.2},
            ],
        ),
    )
    item = result["items"][0]
    assert item["index"] == {"thscode": "884092.TI", "name": "印制电路板", "kind": "industry"}
    assert item["status"] == "normal"
    assert item["breadth"]["equal_weight_change_pct"] == 0.5
    assert item["breadth"]["constituent_semantics"] == "CURRENT_CONSTITUENTS_ONLY"
    assert item["rank_20d_within_mapped"] is None


def test_overview_isolates_one_index_failure_and_ranks_only_mapped_universe():
    def read_index(thscode: str):
        if thscode == "886033.TI":
            raise RuntimeError("controlled failure")
        return _observation(thscode)

    result = context.build_sector_market_context(index_reader=read_index)
    by_key = {item["sector_key"]: item for item in result["items"]}
    assert result["status"] == "partial"
    assert by_key["cpo"]["status"] == "unavailable"
    assert by_key["ai-computing"]["mapping_status"] == "unavailable"
    assert by_key["pcb"]["rank_20d_within_mapped"] is not None
    assert by_key["pcb"]["rank_universe_count"] == len(context.THS_INDEX_BY_SECTOR) - 1


def test_market_context_api_wraps_data_and_validates_sector_key(monkeypatch):
    app_module._DC_CACHE._data.clear()
    payload = {"schema_version": "sector_market_context.v0.1", "status": "normal", "items": []}
    monkeypatch.setattr(app_module.smc, "build_sector_market_context", lambda **_kwargs: payload)
    client = TestClient(app_module.app)
    assert client.get("/api/sector-research/market-context?sector_key=pcb").json() == {"data": payload}

    app_module._DC_CACHE._data.clear()
    def invalid(**_kwargs):
        raise ValueError("未注册的板块：missing")
    monkeypatch.setattr(app_module.smc, "build_sector_market_context", invalid)
    response = client.get("/api/sector-research/market-context?sector_key=missing")
    assert response.status_code == 404
