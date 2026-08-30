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

import astock
import market
import native_intel_service
import native_intel_store
import research_data_plane as rdp

SCHEMA_VERSION = "full-market-discovery.v0.1"
STRATEGIES = ("SHORT", "SWING", "MEDIUM")
QUEUE_LIMIT = 12
QUALIFICATION_LIMIT = 24
EXCLUDED_LIMIT = 60
OUTSIDE_CORE_SAMPLE_LIMIT = 5
QUALIFICATION_WORKERS = 6
QUALIFICATION_TIMEOUT_SECONDS = 45.0
CATALYST_WINDOW_DAYS = 30
EARLY_LISTING_CALENDAR_DAYS = 90
CACHE_TTL_SECONDS = 10 * 60

_BEIJING = ZoneInfo("Asia/Shanghai")
_CACHE_LOCK = threading.Lock()
_CACHE_VALUE: dict[str, Any] | None = None
_CACHE_MONOTONIC = 0.0
_LAST_SUCCESSFUL: dict[str, Any] | None = None


@dataclass(frozen=True)
class DiscoveryProviders:
    market_snapshot: Callable[[], list[dict[str, Any]]]
    full_market: Callable[[], dict[str, Any]]
    financials: Callable[[str], dict[str, Any]]
    announcements: Callable[[str], list[dict[str, Any]]]
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


def _as_of(now: datetime | None = None) -> str:
    instant = now or datetime.now(timezone.utc)
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=timezone.utc)
    return instant.astimezone(_BEIJING).date().isoformat()


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
    offset = 0
    first: dict[str, Any] | None = None
    while True:
        page = rdp.query_full_market(latest=True, limit=rdp._MAX_LIMIT, offset=offset)
        if first is None:
            first = page
        rows.extend(page.get("rows") or [])
        next_offset = page.get("next_offset")
        if next_offset is None:
            break
        if not isinstance(next_offset, int) or next_offset <= offset:
            raise rdp.ResearchDataPlaneValidationError("full-market pagination did not progress")
        offset = next_offset
    result = dict(first or {})
    result["rows"] = rows
    result["returned_rows"] = len(rows)
    return result


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
    market_snapshot=market.get_a_share_snapshot,
    full_market=_default_full_market,
    # Stage 3 needs one bounded financial clue fetch, not the three-statement
    # StockData expansion performed by include_health=True.
    financials=lambda code: astock.financials(code, include_health=False),
    announcements=astock.announcements,
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


def _full_market_rows(providers: DiscoveryProviders, fetched_at: str) -> tuple[dict[str, Any], dict[str, dict[str, Any]], dict[str, Any]]:
    try:
        envelope = providers.full_market()
        status = str(envelope.get("status") or "unavailable")
        if status != "normal":
            raise rdp.ResearchDataPlaneUnavailableError("RDP full-market is unavailable")
        rows: dict[str, dict[str, Any]] = {}
        target_date = str(envelope.get("as_of") or "")
        for raw in envelope.get("rows") or []:
            if not isinstance(raw, dict) or not str(raw.get("code") or "").isdigit():
                continue
            row = dict(raw)
            row["_discovery_stale"] = bool(target_date and str(row.get("latest_date") or "") != target_date)
            rows[str(row["code"])] = row
        provenance = envelope.get("provenance") or {}
        ref = provenance.get("artifact_sha256") or provenance.get("source_name") or "local-rdp"
        dataset = _dataset(
            "research_data_plane.full_market",
            "normal",
            as_of=envelope.get("as_of"),
            fetched_at=str(envelope.get("fetched_at") or fetched_at),
            provenance_refs=[f"research-data-plane:{ref}"],
        )
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

    def observe(code: str, label: str, value: Any, source_ref: str) -> None:
        reasons.append(code)
        observations.append({"code": code, "label": label, "value": value, "source_ref": source_ref})

    liquid = amount is not None and amount_median is not None and amount >= amount_median
    if liquid:
        observe("LIQUIDITY_AT_OR_ABOVE_MARKET_MEDIAN", "成交额位于市场中位数以上", amount, "market:a-share-snapshot:amount")
    elif amount is None:
        missing.append("AMOUNT_UNKNOWN")

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
        return {"passed": passed, "status": "NORMAL" if not missing else "PARTIAL", "reason_codes": reasons, "missing": missing, "observations": observations}

    metric = "return_20d" if strategy == "SWING" else "return_60d"
    history_stale = bool((history or {}).get("_discovery_stale"))
    metric_status = str((history or {}).get(f"{metric}_status") or "")
    momentum = _finite((history or {}).get(metric)) if metric_status == "normal" and not history_stale else None
    history_available = momentum is not None
    if history_available and momentum > 0:
        observe(f"POSITIVE_{metric.upper()}", f"{metric.removeprefix('return_').upper()} 日收益为正", momentum, f"research-data-plane:{metric}")
    elif history_stale:
        missing.append("HISTORICAL_ROW_STALE")
    elif not history_available:
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
    return {"passed": passed, "status": "NORMAL" if history_available and not missing else "PARTIAL", "reason_codes": reasons, "missing": missing, "observations": observations}


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
        return {"status": "UNKNOWN", "clue": None, "source_ref": "astock.financials"}
    available = any(payload.get(key) is not None for key in ("revenue", "net_profit", "operating_cash_flow", "roe"))
    quality = payload.get("data_quality") if isinstance(payload.get("data_quality"), dict) else {}
    status = "AVAILABLE" if available and quality.get("status") != "partial" else "PARTIAL" if available else "UNKNOWN"
    clue = {
        key: payload.get(key)
        for key in ("period", "revenue_yoy", "net_profit_yoy", "operating_cash_flow", "roe")
        if payload.get(key) is not None
    } or None
    return {"status": status, "clue": clue, "source_ref": "astock.financials"}


