"""Tests for backend.trade_calendar.previous_trade_date.

All holiday-boundary dates are derived mechanically from the offline
data artifact (backend/data/cn_a_share_trade_calendar_v01.json) and the
official SSE/SZSE holiday ranges documented in
docs/research/BK11_TRADE_CALENDAR_SOURCE_V01.md.
"""
from __future__ import annotations

import bisect
import json
import os
import sys
from datetime import date

import pytest

import trade_calendar as tc


# ---------------------------------------------------------------------------
# Constants from official SSE/SZSE announcements
# ---------------------------------------------------------------------------

# Each entry: (holiday_name, closed_start, closed_end)
HOLIDAYS_2024 = [
    ("元旦",   "2023-12-30", "2024-01-01"),
    ("春节",   "2024-02-09", "2024-02-17"),
    ("清明节", "2024-04-04", "2024-04-06"),
    ("劳动节", "2024-05-01", "2024-05-05"),
    ("端午节", "2024-06-10", "2024-06-10"),
    ("中秋节", "2024-09-15", "2024-09-17"),
    ("国庆节", "2024-10-01", "2024-10-07"),
]
HOLIDAYS_2025 = [
    ("元旦",          "2025-01-01", "2025-01-01"),
    ("春节",          "2025-01-28", "2025-02-04"),
    ("清明节",        "2025-04-04", "2025-04-06"),
    ("劳动节",        "2025-05-01", "2025-05-05"),
    ("端午节",        "2025-05-31", "2025-06-02"),
    ("国庆节、中秋节", "2025-10-01", "2025-10-08"),
]
HOLIDAYS_2026 = [
    ("元旦",   "2026-01-01", "2026-01-03"),
    ("春节",   "2026-02-15", "2026-02-23"),
    ("清明节", "2026-04-04", "2026-04-06"),
    ("劳动节", "2026-05-01", "2026-05-05"),
    ("端午节", "2026-06-19", "2026-06-21"),
    ("中秋节", "2026-09-25", "2026-09-27"),
    ("国庆节", "2026-10-01", "2026-10-07"),
]
ALL_HOLIDAYS = HOLIDAYS_2024 + HOLIDAYS_2025 + HOLIDAYS_2026

