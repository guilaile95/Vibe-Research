"""Deterministic full-market discovery funnel for research prioritization.

This module consumes existing market, Research Data Plane, Native Intel and
single-security public-data capabilities.  It creates no Campaign, Evidence,
Decision or trading authority and emits no investment action.
"""

from __future__ import annotations

import copy
import math
import re
import statistics
import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

import market
import native_intel_service
import native_intel_store
import public_data_budget
import research_data_plane as rdp
from trade_calendar import OBSERVATION_AUTHORITY_REF, observation_trade_date_at

SCHEMA_VERSION = "full-market-discovery.v0.1"
STRATEGIES = ("SHORT", "SWING", "MEDIUM")
QUEUE_LIMIT = 12
QUALIFICATION_LIMIT = 24
EXCLUDED_LIMIT = 60
OUTSIDE_CORE_SAMPLE_LIMIT = 5
QUALIFICATION_WORKERS = public_data_budget.PUBLIC_DATA_WORKERS
QUALIFICATION_TIMEOUT_SECONDS = 45.0
CATALYST_WINDOW_DAYS = 30
EARLY_LISTING_CALENDAR_DAYS = 90
CACHE_TTL_SECONDS = 10 * 60
FINANCIAL_FRESHNESS_REASON = "REPORT_PERIOD_APPLICABILITY_NOT_RESOLVED"

_BEIJING = ZoneInfo("Asia/Shanghai")
_CACHE_LOCK = threading.Lock()
_CACHE_VALUE: dict[str, Any] | None = None
_CACHE_MONOTONIC = 0.0
_LAST_SUCCESSFUL: dict[str, Any] | None = None
_REFRESH_LOCK = threading.Lock()
# Capacity belongs to the backend, not each refresh. Even injected synchronous
# providers cannot create an unbounded number of lingering worker threads.
_QUALIFICATION_EXECUTOR = ThreadPoolExecutor(
    max_workers=QUALIFICATION_WORKERS, thread_name_prefix="discovery-stage3",
)
# One bounded shortlist may queue while the prior workers are being cancelled.
_QUALIFICATION_SLOTS = threading.BoundedSemaphore(QUALIFICATION_LIMIT + QUALIFICATION_WORKERS)


@dataclass(frozen=True)
class DiscoveryProviders:
    market_snapshot: Callable[[], list[dict[str, Any]] | dict[str, Any]]
    full_market: Callable[[], dict[str, Any]]
    financials: Callable[[str], dict[str, Any]]
    announcements: Callable[[str], list[dict[str, Any]] | dict[str, Any]]
    native_intel: Callable[[list[str]], dict[str, Any]]


def _finite(value: Any, *, positive: bool = False) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number) or (positive and number <= 0):
        return None
    return number


def _iso_now(now: datetime | None = None) -> str:
    instant = now or datetime.now(timezone.utc)
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=timezone.utc)
    return instant.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _beijing_date(now: datetime | None = None) -> date:
    instant = now or datetime.now(timezone.utc)
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=timezone.utc)
    return instant.astimezone(_BEIJING).date()


def _core_board(code: str) -> str | None:
    if code.startswith(("688", "689")):
        return "STAR"
    if code.startswith("30"):
        return "GEM"
    if code.startswith(("600", "601", "603", "605")):
        return "SH_MAIN"
    if code.startswith(("000", "001", "002", "003")):
        return "SZ_MAIN"
    return None


def _restricted(row: dict[str, Any], reference_date: date) -> dict[str, Any]:
    name = str(row.get("name") or "").upper().replace(" ", "")
    reasons: list[str] = []
    if re.match(r"^(?:\*ST|ST|S\*ST|SST)", name):
        reasons.append("ST_OR_STAR_ST")
    if name.startswith("退") or "退市" in name:
        reasons.append("DELISTING_RISK_NAME")
    listing_age_days: int | None = None
    if isinstance(row.get("listing_days"), int) and not isinstance(row.get("listing_days"), bool):
        listing_age_days = int(row["listing_days"])
    elif isinstance(row.get("listing_date"), str):
        try:
            listing_age_days = (reference_date - date.fromisoformat(row["listing_date"])).days
        except ValueError:
            listing_age_days = None
    if listing_age_days is not None and 0 <= listing_age_days < EARLY_LISTING_CALENDAR_DAYS:
        reasons.append("EARLY_LISTING_UNDER_90_CALENDAR_DAYS")
    elif listing_age_days is not None and listing_age_days < 0:
        reasons.append("LISTING_DATE_AFTER_AS_OF")
    explicitly_suspended = row.get("suspended") is True
    price = _finite(row.get("price"), positive=True)
    amount = _finite(row.get("amount"))
    if explicitly_suspended or (price is None and (amount is None or amount == 0)):
        reasons.append("SUSPENDED_OR_ABNORMAL_TRADING")
    for flag in row.get("risk_flags") or []:
        normalized = str(flag).strip().upper()
        if normalized and normalized not in reasons:
            reasons.append(normalized)
    return {
        "status": "RESTRICTED" if reasons else "CLEAR" if listing_age_days is not None else "UNKNOWN",
        "reason_codes": reasons,
        "listing_age_status": "KNOWN" if listing_age_days is not None else "UNKNOWN",
    }


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[round((len(ordered) - 1) * fraction)]


