"""Narrow production client for HiThink unadjusted A-share daily bars.

HiThink is the preferred provider for the legacy ``astock.kline`` daily path
when ``HITHINK_FINANCE_API_KEY`` is configured.  This module deliberately does
not define canonical facts or alter the Tushare Fact Lake authority.  It
validates a provider observation and projects it into the existing K-line row
contract; callers retain the established mootdx fallback.
"""

from __future__ import annotations

import json
import math
import os
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import requests

from security_exchange_policy import (
    POLICY_VERSION_V01,
    SecurityExchangePolicyValidationError,
    resolve_security_exchange,
)


BASE_URL = "https://fuyao.aicubes.cn"
DAILY_ENDPOINT = "/api/a-share/prices/historical"
API_KEY_ENV = "HITHINK_FINANCE_API_KEY"
PROVIDER_ID = "hithink_financial_api"
PROVIDER_CONTRACT = "hithink-daily-bars-v0.1"
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
MAX_OFFSET = 2000
_SHANGHAI = ZoneInfo("Asia/Shanghai")
_PROVIDER_SUFFIX = {"SSE": "SH", "SZSE": "SZ", "BSE": "BJ"}


class HiThinkClientError(RuntimeError):
    """Base error with a credential-safe message."""


class HiThinkNotConfiguredError(HiThinkClientError):
    """The optional production credential is absent."""


class HiThinkTransportError(HiThinkClientError):
    """The provider could not be reached or returned non-JSON content."""


class HiThinkBusinessError(HiThinkClientError):
    """The provider envelope reported a non-zero business code."""


class HiThinkContractError(HiThinkClientError):
    """A successful provider payload violated the qualified contract."""


class HiThinkUnsupportedSecurityError(HiThinkClientError):
    """The qualified provider route does not cover this security identity."""


def is_configured() -> bool:
    """Return whether a non-empty key is available without exposing it."""
    return bool(os.environ.get(API_KEY_ENV, "").strip())


def _api_key() -> str:
    value = os.environ.get(API_KEY_ENV, "").strip()
    if not value:
        raise HiThinkNotConfiguredError(f"{API_KEY_ENV} is not configured")
    return value


def provider_thscode(security_code: str) -> str:
    """Resolve an existing canonical security code to a qualified alias.

    Current ``920xxx`` BSE identities are covered by live meta, snapshot and
    daily-bar evidence.  Legacy BSE codes remain excluded because the
    canonical exchange policy proves their exchange but deliberately does not
    invent the provider's old-to-new code mapping.
    """
    try:
        result = resolve_security_exchange(
            security_code=security_code,
            policy_version=POLICY_VERSION_V01,
        )
    except SecurityExchangePolicyValidationError as exc:
        raise HiThinkUnsupportedSecurityError(
            "security code is invalid under the canonical policy"
        ) from exc
    if result["exchange_resolution_state"] != "RESOLVED":
        raise HiThinkUnsupportedSecurityError(
            "security exchange is not resolved by the canonical policy"
        )
    suffix = _PROVIDER_SUFFIX.get(result["exchange"])
    if suffix is None:
        raise HiThinkUnsupportedSecurityError(
            "HiThink live qualification does not cover this exchange"
        )
    if result["exchange"] == "BSE" and not security_code.startswith("920"):
        raise HiThinkUnsupportedSecurityError(
            "HiThink live qualification does not cover legacy BSE identities"
        )
    return f"{security_code}.{suffix}"


def is_current_bse_security(security_code: object) -> bool:
    """Return whether the canonical policy resolves a current 920xxx BSE code."""
    if type(security_code) is not str or not security_code.startswith("920"):
        return False
    try:
        result = resolve_security_exchange(
            security_code=security_code,
            policy_version=POLICY_VERSION_V01,
        )
    except SecurityExchangePolicyValidationError:
        return False
    return (
        result["exchange_resolution_state"] == "RESOLVED"
        and result["exchange"] == "BSE"
    )


def _milliseconds(day: date) -> int:
    instant = datetime.combine(day, time.min, tzinfo=_SHANGHAI)
    return int(instant.timestamp() * 1000)


def _date_window(offset: int, end_date: date) -> tuple[date, date]:
    if type(offset) is not int or not 1 <= offset <= MAX_OFFSET:
        raise HiThinkContractError(
            f"offset must be an integer between 1 and {MAX_OFFSET}"
        )
    # 1.8 calendar days per requested session covers long holiday clusters
    # while remaining comfortably below the provider's ten-year limit.
    calendar_days = max(32, math.ceil(offset * 1.8) + 10)
    return end_date - timedelta(days=calendar_days), end_date


def _finite_number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise HiThinkContractError(f"daily bar {field} is not numeric")
    parsed = float(value)
    if not math.isfinite(parsed):
        raise HiThinkContractError(f"daily bar {field} is not finite")
    return parsed


def _safe_provider_error(code: int) -> HiThinkBusinessError:
    # Provider-controlled message/request_id values are deliberately omitted:
    # a malformed upstream must not be able to reflect credentials into logs.
    return HiThinkBusinessError(f"HiThink business error code={code}")


