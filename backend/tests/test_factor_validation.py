from __future__ import annotations

import csv
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import factor_validation as fv
import factor_validation_router
import research_data_plane as rdp


def _write_series_fixture(
    tmp_path: Path,
    *,
    days: int = 100,
    future_values: dict[str, float] | None = None,
    short_code: bool = False,
) -> Path:
    source = tmp_path / "factor.csv"
    source.parent.mkdir(parents=True, exist_ok=True)
    codes = ["000001", "000002", "000003", "000004", "000005"]
    future_values = future_values or {}
    with source.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["code", "trade_date", "open", "high", "low", "close", "volume"])
        start = date(2026, 1, 1)
        for index in range(days):
            trade_date = (start + timedelta(days=index)).isoformat()
            for code_index, code in enumerate(codes):
                if short_code and code == "000005" and index > 10:
                    continue
                close = 100.0 + code_index * 10.0
                if index == 60:
                    close += code_index + 1
                if index >= 65:
                    close = future_values.get(code, close + (code_index + 1) * 2.0)
                writer.writerow([code, trade_date, close, close, close, close, 1000 + index])
    return source


def _import_fixture(tmp_path: Path, **kwargs) -> Path:
    root = tmp_path / "research_data_plane"
    rdp.import_csv(_write_series_fixture(tmp_path, **kwargs), root=root, imported_at="2026-09-11T00:00:00Z")
    return root


def _gap_close(code_index: int, day_index: int) -> float:
    return 100.0 + code_index * 10.0 + day_index * (code_index + 1)


def _import_exact_date_gap_fixture(tmp_path: Path) -> Path:
    source = tmp_path / "factor-gap.csv"
    with source.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["code", "trade_date", "open", "high", "low", "close", "volume"])
        start = date(2026, 1, 1)
        for day_index in range(40):
            trade_date = (start + timedelta(days=day_index)).isoformat()
            for code_index, code in enumerate(("000001", "000002", "000003")):
                if code == "000002" and day_index == 9:
                    continue
                close = _gap_close(code_index, day_index)
                writer.writerow([code, trade_date, close, close, close, close, 1000 + day_index])
    root = tmp_path / "research_data_plane"
    rdp.import_csv(source, root=root, imported_at="2026-09-11T00:00:00Z")
    return root


def test_spearman_average_rank_and_bucket_semantics_preserve_null_zero_and_ties():
    assert fv.spearman_average_rank([1, 2, 3], [10, 20, 30]) == (1.0, None)
    assert fv.spearman_average_rank([1, 2, 3], [30, 20, 10]) == (-1.0, None)
    tied, reason = fv.spearman_average_rank([1, 1, 3], [10, 20, 30])
    assert tied == pytest.approx(0.8660254)
    assert reason is None
    assert fv.spearman_average_rank([1, 1], [0, 10]) == (None, "CONSTANT_FACTOR")
    assert fv.spearman_average_rank([1, 2], [0, 0]) == (None, "CONSTANT_FORWARD_RETURN")
    assert fv.spearman_average_rank([0, 1], [0, 1]) == (1.0, None)

    high_count, high_mean, low_count, low_mean, spread, reason = fv._bucket_means(
        [1, 2, 3, 4, 5], [0.10, 0.20, 0.30, 0.40, 0.50]
    )
    assert (high_count, high_mean, low_count, low_mean, spread, reason) == (1, 0.5, 1, 0.1, 0.4, None)

    # Equal factor values at a boundary stay together; no random split.
    high_count, _, low_count, _, _, _ = fv._bucket_means(
        [1, 1, 2, 3, 4], [0.1, 0.2, 0.3, 0.4, 0.5]
    )
    assert high_count == 1
    assert low_count == 2
    assert fv._bucket_means([1], [0.1])[4] is None


