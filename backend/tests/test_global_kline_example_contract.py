"""Synthetic chart conversion tests for the vendored example, never live Yahoo.

Production gstock only exposes its domestic quote/fundamentals subset; this file
executes the actual embedded function, not a second implementation of it.
"""
from __future__ import annotations

import ast
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime
import os
from pathlib import Path
import time
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest


SKILL = Path(__file__).resolve().parents[2] / "global-stock-data" / "SKILL.md"


def stamp(value):
    return int(datetime.fromisoformat(value).timestamp())


def payload(timestamps=None, timezone="America/New_York", granularity="1d", **columns):
    timestamps = [stamp("2024-03-11T09:30:00-04:00")] if timestamps is None else timestamps
    quote = {key: [1.123456] * len(timestamps) for key in ("open", "high", "low", "close")}
    quote["volume"] = [7] * len(timestamps)
    quote.update(columns)
    return {"chart": {"error": None, "result": [{"meta": {"exchangeTimezoneName": timezone, "dataGranularity": granularity},
            "timestamp": timestamps, "indicators": {"quote": [quote]}}]}}


@pytest.fixture
def example():
    blocks = [part.split("```", 1)[0] for part in SKILL.read_text(encoding="utf-8").split("```python\n")[1:]]
    block = next(block for block in blocks if "def stock_kline_yahoo(" in block)
    function = next(node for node in ast.parse(block).body if isinstance(node, ast.FunctionDef) and node.name == "stock_kline_yahoo")
    response = Mock()
    response.json.return_value = payload()
    get = Mock(return_value=response)
    namespace = {"requests": SimpleNamespace(get=get)}
    exec(compile(ast.Module(body=[function], type_ignores=[]), "embedded-stock-kline-yahoo", "exec"), namespace)
    return namespace["stock_kline_yahoo"], response, get


@contextmanager
def host_timezone(name):
    if not hasattr(time, "tzset"):
        pytest.skip("Host timezone switching requires tzset; conversion tests still run separately")
    try:
        with patch.dict(os.environ, {"TZ": name}):
            time.tzset()
            yield
    finally:
        time.tzset()


@pytest.mark.parametrize("exchange,instant,expected", [
    ("America/New_York", "2024-03-01T00:30:00+00:00", "2024-02-29"),
    ("America/New_York", "2024-11-04T00:30:00+00:00", "2024-11-03"),
    ("Asia/Hong_Kong", "2024-12-31T18:00:00+00:00", "2025-01-01"),
])
def test_exchange_date_independent_of_host_timezone(example, exchange, instant, expected):
    fetch, response, _ = example
    response.json.return_value = payload([stamp(instant)], exchange)
    results = []
    for host in ("UTC", "Asia/Shanghai"):
        with host_timezone(host):
            results.append(fetch("SYNTHETIC")[0]["date"])
    assert results == [expected, expected]


@pytest.mark.parametrize("instant,expected", [
    ("2024-03-10T06:59:00+00:00", "2024-03-10 01:59-05:00"),
    ("2024-03-10T07:00:00+00:00", "2024-03-10 03:00-04:00"),
    ("2024-11-03T05:30:00+00:00", "2024-11-03 01:30-04:00"),
    ("2024-11-03T06:30:00+00:00", "2024-11-03 01:30-05:00"),
])
def test_dst_intraday_offsets_are_explicit(example, instant, expected):
    fetch, response, _ = example
    response.json.return_value = payload([stamp(instant)], granularity="1m")
    assert fetch("SYNTHETIC", "1m")[0]["date"] == expected


@pytest.mark.parametrize("interval,expected", [
    ("1m", "2024-03-11 09:30-04:00"), ("1h", "2024-03-11 09:30-04:00"),
    ("1d", "2024-03-11"), ("1wk", "2024-03-11"), ("1mo", "2024-03-11"),
])
def test_explicit_interval_not_month_minute_substring(example, interval, expected):
    fetch, response, get = example
    response.json.return_value = payload(granularity=interval)
    assert fetch("SYNTHETIC", interval, "1mo")[0]["date"] == expected
    assert get.call_args.kwargs["params"] == {"interval": interval, "range": "1mo"}


@pytest.mark.parametrize("requested,declared", [("1d", "1mo"), ("1m", "1d"),
    ("1wk", "1d"), ("1mo", "1d"), ("1h", "1d")])
def test_provider_granularity_must_match_request_even_for_max_range(example, requested, declared):
    fetch, response, _ = example
    response.json.return_value = payload(granularity=declared)
    with pytest.raises(ValueError, match="granularity"):
        fetch("SYNTHETIC", requested, "max")


@pytest.mark.parametrize("declared", [None, "", "invalid", True, ["1d"]])
def test_invalid_declared_granularity_is_not_assumed(example, declared):
    fetch, response, _ = example
    response.json.return_value = payload(granularity=declared)
    with pytest.raises(ValueError, match="granularity"):
        fetch("SYNTHETIC")


def test_missing_declared_granularity_is_not_assumed(example):
    fetch, response, _ = example
    response.json.return_value = payload()
    del response.json.return_value["chart"]["result"][0]["meta"]["dataGranularity"]
    with pytest.raises(ValueError, match="granularity"):
        fetch("SYNTHETIC")


@pytest.mark.parametrize("declared", ["1h", "60m"])
def test_one_hour_response_aliases_are_explicitly_equivalent(example, declared):
    fetch, response, get = example
    response.json.return_value = payload(granularity=declared)
    assert fetch("SYNTHETIC", "1h")[0]["date"] == "2024-03-11 09:30-04:00"
    assert get.call_args.kwargs["params"]["interval"] == "1h"


