"""Offline replay of synthetic provider-shaped inputs through production parsers.

This is parser-contract evidence, not recorded-provider/live availability evidence.
Transport and the existing AkShare boundary are injected; parsers are never mocked.
"""
from copy import deepcopy
from datetime import datetime, timezone
from io import BytesIO
import json
from pathlib import Path
import socket
from types import SimpleNamespace
from urllib.error import HTTPError
import urllib.request

import pytest
import requests

import astock
import tencent_kline

FIXTURES = Path(__file__).parent / "fixtures" / "core_provider_replay"


def corpus(name):
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def cases(name):
    return [pytest.param(case, id=f"{name}:{case['id']}") for case in corpus(name)["cases"]]


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def blocked(*args, **kwargs):
        pytest.fail("Unexpected real transport in offline provider replay")
    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(socket, "getaddrinfo", blocked)
    monkeypatch.setattr(requests.sessions.Session, "request", blocked)
    monkeypatch.setattr(urllib.request, "urlopen", blocked)
    monkeypatch.setattr(astock, "_akshare", blocked)


@pytest.mark.parametrize("name", ["tencent_quote", "tencent_kline", "ths_financials"])
def test_fixture_provenance_is_explicit_and_not_live_evidence(name):
    fixture = corpus(name)
    assert fixture["schema_version"] == 1
    assert fixture["provenance"]["kind"] == "synthetic_constructed"
    assert fixture["provenance"]["captured_at"] is None
    assert fixture["provenance"]["boundary"]
    ids = [case["id"] for case in fixture["cases"]]
    assert len(ids) == len(set(ids))
    assert all(case["reason"] for case in fixture["cases"])


@pytest.mark.parametrize("case", cases("tencent_quote"))
def test_quote_response_replay(monkeypatch, case):
    calls = []
    responses = []

    def urlopen(request, timeout):
        calls.append(request.full_url)
        assert request.full_url == "https://qt.gtimg.cn/q=sh600519"
        assert timeout == 10
        if case.get("http_status") == 429:
            raise HTTPError(request.full_url, 429, "Too Many Requests", {}, None)
        response = BytesIO(case["body"].encode("gbk"))
        responses.append(response)
        return response

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    if case.get("error"):
        with pytest.raises(HTTPError) as error:
            astock.tencent_quote(["600519"])
        assert error.value.code == 429
    else:
        result = astock.tencent_quote(["600519"])
        if not case["expected"]:
            assert result == {}, case["reason"]
        else:
            assert result["600519"]["name"] == "合成测试股票"
            for key, value in case["expected"].items():
                assert result["600519"][key] == value, f"{case['reason']}: {key}"
        assert all(response.closed for response in responses)
    assert len(calls) == 1  # no retry storm on 429 or malformed data


@pytest.mark.parametrize("case", cases("tencent_kline"))
def test_kline_response_replay(monkeypatch, case):
    state = {"calls": 0, "closed": False}

    def get(url, **kwargs):
        state["calls"] += 1
        assert url == tencent_kline.URL
        assert kwargs["params"] == {"param": f"sh{case['code']},day,,,5,"}
        assert kwargs["timeout"] == 12
        response = requests.Response()
        response.status_code = case["http_status"]
        response.close = lambda: state.update(closed=True)
        response.json = lambda: deepcopy(case["payload"])
        return response

    # Freeze the parser's date boundary, not the rows or validation logic.
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 8, 21, 8, tzinfo=timezone.utc).astimezone(tz)

    monkeypatch.setattr(tencent_kline, "datetime", Clock)
    monkeypatch.setattr(requests, "get", get)
    if case["error"]:
        with pytest.raises((ValueError, TypeError, requests.HTTPError), match=case["error"]):
            tencent_kline.unadjusted_bars(case["code"], "day", 5)
    else:
        rows = tencent_kline.unadjusted_bars(case["code"], "day", 5)
        assert len(rows) == 1
        row = rows[0]
        assert row["date"] == "2026-08-20"
        assert (row["open"], row["close"], row["high"], row["low"]) == (10, 11, 12, 9)
        assert row["volume"] == row["vol"] == (23 if case["code"] == "688981" else 2300), case["reason"]
        assert row["amount"] is None, case["reason"]
        assert row["price_adjustment"] == "none"
        assert row["provider_contract"] == "tencent-fqkline-unadjusted.v1"
    assert state == {"calls": 1, "closed": True}


class Frame:
    """Existing SDK boundary only; no dependency on installed AkShare or pandas."""
    def __init__(self, rows):
        self.rows = rows
        self.empty = not rows

    def to_dict(self, orient):
        assert orient == "records"
        return deepcopy(self.rows)


@pytest.mark.parametrize("case", cases("ths_financials"))
def test_financial_response_replay(monkeypatch, case):
    calls = []

    def read(table):
        def fetch(**kwargs):
            assert kwargs == {"symbol": "600519", "indicator": "按报告期"}
            calls.append(table)
            if case["rate_limited_table"] == table:
                response = requests.Response()
                response.status_code = 429
                response.raise_for_status()
            return Frame(case["tables"][table])
        return fetch

    source = SimpleNamespace(**{
        "stock_financial_abstract_ths": read("summary"),
        "stock_financial_benefit_new_ths": read("income"),
        "stock_financial_cash_new_ths": read("cashflow"),
        "stock_financial_debt_new_ths": read("balance"),
    })
    monkeypatch.setattr(astock, "_akshare", lambda: source)
    result = astock.financials("600519", include_health=True)
    if case["id"] == "empty":
        assert result == {}, case["reason"]
        assert calls == ["summary"]
        return
    assert calls == ["summary", "income", "cashflow", "balance"]
    quality = result["data_quality"]
    assert result["report_date"] is None
    assert quality["point_in_time_supported"] is False
    assert quality["publication_date_known"] is False
    assert quality["fetch_mode"] == "snapshot"
    assert result["revenue"] == "100亿"
    assert result["roe"] == "15%"
    if case["id"] == "normal_units":
        assert quality["status"] == "normal"
        assert quality["missing_fields"] == quality["warnings"] == []
        assert result["revenue_amount"] == 1000
        assert result["operating_cash_flow"] == 300
        assert result["free_cash_flow"] == 260
        assert result["cash_conversion_ratio"] == 1.5
    else:
        assert quality["status"] == "partial", case["reason"]
        assert result["operating_cash_flow"] is None
        assert result["free_cash_flow"] is None
        assert "operating_cash_flow" in quality["missing_fields"]
        if case["id"] in ("missing_statement_date", "malformed_units", "rate_limit"):
            assert "cashflow_unavailable" in quality["warnings"], case["reason"]
        if case["id"] == "missing_summary_date":
            assert result["period_end"] is None
            assert result["revenue_amount"] is None
        else:
            assert result["period_end"] == "2025-12-31"
            assert result["revenue_amount"] == 1000  # one bad table cannot erase income
