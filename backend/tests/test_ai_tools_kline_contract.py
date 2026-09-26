"""Provider errors must not become misleading AI price statistics."""
from copy import deepcopy

import pytest
import requests

import ai_tools
import astock


BARS = [["2026-09-24", "20", "21", "22", "19", "100"],
        ["2026-09-25", "21", "22", "23", "20", "0"]]


class Response:
    def __init__(self, node, status=200):
        self.node = node
        self.status = status
        self.closed = False

    def raise_for_status(self):
        if self.status != 200:
            raise requests.HTTPError("upstream failed")

    def json(self):
        return {"data": {"sh600519": self.node}}

    def close(self):
        self.closed = True


def stub_response(monkeypatch, node, status=200):
    response = Response(node, status)
    monkeypatch.setattr(requests, "get", lambda *a, **kw: response)
    return response


@pytest.mark.parametrize("key", ["qfqday", "day"])
def test_valid_adjusted_or_no_adjustment_event_series(monkeypatch, key):
    response = stub_response(monkeypatch, {key: BARS})
    rows = ai_tools._kline_tencent("600519", "day", 5)
    assert [row["close"] for row in rows] == [21.0, 22.0]
    assert rows[-1]["volume"] == 0
    assert response.closed


def test_empty_adjusted_series_never_borrows_raw_prices(monkeypatch):
    stub_response(monkeypatch, {"qfqday": [], "day": BARS})
    with pytest.raises(ValueError):
        ai_tools._kline_tencent("600519", "day", 5)


@pytest.mark.parametrize("bad", [True, None, "NaN", "Infinity", "-1", "0", "999"])
def test_invalid_price_rejects_entire_series(monkeypatch, bad):
    rows = deepcopy(BARS)
    rows[1][2] = bad
    stub_response(monkeypatch, {"qfqday": rows})
    with pytest.raises(ValueError):
        ai_tools._kline_tencent("600519", "day", 5)


@pytest.mark.parametrize("rows", [BARS + [BARS[1]], list(reversed(BARS)),
                                  [BARS[0], ["2026-09-25"]],
                                  [["2026-02-30", *BARS[0][1:]]]])
def test_duplicate_reversed_or_malformed_bars_are_not_silently_dropped(monkeypatch, rows):
    stub_response(monkeypatch, {"qfqday": rows})
    with pytest.raises(ValueError):
        ai_tools._kline_tencent("600519", "day", 5)


def test_http_error_closes_response_and_does_not_parse_success_body(monkeypatch):
    response = stub_response(monkeypatch, {"qfqday": BARS}, status=503)
    with pytest.raises(requests.HTTPError):
        ai_tools._kline_tencent("600519", "day", 5)
    assert response.closed


def test_ai_summary_uses_only_fallback_after_adjusted_series_failure(monkeypatch):
    stub_response(monkeypatch, {"qfqday": [], "day": BARS})
    monkeypatch.setattr(astock, "kline", lambda *a, **kw: [
        {"date": "2026-09-24", "close": 10.0},
        {"date": "2026-09-25", "close": 11.0},
    ])
    result = ai_tools._kline({"code": "600519", "count": 5})
    assert result["summary"]["first_close"] == 10
    assert result["summary"]["last_close"] == 11
    assert result["summary"]["change_pct"] == 10


def test_ai_summary_is_unavailable_when_all_sources_fail(monkeypatch):
    stub_response(monkeypatch, {"qfqday": [BARS[0], ["broken"]]})
    monkeypatch.setattr(astock, "kline", lambda *a, **kw: [])
    result = ai_tools._kline({"code": "600519"})
    assert "error" in result and "summary" not in result