def _announcement_date(row: dict[str, Any]) -> date | None:
    raw = row.get("notice_at") or row.get("date")
    if not isinstance(raw, str) or len(raw) < 10:
        return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


def _qualify_one(code: str, providers: DiscoveryProviders, as_of: date) -> dict[str, Any]:
    try:
        fundamental = _fundamental_result(providers.financials(code))
    except Exception:  # provider boundary: expose a fixed state, never raw exception text
        fundamental = {"status": "ERROR", "clue": None, "source_ref": "astock.financials"}
    try:
        announcements = providers.announcements(code) or []
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
            "count": len(recent),
            "older_or_future_count": max(0, len(announcements) - len(recent) - unknown_date_count),
            "unknown_date_count": unknown_date_count,
            "latest": {
                "title": recent[0].get("title"),
                "date": recent[0].get("notice_at") or recent[0].get("date"),
            } if recent else None,
            "source_ref": "astock.announcements",
        }
    except Exception:
        announcement_result = {"status": "ERROR", "count": 0, "latest": None, "source_ref": "astock.announcements"}
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
    executor = ThreadPoolExecutor(max_workers=QUALIFICATION_WORKERS, thread_name_prefix="discovery-stage3")
    futures = {executor.submit(_qualify_one, code, providers, as_of): code for code in codes}
    # Provider clients keep their own per-call timeout; this outer cap prevents
    # one slow shortlist member from blocking the whole Discovery response.
    done, pending = wait(futures, timeout=QUALIFICATION_TIMEOUT_SECONDS)
    for future in done:
        code = futures[future]
        try:
            results[code] = future.result()
        except Exception:
            results[code] = {
                "fundamental": {"status": "ERROR", "clue": None, "source_ref": "astock.financials"},
                "announcements": {"status": "ERROR", "count": 0, "latest": None, "source_ref": "astock.announcements"},
            }
    for future in pending:
        future.cancel()
        code = futures[future]
        results[code] = {
            "fundamental": {"status": "ERROR", "clue": None, "source_ref": "astock.financials", "reason_code": "TIMEOUT"},
            "announcements": {"status": "ERROR", "count": 0, "latest": None, "source_ref": "astock.announcements", "reason_code": "TIMEOUT"},
        }
    # ponytail: provider calls are already limited to a 24-stock shortlist; a
    # shared job runner is only warranted if concurrent manual refreshes become real.
    executor.shutdown(wait=False, cancel_futures=True)

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
    if restricted["status"] == "RESTRICTED" and not (fundamental == "AVAILABLE" and catalyst_available):
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
    as_of: str,
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
    if catalyst_status != "AVAILABLE":
        uncertainties.append("CATALYST_EVIDENCE_UNKNOWN")
    if (qualification.get("native_intel") or {}).get("mapping_status") != "MAPPED":
        uncertainties.append("NATIVE_INTEL_MAPPING_UNKNOWN")

    reason_codes = list(dict.fromkeys([
        *cheap["reason_codes"],
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
            "label": "近期财务事实可用于继续研究",
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
    fetched_at = _iso_now(now)
    fallback_as_of = _as_of(now)
    try:
        snapshot = providers.market_snapshot()
    except Exception:
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "unavailable",
            "as_of": fallback_as_of,
            "fetched_at": fetched_at,
            "last_successful_at": None,
            "market_context": {"status": "unavailable", "core_universe_count": 0, "sector_count": 0},
            "funnel": {"core_universe": 0, "cheap_scan_passed": 0, "qualification_candidates": 0, "queue_items": {strategy: 0 for strategy in STRATEGIES}, "excluded": 0},
            "datasets": [_dataset("market.a_share_snapshot", "unavailable", as_of=fallback_as_of, fetched_at=fetched_at, provenance_refs=[], reason_code="UPSTREAM_UNAVAILABLE")],
            "queues": {strategy: [] for strategy in STRATEGIES},
            "excluded": [],
            "limitations": ["全 A 股批量快照不可用；Discovery 不回退为逐股抓取。"],
            "cache": {"hit": False, "age_seconds": 0},
        }
    if not isinstance(snapshot, list) or not snapshot:
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "unavailable",
            "as_of": fallback_as_of,
            "fetched_at": fetched_at,
            "last_successful_at": None,
            "market_context": {"status": "unavailable", "core_universe_count": 0, "sector_count": 0},
            "funnel": {"core_universe": 0, "cheap_scan_passed": 0, "qualification_candidates": 0, "queue_items": {strategy: 0 for strategy in STRATEGIES}, "excluded": 0},
            "datasets": [_dataset("market.a_share_snapshot", "unavailable", as_of=fallback_as_of, fetched_at=fetched_at, provenance_refs=[], reason_code="EMPTY_SNAPSHOT")],
            "queues": {strategy: [] for strategy in STRATEGIES},
            "excluded": [],
            "limitations": ["全 A 股批量快照为空；Discovery 不回退为逐股抓取。"],
            "cache": {"hit": False, "age_seconds": 0},
        }

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
            "restricted": _restricted(raw, date.fromisoformat(fallback_as_of)),
        })
    core_rows.sort(key=lambda row: row["code"])
    if not core_rows:
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "unavailable",
            "as_of": fallback_as_of,
            "fetched_at": fetched_at,
            "last_successful_at": None,
            "market_context": {"status": "unavailable", "core_universe_count": 0, "sector_count": 0},
            "funnel": {"core_universe": 0, "cheap_scan_passed": 0, "qualification_candidates": 0, "queue_items": {strategy: 0 for strategy in STRATEGIES}, "excluded": len(outside_core)},
            "datasets": [_dataset("market.a_share_snapshot", "partial", as_of=fallback_as_of, fetched_at=fetched_at, provenance_refs=["market:a-share-snapshot"], reason_code="NO_CORE_ROWS")],
            "queues": {strategy: [] for strategy in STRATEGIES},
            "excluded": outside_core[:EXCLUDED_LIMIT],
            "limitations": ["批量快照没有可识别的沪深主板、创业板或科创板股票。"],
            "cache": {"hit": False, "age_seconds": 0},
        }

    rdp_envelope, histories, rdp_dataset = _full_market_rows(providers, fetched_at)
    effective_as_of = fallback_as_of
    sectors, market_average = _sector_context(core_rows)
    amounts = [value for row in core_rows if (value := _finite(row.get("amount"), positive=True)) is not None]
    turnovers = [value for row in core_rows if (value := _finite(row.get("turnover_pct"))) is not None]
    amount_median = statistics.median(amounts) if amounts else None
    turnover_upper = _percentile(turnovers, 0.75)

    candidates: dict[str, list[dict[str, Any]]] = {strategy: [] for strategy in STRATEGIES}
    cheap_by_code_strategy: dict[tuple[str, str], dict[str, Any]] = {}
    base_by_code: dict[str, dict[str, Any]] = {}
    excluded: list[dict[str, Any]] = list(outside_core[:OUTSIDE_CORE_SAMPLE_LIMIT])
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
        if history and history.get("_discovery_stale"):
            base["restricted"] = {
                **base["restricted"],
                "status": "RESTRICTED",
                "reason_codes": list(dict.fromkeys([
                    *base["restricted"]["reason_codes"],
                    "RDP_LATEST_DATE_BEHIND_MARKET",
                ])),
            }
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
            cheap_by_code_strategy[(code, strategy)] = cheap
            if cheap["passed"]:
                candidates[strategy].append(base)
            elif len(excluded) < EXCLUDED_LIMIT:
                excluded.append({
                    "security_code": code,
                    "name": row["name"],
                    "strategy": strategy,
                    "sector": sector_name,
                    "discovery_state": "EXCLUDED",
                    "reason_codes": cheap["missing"] or ["CHEAP_SCAN_NOT_QUALIFIED"],
                    "data_health": "unknown" if cheap["missing"] else "normal",
                    "restricted_universe": row["restricted"],
                    "as_of": effective_as_of,
                })

    qualification_codes = _qualification_codes(candidates)
    qualifications, intel_summary, provider_summary = _qualify(
        qualification_codes,
        providers,
        as_of=date.fromisoformat(effective_as_of),
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
                as_of=effective_as_of,
                fetched_at=fetched_at,
            )
            if gate in {"INSUFFICIENT", "ERROR"}:
                blocked.append(item)
            else:
                queues[strategy].append(item)

    priority_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    for strategy in STRATEGIES:
        queues[strategy].sort(key=lambda item: (priority_order[item["research_priority"]], item["security_code"]))
        queues[strategy] = queues[strategy][:QUEUE_LIMIT]

    excluded.extend(blocked)
    excluded = excluded[:EXCLUDED_LIMIT]
    market_dataset = _dataset(
        "market.a_share_snapshot",
        "normal",
        as_of=fallback_as_of,
        fetched_at=fetched_at,
        provenance_refs=["market:a-share-snapshot:eastmoney-clist"],
    )
    intel_dataset = _dataset(
        "native_intel.security_mentions",
        intel_summary["status"],
        as_of=effective_as_of,
        fetched_at=fetched_at,
        provenance_refs=[native_intel_service.AUTHORITY_REF] if intel_summary["status"] in {"normal", "partial", "stale"} else [],
        reason_code=intel_summary["reason_code"],
    )
    stage3_status = "normal"
    if provider_summary["timed_out"]:
        stage3_status = "partial"
    if any(
        value.get(domain, {}).get("status") == "ERROR"
        for value in qualifications.values()
        for domain in ("fundamental", "announcements")
    ):
        stage3_status = "partial"
    datasets = [
        market_dataset,
        rdp_dataset,
        _dataset("financials.snapshot", stage3_status, as_of=effective_as_of, fetched_at=fetched_at, provenance_refs=["astock.financials"]),
        _dataset("announcements.recent", stage3_status, as_of=effective_as_of, fetched_at=fetched_at, provenance_refs=["astock.announcements"]),
        intel_dataset,
    ]
    overall = "normal" if all(item["status"] == "normal" for item in datasets) else "partial"
    limitations = [
        "Discovery 是研究优先级 read model，不是 Formal Evidence、投资建议或交易权限。",
        "上市时长只在 Provider 明确提供 listing_date/listing_days 时评估；缺失保持 UNKNOWN。",
        "Theme 仅复用已有 Native Intel 实体映射；没有映射时保持 UNKNOWN。",
    ]
    if rdp_dataset["status"] != "normal":
        limitations.append("RDP 历史横截面不可用；SWING/MEDIUM 仅使用当前批量快照与行业上下文，优先级不会升级为 HIGH。")
    if stage3_status != "normal":
        limitations.append("部分财务或公告资格检查失败/超时；对应股票保持 PARTIAL、UNKNOWN 或 ERROR。")
    return {
        "schema_version": SCHEMA_VERSION,
        "status": overall,
        "as_of": effective_as_of,
        "fetched_at": fetched_at,
        "last_successful_at": fetched_at,
        "market_context": {
            "status": "normal",
            "core_universe_count": len(core_rows),
            "outside_core_count": len(outside_core),
            "sector_count": len(sectors),
            "market_average_change_pct": round(market_average, 4) if market_average is not None else None,
            "amount_median": amount_median,
            "turnover_active_threshold": turnover_upper,
            "source_ref": "market:a-share-snapshot:eastmoney-clist",
        },
        "funnel": {
            "core_universe": len(core_rows),
            "cheap_scan_passed": len({item["code"] for rows in candidates.values() for item in rows}),
            "qualification_candidates": len(qualification_codes),
            "queue_items": {strategy: len(queues[strategy]) for strategy in STRATEGIES},
            "excluded": len(excluded),
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

    result = run_discovery()
    if result["status"] in {"normal", "partial"}:
        with _CACHE_LOCK:
            _CACHE_VALUE = copy.deepcopy(result)
            _CACHE_MONOTONIC = time.monotonic()
            _LAST_SUCCESSFUL = copy.deepcopy(result)
        return result
    if previous is not None:
        previous["status"] = "stale"
        previous["fetched_at"] = result["fetched_at"]
        previous["limitations"] = [*previous.get("limitations", []), "本次刷新失败；当前展示最后一次成功结果。"]
        previous["cache"] = {"hit": True, "age_seconds": None, "refresh_failed": True}
        return previous
    return result
