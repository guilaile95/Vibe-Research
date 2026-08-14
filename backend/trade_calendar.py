"""BK-11 A-share trade calendar: deterministic offline session lookup.

The public lookups use an offline artifact built from official SSE/SZSE
holiday announcements.  :func:`previous_trade_date` returns the most recent
confirmed session strictly before another confirmed session.
:func:`completed_trade_date_at` maps an explicit UTC instant to the most recent
A-share session completed by that instant using a frozen Asia/Shanghai 15:00
close boundary.  :func:`observation_trade_date_at` maps an explicit UTC instant
to the MARKET OBSERVATION DATE of that instant (session-day semantics: a
session date maps to itself intraday or post-close, a weekend/holiday maps to
the latest earlier session).

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

__all__ = [
    "CALENDAR_AUTHORITY_REF",
    "OBSERVATION_AUTHORITY_REF",
    "completed_trade_date_at",
    "observation_trade_date_at",
    "previous_trade_date",
]

CALENDAR_AUTHORITY_REF = "trade_calendar:completed_trade_date:v0.1"
OBSERVATION_AUTHORITY_REF = "trade_calendar:market_observation_date:v0.1"

_DATA_PATH = os.path.join(
    os.path.dirname(__file__), "data", "cn_a_share_trade_calendar_v01.json"
)
_SCHEMA_VERSION = "cn-a-share-trade-calendar-v0.1"
_CALENDAR_ID = "CN_A_SHARE"
_SHANGHAI_TZ = timezone(timedelta(hours=8))
_SUPPORTED_START = date(2024, 1, 1)
_SUPPORTED_END = date(2026, 12, 31)

_TIMEZONE = "Asia/Shanghai"
_SOURCE_POLICY = "SSE_SZSE_OFFICIAL_CONSENSUS"
_SUPPORTED_START_DATE = "2024-01-01"
_SUPPORTED_END_DATE = "2026-12-31"
_REQUIRED_EXCHANGE_YEARS = {
    ("SSE", 2024), ("SZSE", 2024),
    ("SSE", 2025), ("SZSE", 2025),
    ("SSE", 2026), ("SZSE", 2026),
}
_ALLOWED_OFFICIAL_HOSTS = {"www.sse.com.cn", "sse.com.cn", "www.szse.cn", "szse.cn"}

_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_UTC_ZERO_OFFSET_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"
    r"(?:\.\d{1,6})?(?:Z|\+00:00)$"
)
_URL_HOST_RE = re.compile(r"^[a-z][a-z0-9+.\-]*://([^/?#]+)", re.IGNORECASE)

_calendar_cache: Optional[tuple[str, ...]] = None
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


def _url_host_official(url: object) -> bool:
    """Return True when *url* is a non-empty string whose host is SSE/SZSE official."""
    if not isinstance(url, str) or not url:
        return False
    m = _URL_HOST_RE.match(url)
    if m is None:
        return False
    return m.group(1).lower() in _ALLOWED_OFFICIAL_HOSTS


def _validate_sources(raw: object) -> bool:
    """Validate the ``sources`` value from JSON; return True on success only."""
    if not isinstance(raw, list) or not raw:
        return False
    seen: set[tuple[str, int]] = set()
    for entry in raw:
        if not isinstance(entry, dict):
            return False
        exchange = entry.get("exchange")
        if exchange not in ("SSE", "SZSE"):
            return False
        year = entry.get("year")
        if year not in (2024, 2025, 2026):
            return False
        key = (exchange, year)
        if key in seen:
            return False
        seen.add(key)
        title = entry.get("title")
        if not isinstance(title, str) or not title:
            return False
        announcement_date = entry.get("announcement_date")
        if not isinstance(announcement_date, str) or _DATE_RE.match(announcement_date) is None:
            return False
        if _parse_strict_date(announcement_date) is None:
            return False
        reference_number = entry.get("reference_number")
        if not isinstance(reference_number, str) or not reference_number:
            return False
        if not _url_host_official(entry.get("URL")):
            return False
        retrieved_at = entry.get("retrieved_at")
        if not isinstance(retrieved_at, str) or not retrieved_at:
            return False
        if entry.get("verification_status") != "verified_direct_official":
            return False
    return seen == _REQUIRED_EXCHANGE_YEARS


def _validate_metadata(data: dict) -> bool:
    """Validate runtime metadata beyond schema/calendar_id/sessions."""
    if data.get("timezone") != _TIMEZONE:
        return False
    if data.get("source_policy") != _SOURCE_POLICY:
        return False
    if data.get("supported_start_date") != _SUPPORTED_START_DATE:
        return False
    if data.get("supported_end_date") != _SUPPORTED_END_DATE:
        return False
    if not _validate_sources(data.get("sources")):
        return False
    return True


def _load_calendar() -> Optional[tuple[str, ...]]:
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
        except (FileNotFoundError, UnicodeDecodeError, json.JSONDecodeError, OSError):
            return None
        if not isinstance(data, dict):
            return None
        if data.get("schema_version") != _SCHEMA_VERSION:
            return None
        if data.get("calendar_id") != _CALENDAR_ID:
            return None
        if not _validate_metadata(data):
            return None
        sessions = _validate_sessions(data.get("sessions"))
        if sessions is None:
            return None
        cached: tuple[str, ...] = tuple(sessions)
        _calendar_cache = cached
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


def _session_date_at(
    as_of: str, completed_from: tuple[int, int, int, int]
) -> Optional[str]:
    """Shared session lookup for an explicit canonical UTC instant.

    Validate *as_of*, convert it to Asia/Shanghai, and return the latest
    confirmed session for the local calendar date.  When the local time is
    at or after *completed_from* on that date, the date itself may be the
    returned session; otherwise only strictly earlier sessions are
    considered.  Fails closed with ``None`` for invalid input, a Shanghai
    date outside the supported range, no prior session, or a corrupted
    artifact.  Never consults the wall clock.
    """
    if not isinstance(as_of, str) or _UTC_ZERO_OFFSET_RE.fullmatch(as_of) is None:
        return None
    parse_text = as_of[:-1] + "+00:00" if as_of.endswith("Z") else as_of
    try:
        parsed = datetime.fromisoformat(parse_text)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        return None

    local = parsed.astimezone(_SHANGHAI_TZ)
    local_date = local.date()
    if local_date < _SUPPORTED_START or local_date > _SUPPORTED_END:
        return None

    sessions = _load_calendar()
    if sessions is None:
        return None

    local_date_text = local_date.isoformat()
    reached = (
        local.hour,
        local.minute,
        local.second,
        local.microsecond,
    ) >= completed_from

    if reached:
        idx = bisect.bisect_right(sessions, local_date_text)
    else:
        idx = bisect.bisect_left(sessions, local_date_text)
    if idx == 0:
        return None
    return sessions[idx - 1]


def completed_trade_date_at(as_of: str) -> Optional[str]:
    """Return the latest A-share session completed at explicit UTC *as_of*.

    ``as_of`` must be a canonical UTC zero-offset instant accepted by the
    decision-authority contract: seconds are required, fractional seconds may
    contain one to six digits, and the suffix must be exactly ``Z`` or
    ``+00:00``.  Naive timestamps and non-zero offsets are rejected rather
    than silently normalized.

    The instant is converted to Asia/Shanghai.  On a confirmed session date,
    that session becomes completed at exactly 15:00:00 local time; before the
    boundary, the preceding confirmed session is returned.  On a weekend or
    exchange holiday, the latest earlier confirmed session is returned.

    No wall clock is consulted.  ``None`` is returned when the timestamp is
    invalid, its Shanghai calendar date is outside the artifact's supported
    range, no prior completed session exists, or the artifact fails runtime
    validation.
    """
    return _session_date_at(as_of, (15, 0, 0, 0))


def observation_trade_date_at(observed_at: str) -> Optional[str]:
    """Return the A-share MARKET OBSERVATION DATE at explicit UTC *observed_at*.

    The input contract is identical to :func:`completed_trade_date_at`
    (canonical UTC zero-offset instant).  The mapping uses session-day
    semantics instead of the 15:00 close boundary:

    - an instant on a confirmed session date belongs to that session's
      market observation (intraday or post-close);
    - an instant on a weekend or exchange holiday maps to the latest earlier
      confirmed session — the most recent trading day whose data a live
      snapshot can reflect.

    Callers must feed the real observation timestamp recorded at the data
    fetch boundary (never a caller-supplied ``as_of``) to attribute which
    market observation date a snapshot belongs to.  No wall clock is
    consulted; ``None`` is returned on the same fail-closed conditions as
    :func:`completed_trade_date_at`.
    """
    return _session_date_at(observed_at, (0, 0, 0, 0))