def _default_full_market() -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    receipts: list[dict[str, Any]] = []
    seen_codes: set[str] = set()
    offset = 0
    first: dict[str, Any] | None = None
    while True:
        # Resolve latest once. An active-manifest replacement cannot change the
        # immutable artifact used by any following page.
        page = rdp.query_full_market(
            latest=True, limit=rdp._MAX_LIMIT, offset=offset,
            **({"snapshot_id": first["snapshot_id"]} if first is not None else {}),
        )
        if not isinstance(page, dict) or page.get("status") not in {"normal", "partial"}:
            raise rdp.ResearchDataPlaneUnavailableError("RDP full-market is unavailable")
        snapshot_id = page.get("snapshot_id")
        as_of = page.get("as_of")
        receipt = page.get("replay_receipt")
        total = page.get("total_rows")
        page_rows = page.get("rows")
        if (not isinstance(snapshot_id, str) or not re.fullmatch(r"[0-9a-f]{64}", snapshot_id)
                or not isinstance(as_of, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", as_of)
                or type(total) is not int or total < 0 or not isinstance(page_rows, list)
                or type(page.get("returned_rows")) is not int or page["returned_rows"] != len(page_rows)
                or not isinstance(page.get("coverage"), dict) or not isinstance(page.get("provenance"), dict)
                or not isinstance(receipt, dict)):
            raise rdp.ResearchDataPlaneValidationError("invalid full-market page contract")
        try:
            date.fromisoformat(as_of)
        except ValueError as exc:
            raise rdp.ResearchDataPlaneValidationError("invalid full-market as_of") from exc
        if first is None:
            first = page
        elif any(page.get(key) != first.get(key) for key in (
                "snapshot_id", "as_of", "total_rows", "coverage", "provenance", "status",
                "dataset_id", "provider_id", "adjustment")):
            raise rdp.ResearchDataPlaneValidationError("full-market page identity changed")
        parameters = receipt.get("parameters")
        if (receipt.get("snapshot_id") != snapshot_id
                or receipt.get("artifact_sha256") != page["provenance"].get("artifact_sha256")
                or receipt.get("query") != "query_full_market"
                or not isinstance(parameters, dict) or parameters.get("offset") != offset
                or parameters.get("limit") != rdp._MAX_LIMIT):
            raise rdp.ResearchDataPlaneValidationError("full-market receipt identity changed")
        for row in page_rows:
            code = row.get("code") if isinstance(row, dict) else None
            if (not isinstance(code, str) or not re.fullmatch(r"[0-9]{6}", code)
                    or code in seen_codes):
                raise rdp.ResearchDataPlaneValidationError("invalid or duplicate full-market security")
            seen_codes.add(code)
        rows.extend(page_rows)
        receipts.append(copy.deepcopy(receipt))
        next_offset = page.get("next_offset")
        if len(rows) > total:
            raise rdp.ResearchDataPlaneValidationError("full-market page coverage exceeded")
        if next_offset is None:
            if len(rows) != total or page.get("next_page") is not None:
                raise rdp.ResearchDataPlaneValidationError("full-market page coverage incomplete")
            break
        if (type(next_offset) is not int or not page_rows
                or next_offset != offset + len(page_rows) or next_offset >= total
                or page.get("next_page") != {"offset": next_offset, "snapshot_id": snapshot_id}):
            raise rdp.ResearchDataPlaneValidationError("full-market pagination did not progress")
        offset = next_offset
    result = dict(first)
    # Each source receipt hashes one bounded response. Do not relabel the first
    # page's hash as a receipt for this aggregated row collection.
    result.pop("replay_receipt", None)
    result.update(rows=rows, returned_rows=len(rows), next_offset=None, next_page=None,
                  page_receipts=receipts, receipt_scope="PAGED_SOURCE_RESPONSES")
    return result


def _default_financials(code: str, *, timeout: float | None = None,
                        cancel_event: threading.Event | None = None) -> dict[str, Any]:
    return public_data_budget.run("discovery_financials", code, timeout=timeout, cancel_event=cancel_event)


def _default_announcements(code: str, *, timeout: float | None = None,
                           cancel_event: threading.Event | None = None) -> dict[str, Any]:
    return public_data_budget.run("discovery_announcements", code, timeout=timeout, cancel_event=cancel_event)


def _default_native_intel(codes: list[str]) -> dict[str, Any]:
    path = Path(native_intel_service.db_path())
    if not path.exists():
        return {"status": "unavailable", "stats": {}, "terms": [], "reason_code": "STORE_MISSING"}
    try:
        stats = native_intel_store.get_security_mention_stats(codes, path, window_hours=24 * 7)
        terms = native_intel_store.list_entity_terms(path, limit=20_000)
        return {"status": "normal", "stats": stats, "terms": terms, "reason_code": None}
    except native_intel_store.NativeIntelStoreError:
        return {"status": "error", "stats": {}, "terms": [], "reason_code": "STORE_UNREADABLE"}


DEFAULT_PROVIDERS = DiscoveryProviders(
    market_snapshot=market.get_a_share_snapshot_observation,
    full_market=_default_full_market,
    # Stage 3 needs one bounded financial clue fetch, not the three-statement
    # StockData expansion performed by include_health=True.
    financials=_default_financials,
    announcements=_default_announcements,
    native_intel=_default_native_intel,
)


def _dataset(
    dataset_id: str,
    status: str,
    *,
    as_of: str | None,
    fetched_at: str,
    provenance_refs: list[str],
    reason_code: str | None = None,
) -> dict[str, Any]:
    return {
        "dataset_id": dataset_id,
        "status": status,
        "as_of": as_of,
        "fetched_at": fetched_at,
        "reason_code": reason_code,
        "provenance_refs": provenance_refs,
    }


def _full_market_rows(
    providers: DiscoveryProviders,
    fetched_at: str,
    market_as_of: str | None,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]], dict[str, Any]]:
    try:
        envelope = providers.full_market()
        status = str(envelope.get("status") or "unavailable")
        if status not in {"normal", "partial"}:
            raise rdp.ResearchDataPlaneUnavailableError("RDP full-market is unavailable")
        rows: dict[str, dict[str, Any]] = {}
        temporal_reasons: set[str] = set()
        for raw in envelope.get("rows") or []:
            if not isinstance(raw, dict) or not str(raw.get("code") or "").isdigit():
                continue
            row = dict(raw)
            latest_date = str(row.get("latest_date") or "")
            temporal_reason: str | None = None
            try:
                if latest_date:
                    date.fromisoformat(latest_date)
            except ValueError:
                latest_date = ""
            if market_as_of is None:
                temporal_reason = "MARKET_TRADE_DATE_UNKNOWN"
            elif not latest_date:
                temporal_reason = "RDP_LATEST_DATE_UNKNOWN"
            elif latest_date < market_as_of:
                temporal_reason = "RDP_LATEST_DATE_BEHIND_MARKET"
            elif latest_date > market_as_of:
                temporal_reason = "RDP_LATEST_DATE_AFTER_MARKET"
            row["_discovery_stale"] = temporal_reason == "RDP_LATEST_DATE_BEHIND_MARKET"
            row["_discovery_temporal_reason"] = temporal_reason
            if temporal_reason:
                temporal_reasons.add(temporal_reason)
            rows[str(row["code"])] = row
        provenance = envelope.get("provenance") or {}
        ref = provenance.get("artifact_sha256") or provenance.get("source_name") or "local-rdp"
        dataset_status = "partial" if temporal_reasons or status == "partial" else "normal"
        dataset = _dataset(
            "research_data_plane.full_market",
            dataset_status,
            as_of=envelope.get("as_of"),
            fetched_at=str(envelope.get("fetched_at") or fetched_at),
            provenance_refs=[f"research-data-plane:{ref}"],
            reason_code=sorted(temporal_reasons)[0] if temporal_reasons else None,
        )
        # Preserve the immutable source identity and the exact page-scoped
        # receipts/coverage rather than only retaining an artifact label.
        for source_key, dataset_key in (("snapshot_id", "snapshot_id"),
                                        ("page_receipts", "page_receipts"),
                                        ("replay_receipt", "replay_receipt"),
                                        ("receipt_scope", "receipt_scope"),
                                        ("coverage", "source_coverage")):
            if source_key in envelope:
                dataset[dataset_key] = copy.deepcopy(envelope[source_key])
        return envelope, rows, dataset
    except Exception:  # provider boundary: degrade to UNKNOWN instead of failing the whole scan
        dataset = _dataset(
            "research_data_plane.full_market",
            "unavailable",
            as_of=None,
            fetched_at=fetched_at,
            provenance_refs=[],
            reason_code="RDP_UNAVAILABLE",
        )
        return {}, {}, dataset


