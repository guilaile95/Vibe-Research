"""Observation-only reports and deterministic analysis over the Native Intel store.

Behavior specification: docs/NATIVE_INTEL_WAVE4_CONTRACT.md. No AI calls.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from itertools import combinations
from statistics import mean
from typing import Any

import native_intel_filter as filtering
import native_intel_freshness as freshness
import native_intel_service as service
import native_intel_store as store

LOCAL = timezone(timedelta(hours=8))
BOUNDARY = "observation_only_not_an_investment_authority"


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _now(value: datetime | None) -> datetime:
    return (value or datetime.now(timezone.utc)).astimezone(LOCAL)


def _identity(row: dict[str, Any]) -> tuple[str, int]:
    return row["source_id"], row["item_id"]


def _fact(row: dict[str, Any]) -> tuple[Any, ...]:
    return row["observed_title"], row["rank"], row["published_at"]


def _fresh(rows: list[dict[str, Any]], cfg: dict[str, Any], when: datetime) -> list[dict[str, Any]]:
    return [r for r in rows if freshness.evaluate_item_freshness(
        r, global_enabled=cfg["rss_freshness_enabled"],
        global_max_age_days=cfg["rss_global_max_age_days"], now=when).eligible]


def _item(row: dict[str, Any]) -> dict[str, Any]:
    return {"item_id": row["item_id"], "title": row["observed_title"], "url": row["url"],
            "summary": row["summary"], "source_id": row["source_id"], "source_name": row["source_name"],
            "source_type": row["source_type"], "observed_at": row["observed_at"],
            "published_at": row["published_at"], "first_seen_at": row["first_seen_at"],
            "rank": row["rank"] if row["has_real_rank"] else None}


def _new_kind(row: dict[str, Any], runs: list[dict[str, Any]], membership: dict[str, set]) -> str | None:
    if not row["has_real_rank"]:
        return "NEWLY_OBSERVED" if row["obs_id"] == row["first_obs_id"] else None
    if row["obs_id"] == row["first_obs_id"]:
        return "NEW_ON_LIST"
    previous = None
    for run in runs:
        if run["source_id"] != row["source_id"]:
            continue
        if run["run_id"] == row["run_id"]:
            break
        previous = run
    if previous and previous["status"] in ("ok", "empty") and _identity(row) not in membership.get(previous["run_id"], set()):
        return "NEW_ON_LIST"
    return None


def _membership(rows: list[dict[str, Any]]) -> dict[str, set]:
    result: dict[str, set] = defaultdict(set)
    for row in rows:
        result[row["run_id"]].add(_identity(row))
    return result


def _display_order(ranks: list[int], threshold: int) -> float:
    if not ranks:
        return 0.0
    return (0.6 * mean([10 * (11 - min(r, 10)) for r in ranks])
            + 0.3 * 10 * min(len(ranks), 10)
            + 0.1 * 100 * sum(r <= threshold for r in ranks) / len(ranks))


def generate_report(path: str | None = None, *, mode: str = "CURRENT", scope: str = "all",
                    profile_id: str = "default", report_profile: str = "manual", group_by: str = "keyword",
                    rank_threshold: int = 5, max_news_per_keyword: int = 0,
                    sort_by_position_first: bool = False, commit: bool = True,
                    now: datetime | None = None) -> dict[str, Any]:
    if mode not in ("CURRENT", "DAILY", "INCREMENTAL") or scope not in ("all", "my_interests"):
        raise ValueError("报告 mode/scope 非法")
    if group_by not in ("keyword", "platform", "source"):
        raise ValueError("报告 group_by 非法")
    if not 1 <= rank_threshold <= 1000 or not 0 <= max_news_per_keyword <= 500:
        raise ValueError("报告显示限制非法")
    when = _now(now)
    day = when.replace(hour=0, minute=0, second=0, microsecond=0)
    start = day - timedelta(days=30)
    target = path or service.db_path()
    profile = service.get_filter_profile(profile_id, target)
    cfg = store.get_native_intel_config(target)
    # Different scopes / filter and freshness policies cannot consume each other's baseline.
    signature = [report_profile, profile_id, mode, scope, profile["profile_fingerprint"],
                 cfg["rss_freshness_enabled"], cfg["rss_global_max_age_days"],
                 [(s["source_id"], s["enabled"], s["deleted_at"], s["re_enabled_at"], s["max_age_days"])
                  for s in sorted(store.list_sources(target, enabled_only=False, include_deleted=True),
                                  key=lambda s: s["source_id"])]]
    key = hashlib.sha256(json.dumps(signature, sort_keys=True).encode()).hexdigest()
    previous = store.read_report_cursor(key, target)
    baseline = previous["observation_boundary"] if previous else 0
    if mode == "INCREMENTAL" and previous and _time(previous["generated_at"]) < start:
        raise ValueError("BASELINE_OUTSIDE_HISTORY_WINDOW: 增量基线超过 30 天，请使用新报告配置")
    snapshot = store.read_report_history(_iso(start), _iso(when + timedelta(seconds=1)), target, baseline=baseline)
    observations = snapshot["observations"]
    membership = _membership(observations)
    latest_run = {r["source_id"]: r for r in snapshot["runs"]}
    grouped: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in observations:
        grouped[_identity(row)].append(row)
    selected = []
    for pair, history in grouped.items():
        row = history[-1]
        if not row["enabled"] or row["deleted_at"] or (row["re_enabled_at"] and row["observed_at"] < row["re_enabled_at"]):
            continue
        run = latest_run.get(row["source_id"])
        if mode == "DAILY":
            relevant = [r for r in history if r["observed_at"] >= _iso(day)]
        elif mode == "CURRENT" or (mode == "INCREMENTAL" and previous is None):
            relevant = [r for r in history if run and run["status"] in ("ok", "empty") and r["run_id"] == run["run_id"]]
        else:
            earlier = [r for r in history if r["obs_id"] <= baseline]
            changes = [r for r in history if r["obs_id"] > baseline]
            relevant = changes if changes and (not earlier or _fact(changes[-1]) != _fact(earlier[-1])
                                               or _new_kind(changes[-1], snapshot["runs"], membership)) else []
        if not relevant:
            continue
        row = relevant[-1]
        if not _fresh([row], cfg, when):
            continue
        result = _item(row)
        ranks = [r["rank"] for r in history if r["rank"] is not None and r["observed_at"] >= _iso(day)]
        result["highlight"] = result["rank"] is not None and result["rank"] <= rank_threshold
        result["display_order_score"] = round(_display_order(ranks, rank_threshold), 3)
        result["best_rank"] = min(ranks) if ranks else None
        result["observation_count"] = sum(r["observed_at"] >= _iso(day) for r in history)
        result["current_state"] = "STALE" if not run or (_time(run["started_at"]) < when - timedelta(hours=6)) else "OBSERVED"
        new_rows = [r for r in relevant if r["obs_id"] > baseline and _new_kind(r, snapshot["runs"], membership)]
        result["new_kind"] = _new_kind(new_rows[-1], snapshot["runs"], membership) if new_rows else None
        result["change_kind"] = result["new_kind"] or ("CHANGED" if mode == "INCREMENTAL" else None)
        matched, names = filtering.evaluate_keyword_rules(result["title"], result["summary"], profile["keyword_rules"])
        result["keyword_groups"] = names
        result["keyword_match"] = matched
        selected.append(result)
    # Keep different source modalities ordered honestly; RSS never gets a display rank.
    def ordering(r: dict[str, Any]) -> tuple:
        if r["source_type"] != "hotlist":
            published = freshness._parse_iso_or_ts(r["published_at"], None)
            return (1, -(published.timestamp() if published else 0), r["source_id"], r["item_id"])
        return (0, -r["display_order_score"], r["best_rank"] or 10000,
                -r["observation_count"], r["source_id"], r["item_id"])
    selected.sort(key=ordering)
    filter_meta: dict[str, Any] = {"method": profile["method"], "mode": scope}
    incomplete_filter = False
    if scope == "my_interests":
        if profile["method"] == "keyword":
            selected = [r for r in selected if r["keyword_match"]]
        else:
            selected, filter_meta = service.filter_items(selected, profile_id, target)
            incomplete_filter = bool(filter_meta["error_count"] or filter_meta["unclassified_count"])
    groups = profile["keyword_rules"].get("groups", [])
    positions = {g["name"]: i for i, g in enumerate(groups)}
    caps = {g["name"]: g.get("max_count") or max_news_per_keyword for g in groups}
    sections: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in selected:
        names = item["keyword_groups"]
        label = names[0] if names else "其他资讯"
        sections[label].append(item)
    output = []
    for name, items in sections.items():
        cap = caps.get(name, max_news_per_keyword)
        output.append({"name": name, "count": len(items), "items": items[:cap] if cap else items})
    if group_by != "keyword":
        by_source: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for group in output:
            for item in group["items"]:
                name = item["source_name"] + " · " + item["source_id"] if group_by == "source" else (
                    item["source_name"] if item["source_type"] == "hotlist" else "RSS · " + item["source_name"])
                by_source[name].append(item)
        output = [{"name": name, "count": len(items), "items": sorted(items, key=ordering)} for name, items in by_source.items()]
    output.sort(key=lambda g: (positions.get(g["name"], 10000), -g["count"]) if sort_by_position_first and group_by == "keyword"
                else (-g["count"], positions.get(g["name"], 10000)))
    plane = service.data_status(target)
    result = {"status": "partial" if incomplete_filter else plane["status"], "mode": mode, "scope": scope,
              "profile_id": profile_id, "group_by": group_by, "generated_at": _iso(when),
              "data_basis": "CURRENT_ELIGIBLE", "window": {"start": _iso(day if mode == "DAILY" else start), "end": _iso(when)},
              "baseline": previous, "observation_boundary": snapshot["boundary"],
              "sections": output, "total": len(selected), "unique_item_count": len({r["item_id"] for r in selected}),
              "new_items": [r for section in output for r in section["items"] if r["new_kind"]], "filter_meta": filter_meta,
              "cursor_advanced": False, "usage_boundary": BOUNDARY}
    # Serialization is part of generation: invalid output must not consume a cursor.
    json.dumps(result, allow_nan=False)
    if commit and not incomplete_filter and plane["status"] != "unavailable":
        store.advance_report_cursor(key, profile_id, mode, _iso(when), snapshot["boundary"], previous, target)
        result["cursor_advanced"] = True
    return result


def _change(current: int, previous: int) -> float | None:
    return round((current - previous) * 100 / previous, 2) if previous else None


def summarize_counts(counts: list[int], *, complete: bool = True) -> dict[str, Any]:
    """Explain the audited rules; no AI inference or probability calibration."""
    recent, early = sum(counts[-3:]), sum(counts[:3])
    maximum = max(counts, default=0)
    active = [n for n in counts if n]
    stage = "NOT_EVALUATED"
    if active:
        stage = "上升期" if recent > early else "衰退期" if recent < early / 2 else "爆发期" if maximum in counts[-3:] else "稳定期"
    topic_type = ("昙花一现" if len(active) <= 2 and maximum > 2 * mean(active) else
                  "持续热点" if len(active) >= len(counts) * 0.6 else "周期性热点") if active else "NOT_EVALUATED"
    today, yesterday = (counts[-1] if counts else 0), (counts[-2] if len(counts) > 1 else 0)
    ratio = round(today / yesterday, 4) if yesterday else None
    burst = today >= 5 if not yesterday else today >= yesterday * 3
    sequence = [n for n in counts[-4:] if n > 0]
    growth = _change(sequence[-1], sequence[-2]) if len(sequence) >= 2 else None
    strength = (0.9 if all(a <= b for a, b in zip(sequence, sequence[1:])) else 0.7) if len(sequence) >= 3 else 0.6
    predicted = growth is not None and growth > 30 and strength >= 0.7
    return {
        "lifecycle": {"status": stage if complete else "UNKNOWN", "topic_type": topic_type,
                      "reason": f"前3日合计 {early}，后3日合计 {recent}，峰值 {maximum}；按上升→衰退→爆发→稳定规则判定",
                      "input_counts": counts},
        "viral": {"detected": burst if complete else None, "current_count": today,
                  "baseline_count": yesterday, "growth": ratio,
                  "reason": "今日/昨日 ≥ 3；昨日为零时今日至少 5 次" if complete else "采集覆盖不足，不能把缺数当零",
                  "alert_level": ("高" if ratio is None or ratio > 6 else "中") if burst and complete else None},
        "prediction": {"direction": "上升" if predicted and complete else "未触发" if complete else "UNKNOWN",
                       "strength": strength if growth is not None and complete else None,
                       "growth_percent": growth, "reference_nonzero_sequence": sequence,
                       "reason": "最近4日已出现记录中，末次增长严格 >30%；至少3个记录且强度 ≥0.7 才触发。强度是规则档位，不是概率。",
                       "input_counts": counts[-4:], "label": "趋势推断（规则）"},
    }


def analyze_topic(path: str | None = None, *, topic: str, profile_id: str = "default", days: int = 7,
                  data_basis: str = "RAW_HISTORY", now: datetime | None = None) -> dict[str, Any]:
    topic = topic.strip()
    if not topic or len(topic) > 120 or not 2 <= days <= 30 or data_basis not in ("RAW_HISTORY", "CURRENT_ELIGIBLE"):
        raise ValueError("topic、days 或 data_basis 非法")
    target = path or service.db_path()
    when = _now(now)
    day = when.replace(hour=0, minute=0, second=0, microsecond=0)
    start = day - timedelta(days=days - 1)
    before = start - timedelta(days=days)
    snapshot = store.read_report_history(_iso(before), _iso(when + timedelta(seconds=1)), target)
    rows = snapshot["observations"]
    if data_basis == "CURRENT_ELIGIBLE":
        rows = _fresh([r for r in rows if r["enabled"] and not r["deleted_at"]], store.get_native_intel_config(target), when)
    profile = service.get_filter_profile(profile_id, target)
    rules = profile["keyword_rules"]
    group_names = [g["name"] for g in rules.get("groups", [])]
    for row in rows:
        _, row["groups"] = filtering.evaluate_keyword_rules(row["observed_title"], row["summary"], rules)
        row["topic_hit"] = topic in row["groups"] if topic in group_names else topic.lower() in row["observed_title"].lower()
        row["day"] = _time(row["observed_at"]).astimezone(LOCAL).date().isoformat()
    current = [r for r in rows if r["observed_at"] >= _iso(start)]
    matched = [r for r in current if r["topic_hit"]]
    buckets = []
    for offset in range(days):
        date = (start + timedelta(days=offset)).date().isoformat()
        observed = [r for r in matched if r["day"] == date]
        source_runs = [r for r in snapshot["runs"] if _time(r["started_at"]).astimezone(LOCAL).date().isoformat() == date]
        successes = {r["source_id"] for r in source_runs if r["status"] in ("ok", "empty")}
        failures = {r["source_id"] for r in source_runs if r["status"] == "failed"}
        buckets.append({"date": date, "mention_count": len({(r["source_id"], r["observed_title"]) for r in observed}),
                        "unique_item_count": len({r["item_id"] for r in observed}),
                        "source_count": len({r["source_id"] for r in observed}),
                        "platform_count": len({r["source_id"] for r in observed if r["has_real_rank"]}),
                        "coverage": "PARTIAL" if failures else "OBSERVED" if successes else "UNKNOWN",
                        "successful_sources": len(successes), "failed_sources": len(failures)})
    for index, bucket in enumerate(buckets):
        bucket["change"] = _change(bucket["mention_count"], buckets[index - 1]["mention_count"]) if index else None
    counts = [b["mention_count"] for b in buckets]
    heuristics = summarize_counts(counts, complete=all(b["coverage"] == "OBSERVED" for b in buckets))
    trajectories: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in matched:
        if row["has_real_rank"] and row["rank"] is not None:
            trajectories[_identity(row)].append({"observed_at": row["observed_at"], "rank": row["rank"], "run_id": row["run_id"]})
    latest = {_identity(r): r for r in current}
    rank_timeline = [{"source_id": pair[0], "source_name": latest[pair]["source_name"],
                      "item_id": pair[1], "title": latest[pair]["observed_title"], "points": points}
                     for pair, points in trajectories.items()]
    platforms = []
    comparison_sources = [(s, {s["source_id"]}) for s in snapshot["sources"]]
    rss_groups: dict[str, set[str]] = defaultdict(set)
    for source in snapshot["sources"]:
        if source["source_type"] == "rss":
            rss_groups[source["hint"]].add(source["source_id"])
    for hint, source_ids in rss_groups.items():
        comparison_sources.append(({"source_id": "rss-group:" + hint, "name": "RSS 分组 · " + hint,
                                    "source_type": "rss", "has_real_rank": False, "hint": hint}, source_ids))
    for source, source_ids in comparison_sources:
        current_source = [r for r in current if r["source_id"] in source_ids]
        past_source = [r for r in rows if r["observed_at"] < _iso(start) and r["source_id"] in source_ids]
        if not current_source and not past_source:
            continue
        daily_count = len({(r["day"], r["source_id"], r["observed_title"]) for r in current_source})
        past_count = len({(r["day"], r["source_id"], r["observed_title"]) for r in past_source})
        active_days = len({r["day"] for r in current_source})
        real_ranks = [r["rank"] for r in current_source if r["has_real_rank"] and r["rank"] is not None]
        platforms.append({"source_id": source["source_id"], "name": source["name"], "source_type": source["source_type"],
                          "group": source["source_id"] if source["has_real_rank"] else "RSS:" + source["hint"],
                          "source_ids": sorted(source_ids), "coverage_ratio": round(active_days / days, 3),
                          "item_count": daily_count, "unique_item_count": len({r["item_id"] for r in current_source}),
                          "topic_hit_count": len({(r["day"], r["source_id"], r["observed_title"]) for r in current_source if r["topic_hit"]}),
                          "new_item_count": len({_identity(r) for r in current_source if r["obs_id"] == r["first_obs_id"]}),
                          "ranked_visibility": len(real_ranks), "mean_observed_rank": round(mean(real_ranks), 2) if real_ranks else None,
                          "activity_change": _change(daily_count, past_count), "previous_item_count": past_count,
                          "news_per_active_day": round(daily_count / active_days, 2) if active_days else 0,
                          "updates": len({(r["source_id"], r["run_id"]) for r in snapshot["runs"] if r["source_id"] in source_ids
                                          and r["started_at"] >= _iso(start) and r["status"] in ("ok", "empty")})})
    platforms.sort(key=lambda r: -r["news_per_active_day"])
    unique = {r["item_id"]: r for r in current}
    pairs: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in unique.values():
        for pair in combinations(sorted(set(row["groups"])), 2):
            pairs[pair].append(_item(row))
    cooccurrence = [{"pair": list(pair), "count": len(items), "sample_items": items[:3]}
                    for pair, items in sorted(pairs.items(), key=lambda x: -len(x[1]))]
    first = next((c for c in counts if c), 0)
    change = _change(counts[-1], first) if first else 0
    return {"status": service.data_status(target)["status"], "topic": topic, "topics": group_names,
            "data_basis": data_basis, "window": {"start": _iso(start), "end": _iso(when)},
            "trend": buckets, "change_percent": change,
            "trend_direction": "上升" if change and change > 10 else "下降" if change and change < -10 else "稳定",
            "rank_timeline": rank_timeline, "cross_source_visibility": len({r["source_id"] for r in matched}),
            **heuristics, "platforms": platforms, "cooccurrence": cooccurrence,
            "platform_note": "热榜是平台排名观察；RSS 是订阅文章流，分组按来源累加。活跃度为日去重条目数，与前一个等天数窗口比较；今天尚未完成，不代表全网热度；RSS 无排名。",
            "usage_boundary": BOUNDARY}


def similar_items(item_id: int, path: str | None = None, *, threshold: float = 0.6,
                  now: datetime | None = None) -> dict[str, Any]:
    if item_id < 1 or not 0 <= threshold <= 1:
        raise ValueError("item_id/threshold 非法")
    when = _now(now)
    start = when.replace(hour=0, minute=0, second=0, microsecond=0)
    target = path or service.db_path()
    snapshot = store.read_report_history(_iso(start), _iso(when + timedelta(seconds=1)), target)
    latest = {r["item_id"]: r for r in snapshot["observations"]}
    reference = latest.get(item_id)
    if reference is None:
        raise ValueError("今日窗口内未找到参考条目")
    found = []
    for row in latest.values():
        if row["observed_title"] == reference["observed_title"]:
            continue
        score = SequenceMatcher(None, reference["observed_title"], row["observed_title"]).ratio()
        if score >= threshold:
            found.append({"item": _item(row), "similarity_score": round(score, 3)})
    found.sort(key=lambda r: -r["similarity_score"])
    return {"item": _item(reference), "similar_items": found[:50], "threshold": threshold,
            "algorithm": "SequenceMatcher title ratio", "data_basis": "RAW_HISTORY", "usage_boundary": BOUNDARY}
