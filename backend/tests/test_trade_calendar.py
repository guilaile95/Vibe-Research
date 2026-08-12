"""Tests for deterministic lookups in :mod:`backend.trade_calendar`.

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
import threading
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
# Explicit as_of -> completed session authority
# ---------------------------------------------------------------------------

class TestCompletedTradeDateAt:
    def test_public_authority_reference_is_stable(self):
        assert (
            tc.CALENDAR_AUTHORITY_REF
            == "trade_calendar:completed_trade_date:v0.1"
        )
        assert "CALENDAR_AUTHORITY_REF" in tc.__all__
        assert "completed_trade_date_at" in tc.__all__

    def test_intraday_uses_previous_confirmed_session(self):
        # 2024-01-03 14:59:59.999999 Asia/Shanghai.
        assert (
            tc.completed_trade_date_at("2024-01-03T06:59:59.999999Z")
            == "2024-01-02"
        )

    @pytest.mark.parametrize(
        "as_of",
        [
            "2024-01-03T07:00:00Z",
            "2024-01-03T07:00:00+00:00",
            "2024-01-03T07:00:00.000000Z",
            "2024-01-03T07:00:00.000000+00:00",
        ],
    )
    def test_exact_1500_shanghai_boundary_completes_session(self, as_of):
        assert tc.completed_trade_date_at(as_of) == "2024-01-03"

    def test_after_close_uses_same_confirmed_session(self):
        # 2024-01-03 15:00:00.000001 Asia/Shanghai.
        assert (
            tc.completed_trade_date_at("2024-01-03T07:00:00.000001Z")
            == "2024-01-03"
        )

    def test_weekend_uses_latest_previous_session(self):
        # Sunday 2024-01-07 12:00 Asia/Shanghai.
        assert (
            tc.completed_trade_date_at("2024-01-07T04:00:00Z")
            == "2024-01-05"
        )

    def test_saturday_uses_latest_previous_session(self):
        # Saturday 2024-01-06 12:00 Asia/Shanghai.
        assert (
            tc.completed_trade_date_at("2024-01-06T04:00:00Z")
            == "2024-01-05"
        )

    def test_exchange_holiday_uses_latest_previous_session(self):
        # Monday 2024-02-12 is inside the Spring Festival closure.
        assert (
            tc.completed_trade_date_at("2024-02-12T04:00:00Z")
            == "2024-02-08"
        )

    def test_first_session_after_holiday_before_close_uses_preholiday_session(self):
        # 2024-02-19 is the first confirmed session after Spring Festival.
        assert (
            tc.completed_trade_date_at("2024-02-19T06:59:59Z")
            == "2024-02-08"
        )

    def test_first_session_after_holiday_at_close_uses_current_session(self):
        assert (
            tc.completed_trade_date_at("2024-02-19T07:00:00Z")
            == "2024-02-19"
        )

    def test_utc_date_to_next_shanghai_date_crossover(self):
        # 2024-01-02 23:30 UTC is 2024-01-03 07:30 Shanghai; the
        # 2024-01-03 session is not yet completed, so 2024-01-02 is selected.
        assert (
            tc.completed_trade_date_at("2024-01-02T23:30:00Z")
            == "2024-01-02"
        )

    def test_first_session_before_close_has_no_supported_predecessor(self):
        assert tc.completed_trade_date_at("2024-01-02T06:59:59Z") is None

    def test_first_session_at_close_is_completed(self):
        assert (
            tc.completed_trade_date_at("2024-01-02T07:00:00Z")
            == "2024-01-02"
        )

    @pytest.mark.parametrize(
        "as_of",
        [
            "2023-12-31T04:00:00Z",
            "2027-01-01T04:00:00Z",
        ],
    )
    def test_shanghai_date_outside_supported_range_fails_closed(self, as_of):
        assert tc.completed_trade_date_at(as_of) is None

    def test_last_supported_session_at_close_is_completed(self):
        assert (
            tc.completed_trade_date_at("2026-12-31T07:00:00Z")
            == "2026-12-31"
        )

    @pytest.mark.parametrize(
        "bad_input",
        [
            None,
            20240102,
            True,
            "",
            " 2024-01-03T07:00:00Z",
            "2024-01-03T07:00:00Z ",
            "2024-01-03",
            "2024-01-03 07:00:00Z",
            "2024-01-03T07:00Z",
            "2024-01-03T07:00:00",
            "2024-01-03T07:00:00z",
            "2024-01-03T07:00:00+08:00",
            "2024-01-03T07:00:00-00:00",
            "2024-01-03T07:00:00+0000",
            "2024-01-03T07:00:00.0000000Z",
            "2024-02-30T07:00:00Z",
            "2024-01-03T24:00:00Z",
            [],
            {},
        ],
    )
    def test_invalid_or_nonzero_offset_input_fails_closed(self, bad_input):
        assert tc.completed_trade_date_at(bad_input) is None

    def test_corrupted_calendar_fails_closed(self, tmp_path, monkeypatch):
        bad_file = tmp_path / "bad_calendar.json"
        bad_file.write_text("{not valid json", encoding="utf-8")
        tc._calendar_cache = None
        monkeypatch.setattr(tc, "_DATA_PATH", str(bad_file))

        assert tc.completed_trade_date_at("2024-01-03T07:00:00Z") is None

    def test_does_not_consult_wall_clock(self, monkeypatch):
        def forbidden_wall_clock():
            raise AssertionError("completed_trade_date_at must not read wall clock")

        monkeypatch.setattr(tc, "_today_shanghai", forbidden_wall_clock)
        assert (
            tc.completed_trade_date_at("2025-03-17T07:00:00Z")
            == "2025-03-17"
        )

    def test_repeated_calls_are_deterministic(self):
        results = {
            tc.completed_trade_date_at("2025-03-17T07:00:00.000001Z")
            for _ in range(100)
        }
        assert results == {"2025-03-17"}


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
        # 2026-08-04 is Tuesday and within range but future
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


# ---------------------------------------------------------------------------
# Metadata corruption (runtime validation, fail-closed)
# ---------------------------------------------------------------------------

def _valid_artifact(sessions: list[str]) -> dict:
    """Build a minimal valid artifact that passes all runtime metadata checks."""
    return {
        "schema_version": "cn-a-share-trade-calendar-v0.1",
        "calendar_id": "CN_A_SHARE",
        "timezone": "Asia/Shanghai",
        "source_policy": "SSE_SZSE_OFFICIAL_CONSENSUS",
        "supported_start_date": "2024-01-01",
        "supported_end_date": "2026-12-31",
        "sources": [
            {"exchange": "SSE",  "year": 2024, "title": "SSE 2024",
             "announcement_date": "2023-12-26",
             "reference_number": "上证公告〔2023〕47号",
             "URL": "https://www.sse.com.cn/x/y.shtml",
             "retrieved_at": "2026-08-03T00:00:00Z",
             "verification_status": "verified_direct_official"},
            {"exchange": "SZSE", "year": 2024, "title": "SZSE 2024",
             "announcement_date": "2023-12-26",
             "reference_number": "深证会〔2023〕409号",
             "URL": "https://www.szse.cn/x/y.html",
             "retrieved_at": "2026-08-03T00:00:00Z",
             "verification_status": "verified_direct_official"},
            {"exchange": "SSE",  "year": 2025, "title": "SSE 2025",
             "announcement_date": "2024-12-23",
             "reference_number": "上证公告〔2024〕38号",
             "URL": "https://www.sse.com.cn/x/z.shtml",
             "retrieved_at": "2026-08-03T00:00:00Z",
             "verification_status": "verified_direct_official"},
            {"exchange": "SZSE", "year": 2025, "title": "SZSE 2025",
             "announcement_date": "2024-12-23",
             "reference_number": "深证会〔2024〕413号",
             "URL": "https://www.szse.cn/x/z.html",
             "retrieved_at": "2026-08-03T00:00:00Z",
             "verification_status": "verified_direct_official"},
            {"exchange": "SSE",  "year": 2026, "title": "SSE 2026",
             "announcement_date": "2025-12-22",
             "reference_number": "上证公告〔2025〕45号",
             "URL": "https://www.sse.com.cn/x/w.shtml",
             "retrieved_at": "2026-08-03T00:00:00Z",
             "verification_status": "verified_direct_official"},
            {"exchange": "SZSE", "year": 2026, "title": "SZSE 2026",
             "announcement_date": "2025-12-22",
             "reference_number": "深证会〔2025〕481号",
             "URL": "https://www.szse.cn/x/w.html",
             "retrieved_at": "2026-08-03T00:00:00Z",
             "verification_status": "verified_direct_official"},
        ],
        "sessions": sessions,
    }


class TestMetadataCorruption:
    def _patch_and_assert_none(self, tmp_path, monkeypatch, data):
        bad_file = tmp_path / "bad_calendar.json"
        with open(bad_file, "w", encoding="utf-8") as f:
            json.dump(data, f)
        tc._calendar_cache = None
        monkeypatch.setattr(tc, "_DATA_PATH", str(bad_file))
        assert tc.previous_trade_date("2024-01-03") is None

    def test_invalid_utf8_returns_none(self, tmp_path, monkeypatch):
        bad_file = tmp_path / "bad_calendar.json"
        bad_file.write_bytes(b"\xff\xfe\x80\x81not-utf8")
        tc._calendar_cache = None
        monkeypatch.setattr(tc, "_DATA_PATH", str(bad_file))
        assert tc.previous_trade_date("2024-01-03") is None

    def test_top_level_json_list_returns_none(self, tmp_path, monkeypatch):
        bad_file = tmp_path / "bad_calendar.json"
        with open(bad_file, "w", encoding="utf-8") as f:
            json.dump(["not", "a", "dict"], f)
        tc._calendar_cache = None
        monkeypatch.setattr(tc, "_DATA_PATH", str(bad_file))
        assert tc.previous_trade_date("2024-01-03") is None

    def test_wrong_timezone(self, tmp_path, monkeypatch, sessions):
        data = _valid_artifact(sessions)
        data["timezone"] = "UTC"
        self._patch_and_assert_none(tmp_path, monkeypatch, data)

    def test_wrong_source_policy(self, tmp_path, monkeypatch, sessions):
        data = _valid_artifact(sessions)
        data["source_policy"] = "OTHER"
        self._patch_and_assert_none(tmp_path, monkeypatch, data)

    def test_wrong_supported_start_date(self, tmp_path, monkeypatch, sessions):
        data = _valid_artifact(sessions)
        data["supported_start_date"] = "2024-01-02"
        self._patch_and_assert_none(tmp_path, monkeypatch, data)

    def test_wrong_supported_end_date(self, tmp_path, monkeypatch, sessions):
        data = _valid_artifact(sessions)
        data["supported_end_date"] = "2026-12-30"
        self._patch_and_assert_none(tmp_path, monkeypatch, data)

    def test_sources_missing(self, tmp_path, monkeypatch, sessions):
        data = _valid_artifact(sessions)
        del data["sources"]
        self._patch_and_assert_none(tmp_path, monkeypatch, data)

    def test_sources_not_list(self, tmp_path, monkeypatch, sessions):
        data = _valid_artifact(sessions)
        data["sources"] = {}
        self._patch_and_assert_none(tmp_path, monkeypatch, data)

    def test_sources_empty(self, tmp_path, monkeypatch, sessions):
        data = _valid_artifact(sessions)
        data["sources"] = []
        self._patch_and_assert_none(tmp_path, monkeypatch, data)

    def test_sources_missing_exchange_year(self, tmp_path, monkeypatch, sessions):
        data = _valid_artifact(sessions)
        data["sources"] = data["sources"][:5]  # drop one required (exchange,year)
        self._patch_and_assert_none(tmp_path, monkeypatch, data)

    def test_sources_duplicate_exchange_year(self, tmp_path, monkeypatch, sessions):
        data = _valid_artifact(sessions)
        data["sources"].append(data["sources"][0])
        self._patch_and_assert_none(tmp_path, monkeypatch, data)

    def test_sources_url_empty(self, tmp_path, monkeypatch, sessions):
        data = _valid_artifact(sessions)
        data["sources"][0]["URL"] = ""
        self._patch_and_assert_none(tmp_path, monkeypatch, data)

    def test_sources_url_non_official_host(self, tmp_path, monkeypatch, sessions):
        data = _valid_artifact(sessions)
        data["sources"][0]["URL"] = "https://example.com/x.shtml"
        self._patch_and_assert_none(tmp_path, monkeypatch, data)

    def test_source_title_empty(self, tmp_path, monkeypatch, sessions):
        data = _valid_artifact(sessions)
        data["sources"][0]["title"] = ""
        self._patch_and_assert_none(tmp_path, monkeypatch, data)

    def test_source_announcement_date_invalid(self, tmp_path, monkeypatch, sessions):
        data = _valid_artifact(sessions)
        data["sources"][0]["announcement_date"] = "2023/12/26"
        self._patch_and_assert_none(tmp_path, monkeypatch, data)

    def test_source_reference_number_empty(self, tmp_path, monkeypatch, sessions):
        data = _valid_artifact(sessions)
        data["sources"][0]["reference_number"] = ""
        self._patch_and_assert_none(tmp_path, monkeypatch, data)

    def test_source_verification_status_wrong(self, tmp_path, monkeypatch, sessions):
        data = _valid_artifact(sessions)
        data["sources"][0]["verification_status"] = "verified"
        self._patch_and_assert_none(tmp_path, monkeypatch, data)

    def test_cache_is_tuple_on_success(self, sessions):
        tc._calendar_cache = None
        result = tc.previous_trade_date("2024-01-03")
        assert result == "2024-01-02"
        assert isinstance(tc._calendar_cache, tuple)


# ---------------------------------------------------------------------------
# Concurrency
# ---------------------------------------------------------------------------

class TestConcurrency:
    def test_20_threads_first_load_consistent(self, sessions):
        """20 threads concurrently first-load; all results identical, no exception."""
        tc._calendar_cache = None
        results: list = []
        errors: list = []

        def worker():
            try:
                r = tc.previous_trade_date("2025-03-17")
                results.append(r)
            except BaseException as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        assert len(results) == 20
        assert all(r == results[0] for r in results)
        assert results[0] is not None
        assert isinstance(tc._calendar_cache, tuple)


# ---------------------------------------------------------------------------
# Independent official-closure contract
# ---------------------------------------------------------------------------

# Official closed weekday ranges (Mon-Fri only) derived independently from the
# six SSE/SZSE annual notices (sse.com.cn + szse.cn). NOT derived from the
# artifact sessions.
OFFICIAL_CLOSED_WEEKDAYS_2024: list[str] = [
    # 元旦: 2024-01-01 (Mon)
    "2024-01-01",
    # 春节: 2024-02-09 (Fri), 2024-02-12 (Mon), 2024-02-13 (Tue),
    #        2024-02-14 (Wed), 2024-02-15 (Thu), 2024-02-16 (Fri)
    "2024-02-09", "2024-02-12", "2024-02-13",
    "2024-02-14", "2024-02-15", "2024-02-16",
    # 清明节: 2024-04-04 (Thu), 2024-04-05 (Fri)
    "2024-04-04", "2024-04-05",
    # 劳动节: 2024-05-01 (Wed), 2024-05-02 (Thu), 2024-05-03 (Fri)
    "2024-05-01", "2024-05-02", "2024-05-03",
    # 端午节: 2024-06-10 (Mon)
    "2024-06-10",
    # 中秋节: 2024-09-16 (Mon), 2024-09-17 (Tue)
    "2024-09-16", "2024-09-17",
    # 国庆节: 2024-10-01 (Tue) - 2024-10-04 (Fri), 2024-10-07 (Mon)
    "2024-10-01", "2024-10-02", "2024-10-03", "2024-10-04", "2024-10-07",
]
OFFICIAL_CLOSED_WEEKDAYS_2025: list[str] = [
    # 元旦: 2025-01-01 (Wed)
    "2025-01-01",
    # 春节: 2025-01-28 (Tue), 2025-01-29 (Wed), 2025-01-30 (Thu),
    #        2025-01-31 (Fri), 2025-02-03 (Mon), 2025-02-04 (Tue)
    "2025-01-28", "2025-01-29", "2025-01-30",
    "2025-01-31", "2025-02-03", "2025-02-04",
    # 清明节: 2025-04-04 (Fri)
    "2025-04-04",
    # 劳动节: 2025-05-01 (Thu), 2025-05-02 (Fri), 2025-05-05 (Mon)
    "2025-05-01", "2025-05-02", "2025-05-05",
    # 端午节: 2025-06-02 (Mon)
    "2025-06-02",
    # 国庆节+中秋节: 2025-10-01 (Wed) - 2025-10-03 (Fri), 2025-10-06 (Mon),
    #                 2025-10-07 (Tue), 2025-10-08 (Wed)
    "2025-10-01", "2025-10-02", "2025-10-03",
    "2025-10-06", "2025-10-07", "2025-10-08",
]
OFFICIAL_CLOSED_WEEKDAYS_2026: list[str] = [
    # 元旦: 2026-01-01 (Thu), 2026-01-02 (Fri)
    "2026-01-01", "2026-01-02",
    # 春节: 2026-02-16 (Mon), 2026-02-17 (Tue), 2026-02-18 (Wed),
    #        2026-02-19 (Thu), 2026-02-20 (Fri), 2026-02-23 (Mon)
    "2026-02-16", "2026-02-17", "2026-02-18",
    "2026-02-19", "2026-02-20", "2026-02-23",
    # 清明节: 2026-04-06 (Mon)
    "2026-04-06",
    # 劳动节: 2026-05-01 (Fri), 2026-05-04 (Mon), 2026-05-05 (Tue)
    "2026-05-01", "2026-05-04", "2026-05-05",
    # 端午节: 2026-06-19 (Fri)
    "2026-06-19",
    # 中秋节: 2026-09-25 (Fri)
    "2026-09-25",
    # 国庆节: 2026-10-01 (Thu), 2026-10-02 (Fri), 2026-10-05 (Mon),
    #         2026-10-06 (Tue), 2026-10-07 (Wed)
    "2026-10-01", "2026-10-02", "2026-10-05",
    "2026-10-06", "2026-10-07",
]


def _build_expected_sessions() -> list[str]:
    """Build sessions independently from official closed weekday sets.

    expected = Mon-Fri in [2024-01-01..2026-12-31] - OFFICIAL_CLOSED_WEEKDAYS
    """
    closed: set[str] = set(
        OFFICIAL_CLOSED_WEEKDAYS_2024
        + OFFICIAL_CLOSED_WEEKDAYS_2025
        + OFFICIAL_CLOSED_WEEKDAYS_2026
    )
    expected: list[str] = []
    current = date(2024, 1, 1)
    end = date(2026, 12, 31)
    while current <= end:
        if current.weekday() < 5 and current.isoformat() not in closed:
            expected.append(current.isoformat())
        current = date.fromordinal(current.toordinal() + 1)
    return expected


class TestIndependentOfficialClosure:
    def test_artifact_matches_official_closure_contract(self, sessions):
        """Independent official-closure rebuild must equal artifact sessions."""
        expected = _build_expected_sessions()
        assert sessions == expected, (
            f"artifact differs from independent official-closure rebuild: "
            f"artifact_len={len(sessions)} expected_len={len(expected)} "
            f"missing_in_artifact={sorted(set(expected) - set(sessions))[:5]} "
            f"extra_in_artifact={sorted(set(sessions) - set(expected))[:5]}"
        )