def _sector_context(rows: list[dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], float | None]:
    market_changes = [value for row in rows if (value := _finite(row.get("change_pct"))) is not None]
    market_average = statistics.fmean(market_changes) if market_changes else None
    grouped: dict[str, list[float]] = {}
    for row in rows:
        sector = str(row.get("industry") or "").strip()
        change = _finite(row.get("change_pct"))
        if sector and change is not None:
            grouped.setdefault(sector, []).append(change)
    contexts: dict[str, dict[str, Any]] = {}
    for sector, changes in grouped.items():
        average = statistics.fmean(changes)
        state = "UNKNOWN"
        if market_average is not None:
            state = "SUPPORTIVE" if average >= market_average else "WEAK"
        contexts[sector] = {
            "sector": sector,
            "status": state,
            "stock_count": len(changes),
            "average_change_pct": round(average, 4),
            "market_average_change_pct": round(market_average, 4) if market_average is not None else None,
            "source_ref": "market:a-share-snapshot:industry",
        }
    return contexts, market_average


def _cheap_strategy(
    strategy: str,
    row: dict[str, Any],
    history: dict[str, Any] | None,
    sector: dict[str, Any] | None,
    *,
    amount_median: float | None,
    turnover_upper: float | None,
) -> dict[str, Any]:
    amount = _finite(row.get("amount"), positive=True)
    turnover = _finite(row.get("turnover_pct"))
    change = _finite(row.get("change_pct"))
    cap = _finite(row.get("float_market_cap"), positive=True)
    pe_ttm = _finite(row.get("pe_ttm"))
    pb = _finite(row.get("pb"))
    reasons: list[str] = []
    missing: list[str] = []
    observations: list[dict[str, Any]] = []
    failed_conditions: list[str] = []

    def observe(code: str, label: str, value: Any, source_ref: str) -> None:
        reasons.append(code)
        observations.append({"code": code, "label": label, "value": value, "source_ref": source_ref})

    liquid = amount is not None and amount_median is not None and amount >= amount_median
    if liquid:
        observe("LIQUIDITY_AT_OR_ABOVE_MARKET_MEDIAN", "成交额位于市场中位数以上", amount, "market:a-share-snapshot:amount")
    elif amount is None:
        missing.append("AMOUNT_UNKNOWN")

    history_temporal_reason = (history or {}).get("_discovery_temporal_reason")
    history_temporal_unusable = isinstance(history_temporal_reason, str) and bool(history_temporal_reason)
    history_stale = bool((history or {}).get("_discovery_stale"))
    if history_temporal_unusable:
        if history_stale:
            missing.append("HISTORICAL_ROW_STALE")
        missing.append(history_temporal_reason)

    if strategy == "SHORT":
        if history is None:
            missing.append("HISTORICAL_MARKET_CONTEXT_UNKNOWN")
        if change is not None and change > 0:
            observe("POSITIVE_SESSION_MOMENTUM", "当日价格动量为正", change, "market:a-share-snapshot:change_pct")
        elif change is None:
            missing.append("SESSION_RETURN_UNKNOWN")
        active = turnover is not None and turnover_upper is not None and turnover >= turnover_upper
        if active:
            observe("TURNOVER_IN_ACTIVE_MARKET_QUARTILE", "换手率位于活跃区间", turnover, "market:a-share-snapshot:turnover_pct")
        elif turnover is None:
            missing.append("TURNOVER_UNKNOWN")
        passed = bool(liquid and change is not None and change > 0 and active)
        return {"passed": passed, "status": "NORMAL" if not missing else "PARTIAL", "reason_codes": reasons, "missing": missing, "observations": observations, "failed_conditions": failed_conditions, "condition_match": "FULL_CONDITIONS" if passed else "NOT_MATCHED"}

    metric = "return_20d" if strategy == "SWING" else "return_60d"
    metric_status = str((history or {}).get(f"{metric}_status") or "")
    momentum = _finite((history or {}).get(metric)) if metric_status == "normal" and not history_temporal_unusable else None
    history_available = momentum is not None
    if history_available and momentum > 0:
        observe(f"POSITIVE_{metric.upper()}", f"{metric.removeprefix('return_').upper()} 日收益为正", momentum, f"research-data-plane:{metric}")
    elif history_available:
        failed_conditions.append(f"{metric.upper()}_NOT_POSITIVE")
    elif not history_temporal_unusable:
        missing.append(f"{metric.upper()}_UNKNOWN")

    sector_supportive = bool(sector and sector.get("status") == "SUPPORTIVE")
    if sector_supportive:
        observe("SECTOR_CONTEXT_SUPPORTIVE", "行业相对市场状态支持继续研究", sector.get("average_change_pct"), "market:a-share-snapshot:industry")
    elif sector is None:
        missing.append("SECTOR_CONTEXT_UNKNOWN")

    if strategy == "SWING":
        passed = bool(liquid and ((history_available and momentum > 0) or (not history_available and sector_supportive and change is not None and change > 0)))
    else:
        valuation = {"pe_ttm": pe_ttm, "pb": pb}
        if pe_ttm is not None or pb is not None:
            observe("BASIC_VALUATION_AVAILABLE", "基础 PE/PB 可用于后续估值研究", valuation, "market:a-share-snapshot:pe_pb")
        else:
            missing.append("VALUATION_INPUT_UNKNOWN")
        passed = bool((pe_ttm is not None or pb is not None) and cap is not None and ((history_available and momentum > 0) or (not history_available and liquid and sector_supportive)))
    condition_match = "DEGRADED_CLUE" if passed and not history_available else "FULL_CONDITIONS" if passed else "NOT_MATCHED"
    if condition_match == "DEGRADED_CLUE":
        reasons.append("HISTORICAL_RETURN_UNAVAILABLE_SECTOR_FALLBACK")
    return {"passed": passed, "status": "NORMAL" if history_available and not missing else "PARTIAL", "reason_codes": reasons, "missing": missing, "observations": observations, "failed_conditions": failed_conditions, "condition_match": condition_match}


