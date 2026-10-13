"""Synthetic captured-byte seal observations; never fetch or persist data."""
from __future__ import annotations

import builtins
import hashlib
import json
from pathlib import Path
import socket

import pytest

import astock
import short_term_limit_up_pool_adapter as adapter
import short_term_seal_quality as quality
import trade_calendar

DAY = "2026-07-30"
OBSERVED = "2026-07-30T07:05:00Z"


def row(code="000001", **extra):
    return {"c": code, "lbc": 1, "fbt": 93000, "lbt": 93000, "zbc": 0, **extra}


def raw(rows=None, *, day="20260730"):
    return json.dumps({"date": day, "data": {"pool": [row()] if rows is None else rows}}, separators=(",", ":")).encode()


def project(data=None, **kwargs):
    return quality.build_seal_quality_observation(
        raw() if data is None else data,
        **{"requested_trade_date": DAY, "observed_at": OBSERVED, "http_status": 200, **kwargs},
    )


@pytest.fixture(autouse=True)
def offline(monkeypatch, tmp_path):
    monkeypatch.setenv("VR_DATA_DIR", str(tmp_path))

    def forbidden(*args, **kwargs):
        raise AssertionError("projection attempted external I/O or clock/calendar lookup")

    for owner, name in (
        (astock, "em_get"), (adapter, "fetch_limit_up_pool_snapshot"),
        (adapter, "_now_utc_iso"), (trade_calendar, "_load_calendar"),
        (socket.socket, "connect"), (socket.socket, "connect_ex"),
        (socket, "create_connection"), (socket, "getaddrinfo"),
    ):
        monkeypatch.setattr(owner, name, forbidden)


def test_complete_descriptive_metrics_and_identity_without_authority():
    data = raw([row(), row("600001", lbc=3, fbt="100000", lbt="143000", zbc=2)])
    result = project(data)
    assert result["status"] == "normal"
    assert result["metrics"] == {
        "never_broken_count": 1, "never_broken_ratio": 0.5,
        "reopened_count": 1, "ever_opened_ratio": 0.5,
        "average_broken_times": 1.0, "first_seal_by_0935_count": 1, "late_seal_count": 1,
    }
    assert result["raw_payload_sha256"] == hashlib.sha256(data).hexdigest()
    assert result["observed_at"] == OBSERVED and result["source_trade_date"] == DAY
    assert result["finality"] == "NOT_ESTABLISHED" and result["canonical_authority"] is False
    assert result["layer"] == "RESEARCH_OBSERVATION"
    assert result["units"]["ratio"] == "fraction_0_1"
    assert result["descriptive_cutoffs"]["authority"] == "LOCAL_DESCRIPTIVE_CONVENTION"
    assert not {"failed_board_rate", "layered_promotion_rates", "return", "BUY"} & result["metrics"].keys()


@pytest.mark.parametrize("field,value", [
    ("zbc", None), ("zbc", ""), ("zbc", "-"), ("zbc", "0"),
    ("zbc", False), ("zbc", -1), ("zbc", 1.5), ("zbc", 2**31),
    ("fbt", None), ("fbt", "93000"), ("fbt", 93000.0), ("fbt", True),
    ("fbt", 126000), ("fbt", 120000), ("fbt", 92459),
    ("lbt", None), ("lbt", ""), ("lbt", 150001), ("lbt", "14:30:00"),
])
def test_missing_or_invalid_field_does_not_become_zero_or_shrink_denominator(field, value):
    result = project(raw([row(), row("600001", **{field: value})]))
    name = {"zbc": "broken_times", "fbt": "first_seal", "lbt": "last_seal"}[field]
    assert result["status"] == "partial"
    assert result["coverage"][name] == {"known_count": 1, "unknown_count": 1, "complete": False}
    assert result["rows"][1][name] is None
    assert result["rows"][1]["field_issues"][name]
    if field == "zbc":
        assert result["metrics"]["never_broken_ratio"] is None
        assert result["metrics"]["never_broken_count"] is None
        assert result["metrics"]["average_broken_times"] is None
    elif field == "fbt":
        assert result["metrics"]["first_seal_by_0935_count"] is None
    else:
        assert result["metrics"]["late_seal_count"] is None


def test_old_capture_does_not_fabricate_quality_fields():
    result = project(raw([{"c": "000001", "lbc": 2}]))
    assert result["status"] == "unavailable" and result["sample_count"] == 1
    assert all(value is None for value in result["metrics"].values())
    assert result["rows"][0]["field_issues"] == {name: ["MISSING_SOURCE_FIELD"] for name in ("first_seal", "last_seal", "broken_times")}


def test_actual_zero_is_valid_and_distinct_from_unavailable():
    result = project()
    assert result["rows"][0]["broken_times"] == 0
    assert result["metrics"]["reopened_count"] == 0
    assert result["metrics"]["late_seal_count"] == 0
    assert result["metrics"]["never_broken_ratio"] == 1


