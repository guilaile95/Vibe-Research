"""Bounded, read-only market Dragon-Tiger discovery over Eastmoney's existing report.

This is a market-level projection of ``RPT_DAILYBILLBOARD_DETAILSNEW``.  It
does not call the per-security Dragon-Tiger seat reports, create a candidate,
score a security, or write any formal research state.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Mapping

import astock


SCHEMA_VERSION = "dragon_tiger_discovery.v0.1"
PROVIDER = "EASTMONEY_DATA_CENTER"
REPORT_NAME = "RPT_DAILYBILLBOARD_DETAILSNEW"
SOURCE_DATE_SEMANTICS = "SOURCE_PROVIDED_TRADE_DATE"
BILLBOARD_NET_AMOUNT_UNIT = "YUAN"

# Proven by the live contract audit recorded in docs/evidence.  These bounds
# keep the read model deterministic if one trading day becomes unusually large.
PAGE_SIZE = 50
MAX_PAGES = 4
MAX_ROWS = PAGE_SIZE * MAX_PAGES
NO_DATA_CODE = 9201
SOURCE_PAGE_IDENTITY_OVERLAP = "SOURCE_PAGE_IDENTITY_OVERLAP"


class DragonTigerDiscoveryValidationError(ValueError):
    """Caller supplied an invalid explicit source date."""


class DragonTigerDiscoveryProviderError(RuntimeError):
    """The existing Eastmoney report could not be read or validated."""


@dataclass(frozen=True)
class _Page:
    status: str
    rows: list[dict[str, Any]]
    count: int
    pages: int


def _fetched_at() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _parse_date(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    candidate = value.strip()[:10]
    try:
        return date.fromisoformat(candidate).isoformat()
    except ValueError:
        return None


def normalize_trade_date(value: str | None) -> str | None:
    """Return an exact ``YYYY-MM-DD`` request date or raise on invalid input."""
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise DragonTigerDiscoveryValidationError("trade_date 必须是 YYYY-MM-DD")
    parsed = _parse_date(value)
    if parsed is None or value.strip() != parsed:
        raise DragonTigerDiscoveryValidationError("trade_date 必须是 YYYY-MM-DD")
    return parsed


def _as_nonnegative_int(value: Any, field: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise DragonTigerDiscoveryProviderError(f"{field} metadata invalid") from exc
    if parsed < 0:
        raise DragonTigerDiscoveryProviderError(f"{field} metadata invalid")
    return parsed


def _query_page(*, filter_str: str, page_number: int, page_size: int | None = None) -> _Page:
    """Read one page through the repository's existing Eastmoney request path."""
    page_size = PAGE_SIZE if page_size is None else page_size
    params = {
        "reportName": REPORT_NAME,
        "columns": "ALL",
        "filter": filter_str,
        "pageNumber": str(page_number),
        "pageSize": str(page_size),
        "sortColumns": "TRADE_DATE",
        "sortTypes": "-1",
        "source": "WEB",
        "client": "WEB",
    }
    try:
        response = astock.em_get(astock._DATACENTER_URL, params=params, timeout=15)
    except Exception as exc:  # noqa: BLE001 - provider details stay server-side
        raise DragonTigerDiscoveryProviderError("Eastmoney request failed") from exc

    if getattr(response, "status_code", 200) >= 400:
        raise DragonTigerDiscoveryProviderError("Eastmoney response status failed")
    try:
        payload = response.json()
    except Exception as exc:  # noqa: BLE001 - malformed provider JSON
        raise DragonTigerDiscoveryProviderError("Eastmoney response was not JSON") from exc
    if not isinstance(payload, Mapping):
        raise DragonTigerDiscoveryProviderError("Eastmoney response shape invalid")

    code = payload.get("code")
    try:
        numeric_code = int(code)
    except (TypeError, ValueError):
        numeric_code = None
    # The live report uses 9201/result=null for a valid query with no records.
    if numeric_code == NO_DATA_CODE and payload.get("success") is False and payload.get("result") is None:
        return _Page(status="EMPTY", rows=[], count=0, pages=0)
    if payload.get("success") is not True or numeric_code != 0:
        raise DragonTigerDiscoveryProviderError("Eastmoney report query failed")

    result = payload.get("result")
    if not isinstance(result, Mapping):
        raise DragonTigerDiscoveryProviderError("Eastmoney result shape invalid")
    rows = result.get("data")
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise DragonTigerDiscoveryProviderError("Eastmoney row shape invalid")
    count = _as_nonnegative_int(result.get("count"), "count")
    pages = _as_nonnegative_int(result.get("pages"), "pages")
    expected_pages = math.ceil(count / page_size) if count else 0
    if pages != expected_pages:
        raise DragonTigerDiscoveryProviderError("Eastmoney pagination metadata inconsistent")
    expected_rows = min(page_size, max(0, count - (page_number - 1) * page_size))
    if len(rows) != expected_rows:
        raise DragonTigerDiscoveryProviderError("Eastmoney page row count invalid")
    if count == 0 or pages == 0:
        return _Page(status="EMPTY", rows=[], count=0, pages=0)
    return _Page(status="NORMAL", rows=rows, count=count, pages=pages)


