"""Offline regression tests for Shanghai natural-day research windows."""

from datetime import datetime, timedelta, timezone

import pytest

import astock
import trade_calendar


@pytest.mark.parametrize("host_offset", [0, 8])
@pytest.mark.parametrize(
    ("instant", "expected_day"),
    [
        ("2026-10-30T15:59:59+00:00", "2026-10-30"),
        # Saturday remains Saturday, not the preceding trading session.
        ("2026-10-30T16:00:00+00:00", "2026-10-31"),
        ("2026-10-30T23:59:59+00:00", "2026-10-31"),
    ],
)
@pytest.mark.parametrize("function_name", ["dragon_tiger_board", "lockup_expiry"])
def test_missing_date_uses_shanghai_natural_day(
    monkeypatch, host_offset, instant, expected_day, function_name
):
    fixed_instant = datetime.fromisoformat(instant)
    host_tz = timezone(timedelta(hours=host_offset))

    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return fixed_instant.astimezone(host_tz).replace(tzinfo=None)
            return fixed_instant.astimezone(tz)

    monkeypatch.setattr(astock, "datetime", FrozenDatetime)
    monkeypatch.setattr(trade_calendar, "datetime", FrozenDatetime)
    calls = []
    monkeypatch.setattr(
        astock, "eastmoney_datacenter", lambda report, **kwargs: calls.append((report, kwargs)) or []
    )

    getattr(astock, function_name)("600001")

    day = datetime.strptime(expected_day, "%Y-%m-%d")
    if function_name == "dragon_tiger_board":
        start = (day - timedelta(days=30)).strftime("%Y-%m-%d")
        assert len(calls) == 1
        assert calls[0][1]["filter_str"] == (
            f'(TRADE_DATE>=\'{start}\')(TRADE_DATE<=\'{expected_day}\')(SECURITY_CODE="600001")'
        )
    else:
        end = (day + timedelta(days=90)).strftime("%Y-%m-%d")
        assert len(calls) == 2
        assert calls[0][1]["filter_str"] == '(SECURITY_CODE="600001")'
        assert calls[1][1]["filter_str"] == (
            f'(SECURITY_CODE="600001")(FREE_DATE>=\'{expected_day}\')(FREE_DATE<=\'{end}\')'
        )


@pytest.mark.parametrize("function_name", ["dragon_tiger_board", "lockup_expiry"])
def test_explicit_date_does_not_consult_current_day(monkeypatch, function_name):
    def unexpected_today():
        raise AssertionError("An explicit as-of date must not consult the current day")

    monkeypatch.setattr(trade_calendar, "_today_shanghai", unexpected_today)
    calls = []
    monkeypatch.setattr(
        astock, "eastmoney_datacenter", lambda report, **kwargs: calls.append((report, kwargs)) or []
    )

    getattr(astock, function_name)("600001", trade_date="2024-02-29", strict=True)

    assert all(kwargs["strict"] is True for _, kwargs in calls)
    if function_name == "dragon_tiger_board":
        assert calls[0][1]["filter_str"] == (
            '(TRADE_DATE>=\'2024-01-30\')(TRADE_DATE<=\'2024-02-29\')(SECURITY_CODE="600001")'
        )
    else:
        assert calls[0][1]["filter_str"] == '(SECURITY_CODE="600001")'
        assert calls[1][1]["filter_str"] == (
            '(SECURITY_CODE="600001")(FREE_DATE>=\'2024-02-29\')(FREE_DATE<=\'2024-05-29\')'
        )
