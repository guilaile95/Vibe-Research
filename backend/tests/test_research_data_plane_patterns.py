from __future__ import annotations

import csv
import inspect
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import research_data_plane as rdp
import technical_indicators as ti


def _write_pattern_fixture(tmp_path: Path, *, include_short: bool = True) -> tuple[Path, dict[str, list[dict]]]:
    source = tmp_path / "patterns.csv"
    rows_by_code: dict[str, list[dict]] = {}
    with source.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["code", "trade_date", "open", "high", "low", "close", "volume"])
        start = date(2026, 1, 1)
        for code, direction in (("000001", "up"), ("000002", "down"), ("000003", "flat")):
            rows_by_code[code] = []
            for index in range(66):
                trade_date = (start + timedelta(days=index)).isoformat()
                if direction == "up" and index == 65:
                    close = 20.0
                elif direction == "down" and index == 65:
                    close = 1.0
                else:
                    close = 10.0
                volume = 100_000.0 if index == 65 and direction != "flat" else 1_000.0
                row = {
                    "code": code,
                    "trade_date": trade_date,
                    "open": close,
                    "high": close + 0.5,
                    "low": max(0.1, close - 0.5),
                    "close": close,
                    "volume": volume,
                }
                rows_by_code[code].append(row)
                writer.writerow([row[field] for field in ("code", "trade_date", "open", "high", "low", "close", "volume")])
        if include_short:
            rows_by_code["600519"] = []
            for index in range(10):
                trade_date = (start + timedelta(days=index)).isoformat()
                row = {
                    "code": "600519",
                    "trade_date": trade_date,
                    "open": 12.0,
                    "high": 12.5,
                    "low": 11.5,
                    "close": 12.0,
                    "volume": 300.0,
                }
                rows_by_code["600519"].append(row)
                writer.writerow([row[field] for field in ("code", "trade_date", "open", "high", "low", "close", "volume")])
    return source, rows_by_code


def _import_fixture(tmp_path: Path, *, include_short: bool = True) -> tuple[Path, dict[str, list[dict]]]:
    source, rows = _write_pattern_fixture(tmp_path, include_short=include_short)
    root = tmp_path / "rdp"
    rdp.import_csv(source, root=root, imported_at="2026-03-08T00:00:00Z")
    return root, rows


def _single_stock_event_keys(rows: list[dict], code: str) -> set[tuple[str, str, str]]:
    klines = [
        {
            "datetime": row["trade_date"],
            "close": row["close"],
            "high": row["high"],
            "low": row["low"],
            "volume": row["volume"],
        }
        for row in rows
    ]
    result = ti.compute_indicators(
        klines,
        code=code,
        period="daily",
        days=len(klines),
        trade_date=None,
        fetched_at="2026-03-08T00:00:00Z",
    )
    aliases = {
        "sma_golden_cross": "sma20_cross_above_sma60",
        "sma_death_cross": "sma20_cross_below_sma60",
        "volume_spike": "volume_surge",
    }
    return {
        (code, result["trade_date"], aliases.get(trigger["type"], trigger["type"]))
        for trigger in result["triggers"]
    }


def test_patterns_reuse_five_existing_triggers_and_match_single_stock_semantics(tmp_path):
    root, rows = _import_fixture(tmp_path)

    result = rdp.query_patterns(root=root)

    assert result["status"] == "partial"  # the short code is explicit NOT_EVALUABLE.
    assert result["schema_version"] == rdp.PATTERN_SCHEMA_VERSION
    assert result["as_of"] == "2026-03-07"
    assert result["source_scope"] == {
        "start": "2026-01-01",
        "end": "2026-03-07",
        "row_count": 208,
        "code_count": 4,
    }
    assert result["evaluable_count"] == 3
    assert result["not_evaluable_count"] == 5
    assert result["formal_state_write"]["performed"] is False

    set_based_keys = {
        (event["code"], event["trade_date"], event["event_type"])
        for event in result["events"]
    }
    expected = _single_stock_event_keys(rows["000001"], "000001") | _single_stock_event_keys(rows["000002"], "000002")
    assert set_based_keys == expected
    assert len([event for event in result["events"] if event["code"] == "000001"]) == 3
    assert {event["evidence"]["source_trigger_type"] for event in result["events"]} == {
        "close_above_20d_high",
        "close_below_20d_low",
        "sma_golden_cross",
        "sma_death_cross",
        "volume_spike",
    }
    assert all(event["status"] == "MATCHED" for event in result["events"])


def test_patterns_use_artifact_derived_as_of_and_do_not_read_future_rows(tmp_path):
    root, _ = _import_fixture(tmp_path, include_short=False)

    result = rdp.query_patterns(root=root, latest=False, as_of="2026-03-06")

    assert result["status"] == "normal"
    assert result["requested_as_of"] == "2026-03-06"
    assert result["as_of"] == "2026-03-06"
    assert result["events"] == []
    assert all(item["trade_date"] <= "2026-03-06" for item in result["not_evaluable"])


