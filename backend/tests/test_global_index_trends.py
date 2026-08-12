"""全球指数分时走势离线契约测试（Tencent / Yahoo 均完全 mock）。"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Event, Lock
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient
import pytest

import app as app_module
import astock
import gstock
import market


EXPECTED_KEYS = ("dji", "spx", "ndx", "hsi", "hstech", "nikkei", "kospi", "shcomp")
TENCENT_KEYS = {"hsi", "hstech", "shcomp"}
YAHOO_KEYS = set(EXPECTED_KEYS) - TENCENT_KEYS


class _UrlopenResponse:
    def __init__(self, payload: dict):
        self.payload = payload

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


@pytest.fixture(autouse=True)
def _clear_global_trend_cache():
    market._CACHE.pop("global_index_trends", None)
    market._GLOBAL_TRENDS_LAST_RESULT = None
    yield
    market._GLOBAL_TRENDS_LAST_RESULT = None
    market._CACHE.pop("global_index_trends", None)


def _tencent_payload(code: str, previous_close: float = 100.0, *, two_points: bool = True) -> dict:
    rows = ["0930 101.00 0"]
    if two_points:
        rows += [
            "0931 102.00 0",
            "not-time 103.00 0",
            "0931 103.00 0",  # duplicate minute: later source value wins
            "0932 NaN 0",
            "0933 -1 0",
        ]
    return {
        "data": {
            code: {
                "data": {"date": "20260807", "data": rows},
                "qt": {code: ["", "", "", "", str(previous_close)]},
            },
        },
    }


def _yahoo_payload(*, two_points: bool = True) -> dict:
    # 01:30/01:40 UTC = 09:30/09:40 Beijing; source exchange date is 2026-08-06 in New York.
    first = int(datetime(2026, 8, 7, 1, 30, tzinfo=timezone.utc).timestamp())
    timestamps = [first]
    prices = [101.0]
    if two_points:
        timestamps += [first + 300, first + 600]
        prices += [None, 103.0]
    return {
        "chart": {
            "result": [{
                "meta": {"previousClose": 100.0, "exchangeTimezoneName": "America/New_York"},
                "timestamp": timestamps,
                "indicators": {"quote": [{"close": prices}]},
            }],
        },
    }


def _primary_urlopen(urlopen_calls: list[dict], *, fail_yahoo_symbol: str | None = None):
    def fake_urlopen(request, timeout):
        urlopen_calls.append({"url": request.full_url, "timeout": timeout})
        if "ifzq.gtimg.cn" in request.full_url:
            code = parse_qs(urlparse(request.full_url).query)["code"][0]
            return _UrlopenResponse(_tencent_payload(code))
        if "query1.finance.yahoo.com" in request.full_url:
            if fail_yahoo_symbol and fail_yahoo_symbol in request.full_url:
                raise OSError("provider unavailable")
            return _UrlopenResponse(_yahoo_payload())
        raise AssertionError(f"unexpected provider URL: {request.full_url}")

    return fake_urlopen


def test_global_index_trends_uses_eight_primary_series_with_metadata_and_provider_budget(monkeypatch):
    urlopen_calls: list[dict] = []

    def unexpected_eastmoney(*args, **kwargs):
        raise AssertionError("index trends must not fall back to Eastmoney")

    monkeypatch.setattr(gstock, "urlopen", _primary_urlopen(urlopen_calls))
    monkeypatch.setattr(astock, "em_get", unexpected_eastmoney)
    result = gstock.global_index_trends()

    assert [series["key"] for series in result["series"]] == list(EXPECTED_KEYS)
    assert result["missing_keys"] == []
    assert result["budget_seconds"] == pytest.approx(30.0)
    assert len(urlopen_calls) == len(EXPECTED_KEYS)
    assert all(call["timeout"] == pytest.approx(8.0) for call in urlopen_calls)
    assert len([call for call in urlopen_calls if "ifzq.gtimg.cn" in call["url"]]) == len(TENCENT_KEYS)
    assert len([call for call in urlopen_calls if "query1.finance.yahoo.com" in call["url"]]) == len(YAHOO_KEYS)

    hsi = next(series for series in result["series"] if series["key"] == "hsi")
    assert hsi["source"] == "tencent"
    assert hsi["trade_date"] == "2026-08-07"
    assert hsi["source_timezone"] == "Asia/Shanghai"
    assert hsi["display_timezone"] == "Asia/Shanghai"
    assert hsi["points"] == [
        {"time": "2026-08-07 09:30", "price": 101.0, "change_pct": 1.0},
        {"time": "2026-08-07 09:31", "price": 103.0, "change_pct": 3.0},
    ]

    dji = next(series for series in result["series"] if series["key"] == "dji")
    assert dji["source"] == "yahoo"
    assert dji["trade_date"] == "2026-08-06"
    assert dji["source_timezone"] == "America/New_York"
    assert dji["display_timezone"] == "Asia/Shanghai"
    assert dji["points"] == [
        {"time": "2026-08-07 09:30", "price": 101.0, "change_pct": 1.0},
        {"time": "2026-08-07 09:40", "price": 103.0, "change_pct": 3.0},
    ]


def test_provider_returns_none_when_it_has_fewer_than_two_valid_points(monkeypatch):
    def fake_urlopen(request, timeout):
        if "ifzq.gtimg.cn" in request.full_url:
            code = parse_qs(urlparse(request.full_url).query)["code"][0]
            return _UrlopenResponse(_tencent_payload(code, two_points=False))
        return _UrlopenResponse(_yahoo_payload(two_points=False))

    monkeypatch.setattr(gstock, "urlopen", fake_urlopen)
    hsi = next(idx for idx in gstock._INDICES if idx["key"] == "hsi")
    dji = next(idx for idx in gstock._INDICES if idx["key"] == "dji")

    assert gstock._tencent_trend_series(hsi) is None
    assert gstock._yahoo_trend_series(dji) is None


def test_global_index_trends_isolates_single_provider_failure_without_eastmoney(monkeypatch):
    urlopen_calls: list[dict] = []

    def unexpected_eastmoney(*args, **kwargs):
        raise AssertionError("no Eastmoney fallback is permitted")

    monkeypatch.setattr(gstock, "urlopen", _primary_urlopen(urlopen_calls, fail_yahoo_symbol="%5EKS11"))
    monkeypatch.setattr(astock, "em_get", unexpected_eastmoney)
    result = gstock.global_index_trends()

    assert [series["key"] for series in result["series"]] == [key for key in EXPECTED_KEYS if key != "kospi"]
    assert result["missing_keys"] == ["kospi"]
    assert len(urlopen_calls) == len(EXPECTED_KEYS)
    assert all(series["points"] for series in result["series"])


def test_global_index_trends_stops_when_the_30_second_budget_is_exhausted(monkeypatch):
    monotonic_values = iter([100.0, 130.1])
    calls: list[tuple[str, float]] = []

    def fake_monotonic():
        return next(monotonic_values)

    def unexpected_trend(idx, timeout):
        calls.append((idx["key"], timeout))
        raise AssertionError("expired run must not start another provider call")

    monkeypatch.setattr(gstock.time, "monotonic", fake_monotonic)
    monkeypatch.setattr(gstock, "_trend_series", unexpected_trend)
    result = gstock.global_index_trends()

    assert result["series"] == []
    assert result["missing_keys"] == list(EXPECTED_KEYS)
    assert result["budget_seconds"] == pytest.approx(30.0)
    assert calls == []


def _complete_payload() -> dict:
    return {
        "series": [{"key": key, "points": [{"time": "2026-08-07 09:30"}, {"time": "2026-08-07 09:31"}]} for key in EXPECTED_KEYS],
        "missing_keys": [],
        "budget_seconds": 30.0,
        "fetched_at": "now",
    }


def test_market_cache_is_complete_only_and_cold_requests_are_single_flight(monkeypatch):
    calls = {"count": 0}

    def partial_then_complete():
        calls["count"] += 1
        if calls["count"] <= 2:
            return {"series": _complete_payload()["series"][:-1], "missing_keys": ["shcomp"], "budget_seconds": 30.0, "fetched_at": "now"}
        return _complete_payload()

    monkeypatch.setattr(market.gstock, "global_index_trends", partial_then_complete)
    first_partial = market.get_global_index_trends()
    second_partial = market.get_global_index_trends()
    assert calls["count"] == 1
    assert second_partial is first_partial
    assert "global_index_trends" not in market._CACHE
    market._GLOBAL_TRENDS_LAST_RESULT = (market.time.time() - market._GLOBAL_TRENDS_FLIGHT_TTL - 1, first_partial)
    market.get_global_index_trends()
    assert calls["count"] == 2
    market._GLOBAL_TRENDS_LAST_RESULT = (market.time.time() - market._GLOBAL_TRENDS_FLIGHT_TTL - 1, first_partial)
    market.get_global_index_trends()
    assert calls["count"] == 3
    market.get_global_index_trends()
    assert calls["count"] == 3

    market._CACHE.pop("global_index_trends", None)
    market._GLOBAL_TRENDS_LAST_RESULT = None
    entered, release = Event(), Event()
    count_lock = Lock()
    calls["count"] = 0

    def slow_complete():
        with count_lock:
            calls["count"] += 1
        entered.set()
        assert release.wait(timeout=2)
        return _complete_payload()

    monkeypatch.setattr(market.gstock, "global_index_trends", slow_complete)
    with ThreadPoolExecutor(max_workers=4) as pool:
        first = pool.submit(market.get_global_index_trends)
        assert entered.wait(timeout=1)
        rest = [pool.submit(market.get_global_index_trends) for _ in range(3)]
        release.set()
        results = [first.result(timeout=2), *(future.result(timeout=2) for future in rest)]

    assert calls["count"] == 1
    assert all(len(result["series"]) == len(EXPECTED_KEYS) for result in results)


def test_global_index_trends_api_hides_internal_exception_detail(monkeypatch):
    client = TestClient(app_module.app)
    monkeypatch.setattr(market, "get_global_index_trends", lambda: (_ for _ in ()).throw(RuntimeError("secret-provider-detail")))

    response = client.get("/api/global/index-trends")
    assert response.status_code == 502
    assert response.json() == {"detail": "全球指数走势暂不可用"}
    assert "secret-provider-detail" not in response.text