def _qualification_codes(candidates: dict[str, list[dict[str, Any]]]) -> list[str]:
    per_strategy = max(1, QUALIFICATION_LIMIT // len(STRATEGIES))
    selected: list[str] = []
    for strategy in STRATEGIES:
        ordered = sorted(
            candidates[strategy],
            key=lambda item: (-float(item.get("amount") or 0), str(item["code"])),
        )
        for item in ordered[:per_strategy]:
            if item["code"] not in selected:
                selected.append(item["code"])
    if len(selected) < QUALIFICATION_LIMIT:
        remaining = sorted(
            (item for rows in candidates.values() for item in rows if item["code"] not in selected),
            key=lambda item: (-float(item.get("amount") or 0), str(item["code"])),
        )
        for item in remaining:
            if item["code"] not in selected:
                selected.append(item["code"])
            if len(selected) >= QUALIFICATION_LIMIT:
                break
    return selected


def _fundamental_result(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict) or not payload:
        return {
            "status": "UNKNOWN",
            "temporal_state": "UNKNOWN",
            "clue": None,
            "reason_codes": ["FINANCIAL_PAYLOAD_EMPTY"],
            "source_ref": "astock.financials",
        }
    available = any(payload.get(key) is not None for key in ("revenue", "net_profit", "operating_cash_flow", "roe"))
    quality = payload.get("data_quality") if isinstance(payload.get("data_quality"), dict) else {}
    quality_status = str(quality.get("status") or "unknown").lower()
    status = "ERROR" if quality_status == "error" else "PARTIAL" if available else "UNKNOWN"
    reason_codes = [FINANCIAL_FRESHNESS_REASON] if available else ["FINANCIAL_FACTS_MISSING"]
    if available and quality_status != "normal":
        reason_codes.append("FINANCIAL_DATA_QUALITY_NOT_NORMAL")
    clue = {
        key: payload.get(key)
        for key in ("period", "revenue_yoy", "net_profit_yoy", "operating_cash_flow", "roe")
        if payload.get(key) is not None
    } or None
    return {
        "status": status,
        "temporal_state": "UNKNOWN",
        "clue": clue,
        "reason_codes": reason_codes,
        "source_ref": "astock.financials",
    }


def _announcement_date(row: dict[str, Any]) -> date | None:
    raw = row.get("notice_at") or row.get("date")
    if not isinstance(raw, str) or len(raw) < 10:
        return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


def _qualification_error(phase: str, reason: str) -> dict[str, Any]:
    if phase == "fundamental":
        return {"status": "ERROR", "clue": None, "source_ref": "astock.financials", "reason_code": reason}
    return {"status": "ERROR", "count": 0, "latest": None,
            "source_ref": "astock.announcements", "reason_code": reason}


def _qualify_one(code: str, providers: DiscoveryProviders, as_of: date, *,
                 cancel_event: threading.Event, deadline: float,
                 progress: dict[str, dict[str, Any]], progress_lock: threading.Lock) -> dict[str, Any]:
    def cancelled() -> bool:
        return cancel_event.is_set() or time.monotonic() >= deadline

    def call(provider: Callable) -> Any:
        if cancelled():
            raise public_data_budget.PublicDataUnavailable("SOURCE_CANCELLED")
        if provider is _default_financials or provider is _default_announcements:
            return provider(code, timeout=min(public_data_budget.TIMEOUT, max(0.0, deadline - time.monotonic())),
                            cancel_event=cancel_event)
        # Dependency-injected local providers keep the simple callable contract.
        # They share bounded admission; no timed-out call can start a next phase.
        return provider(code)

    def publish(phase: str, result: dict[str, Any]) -> None:
        with progress_lock:
            if not cancelled():
                progress.setdefault(code, {})[phase] = result

    try:
        fundamental = _fundamental_result(call(providers.financials))
    except Exception as exc:  # expose a fixed state, never raw exception text
        fundamental = _qualification_error("fundamental", exc.code if isinstance(exc, public_data_budget.PublicDataUnavailable) else "PROVIDER_ERROR")
    publish("fundamental", fundamental)
    if cancelled():
        return {"fundamental": fundamental, "announcements": _qualification_error("announcements", "TIMEOUT")}
    try:
        payload = call(providers.announcements)
        announcements = payload.get("rows", []) if isinstance(payload, dict) else payload or []
        if not isinstance(announcements, list):
            raise ValueError("announcement rows must be a list")
        coverage = payload.get("source_coverage") if isinstance(payload, dict) else None
        cutoff = as_of - timedelta(days=CATALYST_WINDOW_DAYS)
        recent = [
            row for row in announcements
            if isinstance(row, dict)
            and (published := _announcement_date(row)) is not None
            and cutoff <= published <= as_of
        ]
        unknown_date_count = sum(
            1 for row in announcements
            if isinstance(row, dict) and _announcement_date(row) is None
        )
        announcement_result = {
            "status": "AVAILABLE" if recent else "UNKNOWN",
            "request_status": "NORMAL",
            "source_coverage": coverage or {"status": "unknown", "scope": "provider_announcement_list", "window_complete": False, "full_text_included": False},
            "count": len(recent),
            "older_or_future_count": max(0, len(announcements) - len(recent) - unknown_date_count),
            "unknown_date_count": unknown_date_count,
            "latest": {
                "title": recent[0].get("title"),
                "date": recent[0].get("notice_at") or recent[0].get("date"),
            } if recent else None,
            "source_ref": "astock.announcements",
        }
    except Exception as exc:
        announcement_result = _qualification_error("announcements", exc.code if isinstance(exc, public_data_budget.PublicDataUnavailable) else "PROVIDER_ERROR")
    publish("announcements", announcement_result)
    return {"fundamental": fundamental, "announcements": announcement_result}


def _qualify(
    codes: list[str],
    providers: DiscoveryProviders,
    *,
    as_of: date,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any], dict[str, Any]]:
    try:
        intel = providers.native_intel(codes)
        if not isinstance(intel, dict):
            raise TypeError("native intel provider returned a non-object")
    except Exception:
        intel = {"status": "error", "stats": {}, "terms": [], "reason_code": "PROVIDER_ERROR"}

    results: dict[str, dict[str, Any]] = {}
    progress: dict[str, dict[str, Any]] = {}
    progress_lock = threading.Lock()
    cancel_event = threading.Event()
    deadline = time.monotonic() + QUALIFICATION_TIMEOUT_SECONDS
    futures = {}
    for code in codes:
        if not _QUALIFICATION_SLOTS.acquire(blocking=False):
            results[code] = {phase: _qualification_error(phase, "SOURCE_BUSY")
                             for phase in ("fundamental", "announcements")}
            continue
        try:
            future = _QUALIFICATION_EXECUTOR.submit(
                _qualify_one, code, providers, as_of, cancel_event=cancel_event,
                deadline=deadline, progress=progress, progress_lock=progress_lock,
            )
        except Exception:
            _QUALIFICATION_SLOTS.release()
            raise
        future.add_done_callback(lambda _future, slots=_QUALIFICATION_SLOTS: slots.release())
        futures[future] = code
    done, pending = wait(futures, timeout=max(0.0, deadline - time.monotonic()))
    if pending:
        cancel_event.set()
        for future in pending:
            future.cancel()
        if providers.financials is _default_financials and providers.announcements is _default_announcements:
            # Default providers are killable processes. Wait for their bounded
            # kill/reap cleanup, not only the response timeout, before returning.
            wait(pending, timeout=2.5)
    for future in done:
        code = futures[future]
        try:
            results[code] = future.result()
        except Exception:
            results[code] = {phase: _qualification_error(phase, "PROVIDER_ERROR")
                             for phase in ("fundamental", "announcements")}
    with progress_lock:
        for future in pending:
            code = futures[future]
            results[code] = {
                phase: copy.deepcopy(progress.get(code, {}).get(phase)) or _qualification_error(phase, "TIMEOUT")
                for phase in ("fundamental", "announcements")
            }

    terms_by_code: dict[str, list[dict[str, Any]]] = {}
    for term in intel.get("terms") or []:
        if isinstance(term, dict) and term.get("security_code") in codes:
            terms_by_code.setdefault(str(term["security_code"]), []).append(term)
    stats = intel.get("stats") if isinstance(intel.get("stats"), dict) else {}
    for code in codes:
        raw_stats = stats.get(code) if isinstance(stats.get(code), dict) else None
        mapped = code in terms_by_code or bool(
            raw_stats
            and (
                int(raw_stats.get("mention_count") or 0) > 0
                or int(raw_stats.get("source_count") or 0) > 0
            )
        )
        item = results.setdefault(code, {})
        item["native_intel"] = {
            "mention_count": raw_stats.get("mention_count") if raw_stats else (0 if mapped else None),
            "source_count": raw_stats.get("source_count") if raw_stats else (0 if mapped else None),
            "first_seen_at": raw_stats.get("first_seen_at") if raw_stats else None,
            "last_seen_at": raw_stats.get("last_seen_at") if raw_stats else None,
            "mapping_status": "MAPPED" if mapped else "UNKNOWN",
        }
    intel_summary = {
        "status": str(intel.get("status") or "unavailable"),
        "reason_code": intel.get("reason_code"),
        "terms_by_code": terms_by_code,
    }
    provider_summary = {
        "completed": len(done),
        "timed_out": len(pending),
        "requested": len(codes),
        "busy": len(codes) - len(futures),
    }
    return results, intel_summary, provider_summary


