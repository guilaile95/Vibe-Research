"""Pure retrospective arithmetic. Full fixed cohorts, unknown stays unknown."""
from __future__ import annotations

from collections import Counter
from statistics import mean, median
from decimal import Decimal, ROUND_HALF_UP

import shortline_research_contract as C
from shortline_research_adapters import same_cent


def _eligible(capture):
    return bool(capture and capture["status"] == "normal" and capture["complete"] and capture["post_close_observation"])


def _members(capture):
    return {r["stock_code"]: r for r in capture["rows"]} if _eligible(capture) else None


def _full_field(rows, field, calculate):
    if not rows or any(r.get(field) is None for r in rows):
        return None
    value = calculate([r[field] for r in rows])
    return C.finite(value) if type(value) in (int, float) else value


def daily_observation(inputs):
    up, broken, down = (_members(inputs.get(kind)) for kind in C.KINDS[:3])
    rows = list(up.values()) if up is not None else []
    overlaps = set(up or {}) & set(broken or {})
    union = len(set(up or {}) | set(broken or {}))
    tiers = Counter(r["boards"] for r in rows if r["boards"] is not None)
    boards_complete = bool(rows) and sum(tiers.values()) == len(rows)
    max_boards = max(tiers) if boards_complete else None
    price_input, limit_input = inputs.get("daily_prices"), inputs.get("daily_limits")
    quotes = {r["stock_code"]: r for r in price_input["rows"]} if price_input and price_input["post_close_observation"] and price_input["status"] != "unavailable" and price_input["source_finality"] != "source_declared_provisional" else {}
    limits = {r["stock_code"]: r for r in limit_input["rows"]} if limit_input and limit_input["post_close_observation"] and limit_input["status"] != "unavailable" and limit_input["source_finality"] != "source_declared_provisional" else {}
    bands = Counter()
    for symbol in up or {}:
        quote, bound = quotes.get(symbol), limits.get(symbol)
        candidates = []
        if quote and quote.get("price_valid") and bound and bound["limit_up"] is not None and bound["limit_down"] is not None:
            reference = Decimal(str(quote["previous_close"]))
            for pct in (5, 10, 20, 30):
                delta = Decimal(pct) / 100
                high = (reference * (1 + delta)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                low = (reference * (1 - delta)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                if high == Decimal(str(bound["limit_up"])) and low == Decimal(str(bound["limit_down"])):
                    candidates.append(pct)
        bands[str(candidates[0]) if len(candidates) == 1 else "unknown"] += 1
    band_complete = up is not None and bool(up) and not bands["unknown"]
    result = {"limit_up_count": len(up) if up is not None else None,
              "broken_count": len(broken) if broken is not None else None,
              "limit_down_count": len(down) if down is not None else None,
              "highest_board": max_boards,
              "price_limit_bands": {"denominator": len(up) if up is not None else None, "counts": dict(bands),
                                    "coverage": sum(n for key, n in bands.items() if key != "unknown"),
                                    "share_10": bands["10"] / len(up) if band_complete else None,
                                    "share_20": bands["20"] / len(up) if band_complete else None,
                                    "interpretation": "仅说明来源上下限价格与给定百分比取分一致，不认证法律制度；多重匹配或缺证据未知，范围不含北交所。"},
              "ladder": [{"boards": b, "count": n} for b, n in sorted(tiers.items())] if boards_complete else None,
              "ladder_gaps": [n for n in range(2, max_boards) if n not in tiers] if max_boards is not None else None,
              "broken_rate": len(broken) / union if up is not None and broken is not None and union and not overlaps else None,
              "broken_denominator": union if up is not None and broken is not None else None,
              "pool_overlap_count": len(overlaps) if up is not None and broken is not None else None,
              "seal_quality": {
                  "denominator": len(rows) if up is not None else None,
                  "broken_times_coverage": sum(r["broken_times"] is not None for r in rows),
                  "never_broken_count": _full_field(rows, "broken_times", lambda vals: sum(v == 0 for v in vals)),
                  "reopened_count": _full_field(rows, "broken_times", lambda vals: sum(v >= 1 for v in vals)),
                  "average_broken_times": _full_field(rows, "broken_times", mean),
                  "ever_opened_ratio": _full_field(rows, "broken_times", lambda vals: sum(v >= 1 for v in vals) / len(vals)),
                  "early_first_seal_count": _full_field(rows, "first_seal", lambda vals: sum(v <= "093500" for v in vals)),
                  "late_last_seal_count": _full_field(rows, "last_seal", lambda vals: sum(v >= "143000" for v in vals)),
                  "seal_fund_total_yuan": _full_field(rows, "seal_fund_yuan", sum),
              }}
    return result


def _stats(rows):
    vals = [r["return_pct"] for r in rows if r["return_pct"] is not None]
    full = bool(rows) and len(vals) == len(rows)
    return {"denominator": len(rows), "observed": len(vals), "unknown": len(rows) - len(vals),
            "coverage_ratio": len(vals) / len(rows) if rows else None,
            "status": "normal" if full else "empty" if not rows else "partial",
            "mean_pct": mean(vals) if full else None, "median_pct": median(vals) if full else None,
            "positive_count": sum(v > 0 for v in vals), "negative_count": sum(v < 0 for v in vals),
            "flat_count": sum(v == 0 for v in vals),
            "positive_ratio": sum(v > 0 for v in vals) / len(rows) if full else None,
            "loss_ge_5_count": sum(v <= -5 for v in vals) if full else None,
            "loss_ge_5_ratio": sum(v <= -5 for v in vals) / len(rows) if full else None,
            "loss_ge_7_count": sum(v <= -7 for v in vals) if full else None,
            "worst_pct": min(vals) if full else None,
            "limit_down_count": sum(r["limit_down"] is True for r in rows) if rows and all(r["limit_down"] is not None for r in rows) else None,
            "open_premium_mean_pct": mean(r["open_premium_pct"] for r in rows) if rows and all(r["open_premium_pct"] is not None for r in rows) else None}


def cohort_feedback(previous, current):
    old_up, old_broken = _members(previous.get("limit_up")), _members(previous.get("broken"))
    if old_up is None or old_broken is None:
        return {"status": "unavailable", "reason_codes": ["COMPLETE_PREVIOUS_POOLS_REQUIRED"], "rows": [], "groups": {}, "promotion": []}
    today_up, today_down = _members(current.get("limit_up")), _members(current.get("limit_down"))
    # Partial price feeds still preserve each valid member and explicit gaps.
    price_capture = current.get("daily_prices")
    prices = {r["stock_code"]: r for r in price_capture["rows"]} if price_capture and price_capture["post_close_observation"] and price_capture["status"] in ("normal", "partial") and price_capture["source_finality"] != "source_declared_provisional" else {}
    limit_capture = current.get("daily_limits")
    limits = {r["stock_code"]: r for r in limit_capture["rows"]} if limit_capture and limit_capture["post_close_observation"] and limit_capture["status"] in ("normal", "partial") and limit_capture["source_finality"] != "source_declared_provisional" else {}
    rows = []
    for code in sorted(set(old_up) | set(old_broken)):
        old, quote, boundary = old_up.get(code), prices.get(code), limits.get(code)
        valid = bool(quote and quote.get("price_valid") and quote.get("trading_status") == "traded")
        ret = quote["return_pct"] if valid else None
        up_price = same_cent(quote["close"], boundary["limit_up"]) if valid and boundary else None
        down_price = same_cent(quote["close"], boundary["limit_down"]) if valid and boundary else None
        # A complete source pool can establish membership, never missing prices.
        up_state = (code in today_up) if valid and today_up is not None else up_price
        down_state = (code in today_down) if valid and today_down is not None else down_price
        conflict = ((up_price is not None and up_state != up_price) or (down_price is not None and down_state != down_price)
                    or (up_state is True and down_state is True))
        if conflict:
            up_state = down_state = None
        today = today_up.get(code) if today_up else None
        promotion = None
        if old and old["boards"] is not None and valid and today_up is not None and not conflict:
            if today is None:
                promotion = False
            elif today["boards"] == old["boards"] + 1 and not conflict:
                promotion = True
            # A same-member but contradictory source streak is unknown.
        result = "unknown" if ret is None or conflict or up_state is None or down_state is None else "limit_up" if up_state is True else "limit_down" if down_state is True else "deep_loss" if ret <= -5 else "positive" if ret > 0 else "flat" if ret == 0 else "negative"
        rows.append({"stock_code": code, "previous_limit_up": old is not None, "previous_broken": code in old_broken,
                     "previous_boards": old["boards"] if old else None,
                     "previous_last_seal": old["last_seal"] if old else None,
                     "return_pct": ret, "open_premium_pct": quote["open_premium_pct"] if valid else None,
                     "limit_up": up_state, "limit_down": down_state, "promotion": promotion, "result": result,
                     "price_status": "source_conflict" if conflict else "traded" if valid else quote.get("trading_status", "unknown") if quote else "missing_status_unknown"})
    groups = {"all_yesterday": _stats(rows), "yesterday_limit_up": _stats([r for r in rows if r["previous_limit_up"]]),
              "yesterday_broken": _stats([r for r in rows if r["previous_broken"]]),
              "yesterday_first_board": _stats([r for r in rows if r["previous_boards"] == 1]),
              "yesterday_multi_board": _stats([r for r in rows if r["previous_boards"] is not None and r["previous_boards"] >= 2])}
    promotion = []
    for tier in sorted({r["previous_boards"] for r in rows if r["previous_boards"] is not None}):
        members = [r for r in rows if r["previous_boards"] == tier]
        known = [r for r in members if r["promotion"] is not None]
        count = sum(r["promotion"] is True for r in known)
        promotion.append({"previous_boards": tier, "denominator": len(members), "known": len(known),
                          "promoted": count, "unknown": len(members) - len(known),
                          "rate": count / len(members) if len(known) == len(members) else None})
    matrix = []
    for name, selected in [("yesterday_broken", [r for r in rows if r["previous_broken"]])] + [
            (f"boards_{tier}", [r for r in rows if r["previous_boards"] == tier]) for tier in sorted({r["previous_boards"] for r in rows if r["previous_boards"] is not None})]:
        matrix.append({"identity": name, "denominator": len(selected), "outcomes": dict(Counter(r["result"] for r in selected))})
    return {"status": "normal" if groups["all_yesterday"]["unknown"] == 0 and all(r["result"] != "unknown" for r in rows) else "partial",
            "outcome_coverage": {"classified": sum(r["result"] != "unknown" for r in rows), "unknown": sum(r["result"] == "unknown" for r in rows), "denominator": len(rows)},
            "reason_codes": [],
            "rows": rows, "groups": groups, "promotion": promotion, "matrix": matrix,
            "union_denominator": len(rows), "previous_limit_up_denominator": len(old_up),
            "previous_broken_denominator": len(old_broken), "overlap_count": len(set(old_up) & set(old_broken)),
            "promotion_authority": "DESCRIPTIVE_SOURCE_STREAK_ONLY"}


def historical_summary(days, observations, feedback, selected_date):
    previous = [day for day in days if day < selected_date]
    current = observations[selected_date]
    readings = {}
    for day in days:
        readings[day] = {key: observations[day].get(key) for key in ("limit_up_count", "highest_board", "broken_rate")}
        group = feedback.get(day, {}).get("groups", {}).get("yesterday_limit_up", {})
        first = next((p for p in feedback.get(day, {}).get("promotion", []) if p["previous_boards"] == 1), {})
        readings[day].update(money_effect_pct=group.get("median_pct"), deep_loss_count=group.get("loss_ge_5_count"), promotion_1_to_2=first.get("rate"))
    windows = []
    for size in (10, 20, 30, 60):
        chosen = previous[-size:]
        metrics = {}
        for field, current_value in readings[selected_date].items():
            vals = [readings[day][field] for day in chosen if readings[day][field] is not None]
            complete = len(chosen) == size and len(vals) == size
            metrics[field] = {"current": current_value, "sample_count": len(vals), "expected_sessions": size,
                              "missing_dates": [d for d in chosen if readings[d][field] is None],
                              "percentile": (sum(v < current_value for v in vals) + 0.5 * sum(v == current_value for v in vals)) / len(vals) if complete and current_value is not None else None,
                              "mean": mean(vals) if complete else None,
                              "status": "normal" if complete and current_value is not None else "insufficient_samples"}
        windows.append({"sessions": size, "dates": chosen, "metrics": metrics})
    return {"percentile_formula": "(less + 0.5 * equal) / N; strictly prior fixed sessions; requires full window", "windows": windows,
            "series": [{"trade_date": d, **readings[d]} for d in days]}


def historical_samples(days, observations, feedback, selected_date):
    entries = [day for day in days if day < selected_date]
    next_day = dict(zip(days[:-1], days[1:]))
    result = []
    for size in (20, 30, 60, 90):
        chosen = entries[-size:]
        all_rows, missing = [], []
        for entry in chosen:
            outcome = feedback.get(next_day.get(entry), {})
            if outcome.get("status") == "unavailable" or not outcome:
                missing.append(entry)
                continue
            for member in outcome["rows"]:
                if member["previous_limit_up"]:
                    all_rows.append({**member, "entry_date": entry, "outcome_date": next_day[entry],
                                     "entry_environment_highest_board": observations[entry]["highest_board"]})
        groups = {}
        for key, selector in {
            "previous_boards": lambda r: str(r["previous_boards"]) if r["previous_boards"] is not None else "unknown",
            "last_seal_time": lambda r: "unknown" if r["previous_last_seal"] is None else "by_0935" if r["previous_last_seal"] <= "093500" else "after_1430" if r["previous_last_seal"] >= "143000" else "middle_session",
            "entry_environment_highest_board": lambda r: str(r["entry_environment_highest_board"]) if r["entry_environment_highest_board"] is not None else "unknown",
        }.items():
            labels = sorted({selector(r) for r in all_rows})
            groups[key] = [{"label": label, **_stats([r for r in all_rows if selector(r) == label])} for label in labels]
        summary = _stats(all_rows)
        window_complete = len(chosen) == size and not missing
        if not window_complete:
            # Missing whole entry cohorts have unknown sizes. Do not present a
            # surviving-date mean as the requested fixed-window statistic.
            for item in [summary] + [group for values in groups.values() for group in values]:
                for field in ("mean_pct", "median_pct", "positive_ratio", "loss_ge_5_count", "loss_ge_5_ratio",
                              "loss_ge_7_count", "worst_pct", "limit_down_count", "open_premium_mean_pct"):
                    item[field] = None
                item["status"] = "partial"
        result.append({"sessions": size, "entry_dates": chosen, "missing_entry_dates": missing,
                       "status": "normal" if window_complete and all(r["return_pct"] is not None for r in all_rows) else "partial",
                       "denominator_scope": "COMPLETE_WINDOW" if window_complete else "KNOWN_ENTRY_COHORTS_ONLY",
                       "summary": summary, "groups": groups})
    return {"sample_kind": "POSTHOC_FULL_ENTRY_LIMIT_UP_COHORT", "execution_model": "NONE", "windows": result}


def structure_diagnostics(days, inputs, observations, selected_date):
    prior = [d for d in days if d < selected_date]
    windows = {"recent_10": prior[-10:], "preceding_20": prior[-30:-10]}
    means = {}
    for name, dates in windows.items():
        expected = 10 if name == "recent_10" else 20
        vals = [observations[d]["limit_up_count"] for d in dates if observations[d]["limit_up_count"] is not None]
        shares10 = [observations[d]["price_limit_bands"]["share_10"] for d in dates if observations[d]["price_limit_bands"]["share_10"] is not None]
        shares20 = [observations[d]["price_limit_bands"]["share_20"] for d in dates if observations[d]["price_limit_bands"]["share_20"] is not None]
        means[name] = {"dates": dates, "expected": expected, "samples": len(vals), "mean_limit_up_count": mean(vals) if len(vals) == expected else None,
                       "median_limit_up_count": median(vals) if len(vals) == expected else None,
                       "source_10pct_band_share_median": median(shares10) if len(shares10) == expected else None,
                       "source_20pct_band_share_median": median(shares20) if len(shares20) == expected else None,
                       "price_band_samples": {"10": len(shares10), "20": len(shares20)}}
    drift = []
    for kind in C.KINDS:
        available = [(d, inputs[d].get(kind)) for d in prior[-30:] + [selected_date]]
        valid = [(d, x) for d, x in available if x and x["source_fields"] is not None and _eligible(x)]
        if len(valid) < 2:
            drift.append({"kind": kind, "status": "insufficient_samples", "observed_dates": [d for d, _ in valid], "added": [], "not_observed": []})
            continue
        versions = []
        for observed_day, capture in valid:
            fingerprint = C.digest({"group": capture["source_group"], "fields": capture["source_fields"]})
            if versions and versions[-1]["signature"] == fingerprint:
                versions[-1]["until"] = observed_day
                versions[-1]["samples"] += 1
            else:
                versions.append({"since": observed_day, "until": observed_day, "samples": 1,
                                 "signature": fingerprint, "fields": capture["source_fields"], "source_group": capture["source_group"]})
        left_day, left = valid[-2]
        right_day, right = valid[-1]
        comparable = left["source_group"] == right["source_group"]
        added = sorted(set(right["source_fields"]) - set(left["source_fields"])) if comparable else []
        absent = sorted(set(left["source_fields"]) - set(right["source_fields"])) if comparable else []
        drift.append({"kind": kind, "status": "incomparable" if not comparable else "observed_change" if added or absent else "no_observed_change",
                      "observed_dates": [left_day, right_day], "added": added, "not_observed": absent, "versions": versions})
    comparisons = []
    for key, threshold, kind in (("median_limit_up_count", 0.35, "relative_count"),
                                 ("source_10pct_band_share_median", 0.10, "absolute_share"),
                                 ("source_20pct_band_share_median", 0.10, "absolute_share")):
        recent, prior_value = means["recent_10"][key], means["preceding_20"][key]
        delta = recent - prior_value if recent is not None and prior_value is not None else None
        relative = delta / prior_value if delta is not None and prior_value else None
        comparison_value = relative if kind == "relative_count" else delta
        comparisons.append({"metric": key, "recent": recent, "prior": prior_value, "delta": delta,
                            "relative_change": relative, "descriptive_threshold": threshold,
                            "threshold_crossed": abs(comparison_value) >= threshold if comparison_value is not None else None})
    return {"market_structure": means, "comparisons": comparisons, "field_drift": drift,
            "interpretation": "字段仅指非空完整原始响应的键集合；未出现不是删除/退役，空池没有字段变化证据。市场数量变化与源字段变化分别展示。",
            "regime_events": {"status": "unavailable", "reason_codes": ["DATED_RULE_EVENT_SOURCE_REQUIRED"]}}