@pytest.mark.parametrize("timezone", [None, "", "EST-not-an-IANA-zone"])
def test_missing_or_unknown_timezone_fails_without_host_fallback(example, timezone):
    fetch, response, _ = example
    response.json.return_value = payload(timezone=timezone)
    with pytest.raises(ValueError, match="timezone"):
        fetch("SYNTHETIC")


@pytest.mark.parametrize("kwargs", [{"interval": "1M"}, {"interval": "quarter"},
    {"interval": ""}, {"range_": "nonsense"}, {"range_": ""}])
def test_invalid_parameters_fail_before_request(example, kwargs):
    fetch, _, get = example
    with pytest.raises(ValueError):
        fetch("SYNTHETIC", **kwargs)
    get.assert_not_called()


@pytest.mark.parametrize("column", ["open", "high", "low", "close"])
@pytest.mark.parametrize("invalid", [None, float("nan"), float("inf"), float("-inf"), True, "1.2"])
def test_missing_or_invalid_ohlc_rejects_payload_with_diagnostic(example, column, invalid):
    fetch, response, _ = example
    response.json.return_value = payload(**{column: [invalid]})
    with pytest.raises(ValueError, match=rf"row 0.*{column}"):
        fetch("SYNTHETIC")


def test_precision_and_true_zero_are_not_missing(example):
    fetch, response, _ = example
    response.json.return_value = payload(open=[0], high=[0.00123456789], low=[0], close=[0.0000001], volume=[0])
    assert fetch("SYNTHETIC")[0] == {"date": "2024-03-11", "open": 0,
        "high": 0.00123456789, "low": 0, "close": 0.0000001, "volume": 0}


@pytest.mark.parametrize("volume", [None, 0.4, 7])
def test_volume_unknown_and_fractional_values_not_coerced_to_zero(example, volume):
    fetch, response, _ = example
    response.json.return_value = payload(volume=[volume])
    assert fetch("SYNTHETIC")[0]["volume"] == volume


def test_missing_volume_array_remains_unknown(example):
    fetch, response, _ = example
    response.json.return_value = payload()
    del response.json.return_value["chart"]["result"][0]["indicators"]["quote"][0]["volume"]
    assert fetch("SYNTHETIC")[0]["volume"] is None


@pytest.mark.parametrize("column", ["open", "high", "low", "close", "volume"])
def test_misaligned_columns_fail_explicitly(example, column):
    fetch, response, _ = example
    response.json.return_value = payload(**{column: []})
    with pytest.raises(ValueError, match=column):
        fetch("SYNTHETIC")


@pytest.mark.parametrize("invalid", [None, float("nan"), float("inf"), "", True, 1e100])
def test_invalid_timestamp_is_not_a_fabricated_date(example, invalid):
    fetch, response, _ = example
    response.json.return_value = payload([invalid])
    with pytest.raises(ValueError, match="timestamp"):
        fetch("SYNTHETIC")


def test_empty_timestamp_list_is_a_legitimate_empty_series(example):
    fetch, response, _ = example
    response.json.return_value = payload([])
    assert fetch("SYNTHETIC") == []


@pytest.mark.parametrize("mutation", ["missing", "null"])
def test_absent_timestamps_are_not_a_legitimate_empty_series(example, mutation):
    fetch, response, _ = example
    response.json.return_value = payload()
    chart = response.json.return_value["chart"]["result"][0]
    if mutation == "missing":
        del chart["timestamp"]
    else:
        chart["timestamp"] = None
    with pytest.raises(ValueError, match="timestamp"):
        fetch("SYNTHETIC")


def test_sorting_deduplicates_identical_timestamps_without_summing_volume(example):
    fetch, response, _ = example
    values = [stamp(instant) for instant in ("2025-01-02T09:30:00-05:00", "2024-12-31T09:30:00-05:00", "2024-12-31T09:30:00-05:00")]
    response.json.return_value = payload(values, close=[3, 2, 2], volume=[9, 7, 7])
    rows = fetch("SYNTHETIC")
    assert [(row["date"], row["close"], row["volume"]) for row in rows] == [("2024-12-31", 2, 7), ("2025-01-02", 3, 9)]


@pytest.mark.parametrize("interval", ["1wk", "1mo"])
def test_source_period_labels_and_volume_are_preserved_without_aggregation(example, interval):
    fetch, response, _ = example
    instants = ["2024-12-30T09:30:00-05:00", "2025-01-01T09:30:00-05:00", "2025-02-03T09:30:00-05:00"]
    response.json.return_value = payload([stamp(value) for value in instants], granularity=interval, volume=[7, 8, 9])
    rows = fetch("SYNTHETIC", interval)
    assert [row["date"] for row in rows] == [value[:10] for value in instants]
    assert [row["volume"] for row in rows] == [7, 8, 9]
    assert all("complete" not in row for row in rows)


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), -1, True])
def test_invalid_volume_is_not_fabricated_as_no_trading(example, invalid):
    fetch, response, _ = example
    response.json.return_value = payload(volume=[invalid])
    with pytest.raises(ValueError, match="row 0.*volume"):
        fetch("SYNTHETIC")


def test_conflicting_duplicate_timestamp_is_rejected(example):
    fetch, response, _ = example
    ts = stamp("2024-03-11T09:30:00-04:00")
    response.json.return_value = payload([ts, ts], close=[1, 2])
    with pytest.raises(ValueError, match="duplicate timestamp"):
        fetch("SYNTHETIC")


@pytest.mark.parametrize("chart", [{"result": None, "error": {"code": "synthetic"}}, {"result": []}, {}])
def test_provider_failure_is_not_an_empty_series(example, chart):
    fetch, response, _ = example
    response.json.return_value = {"chart": deepcopy(chart)}
    with pytest.raises(ValueError, match="chart"):
        fetch("SYNTHETIC")