def _evidence_gate(
    cheap: dict[str, Any],
    sector: dict[str, Any] | None,
    qualification: dict[str, Any],
    restricted: dict[str, Any],
) -> str:
    if not cheap["passed"]:
        return "INSUFFICIENT"
    fundamental = qualification["fundamental"]["status"]
    announcements = qualification["announcements"]["status"]
    intel_mentions = int((qualification.get("native_intel") or {}).get("mention_count") or 0)
    catalyst_available = announcements == "AVAILABLE" or intel_mentions > 0
    if fundamental == "ERROR" and announcements == "ERROR" and intel_mentions == 0:
        return "ERROR"
    if restricted["status"] == "RESTRICTED" and not (fundamental in {"AVAILABLE", "PARTIAL"} and catalyst_available):
        return "INSUFFICIENT"
    if fundamental == "AVAILABLE" and catalyst_available and sector and sector.get("status") != "UNKNOWN" and cheap["status"] == "NORMAL":
        return "SUFFICIENT_FOR_RESEARCH"
    if fundamental in {"AVAILABLE", "PARTIAL"} or catalyst_available:
        return "PARTIAL"
    return "UNKNOWN"


def _priority(gate: str, restricted: dict[str, Any], cheap: dict[str, Any], sector: dict[str, Any] | None, qualification: dict[str, Any]) -> str:
    if restricted["status"] == "RESTRICTED":
        return "LOW"
    catalyst_available = qualification["announcements"]["status"] == "AVAILABLE" or int((qualification.get("native_intel") or {}).get("mention_count") or 0) > 0
    if (
        gate == "SUFFICIENT_FOR_RESEARCH"
        and restricted["status"] == "CLEAR"
        and cheap["status"] == "NORMAL"
        and sector
        and sector.get("status") == "SUPPORTIVE"
        and qualification["fundamental"]["status"] == "AVAILABLE"
        and catalyst_available
    ):
        return "HIGH"
    if gate in {"SUFFICIENT_FOR_RESEARCH", "PARTIAL"}:
        return "MEDIUM"
    return "LOW"


