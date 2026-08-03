"""BK-11 A-share trade calendar: offline ``previous_trade_date`` lookup.

This module provides a single public function :func:`previous_trade_date` that
returns the most recent confirmed A-share trading day strictly before the
given date, based on an offline artifact built from official SSE/SZSE holiday
announcements.

The module is pure standard library, performs no network I/O, and fails
closed (returns ``None``) for any invalid input or corrupted data file.
"""
from __future__ import annotations

import bisect
import json
import os
import re
import threading
from datetime import date, datetime, timedelta, timezone
from typing import Optional

__all__ = ["previous_trade_date"]

_DATA_PATH = os.path.join(
    os.path.dirname(__file__), "data", "cn_a_share_trade_calendar_v01.json"
)
_SCHEMA_VERSION = "cn-a-share-trade-calendar-v0.1"
_CALENDAR_ID = "CN_A_SHARE"
_SHANGHAI_TZ = timezone(timedelta(hours=8))
_SUPPORTED_START = date(2024, 1, 1)
_SUPPORTED_END = date(2026, 12, 31)

_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")

_calendar_cache: Optional[list[str]] = None
_cache_lock = threading.Lock()


def _parse_strict_date(s: str) -> Optional[date]:
    """Parse a strict ``YYYY-MM-DD`` string; return ``None`` on any deviation."""
    m = _DATE_RE.match(s)
    if m is None:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def _today_shanghai() -> date:
    """Return today's date in Asia/Shanghai timezone.

    Monkeypatchable in tests for deterministic future-date behaviour.
    """
    return datetime.now(_SHANGHAI_TZ).date()


def _validate_sessions(raw: object) -> Optional[list[str]]:
    """Validate the raw ``sessions`` value from JSON; return list or ``None``."""
    if not isinstance(raw, list) or not raw:
        return None
    validated: list[str] = []
    seen: set[str] = set()
    for entry in raw:
        if not isinstance(entry, str):
            return None
        d = _parse_strict_date(entry)
        if d is None:
            return None
        if d.weekday() >= 5:
            return None  # weekend in sessions
        if d < _SUPPORTED_START or d > _SUPPORTED_END:
            return None  # out of supported range
        if entry in seen:
            return None  # duplicate
        if validated and entry <= validated[-1]:
            return None  # not strictly ascending
        seen.add(entry)
        validated.append(entry)
    return validated


def _load_calendar() -> Optional[list[str]]:
    """Load and validate the trade calendar; cache on success only."""
    global _calendar_cache
    if _calendar_cache is not None:
        return _calendar_cache
    with _cache_lock:
        if _calendar_cache is not None:
            return _calendar_cache
        try:
            with open(_DATA_PATH, encoding="utf-8") as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return None
        if not isinstance(data, dict):
            return None
        if data.get("schema_version") != _SCHEMA_VERSION:
            return None
        if data.get("calendar_id") != _CALENDAR_ID:
            return None
        sessions = _validate_sessions(data.get("sessions"))
        if sessions is None:
            return None
        _calendar_cache = sessions
        return _calendar_cache


def previous_trade_date(current_trade_date: str) -> Optional[str]:
    """Return the confirmed A-share trading day strictly before *current_trade_date*.

    Parameters
    ----------
    current_trade_date:
        A strict ``YYYY-MM-DD`` string representing a confirmed A-share
        trading day in the supported range.

    Returns
    -------
    The previous trading day as a ``YYYY-MM-DD`` string, or ``None`` when:

    - *current_trade_date* is not a strict ``YYYY-MM-DD`` string
    - *current_trade_date* is not a confirmed trading day in the offline calendar
    - *current_trade_date* is a future date relative to Asia/Shanghai today
    - there is no prior trading day in the supported range
    - the offline data file is missing, unreadable, or corrupted
    """
    if not isinstance(current_trade_date, str) or not current_trade_date:
        return None
    d = _parse_strict_date(current_trade_date)
    if d is None:
        return None
    # Future date relative to Asia/Shanghai today
    if d > _today_shanghai():
        return None
    sessions = _load_calendar()
    if sessions is None:
        return None
    # current_trade_date must itself be a confirmed session
    idx = bisect.bisect_left(sessions, current_trade_date)
    if idx >= len(sessions) or sessions[idx] != current_trade_date:
        return None  # not a confirmed trading day
    if idx == 0:
        return None  # no prior trading day
    return sessions[idx - 1]
