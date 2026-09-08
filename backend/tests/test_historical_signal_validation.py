from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import historical_signal_validation as hsv
import historical_signal_validation_router as validation_router
import research_data_plane as rdp


DATES = [(date(2024, 1, 1) + timedelta(days=index)).isoformat() for index in range(130)]


def _crossing_closes() -> list[float]:
    closes = [100.0] * 130
    closes[80] = 101.0
    for index in range(81, 85):
        closes[index] = 101.0
    closes[85] = 105.0
    for index in range(86, 100):
        closes[index] = 101.0
    closes[100] = 110.0
    for index in range(101, 130):
        closes[index] = 110.0
    return closes


def test_production_protocol_is_no_lookahead_and_three_state():
    closes = _crossing_closes()
    full = hsv.run_study({"600001": (DATES, closes)}, None, windows=(5, 20))
    truncated = hsv.run_study({"600001": (DATES[:96], closes[:96])}, None, windows=(5, 20))

    full_row = full["windows"]["5"]["rows"][0]
    truncated_row = truncated["windows"]["5"]["rows"][0]
    assert full_row["signal_date"] == truncated_row["signal_date"] == DATES[80]
    assert full_row["return_pct"] == truncated_row["return_pct"] == pytest.approx(3.9604, abs=1e-4)
    assert truncated["windows"]["20"]["events_immature"] == 1

    # Continuous True is one crossing; the first evaluable True has unknown prior state.
    assert len(hsv.study_series(DATES, closes)["events"]) == 1
    unknown = hsv.study_series(DATES, [40.0] * 40 + [100.0] * 90)
    assert unknown["events"] == []
    assert unknown["excluded_unknown_prior_state"] == 1


def test_production_protocol_keeps_missing_exit_and_benchmark_endpoints_explicit():
    closes = _crossing_closes()
    missing_exit = list(closes)
    missing_exit[85] = None
    missing = hsv.run_study({"600001": (DATES, missing_exit)}, None, windows=(5,))["windows"]["5"]
    assert missing["events_missing_exit"] == 1
    assert missing["rows"][0]["status"] == "MISSING_EXIT"
    assert missing["rows"][0]["return_pct"] is None

    benchmark_dates = [day for day in DATES if day != DATES[85]]
    benchmark_closes = [100.0] * len(benchmark_dates)
    report = hsv.run_study(
        {"600001": (DATES, closes)},
        (benchmark_dates, benchmark_closes),
        windows=(5,),
    )
    row = report["windows"]["5"]["rows"][0]
    assert row["benchmark_return_pct"] is None
    assert row["excess_return_pct"] is None
    assert row["benchmark_missing_reason"] == "benchmark_end_missing"
    assert report["windows"]["5"]["failures"] is None

    start_missing = hsv.run_study(
        {"600001": (DATES, closes)},
        ([day for day in DATES if day != DATES[80]], [100.0] * 129),
        windows=(5,),
    )["windows"]["5"]["rows"][0]
    assert start_missing["benchmark_missing_reason"] == "benchmark_start_missing"


def test_validation_api_is_rdp_only_and_keeps_provenance(tmp_path: Path, monkeypatch):
    csv_path = tmp_path / "daily.csv"
    lines = ["code,trade_date,open,high,low,close,volume"]
    sample = _crossing_closes()
    for index, day in enumerate(DATES):
        lines.append(f"600001,{day},{sample[index]},{sample[index]},{sample[index]},{sample[index]},1000")
        lines.append(f"600002,{day},200,200,200,200,1000")
    csv_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    root = tmp_path / "rdp"
    manifest = rdp.import_csv(csv_path, root=root, imported_at="2026-09-09T00:00:00Z")
    monkeypatch.setenv("VIBE_RESEARCH_RESEARCH_DATA_DIR", str(root))
    monkeypatch.setenv("VIBE_NATIVE_INTEL_DISABLE_STARTUP_FETCH", "1")
    monkeypatch.setenv("VIBE_NATIVE_INTEL_DISABLE_SCHEDULER", "1")

    before = sorted(str(path.relative_to(root)) for path in root.rglob("*"))
    api = FastAPI()
    api.include_router(validation_router.router)
    client = TestClient(api)
    registry = client.get("/api/signals/validation/registry")
    assert registry.status_code == 200
    assert [item["id"] for item in registry.json()["signals"]] == ["sma20_gt_sma60"]

    response = client.post(
        "/api/signals/validation/evaluate",
        json={"signal_id": "sma20_gt_sma60", "codes": ["600001", "600003"], "benchmark_code": "600002"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "normal"
    assert payload["data"]["dataset_id"] == manifest["dataset_id"]
    assert payload["data"]["adjustment"] == "UNADJUSTED"
    assert payload["data"]["sample_codes_missing_data"] == ["600003"]
    assert payload["historical_validity"]["status"] == "NOT_PROVEN"
    assert payload["formal_state_write"]["performed"] is False
    assert payload["results"]["5"]["rows"][0]["benchmark_return_pct"] == 0.0
    after = sorted(str(path.relative_to(root)) for path in root.rglob("*"))
    assert after == before


def test_validation_api_reports_unavailable_rdp(monkeypatch, tmp_path):
    monkeypatch.setenv("VIBE_RESEARCH_RESEARCH_DATA_DIR", str(tmp_path / "missing"))
    monkeypatch.setenv("VIBE_NATIVE_INTEL_DISABLE_STARTUP_FETCH", "1")
    monkeypatch.setenv("VIBE_NATIVE_INTEL_DISABLE_SCHEDULER", "1")
    api = FastAPI()
    api.include_router(validation_router.router)
    response = TestClient(api).post(
        "/api/signals/validation/evaluate",
        json={"signal_id": "sma20_gt_sma60", "codes": ["600001"]},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "unavailable"
    assert payload["data"]["rows"] == []
    assert payload["historical_validity"]["status"] == "NOT_PROVEN"