def _opportunity_item(
    base: dict[str, Any],
    strategy: str,
    cheap: dict[str, Any],
    qualification: dict[str, Any],
    sector: dict[str, Any] | None,
    themes: list[str],
    *,
    as_of: str | None,
    fetched_at: str,
) -> tuple[dict[str, Any], str]:
    restricted = base["restricted"]
    gate = _evidence_gate(cheap, sector, qualification, restricted)
    priority = _priority(gate, restricted, cheap, sector, qualification)
    intel = qualification.get("native_intel") or {}
    announcement = qualification["announcements"]
    catalyst_available = announcement["status"] == "AVAILABLE" or int(intel.get("mention_count") or 0) > 0
    catalyst_status = "AVAILABLE" if catalyst_available else "ERROR" if announcement["status"] == "ERROR" else "UNKNOWN"
    uncertainties = list(cheap["missing"])
    if not sector:
        uncertainties.append("SECTOR_CONTEXT_UNKNOWN")
    if not themes:
        uncertainties.append("THEME_CONTEXT_UNKNOWN")
    if restricted.get("listing_age_status") == "UNKNOWN":
        uncertainties.append("LISTING_AGE_NOT_EVALUATED")
    if qualification["fundamental"]["status"] in {"UNKNOWN", "ERROR"}:
        uncertainties.append("FUNDAMENTAL_FACTS_UNKNOWN")
    elif qualification["fundamental"]["status"] == "PARTIAL":
        uncertainties.append("FUNDAMENTAL_FRESHNESS_UNKNOWN")
    uncertainties.append("ANNOUNCEMENT_WINDOW_COVERAGE_UNPROVEN")
    if catalyst_status != "AVAILABLE":
        uncertainties.append("CATALYST_EVIDENCE_UNKNOWN")
    if (qualification.get("native_intel") or {}).get("mapping_status") != "MAPPED":
        uncertainties.append("NATIVE_INTEL_MAPPING_UNKNOWN")

    reason_codes = list(dict.fromkeys([
        *cheap["reason_codes"],
        *qualification["fundamental"].get("reason_codes", []),
        f"DISCOVERY_EVIDENCE_{gate}",
        *(restricted["reason_codes"] if restricted["status"] == "RESTRICTED" else []),
    ]))
    supporting = list(cheap["observations"])
    if sector:
        supporting.append({
            "code": f"SECTOR_{sector['status']}",
            "label": f"行业状态：{sector['status']}",
            "value": sector.get("average_change_pct"),
            "source_ref": sector["source_ref"],
        })
    if qualification["fundamental"].get("clue"):
        supporting.append({
            "code": "FUNDAMENTAL_FACT_AVAILABLE",
            "label": "财务事实存在；报告期 freshness 仍按时间 authority 评估",
            "value": qualification["fundamental"]["clue"],
            "source_ref": qualification["fundamental"]["source_ref"],
        })
    if catalyst_available:
        supporting.append({
            "code": "CATALYST_CLUE_AVAILABLE",
            "label": "近期公告或公开资讯存在可研究线索",
            "value": {
                "announcement_count": announcement.get("count", 0),
                "intel_mentions": intel.get("mention_count"),
                "intel_sources": intel.get("source_count"),
                "intel_mapping_status": intel.get("mapping_status"),
            },
            "source_ref": "astock.announcements+native-intel",
        })
    health = "normal" if not uncertainties else "partial" if supporting else "unknown"
    item = {
        "security_code": base["code"],
        "name": base["name"],
        "strategy": strategy,
        "sector": base.get("sector"),
        "themes": themes,
        "discovery_state": "QUEUED" if gate not in {"INSUFFICIENT", "ERROR"} else "BLOCKED",
        "condition_match": cheap.get("condition_match", "UNKNOWN"),
        "research_priority": priority,
        "reason_codes": reason_codes,
        "supporting_observations": supporting,
        "uncertainties": list(dict.fromkeys(uncertainties)),
        "data_health": health,
        "catalyst_status": catalyst_status,
        "fundamental_status": qualification["fundamental"]["status"],
        "evidence_gate": gate,
        "restricted_universe": restricted,
        "discovered_at": fetched_at,
        "as_of": as_of,
        "provenance_refs": list(dict.fromkeys([observation["source_ref"] for observation in supporting])),
    }
    return item, gate


