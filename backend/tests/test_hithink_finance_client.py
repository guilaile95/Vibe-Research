"""Offline contracts for the HiThink daily-bar production cutover."""

from __future__ import annotations

import json
from datetime import date

import pytest
import requests

import astock
import hithink_finance_client as client


class _Response:
    def __init__(self, payload, status_code: int = 200):
        self.status_code = status_code
        self.content = json.dumps(payload, ensure_ascii=False).encode("utf-8")


class _Session:
    def __init__(self, response=None, error: Exception | None = None):
        self.response = response
        self.error = error
        self.calls: list[dict] = []

    def get(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        if self.error is not None:
            raise self.error
        return self.response


class _SequenceSession(_Session):
    def __init__(self, *responses):
        super().__init__()
        self.responses = list(responses)

    def get(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        return self.responses.pop(0)


def _bar(day_ms: int, close: float = 10.5) -> dict:
    return {
        "date_ms": day_ms,
        "open_price": 10.0,
        "high_price": 11.0,
        "low_price": 9.0,
        "close_price": close,
        "volume": 1234.0,
        "turnover": 5678.0,
    }


def _index_bar(day_ms: int, close: float) -> dict:
    return {
        "date_ms": day_ms,
        "open_price": close - 1,
        "high_price": close + 1,
        "low_price": close - 2,
        "close_price": close,
        "volume": 1234.0,
        "turnover": 5678.0,
    }


def _payload(*items: dict, thscode: str = "600519.SH", adjust: str = "none") -> dict:
    return {
        "code": 0,
        "message": "ok",
        "request_id": "request-test",
        "data": {
            "thscode": thscode,
            "interval": "1d",
            "adjust": adjust,
            "timestamp": items[-1]["date_ms"] if items else None,
            "item": list(items),
        },
    }


@pytest.fixture(autouse=True)
def _credential(monkeypatch):
    monkeypatch.setenv(client.API_KEY_ENV, "test-value")


def test_provider_alias_reuses_canonical_exchange_policy_and_bounds_bse():
    assert client.provider_thscode("600519") == "600519.SH"
    assert client.provider_thscode("000001") == "000001.SZ"
    assert client.provider_thscode("920000") == "920000.BJ"
    with pytest.raises(client.HiThinkUnsupportedSecurityError):
        client.provider_thscode("837023")
    with pytest.raises(client.HiThinkUnsupportedSecurityError):
        client.provider_thscode("999999")
    with pytest.raises(client.HiThinkUnsupportedSecurityError):
        client.provider_thscode("not-a-code")


def test_fetch_daily_bars_projects_existing_contract_without_exposing_key():
    first = client._milliseconds(date(2026, 8, 20))
    second = client._milliseconds(date(2026, 8, 21))
    session = _Session(_Response(_payload(_bar(first), _bar(second, 10.8))))

    rows = client.fetch_daily_bars(
        "600519", 2, session=session, end_date=date(2026, 8, 24)
    )

    assert rows == [
        {
            "datetime": "2026-08-20 15:00:00",
            "date": "2026-08-20",
            "open": 10.0,
            "high": 11.0,
            "low": 9.0,
            "close": 10.5,
            "vol": 1234.0,
            "volume": 1234.0,
            "amount": 5678.0,
            "provider_id": client.PROVIDER_ID,
            "provider_symbol": "600519.SH",
            "price_adjustment": "none",
            "provider_contract": client.PROVIDER_CONTRACT,
        },
        {
            "datetime": "2026-08-21 15:00:00",
            "date": "2026-08-21",
            "open": 10.0,
            "high": 11.0,
            "low": 9.0,
            "close": 10.8,
            "vol": 1234.0,
            "volume": 1234.0,
            "amount": 5678.0,
            "provider_id": client.PROVIDER_ID,
            "provider_symbol": "600519.SH",
            "price_adjustment": "none",
            "provider_contract": client.PROVIDER_CONTRACT,
        },
    ]
    call = session.calls[0]
    assert call["url"] == client.BASE_URL + client.DAILY_ENDPOINT
    assert call["params"]["adjust"] == "none"
    assert call["params"]["thscode"] == "600519.SH"
    assert call["headers"]["X-api-key"] == "test-value"
    assert call["allow_redirects"] is False
    assert "test-value" not in json.dumps(rows)


@pytest.mark.parametrize(
    "payload,error_fragment",
    [
        ({"code": 2003, "message": "contains-sensitive-upstream-text", "request_id": "r1", "data": None}, "code=2003"),
        ({"code": "test-value", "data": None}, "code is not an integer"),
        ({"code": False, "data": None}, "code is not an integer"),
        (_payload(_bar(client._milliseconds(date(2026, 8, 21))), thscode="000001.SZ"), "identity drifted"),
        (_payload(_bar(client._milliseconds(date(2026, 8, 21))), adjust="forward"), "interval/adjustment drifted"),
    ],
)
def test_fetch_daily_bars_fails_closed_on_business_or_contract_drift(
    payload, error_fragment
):
    session = _Session(_Response(payload))
    with pytest.raises(client.HiThinkClientError) as captured:
        client.fetch_daily_bars(
            "600519", 5, session=session, end_date=date(2026, 8, 24)
        )
    assert error_fragment in str(captured.value)
    assert "contains-sensitive-upstream-text" not in str(captured.value)
    assert "test-value" not in str(captured.value)


def test_fetch_daily_bars_rejects_duplicate_and_non_midnight_dates():
    valid = client._milliseconds(date(2026, 8, 21))
    duplicate = _Session(_Response(_payload(_bar(valid), _bar(valid))))
    with pytest.raises(client.HiThinkContractError, match="duplicate date"):
        client.fetch_daily_bars(
            "600519", 5, session=duplicate, end_date=date(2026, 8, 24)
        )

    non_midnight = _Session(_Response(_payload(_bar(valid + 1))))
    with pytest.raises(client.HiThinkContractError, match="Shanghai midnight"):
        client.fetch_daily_bars(
            "600519", 5, session=non_midnight, end_date=date(2026, 8, 24)
        )


def test_fetch_daily_bars_rejects_successful_empty_result_for_fallback():
    session = _Session(_Response(_payload()))
    with pytest.raises(client.HiThinkContractError, match="unexpectedly empty"):
        client.fetch_daily_bars(
            "600519", 5, session=session, end_date=date(2026, 8, 24)
        )


def test_fetch_daily_bars_transport_error_is_credential_safe():
    session = _Session(error=requests.ConnectionError("upstream details"))
    with pytest.raises(client.HiThinkTransportError) as captured:
        client.fetch_daily_bars(
            "600519", 5, session=session, end_date=date(2026, 8, 24)
        )
    assert "ConnectionError" in str(captured.value)
    assert "upstream details" not in str(captured.value)
    assert "test-value" not in str(captured.value)


def _anomaly_payload(*items: dict, timestamp: int = 1787529600000) -> dict:
    return {
        "code": 0,
        "message": "ok",
        "data": {"timestamp": timestamp, "item": list(items)},
    }


def test_fetch_watchlist_anomalies_projects_multiple_rows_and_request_contract():
    session = _Session(_Response(_anomaly_payload(
        {
            "stock_name": "贵州茅台",
            "analysis_content": "成交活跃",
            "keyword_list": ["白酒"],
            "thscode": "600519.SH",
            "tag_name": "大幅上涨",
        },
        {
            "stock_name": "贵州茅台",
            "analysis_content": "快速反弹",
            "keyword_list": [],
            "thscode": "600519.SH",
            "tag_name": "快速反弹",
        },
    )))

    result = client.fetch_watchlist_anomalies(
        ["600519", "000001", "600519"], session=session
    )

    assert result["as_of_ms"] == 1787529600000
    assert [item["type"] for item in result["items"]] == ["大幅上涨", "快速反弹"]
    call = session.calls[0]
    assert call["url"] == client.BASE_URL + client.ANOMALY_ENDPOINT
    assert call["params"] == {"thscodes": "600519.SH,000001.SZ"}
    assert call["headers"] == {"X-api-key": "test-value"}
    assert call["allow_redirects"] is False


def test_fetch_watchlist_anomalies_preserves_successful_empty_and_rejects_identity_drift():
    empty = _Session(_Response(_anomaly_payload()))
    result = client.fetch_watchlist_anomalies(["600519"], session=empty)
    assert result["items"] == []

    drift = _Session(_Response(_anomaly_payload({
        "stock_name": "平安银行",
        "analysis_content": "原因",
        "keyword_list": [],
        "thscode": "000001.SZ",
        "tag_name": "大幅上涨",
    })))
    with pytest.raises(client.HiThinkContractError, match="identity drifted"):
        client.fetch_watchlist_anomalies(["600519"], session=drift)


def test_fetch_watchlist_anomalies_keeps_supported_codes_when_one_is_not_covered():
    session = _Session(_Response(_anomaly_payload()))

    result = client.fetch_watchlist_anomalies(["600519", "837023"], session=session)

    assert result["items"] == []
    assert result["unavailable_codes"] == ["837023"]
    assert session.calls[0]["params"] == {"thscodes": "600519.SH"}


def test_fetch_index_market_observation_validates_history_and_current_constituents():
    days = [client._milliseconds(date(2026, 8, day)) for day in (19, 20, 21)]
    history = _payload(*[_index_bar(day, 100 + index) for index, day in enumerate(days)], thscode="884092.TI", adjust=None)
    constituents = {
        "code": 0,
        "data": {
            "timestamp": 1787542767000,
            "item": [
                {"thscode": "002463.SZ", "ticker": "002463", "name": "沪电股份"},
                {"thscode": "002916.SZ", "ticker": "002916", "name": "深南电路"},
            ],
        },
    }
    session = _SequenceSession(_Response(history), _Response(constituents))

    result = client.fetch_index_market_observation(
        "884092.TI", offset=3, session=session, end_date=date(2026, 8, 24)
    )

    assert [row["close"] for row in result["history"]] == [100.0, 101.0, 102.0]
    assert [row["ticker"] for row in result["constituents"]] == ["002463", "002916"]
    assert result["constituents_as_of_ms"] == 1787542767000
    assert session.calls[0]["url"] == client.BASE_URL + client.INDEX_HISTORY_ENDPOINT
    assert session.calls[0]["params"]["interval"] == "1d"
    assert session.calls[1]["url"] == client.BASE_URL + client.INDEX_CONSTITUENTS_ENDPOINT
    assert session.calls[1]["params"] == {"thscode": "884092.TI"}


def test_index_overview_can_skip_constituents_and_rejects_invalid_identity():
    day = client._milliseconds(date(2026, 8, 21))
    session = _SequenceSession(_Response(_payload(_index_bar(day, 100), thscode="886069.TI", adjust=None)))
    result = client.fetch_index_market_observation(
        "886069.TI", offset=1, include_constituents=False, session=session, end_date=date(2026, 8, 24)
    )
    assert result["constituents"] is None
    assert len(session.calls) == 1
    with pytest.raises(client.HiThinkContractError, match="identity is invalid"):
        client.fetch_index_market_observation("885959.SH", session=session)


def test_index_observation_preserves_history_when_optional_detail_calls_fail():
    day = client._milliseconds(date(2026, 8, 21))
    history = _payload(_index_bar(day, 100), thscode="884092.TI", adjust=None)
    constituents = {
        "code": 0,
        "data": {
            "timestamp": 1787542767000,
            "item": [{"thscode": "002463.SZ", "ticker": "002463", "name": "沪电股份"}],
        },
    }

    constituent_failure = _SequenceSession(
        _Response(history),
        _Response({"code": 429, "data": None}),
    )
    result = client.fetch_index_market_observation(
        "884092.TI", offset=1, session=constituent_failure, end_date=date(2026, 8, 24)
    )
    assert len(result["history"]) == 1
    assert result["constituents"] is None
    assert result["constituents_error"] == "HiThinkBusinessError"

    snapshot_failure = _SequenceSession(
        _Response(history),
        _Response(constituents),
        _Response({"code": 429, "data": None}),
    )
    result = client.fetch_index_market_observation(
        "884092.TI",
        offset=1,
        include_constituent_snapshots=True,
        session=snapshot_failure,
        end_date=date(2026, 8, 24),
    )
    assert len(result["history"]) == 1
    assert result["constituents"][0]["ticker"] == "002463"
    assert result["constituent_snapshots"] is None
    assert result["constituent_snapshots_error"] == "HiThinkBusinessError"


def test_fetch_stock_snapshots_projects_current_change_and_preserves_null():
    payload = {
        "code": 0,
        "data": {
            "timestamp": 1787542768000,
            "total": 2,
            "item": [
                {"thscode": "002463.SZ", "ticker": "002463", "price_change_ratio_pct": 1.2, "turnover": 100.0},
                {"thscode": "002916.SZ", "ticker": "002916", "price_change_ratio_pct": None, "turnover": None},
            ],
        },
    }
    session = _Session(_Response(payload))
    result = client.fetch_stock_snapshots(["002463.SZ", "002916.SZ"], session=session)
    assert result == {
        "as_of_ms": 1787542768000,
        "items": [
            {"thscode": "002463.SZ", "ticker": "002463", "change_pct": 1.2, "turnover": 100.0},
            {"thscode": "002916.SZ", "ticker": "002916", "change_pct": None, "turnover": None},
        ],
    }
    assert session.calls[0]["params"] == {"thscodes": "002463.SZ,002916.SZ"}


class _Frame:
    empty = False

    def __init__(self, rows):
        self.rows = rows

    def to_dict(self, orient):
        assert orient == "records"
        return self.rows


class _Mootdx:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def bars(self, **kwargs):
        self.calls.append(kwargs)
        return _Frame(self.rows)


def test_astock_daily_uses_hithink_primary(monkeypatch):
    expected = [{"datetime": "2026-08-21 15:00:00", "close": 10.0}]
    monkeypatch.setattr(client, "fetch_daily_bars", lambda code, offset: expected)
    monkeypatch.setattr(
        astock, "_mootdx_client", lambda: pytest.fail("mootdx fallback was called")
    )
    assert astock.kline("600519", category=4, offset=20) is expected


def test_astock_daily_falls_back_on_hithink_failure(monkeypatch):
    def fail(code, offset):
        raise client.HiThinkTransportError("safe failure")

    fallback = _Mootdx([{"datetime": "2026-08-21", "close": 9.9}])
    monkeypatch.setattr(client, "fetch_daily_bars", fail)
    monkeypatch.setattr(astock, "_mootdx_client", lambda: fallback)

    assert astock.kline("600519", category=4, offset=20) == fallback.rows
    assert fallback.calls == [{"symbol": "600519", "category": 4, "offset": 20}]


def test_astock_current_bse_fails_closed_instead_of_wrong_mootdx_route(monkeypatch):
    def fail(code, offset):
        raise client.HiThinkTransportError("safe failure")

    monkeypatch.setattr(client, "fetch_daily_bars", fail)
    monkeypatch.setattr(
        astock, "_mootdx_client", lambda: pytest.fail("unsafe BSE fallback was called")
    )
    with pytest.raises(client.HiThinkTransportError, match="safe failure"):
        astock.kline("920000", category=4, offset=20)


def test_astock_non_daily_keeps_existing_provider(monkeypatch):
    fallback = _Mootdx([{"datetime": "2026-08-21", "close": 9.9}])
    monkeypatch.setattr(
        client, "fetch_daily_bars", lambda *args: pytest.fail("HiThink was called")
    )
    monkeypatch.setattr(astock, "_mootdx_client", lambda: fallback)
    assert astock.kline("600519", category=5, offset=20) == fallback.rows
    assert fallback.calls == [{"symbol": "600519", "category": 5, "offset": 20}]


def test_astock_without_key_keeps_existing_provider(monkeypatch):
    monkeypatch.delenv(client.API_KEY_ENV, raising=False)
    fallback = _Mootdx([{"datetime": "2026-08-21", "close": 9.9}])
    monkeypatch.setattr(
        client, "fetch_daily_bars", lambda *args: pytest.fail("HiThink was called")
    )
    monkeypatch.setattr(astock, "_mootdx_client", lambda: fallback)
    assert astock.kline("600519", category=4, offset=20) == fallback.rows


def test_astock_current_bse_without_key_fails_closed(monkeypatch):
    monkeypatch.delenv(client.API_KEY_ENV, raising=False)
    monkeypatch.setattr(
        astock, "_mootdx_client", lambda: pytest.fail("unsafe BSE fallback was called")
    )
    with pytest.raises(client.HiThinkNotConfiguredError, match="required"):
        astock.kline("920000", category=4, offset=20)
