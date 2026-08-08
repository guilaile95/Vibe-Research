"""Candidate signal screener service v0.1.

Pulls klines → technical_indicators.compute_indicators → AND condition eval.
Per-stock isolation; max 4 concurrent workers. No portfolio/watchlist I/O.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any

import re

import astock
import sector_research_data as srd
import technical_indicators as ti
from screener_models import (
    SCHEMA_VERSION,
    SCREENER_KLINE_DAYS,
    ScreenerCondition,
    ScreenerEvaluateIn,
)

_CODE_RE = re.compile(r"^\d{6}$")

_MAX_WORKERS = 4

# Trigger keys from technical_indicators._detect_triggers (do not invent names)
_TRIGGER_BREAKOUT = "close_above_20d_high"
_TRIGGER_BREAKDOWN = "close_below_20d_low"

def _price_range_trigger_unevaluable(envelope: dict) -> bool:
    """True when compute_indicators reports incomplete high/low window for range triggers."""
    prefix = ti.PRICE_RANGE_TRIGGER_UNAVAILABLE_PREFIX
    for lim in envelope.get("limitations") or []:
        if isinstance(lim, str) and lim.startswith(prefix):
            return True
    return False


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def list_sector_representative_codes() -> list[str]:
    """Authoritative sector representative codes from sector_research_data.

    Uses public list_sector_source_keys() + get_sector_source() only.
    Filters strict 6-digit codes, dedupes, returns ascending order.
    """
    seen: set[str] = set()
    out: list[str] = []
    for key in srd.list_sector_source_keys():
        src = srd.get_sector_source(key)
        if src is None:
            continue
        for raw in src.representative_company_codes or []:
            code = str(raw).strip()
            if not _CODE_RE.fullmatch(code) or code in seen:
                continue
            seen.add(code)
            out.append(code)
    out.sort()
    return out


def _trigger_types(envelope: dict) -> set[str]:
    out: set[str] = set()
    for t in envelope.get("triggers") or []:
        if isinstance(t, dict) and isinstance(t.get("type"), str):
            out.add(t["type"])
    return out


def _latest(envelope: dict) -> dict:
    latest = envelope.get("latest")
    return latest if isinstance(latest, dict) else {}


def evaluate_condition(condition: ScreenerCondition, envelope: dict) -> dict:
    """Evaluate one condition against a compute_indicators envelope.

    Returns ConditionResult dict: id, evaluable, passed, evidence.
    """
    cid = condition.id
    latest = _latest(envelope)
    close = latest.get("close")
    sma20 = latest.get("sma20")
    sma60 = latest.get("sma60")
    rsi14 = latest.get("rsi14")
    macd_hist = latest.get("macd_histogram")
    vr = latest.get("volume_ratio_5_20")
    triggers = _trigger_types(envelope)

    def unevaluable(evidence: dict) -> dict:
        return {"id": cid, "evaluable": False, "passed": None, "evidence": evidence}

    def ok(passed: bool, evidence: dict) -> dict:
        return {"id": cid, "evaluable": True, "passed": passed, "evidence": evidence}

    if cid == "price_gt_sma20":
        if close is None or sma20 is None:
            return unevaluable({"close": close, "sma20": sma20})
        return ok(close > sma20, {"close": close, "sma20": sma20})

    if cid == "price_lt_sma20":
        if close is None or sma20 is None:
            return unevaluable({"close": close, "sma20": sma20})
        return ok(close < sma20, {"close": close, "sma20": sma20})

    if cid == "price_gt_sma60":
        if close is None or sma60 is None:
            return unevaluable({"close": close, "sma60": sma60})
        return ok(close > sma60, {"close": close, "sma60": sma60})

    if cid == "price_lt_sma60":
        if close is None or sma60 is None:
            return unevaluable({"close": close, "sma60": sma60})
        return ok(close < sma60, {"close": close, "sma60": sma60})

    if cid == "sma20_gt_sma60":
        if sma20 is None or sma60 is None:
            return unevaluable({"sma20": sma20, "sma60": sma60})
        return ok(sma20 > sma60, {"sma20": sma20, "sma60": sma60})

    if cid == "sma20_lt_sma60":
        if sma20 is None or sma60 is None:
            return unevaluable({"sma20": sma20, "sma60": sma60})
        return ok(sma20 < sma60, {"sma20": sma20, "sma60": sma60})

    if cid == "macd_hist_positive":
        if macd_hist is None:
            return unevaluable({"macd_histogram": macd_hist})
        return ok(macd_hist > 0, {"macd_histogram": macd_hist})

    if cid == "macd_hist_negative":
        if macd_hist is None:
            return unevaluable({"macd_histogram": macd_hist})
        return ok(macd_hist < 0, {"macd_histogram": macd_hist})

    if cid == "breakout_20d_high":
        # Do not recompute 20d high/low — only trigger keys + limitation prefix.
        if _TRIGGER_BREAKOUT in triggers:
            return ok(True, {"trigger": _TRIGGER_BREAKOUT, "present": True, "close": close})
        if close is None:
            return unevaluable({"trigger": _TRIGGER_BREAKOUT, "present": False, "close": close})
        if _price_range_trigger_unevaluable(envelope):
            return unevaluable(
                {
                    "trigger": _TRIGGER_BREAKOUT,
                    "present": False,
                    "close": close,
                    "reason": "price_range_incomplete",
                }
            )
        return ok(False, {"trigger": _TRIGGER_BREAKOUT, "present": False, "close": close})

    if cid == "breakdown_20d_low":
        if _TRIGGER_BREAKDOWN in triggers:
            return ok(True, {"trigger": _TRIGGER_BREAKDOWN, "present": True, "close": close})
        if close is None:
            return unevaluable({"trigger": _TRIGGER_BREAKDOWN, "present": False, "close": close})
        if _price_range_trigger_unevaluable(envelope):
            return unevaluable(
                {
                    "trigger": _TRIGGER_BREAKDOWN,
                    "present": False,
                    "close": close,
                    "reason": "price_range_incomplete",
                }
            )
        return ok(False, {"trigger": _TRIGGER_BREAKDOWN, "present": False, "close": close})

    if cid == "rsi_between":
        params = condition.params  # type: ignore[attr-defined]
        if rsi14 is None:
            return unevaluable({"rsi14": rsi14, "min": params.min, "max": params.max})
        passed = params.min <= rsi14 <= params.max
        return ok(passed, {"rsi14": rsi14, "min": params.min, "max": params.max})

    if cid == "volume_ratio_gte":
        params = condition.params  # type: ignore[attr-defined]
        if vr is None:
            return unevaluable({"volume_ratio_5_20": vr, "threshold": params.threshold})
        return ok(
            vr >= params.threshold,
            {"volume_ratio_5_20": vr, "threshold": params.threshold},
        )

    if cid == "volume_ratio_lte":
        params = condition.params  # type: ignore[attr-defined]
        if vr is None:
            return unevaluable({"volume_ratio_5_20": vr, "threshold": params.threshold})
        return ok(
            vr <= params.threshold,
            {"volume_ratio_5_20": vr, "threshold": params.threshold},
        )

    # Unknown id should be rejected by Pydantic; defensive fallback
    return unevaluable({"error": "unknown_condition"})


def classify_stock(condition_results: list[dict], technical_status: str) -> str:
    """Return bucket: matched | rejected | unavailable."""
    if technical_status == "unavailable":
        return "unavailable"

    has_false = False
    has_unevaluable = False
    for cr in condition_results:
        if cr.get("evaluable") is False:
            has_unevaluable = True
        elif cr.get("passed") is False:
            has_false = True

    # Explicit AND false → rejected even if other conditions are unevaluable
    if has_false:
        return "rejected"
    if has_unevaluable:
        return "unavailable"
    return "matched"


def evaluate_one_stock(
    code: str,
    conditions: list[ScreenerCondition],
    *,
    kline_fn=None,
    compute_fn=None,
    days: int = SCREENER_KLINE_DAYS,
) -> dict:
    """Evaluate a single code. Isolates all exceptions into unavailable."""
    kline_fn = kline_fn or (lambda c, d: astock.kline(c, category=4, offset=d))
    compute_fn = compute_fn or ti.compute_indicators
    fetched_at = _utc_now_iso()

    try:
        try:
            raw_klines = kline_fn(code, days)
        except Exception:
            return _unavailable_stock(
                code,
                technical_status="unavailable",
                trade_date=None,
                condition_results=[],
                limitations=["K 线数据不可用"],
                conditions=conditions,
            )

        if not raw_klines:
            return _unavailable_stock(
                code,
                technical_status="unavailable",
                trade_date=None,
                condition_results=[],
                limitations=["无有效 K 线数据"],
                conditions=conditions,
            )

        envelope = compute_fn(
            raw_klines,
            code=code,
            period="daily",
            days=days,
            trade_date=None,
            fetched_at=fetched_at,
        )
        tech_status = str(envelope.get("status") or "unavailable")
        trade_date = envelope.get("trade_date")
        limitations = list(envelope.get("limitations") or [])

        if tech_status == "unavailable":
            return _unavailable_stock(
                code,
                technical_status="unavailable",
                trade_date=trade_date if isinstance(trade_date, str) else None,
                condition_results=[],
                limitations=limitations or ["技术指标不可用"],
                conditions=conditions,
            )

        condition_results = [evaluate_condition(c, envelope) for c in conditions]
        bucket = classify_stock(condition_results, tech_status)
        matched: bool | None
        if bucket == "matched":
            matched = True
        elif bucket == "rejected":
            matched = False
        else:
            matched = None

        return {
            "code": code,
            "bucket": bucket,
            "matched": matched,
            "technical_status": tech_status,
            "trade_date": trade_date if isinstance(trade_date, str) else None,
            "condition_results": condition_results,
            "limitations": limitations,
        }
    except Exception:
        return _unavailable_stock(
            code,
            technical_status="unavailable",
            trade_date=None,
            condition_results=[],
            limitations=["单票评估异常"],
            conditions=conditions,
        )


def _unavailable_stock(
    code: str,
    *,
    technical_status: str,
    trade_date: str | None,
    condition_results: list[dict],
    limitations: list[str],
    conditions: list[ScreenerCondition],
) -> dict:
    # If no condition results yet, still return empty list (not fabricated passes)
    return {
        "code": code,
        "bucket": "unavailable",
        "matched": None,
        "technical_status": technical_status,
        "trade_date": trade_date,
        "condition_results": condition_results,
        "limitations": limitations,
    }


def _top_status(stocks: list[dict]) -> str:
    if not stocks:
        return "unavailable"
    if all(s.get("bucket") == "unavailable" for s in stocks):
        return "unavailable"
    for s in stocks:
        if s.get("bucket") == "unavailable":
            return "partial"
        if s.get("technical_status") == "partial":
            return "partial"
    return "normal"


def evaluate_screener(
    body: ScreenerEvaluateIn,
    *,
    kline_fn=None,
    compute_fn=None,
    max_workers: int = _MAX_WORKERS,
    now_iso: str | None = None,
) -> dict:
    """Run screener for normalized codes/conditions. Deterministic bucket sort by code."""
    codes = list(body.codes)  # already sorted + deduped by model
    conditions = list(body.conditions)
    evaluated_at = now_iso or _utc_now_iso()

    results: dict[str, dict] = {}
    workers = max(1, min(max_workers, len(codes)))

    if len(codes) == 1:
        results[codes[0]] = evaluate_one_stock(
            codes[0], conditions, kline_fn=kline_fn, compute_fn=compute_fn
        )
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(
                    evaluate_one_stock,
                    code,
                    conditions,
                    kline_fn=kline_fn,
                    compute_fn=compute_fn,
                ): code
                for code in codes
            }
            for fut in as_completed(futures):
                code = futures[fut]
                try:
                    results[code] = fut.result()
                except Exception:
                    results[code] = _unavailable_stock(
                        code,
                        technical_status="unavailable",
                        trade_date=None,
                        condition_results=[],
                        limitations=["单票评估异常"],
                        conditions=conditions,
                    )

    stocks = [results[c] for c in codes]  # preserve request order intermediate
    matched = sorted(
        [s for s in stocks if s["bucket"] == "matched"], key=lambda x: x["code"]
    )
    rejected = sorted(
        [s for s in stocks if s["bucket"] == "rejected"], key=lambda x: x["code"]
    )
    unavailable = sorted(
        [s for s in stocks if s["bucket"] == "unavailable"], key=lambda x: x["code"]
    )

    return {
        "status": _top_status(stocks),
        "evaluated_at": evaluated_at,
        "logic": "AND",
        "matched": matched,
        "rejected": rejected,
        "unavailable": unavailable,
        "limitations": [],
        "schema_version": SCHEMA_VERSION,
    }