@pytest.mark.parametrize("first,last,early,late", [
    (92500, 92500, 1, 0), (93500, 93500, 1, 0),
    (93501, 142959, 0, 0), (113000, 143000, 0, 1), (130000, 150000, 0, 1),
])
def test_time_cutoffs_are_explicit_and_inclusive(first, last, early, late):
    result = project(raw([row(fbt=first, lbt=last)]))
    assert result["metrics"]["first_seal_by_0935_count"] == early
    assert result["metrics"]["late_seal_count"] == late


def test_time_order_and_future_source_time_are_unknown():
    result = project(raw([row(fbt=143000, lbt=100000)]))
    assert result["rows"][0]["first_seal"] is None
    assert result["rows"][0]["last_seal"] is None
    assert result["rows"][0]["field_issues"]["first_seal"] == ["SEAL_TIME_ORDER_INVALID"]
    intraday = project(raw([row(fbt=100000, lbt=143000)]), observed_at="2026-07-30T02:05:00Z")
    assert intraday["rows"][0]["first_seal"] == "100000"
    assert intraday["rows"][0]["last_seal"] is None
    assert intraday["finality"] == "NOT_ESTABLISHED"


@pytest.mark.parametrize("kwargs", [
    {"requested_trade_date": "2026-02-30"}, {"requested_trade_date": "20260730"},
    {"observed_at": "2026-07-30T08:00:00"}, {"observed_at": "2026-07-29T07:00:00Z"},
    {"observed_at": "bad"}, {"observed_at": "2026-07-30T08:00:00+99:00"},
    {"observed_at": "9999-12-31T23:59:59-23:59"},
])
def test_invalid_capture_binding_fails_closed(kwargs):
    result = project(**kwargs)
    assert result["reason_codes"] == ["OBSERVATION_BINDING_INVALID"]
    assert not result["rows"] and result["source_trade_date"] is None


@pytest.mark.parametrize("data,kwargs", [
    (raw(day=None), {}), (raw(day="20260729"), {}),
    (raw([row(), row()]), {}), (raw([row(), row("invalid")]), {}),
    (raw([row(), row("600001", lbc=None)]), {}), (raw([]), {}),
    (b"not-json", {}), (b'{"date":"20260730","data":null}', {}),
    (raw(), {"http_status": 403}), (raw(), {"http_status": 429}),
    (raw(), {"http_status": True}), (b'{"data":{"pool":[]},"bad":NaN}', {}),
])
def test_source_admission_is_reused_without_promoting_partial_or_empty(data, kwargs):
    result = project(data, **kwargs)
    assert result["status"] == "unavailable" and result["reason_codes"] == ["SOURCE_NOT_QUALIFIED"]
    assert not result["rows"] and all(x is None for x in result["metrics"].values())


def test_duplicate_json_keys_cannot_silently_replace_quality_values():
    data = raw().replace(b'"zbc":0', b'"zbc":4,"zbc":0')
    assert project(data)["reason_codes"] == ["AMBIGUOUS_SOURCE_JSON"]


def test_excluded_universe_is_not_mixed_with_admitted_sample():
    result = project(raw([row(), row("920001", zbc=99)]))
    assert result["sample_count"] == 1 and result["excluded_universe_count"] == 1
    assert result["metrics"]["never_broken_ratio"] == 1
    empty = project(raw([row("920001")]))
    assert empty["status"] == "unavailable" and empty["sample_count"] == 0
    assert empty["reason_codes"] == ["EMPTY_TARGET_SAMPLE"]


def test_exact_legacy_stat_and_units_are_preserved_without_importing_prices_or_returns():
    result = project(raw([row(zttj={"days": 3, "ct": 2}, p=12340, zdp=10.0)]))
    assert result["rows"][0]["zt_stat"] == "3/2"
    assert result["rows"][0]["lbc"] == 1
    assert not {"p", "price", "ret", "zdp", "return", "effective_height"} & result["rows"][0].keys()


def test_code_alias_and_whitespace_follow_existing_adapter_without_duplicate_overwrite():
    aliased = row()
    aliased["code"] = " 000001 "
    aliased.pop("c")
    assert project(raw([aliased]))["rows"][0]["stock_code"] == "000001"
    assert project(raw([row(), aliased]))["reason_codes"] == ["SOURCE_NOT_QUALIFIED"]


def test_deterministic_read_only_projection_does_not_change_legacy_contract(monkeypatch):
    data = raw([row(zttj={"days": 3, "ct": 2})])
    arguments = {"requested_trade_date": DAY, "http_status": 200, "observed_at": OBSERVED}
    before = adapter.interpret_limit_up_pool_response_bytes(data, **arguments)

    def forbidden(*args, **kwargs):
        raise AssertionError("filesystem I/O prohibited")

    with monkeypatch.context() as patch:
        for owner, name in ((builtins, "open"), (Path, "read_bytes"), (Path, "write_bytes"), (Path, "read_text"), (Path, "write_text")):
            patch.setattr(owner, name, forbidden)
        one = project(data)
        two = project(data)
    assert one == two
    after = adapter.interpret_limit_up_pool_response_bytes(data, **arguments)
    assert before == after
    assert set(after["rows"][0]) == {"stock_code", "lbc", "zt_stat"}
    assert json.loads(json.dumps(one, allow_nan=False)) == one