def _parse_payload(
    payload: Any,
    *,
    expected_thscode: str,
    start_ms: int,
    end_ms: int,
    offset: int,
) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        raise HiThinkContractError("HiThink response envelope is not an object")
    code = payload.get("code")
    if type(code) is not int:
        raise HiThinkContractError("HiThink business code is not an integer")
    if code != 0:
        raise _safe_provider_error(code)
    data = payload.get("data")
    if not isinstance(data, dict):
        raise HiThinkContractError("HiThink daily data is not an object")
    if data.get("thscode") != expected_thscode:
        raise HiThinkContractError("HiThink daily security identity drifted")
    if data.get("interval") != "1d" or data.get("adjust") != "none":
        raise HiThinkContractError("HiThink daily interval/adjustment drifted")
    items = data.get("item")
    if not isinstance(items, list):
        raise HiThinkContractError("HiThink daily item is not a list")
    if not items:
        raise HiThinkContractError("HiThink daily result is unexpectedly empty")
    if len(items) > 3000:
        raise HiThinkContractError("HiThink daily result exceeds the bounded limit")

    rows: list[dict[str, Any]] = []
    seen_dates: set[int] = set()
    previous_date: int | None = None
    for item in items:
        if not isinstance(item, dict):
            raise HiThinkContractError("HiThink daily row is not an object")
        date_ms = item.get("date_ms")
        if isinstance(date_ms, bool) or not isinstance(date_ms, int):
            raise HiThinkContractError("HiThink daily date_ms is not an integer")
        if not start_ms <= date_ms <= end_ms:
            raise HiThinkContractError("HiThink daily row escaped the request window")
        if date_ms in seen_dates:
            raise HiThinkContractError("HiThink daily result contains a duplicate date")
        if previous_date is not None and date_ms <= previous_date:
            raise HiThinkContractError("HiThink daily result is not strictly ascending")
        seen_dates.add(date_ms)
        previous_date = date_ms

        opened = _finite_number(item.get("open_price"), "open_price")
        high = _finite_number(item.get("high_price"), "high_price")
        low = _finite_number(item.get("low_price"), "low_price")
        closed = _finite_number(item.get("close_price"), "close_price")
        volume = _finite_number(item.get("volume"), "volume")
        turnover = _finite_number(item.get("turnover"), "turnover")
        if high < low or not low <= opened <= high or not low <= closed <= high:
            raise HiThinkContractError("HiThink daily OHLC invariants failed")
        if volume < 0 or turnover < 0:
            raise HiThinkContractError("HiThink daily volume/turnover is negative")

        session_date = datetime.fromtimestamp(date_ms / 1000, _SHANGHAI).date()
        if _milliseconds(session_date) != date_ms:
            raise HiThinkContractError("HiThink daily date_ms is not Shanghai midnight")
        rows.append({
            "datetime": f"{session_date.isoformat()} 15:00:00",
            "date": session_date.isoformat(),
            "open": opened,
            "high": high,
            "low": low,
            "close": closed,
            "vol": volume,
            "volume": volume,
            "amount": turnover,
            "provider_id": PROVIDER_ID,
            "provider_symbol": expected_thscode,
            "price_adjustment": "none",
            "provider_contract": PROVIDER_CONTRACT,
        })
    return rows[-offset:]


def fetch_daily_bars(
    security_code: str,
    offset: int,
    *,
    session: requests.Session | None = None,
    end_date: date | None = None,
    timeout: tuple[int, int] = (5, 30),
) -> list[dict[str, Any]]:
    """Fetch and validate unadjusted daily bars for one SSE/SZSE stock."""
    thscode = provider_thscode(security_code)
    active_end = end_date or datetime.now(_SHANGHAI).date()
    start, end = _date_window(offset, active_end)
    start_ms, end_ms = _milliseconds(start), _milliseconds(end)
    active_session = session or requests.Session()
    try:
        response = active_session.get(
            BASE_URL + DAILY_ENDPOINT,
            params={
                "thscode": thscode,
                "interval": "1d",
                "adjust": "none",
                "start": start_ms,
                "end": end_ms,
            },
            headers={"X-api-key": _api_key()},
            timeout=timeout,
            allow_redirects=False,
        )
    except requests.RequestException as exc:
        raise HiThinkTransportError(
            f"HiThink transport failed: {type(exc).__name__}"
        ) from exc
    if response.status_code != 200:
        raise HiThinkTransportError(
            f"HiThink HTTP status {response.status_code}"
        )
    raw = response.content
    if len(raw) > MAX_RESPONSE_BYTES:
        raise HiThinkContractError("HiThink daily response exceeds size limit")
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HiThinkTransportError("HiThink response is not valid JSON") from exc
    return _parse_payload(
        payload,
        expected_thscode=thscode,
        start_ms=start_ms,
        end_ms=end_ms,
        offset=offset,
    )


__all__ = [
    "API_KEY_ENV",
    "BASE_URL",
    "DAILY_ENDPOINT",
    "HiThinkBusinessError",
    "HiThinkClientError",
    "HiThinkContractError",
    "HiThinkNotConfiguredError",
    "HiThinkTransportError",
    "HiThinkUnsupportedSecurityError",
    "PROVIDER_CONTRACT",
    "PROVIDER_ID",
    "fetch_daily_bars",
    "is_current_bse_security",
    "is_configured",
    "provider_thscode",
]