def test_factor_registry_uses_each_existing_full_market_metric_and_keeps_zero_writes(tmp_path: Path):
    root = _import_fixture(tmp_path, short_code=True)
    as_of = "2026-03-20"
    before = sorted(str(path.relative_to(root)) for path in root.rglob("*"))
    full_market = rdp.query_full_market(root=root, as_of=as_of, latest=False, limit=1000)
    by_code = {row["code"]: row for row in full_market["rows"]}
    exact_date_count = sum(row["latest_date"] == as_of for row in full_market["rows"])

    assert {item["factor_id"] for item in fv.factor_registry()} == {
        "return_5d", "return_20d", "return_60d", "close_vs_ma20", "close_vs_ma60", "volume_ratio_20d",
    }
    for definition in fv.factor_registry():
        report = fv.evaluate_rdp(
            factor_id=definition["factor_id"],
            date_from=as_of,
            date_to=as_of,
            data_root=root,
        )
        observation = report["results"]["5"]["observations"][0]
        assert report["status"] == "normal"
        assert report["schema_version"] == fv.SCHEMA_VERSION
        assert report["factor"]["source_metric"] == definition["source_metric"]
        assert report["parity"]["status"] == "PROVEN"
        assert report["parity"]["mismatches"] == 0
        assert report["parity"]["factor_dates_checked"] == 1
        assert report["formal_state_write"]["performed"] is False
        assert by_code["000001"][definition["source_metric"]] is not None
        assert observation["source_asof_row_count"] == full_market["coverage"]["universe_count"]
        assert observation["exact_date_universe_count"] == exact_date_count
        assert observation["universe_count"] == exact_date_count
        assert observation["stale_source_row_count"] == (
            full_market["coverage"]["universe_count"] - exact_date_count
        )
    after = sorted(str(path.relative_to(root)) for path in root.rglob("*"))
    assert after == before


def test_factor_values_are_directly_reused_from_full_market_for_all_six_factors(
    tmp_path: Path, monkeypatch
):
    root = _import_fixture(tmp_path)
    as_of = "2026-03-20"
    original_query = rdp.query_full_market
    original_spearman = fv.spearman_average_rank
    captured: list[list[float]] = []
    active_metric: str | None = None

    def query_with_distinct_source_values(**kwargs):
        payload = original_query(**kwargs)
        if kwargs.get("as_of") != as_of or kwargs.get("latest") is not False or active_metric is None:
            return payload
        rows = []
        for index, row in enumerate(payload["rows"]):
            changed = dict(row)
            changed[active_metric] = 1000.0 + index
            rows.append(changed)
        return {**payload, "rows": rows}

    def capture_factor_values(factor_values, forward_returns):
        captured.append(list(factor_values))
        return original_spearman(factor_values, forward_returns)

    monkeypatch.setattr(rdp, "query_full_market", query_with_distinct_source_values)
    monkeypatch.setattr(fv, "spearman_average_rank", capture_factor_values)

    for definition in fv.factor_registry():
        active_metric = definition["source_metric"]
        captured.clear()
        report = fv.evaluate_rdp(
            factor_id=definition["factor_id"],
            date_from=as_of,
            date_to=as_of,
            data_root=root,
        )
        expected = [1000.0 + index for index in range(5)]
        assert captured[0] == expected
        assert captured[1] == expected
        assert report["parity"]["source_metric"] == definition["source_metric"]
        assert report["parity"]["mode"] == "DIRECT_SOURCE_METRIC_REUSE"


