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
