"""Observation-only reports and deterministic analysis over the Native Intel store.

Behavior specification: docs/NATIVE_INTEL_WAVE4_CONTRACT.md. No AI calls.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict, deque
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
RANK_TIMELINE_POINT_LIMIT = 10000


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


def _eligible(row: dict[str, Any], cfg: dict[str, Any], when: datetime) -> bool:
    return bool(row["enabled"] and not row["deleted_at"]
                and (not row["re_enabled_at"] or row["observed_at"] >= row["re_enabled_at"])
                and freshness.evaluate_item_freshness(
                    row, global_enabled=cfg["rss_freshness_enabled"],
                    global_max_age_days=cfg["rss_global_max_age_days"], now=when).eligible)


def _item(row: dict[str, Any]) -> dict[str, Any]:
    return {"item_id": row["item_id"], "title": row["observed_title"], "url": row["url"],
            "summary": row["summary"], "source_id": row["source_id"], "source_name": row["source_name"],
            "source_type": row["source_type"], "observed_at": row["observed_at"],
            "published_at": row["published_at"], "first_seen_at": row["first_seen_at"],
            "rank": row["rank"] if row["has_real_rank"] else None}


def _new_kind(row: dict[str, Any]) -> str | None:
    if not row["has_real_rank"]:
        return "NEWLY_OBSERVED" if row["obs_id"] == row["first_obs_id"] else None
    if row["obs_id"] == row["first_obs_id"] or row["returned_to_list"]:
        return "NEW_ON_LIST"
    return None


def _display_order(stats: dict[str, Any]) -> float:
    count = stats.get("rank_count", 0)
    if not count:
        return 0.0
    return (0.6 * stats["rank_strength"] / count + 0.3 * 10 * min(count, 10)
            + 0.1 * 100 * stats["highlighted"] / count)


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
    read_mode = "CURRENT" if mode == "INCREMENTAL" and previous is None else mode
    latest, earlier, new_kinds = {}, {}, {}
    with store.read_report_history(_iso(day), _iso(when + timedelta(seconds=1)), target,
                                   mode=read_mode, baseline=baseline, day_start=_iso(day),
                                   rank_threshold=rank_threshold) as snapshot:
        for row in snapshot["observations"]:
            pair = _identity(row)
            if read_mode == "INCREMENTAL" and row["obs_id"] <= baseline:
                earlier[pair] = row
                continue
            latest[pair] = row
            kind = _new_kind(row)
            if row["obs_id"] > baseline and kind and _eligible(row, cfg, when):
                new_kinds[pair] = kind
    selected = []
    for pair, row in latest.items():
        if not _eligible(row, cfg, when):
            continue
        if read_mode == "INCREMENTAL" and pair in earlier and _fact(row) == _fact(earlier[pair]) and not _new_kind(row):
            continue
        result = _item(row)
        stats = snapshot["day_stats"].get(pair, {})
        run = snapshot["latest_runs"].get(row["source_id"])
        result["highlight"] = result["rank"] is not None and result["rank"] <= rank_threshold
        result["display_order_score"] = round(_display_order(stats), 3)
        result["best_rank"] = stats.get("best_rank")
        result["observation_count"] = stats.get("observation_count", 0)
        result["latest_source_status"] = run["status"].upper() if run else "UNKNOWN"
        result["current_state"] = store.get_item_rank_state(
            row["item_id"], target, include_history=False, now=when).get("current_state", "UNKNOWN") if row["has_real_rank"] else store.ITEM_STATE_NO_RANK_SEMANTICS
        result["new_kind"] = new_kinds.get(pair)
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
              "data_basis": "CURRENT_ELIGIBLE", "window": {
                  "start": _iso(day) if mode == "DAILY" else previous["generated_at"] if read_mode == "INCREMENTAL"
                  else min((r["observed_at"] for r in selected), default=_iso(when)), "end": _iso(when)},
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
    cfg = store.get_native_intel_config(target)
    profile = service.get_filter_profile(profile_id, target)
    rules = profile["keyword_rules"]
    group_names = [g["name"] for g in rules.get("groups", [])]
    # Retain distinct aggregation keys, not repeated raw observations/source runs.
    daily = defaultdict(lambda: {k: set() for k in ("mentions", "items", "sources", "platforms", "ok", "failed")})
    latest = {}
    points = deque(maxlen=RANK_TIMELINE_POINT_LIMIT)
    point_count = 0
    start_iso = _iso(start)
    with store.read_report_history(_iso(before), _iso(when + timedelta(seconds=1)), target) as snapshot:
        stats = {s["source_id"]: {"current": set(), "past": set(), "hits": set(), "items": set(),
                 "new": set(), "days": set(), "rank_count": 0, "rank_sum": 0, "updates": 0}
                 for s in snapshot["sources"]}
        for row in snapshot["observations"]:
            if data_basis == "CURRENT_ELIGIBLE" and not _eligible(row, cfg, when):
                continue
            date = _time(row["observed_at"]).astimezone(LOCAL).date().isoformat()
            stat = stats[row["source_id"]]
            title_key = (date, row["observed_title"])
            if row["observed_at"] < start_iso:
                stat["past"].add(title_key)
                continue
            _, row["groups"] = filtering.evaluate_keyword_rules(row["observed_title"], row["summary"], rules)
            hit = topic in row["groups"] if topic in group_names else topic.lower() in row["observed_title"].lower()
            stat["current"].add(title_key)
            stat["items"].add(row["item_id"])
            stat["days"].add(date)
            if row["obs_id"] == row["first_obs_id"]:
                stat["new"].add(row["item_id"])
            ranked = row["has_real_rank"] and row["rank"] is not None
            if ranked:
                stat["rank_count"] += 1
                stat["rank_sum"] += row["rank"]
            pair = _identity(row)
            latest[pair] = row
            if hit:
                stat["hits"].add(title_key)
                bucket = daily[date]
                bucket["mentions"].add((row["source_id"], row["observed_title"]))
                bucket["items"].add(row["item_id"])
                bucket["sources"].add(row["source_id"])
                if row["has_real_rank"]:
                    bucket["platforms"].add(row["source_id"])
                if ranked:
                    point_count += 1
                    points.append((pair, {"observed_at": row["observed_at"], "rank": row["rank"], "run_id": row["run_id"]}))
        for run in snapshot["runs"]:
            if run["started_at"] < start_iso:
                continue
            date = _time(run["started_at"]).astimezone(LOCAL).date().isoformat()
            if run["status"] in ("ok", "empty"):
                daily[date]["ok"].add(run["source_id"])
                stats[run["source_id"]]["updates"] += 1
            elif run["status"] == "failed":
                daily[date]["failed"].add(run["source_id"])
    buckets = []
    for offset in range(days):
        date = (start + timedelta(days=offset)).date().isoformat()
        observed = daily[date]
        buckets.append({"date": date, "mention_count": len(observed["mentions"]),
                        "unique_item_count": len(observed["items"]), "source_count": len(observed["sources"]),
                        "platform_count": len(observed["platforms"]),
                        "coverage": "PARTIAL" if observed["failed"] else "OBSERVED" if observed["ok"] else "UNKNOWN",
                        "successful_sources": len(observed["ok"]), "failed_sources": len(observed["failed"])})
    for index, bucket in enumerate(buckets):
        bucket["change"] = _change(bucket["mention_count"], buckets[index - 1]["mention_count"]) if index else None
    counts = [b["mention_count"] for b in buckets]
    heuristics = summarize_counts(counts, complete=all(b["coverage"] == "OBSERVED" for b in buckets))
    trajectories: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for pair, point in points:
        trajectories[pair].append(point)
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
        parts = [stats[sid] for sid in source_ids]
        daily_count = sum(len(p["current"]) for p in parts)
        past_count = sum(len(p["past"]) for p in parts)
        if not daily_count and not past_count:
            continue
        active_days = len(set().union(*(p["days"] for p in parts)))
        rank_count = sum(p["rank_count"] for p in parts)
        platforms.append({"source_id": source["source_id"], "name": source["name"], "source_type": source["source_type"],
                          "group": source["source_id"] if source["has_real_rank"] else "RSS:" + source["hint"],
                          "source_ids": sorted(source_ids), "coverage_ratio": round(active_days / days, 3),
                          "item_count": daily_count, "unique_item_count": len(set().union(*(p["items"] for p in parts))),
                          "topic_hit_count": sum(len(p["hits"]) for p in parts),
                          "new_item_count": sum(len(p["new"]) for p in parts),
                          "ranked_visibility": rank_count,
                          "mean_observed_rank": round(sum(p["rank_sum"] for p in parts) / rank_count, 2) if rank_count else None,
                          "activity_change": _change(daily_count, past_count), "previous_item_count": past_count,
                          "news_per_active_day": round(daily_count / active_days, 2) if active_days else 0,
                          "updates": sum(p["updates"] for p in parts)})
    platforms.sort(key=lambda r: -r["news_per_active_day"])
    unique = {r["item_id"]: r for r in sorted(latest.values(), key=lambda r: r["obs_id"])}
    pairs = {}
    for row in unique.values():
        for pair in combinations(sorted(set(row["groups"])), 2):
            aggregate = pairs.setdefault(pair, {"pair": list(pair), "count": 0, "sample_items": []})
            aggregate["count"] += 1
            if len(aggregate["sample_items"]) < 3:
                aggregate["sample_items"].append(_item(row))
    cooccurrence = sorted(pairs.values(), key=lambda p: -p["count"])
    first = next((c for c in counts if c), 0)
    change = _change(counts[-1], first) if first else 0
    return {"status": service.data_status(target)["status"], "topic": topic, "topics": group_names,
            "data_basis": data_basis, "window": {"start": _iso(start), "end": _iso(when)},
            "trend": buckets, "change_percent": change,
            "trend_direction": "上升" if change and change > 10 else "下降" if change and change < -10 else "稳定",
            "rank_timeline": rank_timeline,
            "rank_timeline_sample": {"total_points": point_count, "returned_points": len(points),
                                     "limit": RANK_TIMELINE_POINT_LIMIT, "truncated": point_count > len(points),
                                     "selection": "latest_observation_ids"},
            "cross_source_visibility": len(set().union(*(b["sources"] for b in daily.values()))),
            **heuristics, "platforms": platforms, "cooccurrence": cooccurrence,
            "platform_note": "逐个热榜来源、逐个 RSS 来源及 RSS 分组汇总分别展示；汇总行不可与单源行再次求和。活跃度为来源/日去重条目数，与前一个等天数窗口比较；今天尚未完成，不代表全网热度；RSS 无排名。",
            "usage_boundary": BOUNDARY}


def similar_items(item_id: int, path: str | None = None, *, threshold: float = 0.6,
                  now: datetime | None = None) -> dict[str, Any]:
    if item_id < 1 or not 0 <= threshold <= 1:
        raise ValueError("item_id/threshold 非法")
    when = _now(now)
    start = when.replace(hour=0, minute=0, second=0, microsecond=0)
    target = path or service.db_path()
    with store.read_report_history(_iso(start), _iso(when + timedelta(seconds=1)), target) as snapshot:
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