def run_discovery(
    *,
    providers: DiscoveryProviders = DEFAULT_PROVIDERS,
    now: datetime | None = None,
) -> dict[str, Any]:
    refresh_attempted_at = _iso_now(now)
    try:
        snapshot = providers.market_snapshot()
    except Exception:
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "unavailable",
            "as_of": None,
            "fetched_at": refresh_attempted_at,
            "last_successful_at": None,
            "refresh_attempted_at": refresh_attempted_at,
            "market_context": {"status": "unavailable", "core_universe_count": 0, "sector_count": 0},
            "funnel": {"core_universe": 0, "cheap_scan_passed": 0, "qualification_candidates": 0, "queue_items": {strategy: 0 for strategy in STRATEGIES}, "excluded": 0},
            "datasets": [_dataset("market.a_share_snapshot", "unavailable", as_of=None, fetched_at=refresh_attempted_at, provenance_refs=[], reason_code="UPSTREAM_UNAVAILABLE")],
            "queues": {strategy: [] for strategy in STRATEGIES},
            "excluded": [],
            "limitations": ["全 A 股批量快照不可用；Discovery 不回退为逐股抓取。"],
            "cache": {"hit": False, "age_seconds": 0},
        }
    observation = snapshot if isinstance(snapshot, dict) else {}
    if observation:
        snapshot = observation.get("rows")
    if not isinstance(snapshot, list) or not snapshot:
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "unavailable",
            "as_of": None,
            "fetched_at": refresh_attempted_at,
            "last_successful_at": None,
            "refresh_attempted_at": refresh_attempted_at,
            "market_context": {"status": "unavailable", "core_universe_count": 0, "sector_count": 0},
            "funnel": {"core_universe": 0, "cheap_scan_passed": 0, "qualification_candidates": 0, "queue_items": {strategy: 0 for strategy in STRATEGIES}, "excluded": 0},
            "datasets": [_dataset("market.a_share_snapshot", "unavailable", as_of=None, fetched_at=refresh_attempted_at, provenance_refs=[], reason_code="EMPTY_SNAPSHOT")],
            "queues": {strategy: [] for strategy in STRATEGIES},
            "excluded": [],
            "limitations": ["全 A 股批量快照为空；Discovery 不回退为逐股抓取。"],
            "cache": {"hit": False, "age_seconds": 0},
        }

    fetched_at = observation.get("observed_at")
    evaluation_date = _beijing_date(now)
    market_as_of = observation_trade_date_at(fetched_at) if isinstance(fetched_at, str) else None

    core_rows: list[dict[str, Any]] = []
    outside_core: list[dict[str, Any]] = []
    for raw in snapshot:
        if not isinstance(raw, dict):
            continue
        code = str(raw.get("code") or "").strip()
        name = str(raw.get("name") or "").strip()
        board = _core_board(code)
        if not board or not name:
            if code and name:
                outside_core.append({"security_code": code, "name": name, "reason_codes": ["OUTSIDE_CORE_A_SHARE_UNIVERSE"]})
            continue
        core_rows.append({
            **raw,
            "code": code,
            "name": name,
            "board": board,
            "restricted": _restricted(raw, evaluation_date),
        })
    core_rows.sort(key=lambda row: row["code"])
    if not core_rows:
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "unavailable",
            "as_of": market_as_of,
            "fetched_at": fetched_at,
            "last_successful_at": None,
            "refresh_attempted_at": refresh_attempted_at,
            "market_context": {"status": "unavailable", "core_universe_count": 0, "sector_count": 0},
            "funnel": {"core_universe": 0, "cheap_scan_passed": 0, "qualification_candidates": 0, "queue_items": {strategy: 0 for strategy in STRATEGIES}, "excluded": len(outside_core)},
            "datasets": [_dataset("market.a_share_snapshot", "partial", as_of=market_as_of, fetched_at=fetched_at, provenance_refs=["market:a-share-snapshot", OBSERVATION_AUTHORITY_REF], reason_code="NO_CORE_ROWS")],
            "queues": {strategy: [] for strategy in STRATEGIES},
            "excluded": outside_core[:EXCLUDED_LIMIT],
            "limitations": ["批量快照没有可识别的沪深主板、创业板或科创板股票。"],
            "cache": {"hit": False, "age_seconds": 0},
        }

    rdp_envelope, histories, rdp_dataset = _full_market_rows(providers, fetched_at, market_as_of)
    sectors, market_average = _sector_context(core_rows)
    amounts = [value for row in core_rows if (value := _finite(row.get("amount"), positive=True)) is not None]
    turnovers = [value for row in core_rows if (value := _finite(row.get("turnover_pct"))) is not None]
    amount_median = statistics.median(amounts) if amounts else None
    turnover_upper = _percentile(turnovers, 0.75)

    candidates: dict[str, list[dict[str, Any]]] = {strategy: [] for strategy in STRATEGIES}
    cheap_by_code_strategy: dict[tuple[str, str], dict[str, Any]] = {}
    base_by_code: dict[str, dict[str, Any]] = {}
    excluded: list[dict[str, Any]] = list(outside_core[:OUTSIDE_CORE_SAMPLE_LIMIT])
    excluded_total = len(outside_core)
    for row in core_rows:
        code = row["code"]
        sector_name = str(row.get("industry") or "").strip() or None
        base = {
            "code": code,
            "name": row["name"],
            "board": row["board"],
            "sector": sector_name,
            "amount": _finite(row.get("amount"), positive=True),
            "restricted": row["restricted"],
        }
        history = histories.get(code)
        base_by_code[code] = base
        for strategy in STRATEGIES:
            cheap = _cheap_strategy(
                strategy,
                row,
                history,
                sectors.get(sector_name) if sector_name else None,
                amount_median=amount_median,
                turnover_upper=turnover_upper,
            )
            if market_as_of is None:
                cheap["status"] = "PARTIAL"
                cheap["missing"] = list(dict.fromkeys([
                    *cheap["missing"],
                    "MARKET_TRADE_DATE_UNKNOWN",
                ]))
            cheap_by_code_strategy[(code, strategy)] = cheap
            if cheap["passed"]:
                candidates[strategy].append(base)
            else:
                excluded_total += 1
                if len(excluded) >= EXCLUDED_LIMIT:
                    continue
                excluded.append({
                    "security_code": code,
                    "name": row["name"],
                    "strategy": strategy,
                    "sector": sector_name,
                    "discovery_state": "EXCLUDED",
                    "reason_codes": [*cheap["failed_conditions"], *cheap["missing"]] or ["CHEAP_SCAN_NOT_QUALIFIED"],
                    "data_health": "unknown" if cheap["missing"] else "normal",
                    "restricted_universe": row["restricted"],
                    "as_of": market_as_of,
                })

    qualification_codes = _qualification_codes(candidates)
    qualifications, intel_summary, provider_summary = _qualify(
        qualification_codes,
        providers,
        as_of=evaluation_date,
    )
    themes_by_code: dict[str, list[str]] = {}
    for code, terms in intel_summary["terms_by_code"].items():
        themes_by_code[code] = sorted({
            str(term.get("term"))
            for term in terms
            if term.get("term_kind") == native_intel_store.TERM_CONCEPT and term.get("term")
        })

    queues: dict[str, list[dict[str, Any]]] = {strategy: [] for strategy in STRATEGIES}
    blocked: list[dict[str, Any]] = []
    for strategy in STRATEGIES:
        for base in candidates[strategy]:
            code = base["code"]
            if code not in qualifications:
                continue
            item, gate = _opportunity_item(
                base,
                strategy,
                cheap_by_code_strategy[(code, strategy)],
                qualifications[code],
                sectors.get(base.get("sector")) if base.get("sector") else None,
                themes_by_code.get(code, []),
                as_of=market_as_of,
                fetched_at=fetched_at,
            )
            if gate in {"INSUFFICIENT", "ERROR"}:
                blocked.append(item)
            else:
                queues[strategy].append(item)

    queue_eligible_counts = {strategy: len(queues[strategy]) for strategy in STRATEGIES}
    priority_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    for strategy in STRATEGIES:
        queues[strategy].sort(key=lambda item: (priority_order[item["research_priority"]], item["security_code"]))
        queues[strategy] = queues[strategy][:QUEUE_LIMIT]

    excluded_total += len(blocked)
    excluded.extend(blocked)
    excluded = excluded[:EXCLUDED_LIMIT]
    market_dataset = _dataset(
        "market.a_share_snapshot",
        "normal" if market_as_of is not None else "partial",
        as_of=market_as_of,
        fetched_at=fetched_at,
        provenance_refs=["market:a-share-snapshot:eastmoney-clist", OBSERVATION_AUTHORITY_REF],
        reason_code=None if market_as_of is not None else "MARKET_TRADE_DATE_UNKNOWN",
    )
    intel_dataset = _dataset(
        "native_intel.security_mentions",
        intel_summary["status"],
        as_of=evaluation_date.isoformat(),
        fetched_at=fetched_at,
        provenance_refs=[native_intel_service.AUTHORITY_REF] if intel_summary["status"] in {"normal", "partial", "stale"} else [],
        reason_code=intel_summary["reason_code"],
    )
    financial_partial = bool(provider_summary["timed_out"]) or any(
        value.get("fundamental", {}).get("status") != "AVAILABLE"
        for value in qualifications.values()
    )
    announcements_partial = bool(provider_summary["timed_out"]) or any(
        value.get("announcements", {}).get("status") == "ERROR"
        for value in qualifications.values()
    )
    datasets = [
        market_dataset,
        rdp_dataset,
        _dataset(
            "financials.snapshot",
            "partial" if financial_partial else "normal",
            as_of=None,
            fetched_at=fetched_at,
            provenance_refs=["astock.financials"],
            reason_code=FINANCIAL_FRESHNESS_REASON if financial_partial else None,
        ),
        _dataset(
            "announcements.recent",
            "partial",
            as_of=evaluation_date.isoformat(),
            fetched_at=fetched_at,
            provenance_refs=["astock.announcements"],
            reason_code="PROVIDER_PARTIAL" if announcements_partial else "BOUNDED_LIST_WINDOW_COVERAGE_UNPROVEN",
        ),
        intel_dataset,
    ]
    announcement_dataset = next(item for item in datasets if item["dataset_id"] == "announcements.recent")
    announcement_dataset["request_status"] = "PARTIAL" if announcements_partial else "NORMAL" if qualification_codes else "NOT_REQUESTED"
    announcement_dataset["material_completeness"] = "UNKNOWN"
    announcement_dataset["source_coverage"] = {"scope": "qualified_securities_provider_lists", "window_complete": False, "full_text_included": False}
    overall = "normal" if all(item["status"] == "normal" for item in datasets) else "partial"
    limitations = [
        "Discovery 是研究优先级 read model，不是 Formal Evidence、投资建议或交易权限。",
        "上市时长只在 Provider 明确提供 listing_date/listing_days 时评估；缺失保持 UNKNOWN。",
        "Theme 仅复用已有 Native Intel 实体映射；没有映射时保持 UNKNOWN。",
        "仅扫描 Provider 返回的沪深主板、创业板与科创板行情，不包含北交所，不保证完整 A 股覆盖。",
        "按成交额在三个策略初筛结果中抽样并去重，最多 24 股补充财务与公告；每队列最多返回 12 条，按研究优先级再按证券代码排序。",
        "行业/主题过滤只作用于已返回的有限队列，不重新扫描全行业；空结果不代表该行业没有研究对象。",
        "公告请求成功仅代表取到有界列表，通常为首页 15 条；不证明 30 日窗口查全，也不代表已读取公告全文。",
        "历史收益缺失时可按既有行业条件降级入选；降级线索不等于完整条件匹配，不能因缺数提高可信度。",
    ]
    if rdp_dataset["status"] != "normal":
        limitations.append("RDP 历史上下文为 PARTIAL/UNKNOWN；它会收窄 Data Health、Evidence Gate 与优先级，但不会把股票本身标记为 Restricted。")
    if market_as_of is None:
        limitations.append("行情交易日无法由权威市场观察时间证明；行情 as_of 保持 UNKNOWN，优先级不会升级为 HIGH。")
    if financial_partial:
        limitations.append("财务报告期 applicability/freshness 尚未被现有 authority 证明；财务线索保持 PARTIAL，不贡献 fully-current HIGH 优先级。")
    if announcements_partial:
        limitations.append("部分公告资格检查失败/超时；对应股票保持 PARTIAL、UNKNOWN 或 ERROR。")
    return {
        "schema_version": SCHEMA_VERSION,
        "status": overall,
        "as_of": market_as_of,
        "fetched_at": fetched_at,
        "last_successful_at": fetched_at,
        "refresh_attempted_at": refresh_attempted_at,
        "market_context": {
            "status": "normal" if market_as_of is not None else "partial",
            "core_universe_count": len(core_rows),
            "outside_core_count": len(outside_core),
            "sector_count": len(sectors),
            "market_average_change_pct": round(market_average, 4) if market_average is not None else None,
            "amount_median": amount_median,
            "turnover_active_threshold": turnover_upper,
            "source_ref": "market:a-share-snapshot:eastmoney-clist",
            "temporal_authority_ref": OBSERVATION_AUTHORITY_REF,
        },
        "funnel": {
            "core_universe": len(core_rows),
            "cheap_scan_passed": len({item["code"] for rows in candidates.values() for item in rows}),
            "qualification_candidates": len(qualification_codes),
            "queue_items": {strategy: len(queues[strategy]) for strategy in STRATEGIES},
            "excluded": len(excluded),
        },
        "coverage": {
            "universe": "PROVIDER_SH_SZ_CORE_A_SHARES_EXCLUDES_BEIJING",
            "qualification_limit": QUALIFICATION_LIMIT,
            "qualification_omitted": max(0, len({item["code"] for rows in candidates.values() for item in rows}) - len(qualification_codes)),
            "qualification_order": "STRATEGY_AMOUNT_DESC_THEN_CODE_DEDUPLICATED",
            "queue_limit": QUEUE_LIMIT,
            "queue_eligible": queue_eligible_counts,
            "queue_omitted": {strategy: queue_eligible_counts[strategy] - len(queues[strategy]) for strategy in STRATEGIES},
            "queue_order": "RESEARCH_PRIORITY_THEN_SECURITY_CODE",
            "filter_scope": "RETURNED_QUEUE_ONLY",
            "excluded_total": excluded_total,
            "excluded_omitted": excluded_total - len(excluded),
        },
        "datasets": datasets,
        "queues": queues,
        "excluded": excluded,
        "limitations": limitations,
        "cache": {"hit": False, "age_seconds": 0},
    }


