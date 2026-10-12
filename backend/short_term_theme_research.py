"""Versioned, deterministic theme/rotation/lineage research; no I/O or authority writes.

Provider editorial attribution is never a company fact. All inputs are dated
captured evidence; a capture timestamp does not establish historical availability.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math
import re
from typing import Any

VERSION = "short-term-theme-research-v1"
THEME_NORMALIZER = "ths-theme-pages-v1"
THEME_DATASET = "research_shortline_themes"
MAX_THEME_ROWS = 10000
MAX_TAGS_PER_STOCK = 64
MAX_LABEL_LENGTH = 256
MAX_REASON_LENGTH = 16384
SHANGHAI = timezone(timedelta(hours=8))
CODE = re.compile(r"\d{6}\Z")


def normalize_ths_theme_pages(pages: Any, trade_date: str) -> dict:
    """Decode captured provider envelopes, checking EVERY row's source timestamp.

    Capture manifests must retain individual response bytes. This function receives
    their decoded envelopes, never performs HTTP, and does not infer dates from a
    requested date or capture clock. Incomplete pagination is not admissible.
    """
    if not isinstance(pages, list) or not pages or len(pages) > 20:
        raise ValueError("THEME_PAGES_INVALID")
    rows, seen, total = [], set(), None
    for page in pages:
        if not isinstance(page, dict) or type(page.get("status_code")) is not int or page["status_code"] != 0:
            raise ValueError("THEME_PROVIDER_ERROR")
        data = page.get("data")
        if not isinstance(data, dict) or not isinstance(data.get("info"), list):
            raise ValueError("THEME_ROWS_INVALID")
        count = (data.get("page") or {}).get("total")
        if type(count) is not int or not 0 <= count <= MAX_THEME_ROWS or (total is not None and total != count):
            raise ValueError("THEME_TOTAL_INVALID")
        total = count
        for row in data["info"]:
            if not isinstance(row, dict):
                raise ValueError("THEME_ROW_INVALID")
            code = row.get("code")
            if not isinstance(code, str) or not CODE.fullmatch(code) or code in seen:
                raise ValueError("THEME_DUPLICATE_OR_INVALID_CODE")
            seen.add(code)
            stamp = row.get("first_limit_up_time")
            if isinstance(stamp, bool) or not isinstance(stamp, (float, int)) or not math.isfinite(stamp):
                raise ValueError("THEME_SOURCE_TIME_MISSING")
            try:
                when = datetime.fromtimestamp(stamp, SHANGHAI)
            except (ValueError, OverflowError, OSError):
                raise ValueError("THEME_SOURCE_TIME_INVALID") from None
            if when.date().isoformat() != trade_date:
                raise ValueError("THEME_SOURCE_DATE_MISMATCH")
            if not ("09:25:00" <= when.strftime("%H:%M:%S") <= "11:30:00" or "13:00:00" <= when.strftime("%H:%M:%S") <= "15:00:00"):
                raise ValueError("THEME_SOURCE_TIME_OUTSIDE_SESSION")
            reason = row.get("reason_type")
            tags = []
            if isinstance(reason, str) and len(reason) > MAX_REASON_LENGTH:
                raise ValueError("THEME_REASON_OVERSIZED")
            if isinstance(reason, str) and reason.strip() not in {"", "-", "暂无"}:
                # A delimiter split is explicit parsing, not synonym normalization.
                # Keep exact label text (apart from surrounding whitespace), no cap,
                # generic-label exclusion, industry fallback or partial-word truncation.
                tags = list(dict.fromkeys(t.strip() for t in re.split(r"[+，,]", reason) if t.strip()))
            if len(tags) > MAX_TAGS_PER_STOCK or any(len(t) > MAX_LABEL_LENGTH for t in tags):
                raise ValueError("THEME_TAGS_OVERSIZED")
            rows.append({"stock_code": code, "source_trade_date": trade_date,
                         "first_seal": when.strftime("%H:%M:%S"), "raw_reason": reason if isinstance(reason, str) else None,
                         "tags": tags, "attribution": "PROVIDER_EDITORIAL_NOT_COMPANY_FACT"})
    if len(seen) > MAX_THEME_ROWS or len(seen) != total or not seen:
        raise ValueError("THEME_PAGINATION_INCOMPLETE_OR_EMPTY_UNDATED")
    return {"schema_version": THEME_NORMALIZER, "trade_date": trade_date,
            "provider_id": "ths", "complete": True, "source_total": total, "rows": rows}


def _integer(value: Any, minimum: int = 0) -> bool:
    return type(value) is int and value >= minimum


def _day(day: str, evidence: dict | None) -> dict:
    empty = {"date": day, "available": False, "complete": False, "limit_up": None,
             "covered": None, "concentration": None, "concentration_numerator": None, "concentration_denominator": None, "highest_board": None, "broken_rate": None, "pool_overlap_count": None, "leaders": [],
             "tags": {}, "members": {}, "firstboards": [], "source": None, "outcome_pools": {}}
    if not evidence or evidence.get("trade_date") != day:
        return empty
    pool, themes = evidence.get("pool"), evidence.get("themes")
    if not isinstance(pool, dict) or pool.get("trade_date") != day or not isinstance(pool.get("rows"), list) or pool.get("post_close_observation") is not True or pool.get("status") not in {"normal", "partial"}:
        return empty
    by = {}
    for row in pool["rows"]:
        if not isinstance(row, dict) or not isinstance(row.get("stock_code"), str) or not CODE.fullmatch(row["stock_code"]) or row["stock_code"] in by or (row.get("boards") is not None and not _integer(row.get("boards"), 1)):
            return empty
        by[row["stock_code"]] = dict(row)
    pool_complete = pool.get("complete") is True and pool.get("status") == "normal"
    if not by and not (pool_complete and pool.get("legal_zero") is True):
        return empty
    heights_known = all(_integer(r.get("boards"), 1) for r in by.values())
    highest = max((r["boards"] for r in by.values()), default=0) if heights_known else None
    leaders = sorted((r for r in by.values() if r["boards"] == highest), key=lambda r: (r.get("first_seal") or "99:99:99", r["stock_code"]))
    out = {**empty, "limit_up": len(by) if pool_complete else None,
           "highest_board": highest if pool_complete else None,
           "leaders": leaders if pool_complete and heights_known else [], "members": by, "source": evidence.get("source"),
           "outcome_pools": {k: {"complete": pool.get(k + "_complete") is True, "rows": pool.get(k + "_rows", [])} for k in ("broken", "limit_down")},
           "firstboards": sorted((r for r in by.values() if r["boards"] == 1), key=lambda r: (r.get("first_seal") or "99:99:99", r["stock_code"]))}
    broken_codes = {r["stock_code"] for r in pool.get("broken_rows", [])}
    overlap = set(by) & broken_codes
    if pool_complete and pool.get("broken_complete") is True:
        out["pool_overlap_count"] = len(overlap)
        union = len(set(by) | broken_codes)
        if union and not overlap:
            out["broken_rate"] = len(broken_codes) / union
    if overlap:
        out["outcome_pools"]["broken"]["complete"] = False
    if not isinstance(themes, dict) or themes.get("trade_date") != day or not isinstance(themes.get("rows"), list):
        return out
    assignments = {}
    for row in themes["rows"]:
        if not isinstance(row, dict) or row.get("source_trade_date") != day or row.get("stock_code") in assignments or not isinstance(row.get("tags"), list) or any(not isinstance(t, str) or not t for t in row["tags"]):
            return out
        assignments[row["stock_code"]] = row
    groups, matched = {}, 0
    for code, member in by.items():
        assignment = assignments.get(code, {})
        tags = list(dict.fromkeys(assignment.get("tags", [])))
        member["tags"] = tags
        member["theme_source_date"] = assignment.get("source_trade_date")
        member["theme_first_seal"] = assignment.get("first_seal")
        if tags:
            matched += 1
        for tag in tags:
            groups.setdefault(tag, []).append(member)
    complete = pool_complete and themes.get("complete") is True and matched == len(by)
    stats = {t: {"count": len(ms), "highest": max(m["boards"] for m in ms) if all(_integer(m.get("boards"), 1) for m in ms) else None, "members": ms} for t, ms in groups.items()}
    for g in stats.values():
        g["rank"] = 1 + sum(x["count"] > g["count"] for x in stats.values()) if complete else None
    return {**out, "available": True, "complete": complete, "covered": matched, "tags": stats,
            "concentration": max((x["count"] for x in stats.values()), default=0) / len(by) if complete and by else None,
            "concentration_numerator": max((x["count"] for x in stats.values()), default=0) if complete else None,
            "concentration_denominator": len(by) if complete else None}


def _return_pct(close, base):
    if close is None or base is None:
        return None
    value = (close / base - 1) * 100
    return round(value, 6) if math.isfinite(value) else None


def _drawdown(final, peak):
    if final is None or peak is None or 1 + peak / 100 <= 0:
        return None
    value = ((1 + final / 100) / (1 + peak / 100) - 1) * 100
    return round(value, 6) if math.isfinite(value) else None


def _lineage(days: list[dict], prices: dict[str, dict]) -> list[dict]:
    result, seen = [], set()
    current = {r["stock_code"] for r in days[-1]["leaders"]}
    for day in days:
        for leader in day["leaders"]:
            code = leader["stock_code"]
            if code in seen:
                continue
            seen.add(code)
            expected = [d["date"] for d in days if d["date"] >= day["date"]]
            price = prices.get(code, {})
            # A common versioned corporate-action basis is required, not just qfq.
            comparable = (price.get("price_unit") == "CNY/share" and price.get("adjustment") == "forward_adjusted"
                          and isinstance(price.get("adjustment_basis_id"), str) and bool(price["adjustment_basis_id"])
                          and price.get("single_capture") is True and price.get("stock_code") == code)
            closes = {}
            if comparable:
                for row in price.get("rows", []):
                    if not isinstance(row, dict) or row.get("date") in closes:
                        comparable = False
                        break
                    val = row.get("close")
                    closes[row.get("date")] = val if type(val) in (int, float) and math.isfinite(val) and val > 0 else None
            base = closes.get(day["date"]) if comparable else None
            series = [{"date": d, "cum_return_pct": _return_pct(closes.get(d), base)} for d in expected]
            complete = all(p["cum_return_pct"] is not None for p in series)
            vals = [p["cum_return_pct"] for p in series] if complete else []
            peak = max(vals) if len(vals) >= 2 else None
            final = series[-1]["cum_return_pct"]
            result.append({"stock_code": code, "name": leader.get("name"), "appear_date": day["date"],
                           "boards_then": leader["boards"], "is_current_top": code in current if days[-1]["highest_board"] is not None else None,
                           "series": series, "cum_return_pct": final, "peak_cum_return_pct": peak,
                           "drawdown_from_peak_pct": _drawdown(final, peak),
                           "price_unit": price.get("price_unit"), "adjustment": price.get("adjustment"),
                           "adjustment_basis_id": price.get("adjustment_basis_id"), "source": price.get("source"),
                           "status": "complete" if complete else "unknown_or_partial"})
    return result


def build_theme_research(sessions: list[str], evidence: dict[str, dict], prices: dict[str, dict] | None = None) -> dict:
    """Exact five exchange sessions, not the latest five observed dates.

    Counts are distinct stocks per tag; multi-labelled stocks contribute to each
    separate tag. Coverage denominator is distinct qualified pool stocks. Tags are
    never exclusive partitions and their counts must not be added into market size.
    """
    if len(sessions) != 5 or sessions != sorted(set(sessions)):
        raise ValueError("FIVE_FIXED_SESSIONS_REQUIRED")
    days = [_day(d, evidence.get(d)) for d in sessions]
    union = sorted({t for d in days for t in d["tags"]})
    if len(union) > 1024 or sum(len(g["members"]) for d in days for g in d["tags"].values()) > 50000:
        raise ValueError("THEME_PROJECTION_OVERSIZED")
    rotations, tree = [], []
    for tag in union:
        cells = []
        for d in days:
            group = d["tags"].get(tag)
            cells.append({"date": d["date"], "count": group["count"] if group else 0 if d["complete"] else None,
                          "rank": group["rank"] if group else None, "highest": group["highest"] if group else 0 if d["complete"] else None,
                          "lower_bound": bool(group and not d["complete"])})
        streak = 0
        for cell in reversed(cells):
            if cell["count"] is None or cell["count"] == 0:
                break
            streak += 1
        rotations.append({"tag": tag, "cells": cells, "observed_active_days": sum(c["count"] is not None and c["count"] > 0 for c in cells),
                          "top3_days": sum(c["rank"] is not None and c["rank"] <= 3 for c in cells),
                          "streak": streak if cells[-1]["count"] is not None else None,
                          "streak_lower_bound": streak == 5 or (streak > 0 and cells[-streak-1]["count"] is None)})
        today, previous = days[-1], days[-2]
        group, prev_group = today["tags"].get(tag), previous["tags"].get(tag)
        if group or prev_group:
            prior_members = prev_group["members"] if prev_group else []
            continued = sum(m["stock_code"] in today["members"] for m in prior_members) if today["limit_up"] is not None else None
            current_members = group["members"] if group else []
            historical_codes = {m["stock_code"] for m in prior_members}
            current_codes = {m["stock_code"] for m in current_members}
            outcome_counts = {}
            for outcome in ("broken", "limit_down"):
                source = today["outcome_pools"].get(outcome, {})
                codes = {r.get("stock_code") for r in source.get("rows", []) if isinstance(r, dict)}
                # These are outcomes of the explicitly named prior/current tagged
                # cohort, not today's new editorial attribution of failed stocks.
                outcome_counts[outcome] = len(codes & (historical_codes | current_codes)) if source.get("complete") else None
            times = sorted(m["theme_first_seal"] for m in current_members if m.get("theme_first_seal"))
            tree.append({"tag": tag, "first_seal": times[0] if times else None,
                         "first_boards": sum(m["boards"] == 1 for m in current_members) if group else 0 if today["complete"] else None,
                         "highest": group["highest"] if group else 0 if today["complete"] else None,
                         "cohort_broken": outcome_counts["broken"], "cohort_limit_down": outcome_counts["limit_down"],
                         "outcome_attribution_basis": "CURRENT_OR_PREVIOUS_DATED_TAGGED_COHORT", "count": cells[-1]["count"], "lower_bound": cells[-1]["lower_bound"],
                         "members": group["members"] if group else [], "previous_members": prior_members,
                         "previous_count": len(prior_members) if prev_group else 0 if previous["complete"] else None,
                         "continued_count": continued,
                         "continuation_rate": continued / len(prior_members) if continued is not None and prior_members else None,
                         "continuation_sample_only": not previous["complete"],
                         "state": "unknown" if cells[-1]["count"] is None else "no_current_limit_up" if cells[-1]["count"] == 0 else "observed"})
    public_days = [{k: v for k, v in d.items() if k not in {"tags", "members", "outcome_pools"}} for d in days]
    return {"schema_version": VERSION, "trade_date": sessions[-1], "sessions": sessions,
            "status": "complete" if all(d["complete"] for d in days) else "partial" if any(d["available"] for d in days) else "unavailable",
            "days": public_days, "tree": tree, "rotation": rotations, "lineage": _lineage(days, prices or {}),
            "attribution": "PROVIDER_EDITORIAL_NOT_COMPANY_FACT", "point_in_time_claim": "NONE",
            "multi_label_policy": "distinct stock per exact tag; denominator distinct qualified pool stocks; labels overlap",
            "rank_policy": "competition rank by count; all ties retained; incomplete days unranked",
            "canonical_authority": False}