def _text_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _number_or_none(value: Any) -> float | None:
    # Do not turn missing values into zero.  A real numeric zero survives.
    if value is None or value == "" or value == "-":
        return None
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _source_record_identity(row: Mapping[str, Any]) -> str:
    trade_id = _text_or_none(row.get("TRADE_ID"))
    if trade_id:
        return f"TRADE_ID:{trade_id}"
    stable_fields = {
        key: row.get(key)
        for key in (
            "TRADE_DATE",
            "SECURITY_CODE",
            "EXPLANATION",
            "BILLBOARD_NET_AMT",
            "TURNOVERRATE",
        )
    }
    encoded = json.dumps(stable_fields, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:24]
    return f"ROW_SHA256:{digest}"


def _normalise_row(row: Mapping[str, Any], trade_date: str) -> dict[str, Any] | None:
    row_date = _parse_date(row.get("TRADE_DATE"))
    code = _text_or_none(row.get("SECURITY_CODE"))
    if row_date != trade_date or code is None or len(code) != 6 or not code.isdigit():
        return None
    return {
        "trade_date": row_date,
        "security_code": code,
        "security_name": _text_or_none(row.get("SECURITY_NAME_ABBR")),
        "reason": _text_or_none(row.get("EXPLANATION")),
        "billboard_net_amount": _number_or_none(row.get("BILLBOARD_NET_AMT")),
        "billboard_net_amount_unit": BILLBOARD_NET_AMOUNT_UNIT,
        "turnover_rate_pct": _number_or_none(row.get("TURNOVERRATE")),
        "source_record_identity": _source_record_identity(row),
    }


def _source_descriptor() -> dict[str, str]:
    return {
        "provider": PROVIDER,
        "report_name": REPORT_NAME,
        "query_scope": "MARKET_LEVEL_WITHOUT_SECURITY_CODE_FILTER",
        "date_semantics": SOURCE_DATE_SEMANTICS,
        "billboard_net_amount_semantics": "BILLBOARD_BUY_AMT_MINUS_BILLBOARD_SELL_AMT",
    }


def _pagination(
    *,
    fetched_pages: int,
    source_count: int | None,
    source_pages: int | None,
    returned_rows: int,
    truncated: bool,
) -> dict[str, Any]:
    return {
        "page_size": PAGE_SIZE,
        "max_pages": MAX_PAGES,
        "max_rows": MAX_ROWS,
        "fetched_pages": fetched_pages,
        "source_count": source_count,
        "source_pages": source_pages,
        "returned_rows": returned_rows,
        "truncated": truncated,
    }


def _base_envelope(*, status: str, fetched_at: str, requested_trade_date: str | None) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "provider": PROVIDER,
        "report_name": REPORT_NAME,
        "source": _source_descriptor(),
        "status": status,
        "trade_date": None,
        "requested_trade_date": requested_trade_date,
        "date_semantics": SOURCE_DATE_SEMANTICS,
        "fetched_at": fetched_at,
        "pagination": _pagination(
            fetched_pages=0,
            source_count=None,
            source_pages=None,
            returned_rows=0,
            truncated=False,
        ),
        "completeness": {
            "status": status,
            "source_count": None,
            "returned_rows": 0,
            "truncated": False,
            "malformed_rows": 0,
        },
        "rows": [],
        "limitations": [],
        "formal_state_write": {"performed": False, "scope": "read-only market discovery"},
    }


def _empty_envelope(*, fetched_at: str, requested_trade_date: str | None, fetched_pages: int = 1) -> dict[str, Any]:
    envelope = _base_envelope(
        status="EMPTY",
        fetched_at=fetched_at,
        requested_trade_date=requested_trade_date,
    )
    envelope["pagination"] = _pagination(
        fetched_pages=fetched_pages,
        source_count=0,
        source_pages=0,
        returned_rows=0,
        truncated=False,
    )
    envelope["completeness"] = {
        "status": "NO_RECORD",
        "source_count": 0,
        "returned_rows": 0,
        "truncated": False,
        "malformed_rows": 0,
    }
    envelope["limitations"] = ["NO_RECORD_FOR_TRADE_DATE"]
    return envelope


def _unavailable_envelope(
    *,
    fetched_at: str,
    requested_trade_date: str | None,
    limitations: list[str] | None = None,
) -> dict[str, Any]:
    envelope = _base_envelope(
        status="UNAVAILABLE",
        fetched_at=fetched_at,
        requested_trade_date=requested_trade_date,
    )
    envelope["limitations"] = list(limitations) if limitations is not None else ["SOURCE_UNAVAILABLE"]
    return envelope