def clear_cache() -> None:
    global _CACHE_VALUE, _CACHE_MONOTONIC, _LAST_SUCCESSFUL
    with _CACHE_LOCK:
        _CACHE_VALUE = None
        _CACHE_MONOTONIC = 0.0
        _LAST_SUCCESSFUL = None


def get_discovery(*, force_refresh: bool = False) -> dict[str, Any]:
    global _CACHE_VALUE, _CACHE_MONOTONIC, _LAST_SUCCESSFUL
    with _CACHE_LOCK:
        age = time.monotonic() - _CACHE_MONOTONIC
        if not force_refresh and _CACHE_VALUE is not None and age < CACHE_TTL_SECONDS:
            cached = copy.deepcopy(_CACHE_VALUE)
            cached["cache"] = {"hit": True, "age_seconds": round(max(0.0, age), 3)}
            return cached
        previous = copy.deepcopy(_LAST_SUCCESSFUL)

    if not _REFRESH_LOCK.acquire(blocking=False):
        if previous is not None:
            previous["status"] = "stale"
            previous["cache"] = {"hit": True, "age_seconds": None, "refresh_in_progress": True}
            return previous
        return {
            "schema_version": SCHEMA_VERSION, "status": "unavailable",
            "reason_code": "DISCOVERY_REFRESH_IN_PROGRESS", "as_of": None,
            "fetched_at": None, "last_successful_at": None, "refresh_attempted_at": _iso_now(),
            "market_context": {"status": "unavailable", "core_universe_count": 0, "sector_count": 0},
            "funnel": {"core_universe": 0, "cheap_scan_passed": 0, "qualification_candidates": 0,
                       "queue_items": {strategy: 0 for strategy in STRATEGIES}, "excluded": 0},
            "datasets": [], "queues": {strategy: [] for strategy in STRATEGIES}, "excluded": [],
            "limitations": ["Discovery 刷新进行中；本次请求未重复启动上游工作。"],
            "cache": {"hit": False, "age_seconds": 0, "refresh_in_progress": True},
        }
    try:
        result = run_discovery()
        if result["status"] in {"normal", "partial"}:
            with _CACHE_LOCK:
                _CACHE_VALUE = copy.deepcopy(result)
                _CACHE_MONOTONIC = time.monotonic()
                _LAST_SUCCESSFUL = copy.deepcopy(result)
            return result
        if previous is not None:
            previous["status"] = "stale"
            previous["refresh_attempted_at"] = result.get("refresh_attempted_at") or result["fetched_at"]
            previous["limitations"] = [*previous.get("limitations", []), "本次刷新失败；当前展示最后一次成功结果。"]
            previous["cache"] = {"hit": True, "age_seconds": None, "refresh_failed": True}
            return previous
        return result
    finally:
        _REFRESH_LOCK.release()