def test_patterns_event_filter_and_pagination_are_bounded_and_deterministic(tmp_path):
    root, _ = _import_fixture(tmp_path, include_short=False)

    first = rdp.query_patterns(root=root, limit=1, offset=0)
    second = rdp.query_patterns(root=root, limit=1, offset=1)
    filtered = rdp.query_patterns(root=root, event_type="volume_surge", limit=10)

    assert first["returned_events"] == 1
    assert first["total_events"] == 6
    assert first["next_offset"] == 1
    assert second["events"][0] != first["events"][0]
    assert filtered["event_type_filter"] == "volume_surge"
    assert filtered["total_events"] == 2
    assert {event["event_type"] for event in filtered["events"]} == {"volume_surge"}


def test_patterns_not_evaluable_is_distinct_from_no_trigger(tmp_path):
    root, _ = _import_fixture(tmp_path)

    result = rdp.query_patterns(root=root)
    short_items = [item for item in result["not_evaluable"] if item["code"] == "600519"]
    flat_events = [event for event in result["events"] if event["code"] == "000003"]

    assert len(short_items) == 5
    assert {item["status"] for item in short_items} == {"NOT_EVALUABLE"}
    assert {item["reason_code"] for item in short_items} == {"INSUFFICIENT_HISTORY"}
    assert flat_events == []


def test_pattern_volume_event_keeps_the_exact_two_times_boundary():
    row = {
        "code": "000001",
        "trade_date": "2026-03-07",
        "close": 10.0,
        "observations_count": 25,
        "close20_count": 25,
        "close60_count": 25,
        "prior_high_count": 20,
        "prior_high": 11.0,
        "prior_low_count": 20,
        "prior_low": 9.0,
        "sma20": 10.0,
        "sma60": None,
        "previous_sma20": 10.0,
        "previous_sma60": None,
        "volume5_count": 5,
        "avg_volume5": 3000.0,
        "volume20_count": 20,
        "avg_volume20": 1500.0,
        "volume": 11000.0,
    }

    events, not_evaluable = rdp._evaluate_pattern_record(
        row,
        (next(item for item in rdp._PATTERN_EVENT_REGISTRY if item["event_type"] == "volume_surge"),),
    )

    assert not not_evaluable
    assert [event["event_type"] for event in events] == ["volume_surge"]
    assert events[0]["evidence"]["volume_ratio_5_20"] == pytest.approx(2.0)


def test_patterns_fail_closed_for_missing_source_and_preserve_duplicate_import_guard(tmp_path):
    with pytest.raises(rdp.ResearchDataPlaneUnavailableError, match="not configured"):
        rdp.query_patterns(root=tmp_path / "missing")

    source, _ = _write_pattern_fixture(tmp_path)
    duplicate = tmp_path / "duplicate.csv"
    duplicate.write_text(source.read_text(encoding="utf-8") + "000001,2026-03-07,20,20.5,19.5,20,100000\n", encoding="utf-8")
    try:
        rdp.import_csv(duplicate, root=tmp_path / "duplicate-rdp")
    except rdp.ResearchDataPlaneValidationError as exc:
        assert "duplicate" in str(exc)
    else:
        raise AssertionError("duplicate source identity was accepted")


def test_patterns_missing_window_values_remain_not_evaluable_without_deduplication():
    row = {
        "code": "000001",
        "trade_date": "2026-03-07",
        "close": 20.0,
        "observations_count": 66,
        "close20_count": 66,
        "close60_count": 66,
        "prior_high_count": 19,
        "prior_high": None,
        "prior_low_count": 20,
        "prior_low": 9.0,
        "sma20": 10.0,
        "sma60": 10.0,
        "previous_sma20": 10.0,
        "previous_sma60": 10.0,
        "volume5_count": 4,
        "avg_volume5": None,
        "volume20_count": 19,
        "avg_volume20": None,
        "volume": None,
    }

    events, not_evaluable = rdp._evaluate_pattern_record(row, rdp._PATTERN_EVENT_REGISTRY)

    assert events == []
    assert {item["reason_code"] for item in not_evaluable} == {"MISSING_HIGH", "MISSING_VOLUME"}
    assert {item["event_type"] for item in not_evaluable} == {
        "close_above_20d_high",
        "volume_surge",
    }


def test_pattern_scan_is_set_based_and_has_no_per_security_indicator_or_http_call():
    source = inspect.getsource(rdp.query_patterns)
    assert "technical_indicators" not in source
    assert "requests." not in source
    assert source.count("read_parquet(?)") == 1


def test_patterns_route_is_read_only_and_exposes_event_contract(tmp_path, monkeypatch):
    root, _ = _import_fixture(tmp_path, include_short=False)
    monkeypatch.setenv("VIBE_RESEARCH_RESEARCH_DATA_DIR", str(root))

    import app

    response = TestClient(app.app).get("/api/research-data/patterns", params={"limit": 2})

    assert response.status_code == 200
    payload = response.json()
    assert payload["schema_version"] == rdp.PATTERN_SCHEMA_VERSION
    assert payload["status"] == "normal"
    assert payload["returned_events"] == 2
    assert payload["formal_state_write"]["performed"] is False
    assert payload["events"][0]["evidence"]["source_trigger_type"]