def build_dragon_tiger_discovery(trade_date: str | None = None) -> dict[str, Any]:
    """Build the bounded market projection; no formal state or user data is written."""
    requested_trade_date = normalize_trade_date(trade_date)
    fetched_at = _fetched_at()
    source_trade_date = requested_trade_date

    try:
        # Resolve the default from the source's own latest sorted row.  The
        # market query deliberately has no SECURITY_CODE filter.
        if source_trade_date is None:
            latest_page = _query_page(filter_str="", page_number=1)
            if latest_page.status == "EMPTY":
                return _empty_envelope(fetched_at=fetched_at, requested_trade_date=None)
            source_dates = [
                parsed
                for row in latest_page.rows
                if (parsed := _parse_date(row.get("TRADE_DATE"))) is not None
            ]
            if not source_dates:
                raise DragonTigerDiscoveryProviderError("source latest date missing")
            source_trade_date = max(source_dates)

        exact_page = _query_page(
            filter_str=f"(TRADE_DATE='{source_trade_date}')",
            page_number=1,
        )
        if exact_page.status == "EMPTY":
            return _empty_envelope(
                fetched_at=fetched_at,
                requested_trade_date=requested_trade_date or source_trade_date,
            )

        source_count = exact_page.count
        source_pages = exact_page.pages
        raw_rows = list(exact_page.rows)
        raw_source_identities: list[str] = []
        seen_source_identities: set[str] = set()
        identity_overlap = False
        for raw in raw_rows:
            identity = _source_record_identity(raw)
            raw_source_identities.append(identity)
            if identity in seen_source_identities:
                identity_overlap = True
            seen_source_identities.add(identity)
        pages_to_fetch = min(source_pages, MAX_PAGES)
        for page_number in range(2, pages_to_fetch + 1):
            page = _query_page(
                filter_str=f"(TRADE_DATE='{source_trade_date}')",
                page_number=page_number,
            )
            if page.status == "EMPTY":
                raise DragonTigerDiscoveryProviderError("source page ended before reported page count")
            if page.count != source_count or page.pages != source_pages:
                raise DragonTigerDiscoveryProviderError("source pagination metadata changed")
            raw_rows.extend(page.rows)
            for raw in page.rows:
                identity = _source_record_identity(raw)
                raw_source_identities.append(identity)
                if identity in seen_source_identities:
                    identity_overlap = True
                seen_source_identities.add(identity)

        truncated = source_pages > MAX_PAGES or source_count > MAX_ROWS
        raw_rows = raw_rows[:MAX_ROWS]
        raw_source_identities = raw_source_identities[:MAX_ROWS]
        raw_row_count = len(raw_rows)
        unique_source_identity_count = len(set(raw_source_identities))
        identity_overlap = identity_overlap or unique_source_identity_count != raw_row_count
        if not truncated and (
            raw_row_count != source_count
            or unique_source_identity_count != source_count
            or identity_overlap
        ):
            return _unavailable_envelope(
                fetched_at=fetched_at,
                requested_trade_date=requested_trade_date,
                limitations=[SOURCE_PAGE_IDENTITY_OVERLAP] if identity_overlap else ["SOURCE_UNAVAILABLE"],
            )
        rows: list[dict[str, Any]] = []
        malformed_rows = 0
        for raw in raw_rows:
            normalized = _normalise_row(raw, source_trade_date)
            if normalized is None:
                malformed_rows += 1
                continue
            rows.append(normalized)

        partial = truncated or malformed_rows > 0
        envelope = _base_envelope(
            status="PARTIAL" if partial else "NORMAL",
            fetched_at=fetched_at,
            requested_trade_date=requested_trade_date,
        )
        envelope["trade_date"] = source_trade_date
        envelope["pagination"] = _pagination(
            fetched_pages=pages_to_fetch,
            source_count=source_count,
            source_pages=source_pages,
            returned_rows=len(rows),
            truncated=truncated,
        )
        envelope["completeness"] = {
            "status": "TRUNCATED" if truncated else ("PARTIAL" if malformed_rows else "COMPLETE"),
            "source_count": source_count,
            "returned_rows": len(rows),
            "truncated": truncated,
            "malformed_rows": malformed_rows,
        }
        envelope["rows"] = rows
        envelope["limitations"] = []
        if truncated:
            envelope["limitations"].append("BOUNDED_PAGE_OR_ROW_LIMIT_REACHED")
        if identity_overlap:
            envelope["limitations"].append(SOURCE_PAGE_IDENTITY_OVERLAP)
        if malformed_rows:
            envelope["limitations"].append("MALFORMED_SOURCE_ROWS_SKIPPED")
        return envelope
    except DragonTigerDiscoveryProviderError:
        return _unavailable_envelope(
            fetched_at=fetched_at,
            requested_trade_date=requested_trade_date,
        )


__all__ = [
    "BILLBOARD_NET_AMOUNT_UNIT",
    "MAX_PAGES",
    "MAX_ROWS",
    "PAGE_SIZE",
    "PROVIDER",
    "REPORT_NAME",
    "SCHEMA_VERSION",
    "SOURCE_PAGE_IDENTITY_OVERLAP",
    "DragonTigerDiscoveryProviderError",
    "DragonTigerDiscoveryValidationError",
    "build_dragon_tiger_discovery",
    "normalize_trade_date",
]