# Makeup-workday weekends that must NOT be sessions
MAKEUP_WEEKENDS = [
    "2024-02-04", "2024-04-28", "2024-05-11",
    "2024-09-29", "2024-10-12",
    "2025-01-26", "2025-02-08", "2025-04-27",
    "2025-09-28", "2025-10-11",
    "2026-02-14", "2026-02-28", "2026-05-09",
    "2026-09-20", "2026-10-10",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_sessions() -> list[str]:
    data_path = os.path.join(
        os.path.dirname(tc.__file__), "data", "cn_a_share_trade_calendar_v01.json"
    )
    with open(data_path, encoding="utf-8") as f:
        data = json.load(f)
    return data["sessions"]


def _first_session_after(sessions: list[str], boundary: str) -> str:
    idx = bisect.bisect_right(sessions, boundary)
    assert idx < len(sessions), f"No session after {boundary}"
    return sessions[idx]


def _last_session_before(sessions: list[str], boundary: str) -> str:
    idx = bisect.bisect_left(sessions, boundary)
    assert idx > 0, f"No session before {boundary}"
    return sessions[idx - 1]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_cache():
    """Reset the module-level cache and patch 'today' for determinism."""
    tc._calendar_cache = None
    old_today = tc._today_shanghai
    tc._today_shanghai = lambda: date(2026, 12, 31)
    yield
    tc._calendar_cache = None
    tc._today_shanghai = old_today


@pytest.fixture
def sessions() -> list[str]:
    return _load_sessions()


# ---------------------------------------------------------------------------
# Normal paths
# ---------------------------------------------------------------------------

class TestNormalPaths:
    def test_consecutive_trading_days(self, sessions):
        # 2024-01-02 (Tue) → previous = None (first session)
        # 2024-01-03 (Wed) → previous = 2024-01-02
        assert tc.previous_trade_date("2024-01-03") == "2024-01-02"
        assert tc.previous_trade_date("2024-01-04") == "2024-01-03"
        assert tc.previous_trade_date("2024-01-05") == "2024-01-04"

    def test_across_weekend(self, sessions):
        # 2024-01-08 (Mon) → previous = 2024-01-05 (Fri)
        assert tc.previous_trade_date("2024-01-08") == "2024-01-05"

    @pytest.mark.parametrize(
        "holiday_name, closed_start, closed_end",
        ALL_HOLIDAYS,
        ids=[h[0] for h in ALL_HOLIDAYS],
    )
    def test_holiday_boundary(self, sessions, holiday_name, closed_start, closed_end):
        """First session after a holiday → previous = last session before holiday.

        Special case: if ``closed_start`` is before the supported range
        (e.g., 2024 元旦 starts 2023-12-30), the first session after the
        holiday is the very first session in the calendar and has no
        previous trading day → ``previous_trade_date`` returns ``None``.
        """
        first_after = _first_session_after(sessions, closed_end)
        idx = bisect.bisect_left(sessions, closed_start)
        if idx == 0:
            # No session exists before this holiday's start boundary.
            assert tc.previous_trade_date(first_after) is None, (
                f"{holiday_name}: previous_trade_date({first_after}) "
                f"should be None (no prior session before {closed_start})"
            )
            return
        last_before = sessions[idx - 1]
        result = tc.previous_trade_date(first_after)
        assert result == last_before, (
            f"{holiday_name}: previous_trade_date({first_after}) = {result}, "
            f"expected {last_before}"
        )


# ---------------------------------------------------------------------------
# Input boundaries
# ---------------------------------------------------------------------------

class TestInputBoundaries:
    @pytest.mark.parametrize(
        "bad_input",
        [
            None,
            20240102,
            True,
            False,
            "",
            " 2024-01-02",
            "2024-01-02 ",
            " 2024-01-02 ",
            "20240102",
            "2024/01/02",
            "2024-13-01",
            "2024-00-01",
            "2024-01-00",
            "2024-02-30",
            "2024-04-31",
            "2024-01-32",
            "2024-1-2",
            "24-01-02",
            "2024-01-02T00:00:00",
            "2024-01-02 00:00:00",
            "2024-01-02Z",
            "abcd-ef-gh",
            "2024-01-02-extra",
            [],
            {},
            object(),
        ],
    )
    def test_invalid_input_returns_none(self, bad_input):
        assert tc.previous_trade_date(bad_input) is None


# ---------------------------------------------------------------------------
# Non-trading days
# ---------------------------------------------------------------------------

class TestNonTradingDays:
    def test_saturday(self):
        # 2024-01-06 is Saturday
        assert tc.previous_trade_date("2024-01-06") is None

    def test_sunday(self):
        # 2024-01-07 is Sunday
        assert tc.previous_trade_date("2024-01-07") is None

    def test_holiday_weekday_new_year_2024(self):
        # 2024-01-01 is Monday but New Year holiday
        assert tc.previous_trade_date("2024-01-01") is None

    def test_holiday_weekday_spring_festival_2024(self):
        # 2024-02-12 is Monday but Spring Festival
        assert tc.previous_trade_date("2024-02-12") is None

    @pytest.mark.parametrize("weekend_date", MAKEUP_WEEKENDS)
    def test_makeup_workday_weekend(self, weekend_date):
        assert tc.previous_trade_date(weekend_date) is None

    def test_before_supported_range(self):
        assert tc.previous_trade_date("2023-12-29") is None

    def test_after_supported_range(self):
        assert tc.previous_trade_date("2027-01-04") is None

    def test_future_date(self):
        tc._today_shanghai = lambda: date(2026, 8, 3)
        # 2026-08-04 is Monday and within range but future
        assert tc.previous_trade_date("2026-08-04") is None

    def test_today_is_allowed(self):
        """The monkeypatched 'today' itself is not a future date."""
        tc._today_shanghai = lambda: date(2026, 8, 3)
        # 2026-08-03 is Monday; verify it's a session
        sessions = _load_sessions()
        if "2026-08-03" in sessions:
            result = tc.previous_trade_date("2026-08-03")
            assert result is not None
            assert result < "2026-08-03"


# ---------------------------------------------------------------------------
# Data integrity
# ---------------------------------------------------------------------------

class TestDataIntegrity:
    def _write_and_test(self, tmp_path, monkeypatch, content):
        """Write content to a temp JSON file, patch _DATA_PATH, assert None."""
        bad_file = tmp_path / "bad_calendar.json"
        if isinstance(content, str):
            bad_file.write_text(content, encoding="utf-8")
        else:
            with open(bad_file, "w", encoding="utf-8") as f:
                json.dump(content, f)
        tc._calendar_cache = None
        monkeypatch.setattr(tc, "_DATA_PATH", str(bad_file))
        assert tc.previous_trade_date("2024-01-03") is None

    def test_bad_schema_version(self, tmp_path, monkeypatch, sessions):
        self._write_and_test(tmp_path, monkeypatch, {
            "schema_version": "wrong",
            "calendar_id": "CN_A_SHARE",
            "timezone": "Asia/Shanghai",
            "supported_start_date": "2024-01-01",
            "supported_end_date": "2026-12-31",
            "sources": [],
            "sessions": sessions,
        })

    def test_bad_calendar_id(self, tmp_path, monkeypatch, sessions):
        self._write_and_test(tmp_path, monkeypatch, {
            "schema_version": "cn-a-share-trade-calendar-v0.1",
            "calendar_id": "WRONG",
            "timezone": "Asia/Shanghai",
            "supported_start_date": "2024-01-01",
            "supported_end_date": "2026-12-31",
            "sources": [],
            "sessions": sessions,
        })

    def test_missing_file(self, tmp_path, monkeypatch):
        tc._calendar_cache = None
        monkeypatch.setattr(tc, "_DATA_PATH", str(tmp_path / "nonexistent.json"))
        assert tc.previous_trade_date("2024-01-03") is None

    def test_invalid_json(self, tmp_path, monkeypatch):
        self._write_and_test(tmp_path, monkeypatch, "{not valid json")

    def test_empty_sessions(self, tmp_path, monkeypatch):
        self._write_and_test(tmp_path, monkeypatch, {
            "schema_version": "cn-a-share-trade-calendar-v0.1",
            "calendar_id": "CN_A_SHARE",
            "sessions": [],
        })

    def test_duplicate_sessions(self, tmp_path, monkeypatch):
        self._write_and_test(tmp_path, monkeypatch, {
            "schema_version": "cn-a-share-trade-calendar-v0.1",
            "calendar_id": "CN_A_SHARE",
            "sessions": ["2024-01-02", "2024-01-02", "2024-01-03"],
        })

    def test_unsorted_sessions(self, tmp_path, monkeypatch):
        self._write_and_test(tmp_path, monkeypatch, {
            "schema_version": "cn-a-share-trade-calendar-v0.1",
            "calendar_id": "CN_A_SHARE",
            "sessions": ["2024-01-03", "2024-01-02"],
        })

    def test_weekend_in_sessions(self, tmp_path, monkeypatch):
        # 2024-01-06 is Saturday
        self._write_and_test(tmp_path, monkeypatch, {
            "schema_version": "cn-a-share-trade-calendar-v0.1",
            "calendar_id": "CN_A_SHARE",
            "sessions": ["2024-01-02", "2024-01-03", "2024-01-06"],
        })

    def test_out_of_range_sessions(self, tmp_path, monkeypatch):
        self._write_and_test(tmp_path, monkeypatch, {
            "schema_version": "cn-a-share-trade-calendar-v0.1",
            "calendar_id": "CN_A_SHARE",
            "sessions": ["2024-01-02", "2024-01-03", "2027-01-04"],
        })

    def test_invalid_date_in_sessions(self, tmp_path, monkeypatch):
        self._write_and_test(tmp_path, monkeypatch, {
            "schema_version": "cn-a-share-trade-calendar-v0.1",
            "calendar_id": "CN_A_SHARE",
            "sessions": ["2024-01-02", "2024-13-01"],
        })

    def test_non_string_in_sessions(self, tmp_path, monkeypatch):
        self._write_and_test(tmp_path, monkeypatch, {
            "schema_version": "cn-a-share-trade-calendar-v0.1",
            "calendar_id": "CN_A_SHARE",
            "sessions": ["2024-01-02", 20240103],
        })


# ---------------------------------------------------------------------------
# Invariants
# ---------------------------------------------------------------------------

class TestInvariants:
    def test_return_strictly_before_input(self, sessions):
        for s in sessions[1:50]:
            result = tc.previous_trade_date(s)
            assert result is not None
            assert result < s

    def test_return_in_sessions(self, sessions):
        session_set = set(sessions)
        for s in sessions[1:50]:
            result = tc.previous_trade_date(s)
            assert result in session_set

    def test_deterministic(self, sessions):
        for s in ["2024-03-15", "2025-06-20", "2026-09-10"]:
            if s in sessions:
                r1 = tc.previous_trade_date(s)
                r2 = tc.previous_trade_date(s)
                assert r1 == r2

    def test_input_not_modified(self):
        inp = "2024-03-15"
        tc.previous_trade_date(inp)
        assert inp == "2024-03-15"

    def test_no_exception_for_any_input(self):
        for bad in [None, 0, "", "garbage", "2024-02-30", 3.14, [], {}]:
            # Must not raise
            result = tc.previous_trade_date(bad)
            assert result is None

    def test_no_network_imports(self):
        """Verify the module source does not import network libraries."""
        source_path = os.path.join(os.path.dirname(tc.__file__), "trade_calendar.py")
        with open(source_path, encoding="utf-8") as f:
            source = f.read()
        forbidden = ["requests", "urllib", "httpx", "akshare",
                      "exchange_calendars", "pandas_market_calendars"]
        for lib in forbidden:
            assert f"import {lib}" not in source, f"Forbidden import: {lib}"
            assert f"from {lib}" not in source, f"Forbidden import: {lib}"


# ---------------------------------------------------------------------------
# Year boundaries
# ---------------------------------------------------------------------------

class TestYearBoundaries:
    def test_first_session_returns_none(self, sessions):
        assert sessions[0] == "2024-01-02"
        assert tc.previous_trade_date("2024-01-02") is None

    def test_2024_to_2025_boundary(self, sessions):
        # 2025-01-02 (Thu) → previous = 2024-12-31 (Tue)
        assert "2025-01-02" in sessions
        result = tc.previous_trade_date("2025-01-02")
        assert result == "2024-12-31"

    def test_2025_to_2026_boundary(self, sessions):
        # 2026-01-05 (Mon) → previous = 2025-12-31 (Wed)
        assert "2026-01-05" in sessions
        result = tc.previous_trade_date("2026-01-05")
        assert result == "2025-12-31"

    def test_2026_last_past_session(self, sessions):
        """With 'today' patched to 2026-08-03, verify the last past session."""
        tc._today_shanghai = lambda: date(2026, 8, 3)
        # 2026-07-31 is Friday; verify it's a session
        if "2026-07-31" in sessions:
            result = tc.previous_trade_date("2026-07-31")
            assert result is not None
            assert result < "2026-07-31"

    def test_last_session_in_range(self, sessions):
        """The very last session (2026-12-31) has a valid previous."""
        last = sessions[-1]
        assert last == "2026-12-31"
        result = tc.previous_trade_date(last)
        assert result is not None
        assert result < last