def test_factor_value_temporal_boundary_is_full_market_as_of_and_future_only(tmp_path: Path):
    root_a = _import_fixture(tmp_path / "a")
    report_a = fv.evaluate_rdp(
        factor_id="return_5d", date_from="2026-03-02", date_to="2026-03-02", data_root=root_a
    )
    observation_a = report_a["results"]["5"]["observations"][0]

    root_b = _import_fixture(
        tmp_path / "b",
        future_values={"000001": 180.0, "000002": 170.0, "000003": 160.0, "000004": 150.0, "000005": 140.0},
    )
    report_b = fv.evaluate_rdp(
        factor_id="return_5d", date_from="2026-03-02", date_to="2026-03-02", data_root=root_b
    )
    observation_b = report_b["results"]["5"]["observations"][0]

    assert observation_a["factor_date"] == observation_b["factor_date"] == "2026-03-02"
    assert report_a["parity"]["artifact_sha256"] != report_b["parity"]["artifact_sha256"]
    # The exact-as-of source values are unchanged; only the future outcome is allowed to move.
    assert observation_a["factor_non_null_count"] == observation_b["factor_non_null_count"]
    assert observation_a["pair_count"] == observation_b["pair_count"]
    assert observation_a["rank_ic"] != observation_b["rank_ic"]


def test_factor_date_cross_section_excludes_stale_rows_and_allows_t_plus_1_reentry(
    tmp_path: Path, monkeypatch
):
    root = _import_exact_date_gap_fixture(tmp_path)
    factor_date = "2026-01-10"
    resumed_date = "2026-01-11"
    source_at_factor_date = rdp.query_full_market(
        root=root, as_of=factor_date, latest=False, limit=1000
    )
    stale_row = next(row for row in source_at_factor_date["rows"] if row["code"] == "000002")
    assert stale_row["latest_date"] == "2026-01-09"

    captured: list[tuple[list[float], list[float]]] = []
    original_spearman = fv.spearman_average_rank

    def capture_pairs(factor_values, forward_returns):
        captured.append((list(factor_values), list(forward_returns)))
        return original_spearman(factor_values, forward_returns)

    monkeypatch.setattr(fv, "spearman_average_rank", capture_pairs)
    report = fv.evaluate_rdp(
        factor_id="return_5d",
        date_from=factor_date,
        date_to=factor_date,
        data_root=root,
    )
    observation = report["results"]["5"]["observations"][0]
    exact_rows = [row for row in source_at_factor_date["rows"] if row["latest_date"] == factor_date]

    assert observation["source_asof_row_count"] == 3
    assert observation["exact_date_universe_count"] == 2
    assert observation["universe_count"] == 2
    assert observation["stale_source_row_count"] == 1
    assert observation["factor_null_count"] == 0
    assert observation["immature_outcome_count"] == 0
    assert observation["pair_count"] == 2
    assert observation["mature_outcome_count"] == 2
    assert observation["invalid_outcome_count"] == 0
    assert observation["high_bucket_count"] == 1
    assert observation["low_bucket_count"] == 1
    assert observation["high_minus_low_spread"] is not None
    assert fv.STALE_SOURCE_ROW_REASON in (observation["reason"] or "")
    assert report["sample"]["source_asof_rows_total"] == 3
    assert report["sample"]["exact_date_rows_total"] == 2
    assert report["sample"]["stale_source_rows_total"] == 1
    assert captured[0][0] == [row["return_5d"] for row in exact_rows]
    expected_forward_5 = [
        _gap_close(int(row["code"]) - 1, 14) / _gap_close(int(row["code"]) - 1, 9) - 1
        for row in exact_rows
    ]
    assert captured[0][1] == pytest.approx(expected_forward_5)
    expected_forward_20 = [
        _gap_close(int(row["code"]) - 1, 29) / _gap_close(int(row["code"]) - 1, 9) - 1
        for row in exact_rows
    ]
    assert captured[1][1] == pytest.approx(expected_forward_20)
    twenty_observation = report["results"]["20"]["observations"][0]
    assert twenty_observation["exact_date_universe_count"] == 2
    assert twenty_observation["stale_source_row_count"] == 1
    assert twenty_observation["pair_count"] == 2

    captured.clear()
    resumed_report = fv.evaluate_rdp(
        factor_id="return_5d",
        date_from=resumed_date,
        date_to=resumed_date,
        data_root=root,
    )
    resumed_observation = resumed_report["results"]["5"]["observations"][0]
    assert resumed_observation["source_asof_row_count"] == 3
    assert resumed_observation["exact_date_universe_count"] == 3
    assert resumed_observation["stale_source_row_count"] == 0
    assert resumed_observation["pair_count"] == 3
    resumed_twenty_observation = resumed_report["results"]["20"]["observations"][0]
    assert resumed_twenty_observation["exact_date_universe_count"] == 3
    assert resumed_twenty_observation["pair_count"] == 3
    assert len(captured[0][0]) == 3
    assert len(captured[0][1]) == 3


def test_factor_date_future_row_fails_closed(tmp_path: Path, monkeypatch):
    root = _import_exact_date_gap_fixture(tmp_path)
    original_query = rdp.query_full_market

    def query_with_future_row(**kwargs):
        payload = original_query(**kwargs)
        if kwargs.get("as_of") != "2026-01-10":
            return payload
        rows = [dict(row) for row in payload["rows"]]
        rows[0]["latest_date"] = "2026-01-11"
        return {**payload, "rows": rows}

    monkeypatch.setattr(rdp, "query_full_market", query_with_future_row)
    with pytest.raises(rdp.ResearchDataPlaneValidationError, match=fv.FUTURE_SOURCE_ROW_REASON):
        fv.evaluate_rdp(
            factor_id="return_5d",
            date_from="2026-01-10",
            date_to="2026-01-10",
            data_root=root,
        )


def test_factor_api_registry_evaluation_and_missing_rdp_are_read_only(tmp_path: Path, monkeypatch):
    root = _import_fixture(tmp_path)
    monkeypatch.setenv("VIBE_RESEARCH_RESEARCH_DATA_DIR", str(root))
    api = FastAPI()
    api.include_router(factor_validation_router.router)
    client = TestClient(api)

    registry = client.get("/api/signals/factor-validation/registry")
    assert registry.status_code == 200
    assert len(registry.json()["factors"]) == 6

    response = client.post(
        "/api/signals/factor-validation/evaluate",
        json={"factor_id": "return_5d", "forward_windows": [5, 20], "date_from": "2026-03-01", "date_to": "2026-03-05"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "normal"
    assert payload["source"]["artifact_sha256"]
    assert payload["sample"]["universe"] == "RDP_OBSERVED_CROSS_SECTION"
    assert payload["results"]["5"]["forward_window"] == 5
    assert payload["results"]["20"]["forward_window"] == 20
    assert payload["historical_validity"]["status"] == "NOT_PROVEN"
    assert payload["formal_state_write"]["performed"] is False

    monkeypatch.setenv("VIBE_RESEARCH_RESEARCH_DATA_DIR", str(tmp_path / "missing"))
    unavailable = client.post(
        "/api/signals/factor-validation/evaluate",
        json={"factor_id": "return_5d", "forward_windows": [5, 20]},
    )
    assert unavailable.status_code == 200
    assert unavailable.json()["status"] == "unavailable"
    assert unavailable.json()["results"] == {}
    assert unavailable.json()["parity"]["source_contract"] == fv.FULL_MARKET_CONTRACT
    assert unavailable.json()["sample"]["factor_dates_evaluated"] == {"5": 0, "20": 0}


def test_factor_validation_bounds_history_and_exposes_immature_dates(tmp_path: Path):
    root = _import_fixture(tmp_path, days=300)
    report = fv.evaluate_rdp(factor_id="return_5d", data_root=root)
    assert report["sample"]["factor_dates_attempted"] == fv.MAX_FACTOR_DATES
    assert report["sample"]["truncated"] is True
    assert report["sample"]["effective_date_from"] == "2026-02-20"
    assert report["results"]["20"]["immature_factor_dates"] >= 1
    assert report["results"]["20"]["observations"][-1]["status"] == "IMMATURE_FORWARD_WINDOW"
