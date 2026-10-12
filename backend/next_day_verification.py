"""User-authored, research-only market conditions; no advice or formal writes.

Only replace_plan mutates the isolated journal. Reads never create either DB.
Prior readings and historical frequency are frozen at explicit save time. Later
reconciliation uses the currently recorded final observation, not a PIT claim.
"""
from __future__ import annotations

import json
import math
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

import short_term_fact_store as facts_store
import trade_calendar
import verification_research_observation as research_observation

SCHEMA_VERSION = "next-day-verification.v0.2"
LEGACY_METRICS = {"limit_up_count", "failed_board_rate"}
SHANGHAI = timezone(timedelta(hours=8))
MIN_SAMPLES = 12
BASELINE_SESSIONS = 60
METRICS = {
    "limit_up_count": {"label": "涨停家数", "unit": "家", "epsilon": 5},
    "failed_board_rate": {"label": "炸板率", "unit": "0–1 比率", "epsilon": 0.05},
    "highest_board": {"label": "最高连板高度（源口径）", "unit": "板", "epsilon": 0.5},
    "promotion_1to2": {"label": "1进2晋级率（研究观察）", "unit": "0–1 比率", "epsilon": 0.05},
    "money_effect_median": {"label": "昨日涨停队列收益中位数", "unit": "百分点", "epsilon": 0.5},
    "deep_loss_count": {"label": "昨日涨停队列跌幅≥5%家数", "unit": "家", "epsilon": 5},
    "theme_concentration": {"label": "头部题材集中度（供应商标签）", "unit": "0–1 比率", "epsilon": 0.05},
    "market_limit_down": {"label": "全市场跌停家数", "unit": "家", "epsilon": 5},
}
LIMITATIONS = [
    "仅记录您事前写下的市场读数条件，不提供个股建议，不自动交易。",
    "只读取本地已存的合格收盘事实；未启用自动采集，缺少事实时保留待核验，不算失败。",
    "基准为保存时已知的历史发生频率，不代表投资胜率或未来概率。",
    "对账使用当前已存的收盘观察，源数据更正可能改变结果；事前值和基准已冻结。",
    "新增六项仅冻结保存时读取的当前归档研究观察，不宣称历史收盘时已知；历史基准保持未知。",
]


class Condition(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    metric: Literal["limit_up_count", "failed_board_rate", "highest_board", "promotion_1to2", "money_effect_median", "deep_loss_count", "theme_concentration", "market_limit_down"]
    direction: Literal["up", "down", "flat"]
    reason: str = Field(default="", max_length=200)


class SavePlan(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    revision: int = Field(ge=0)
    items: list[Condition] = Field(max_length=8)


class VerificationError(ValueError):
    pass


class JournalError(RuntimeError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _stamp(now: datetime) -> str:
    return now.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _instant(value: object) -> datetime | None:
    if not isinstance(value, str) or not trade_calendar._UTC_ZERO_OFFSET_RE.fullmatch(value):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def journal_path() -> Path:
    return Path(os.environ.get("VR_DATA_DIR") or Path.home() / ".vibe-research") / "next_day_verification.sqlite3"


def _boundary(day: str, now: datetime) -> dict:
    next_day = trade_calendar.next_trade_date(day)
    if next_day is None or trade_calendar.completed_trade_date_at(_stamp(now)) is None:
        return {"state": "CALENDAR_UNKNOWN", "next_trade_date": None, "seals_at": None}
    seal = datetime.fromisoformat(f"{next_day}T09:15:00+08:00")
    close = datetime.fromisoformat(f"{day}T15:00:00+08:00")
    state = "SEALED" if now >= seal else "OPEN" if now >= close else "NOT_YET_OPEN"
    return {"state": state, "next_trade_date": next_day, "seals_at": _stamp(seal)}


def _validate_plan(day: str, revision: int, payload: object) -> dict:
    if (not isinstance(day, str) or trade_calendar._parse_strict_date(day) is None
            or type(revision) is not int or revision < 1
            or not isinstance(payload, list) or len(payload) > len(METRICS)):
        raise ValueError("invalid journal")
    for item in payload:
        if not isinstance(item, dict) or set(item) != {"metric", "direction", "reason", "written_at", "prior_value", "prior_evidence", "baseline"}:
            raise ValueError("invalid journal")
        # Validate the whole frozen JSON tree, not only displayed operands.
        json.dumps(item, allow_nan=False)
        Condition.model_validate({k: item[k] for k in ("metric", "direction", "reason")})
        baseline = item["baseline"]
        written = _instant(item["written_at"])
        if (not isinstance(baseline, dict) or set(baseline) != {"rate", "samples", "possible_pairs", "coverage", "from", "through", "as_of", "minimum_samples"}
                or any(type(baseline[k]) is not int or baseline[k] < 0 for k in ("samples", "possible_pairs", "minimum_samples"))
                or baseline["samples"] > baseline["possible_pairs"] or baseline["possible_pairs"] > BASELINE_SESSIONS
                or baseline["minimum_samples"] != MIN_SAMPLES
                or any(baseline[k] is not None and (isinstance(baseline[k], bool) or not isinstance(baseline[k], (int, float)) or not 0 <= baseline[k] <= 1 or not math.isfinite(baseline[k])) for k in ("rate", "coverage"))
                or _instant(baseline["as_of"]) != written
                or written is None or written < datetime.fromisoformat(f"{day}T15:00:00+08:00")
                or baseline["through"] != day or not isinstance(baseline["from"], str)
                or trade_calendar._parse_strict_date(baseline["from"]) is None or baseline["from"] > day
                or (baseline["rate"] is None) != (baseline["samples"] < MIN_SAMPLES)
                or baseline["coverage"] != (baseline["samples"] / baseline["possible_pairs"] if baseline["possible_pairs"] else None)
                or (item["prior_value"] is not None and _value({"values": {item["metric"]: item["prior_value"]}}, item["metric"]) is None)
                or (item["prior_evidence"] is not None and not isinstance(item["prior_evidence"], dict))):
            raise ValueError("invalid journal")
        if item["metric"] not in LEGACY_METRICS and (baseline["samples"] != 0 or baseline["possible_pairs"] != 0):
            raise ValueError("research baseline cannot claim historical PIT")
        evidence = item["prior_evidence"]
        if evidence is None:
            if item["prior_value"] is not None:
                raise ValueError("invalid journal")
        elif item["metric"] not in LEGACY_METRICS:
            if not research_observation.validate(evidence, day, item["written_at"], _value) or _value(evidence, item["metric"]) != item["prior_value"]:
                raise ValueError("invalid observation-at-save evidence")
            if baseline["samples"] != 0 or baseline["possible_pairs"] != 0:
                raise ValueError("research baseline cannot claim historical PIT")
        else:
            if (set(evidence) != {"values", "source_ids", "fetched_at", "snapshot_at", "stored_at"}
                    or not isinstance(evidence["values"], dict) or set(evidence["values"]) != LEGACY_METRICS
                    or not isinstance(evidence["source_ids"], list) or not evidence["source_ids"]
                    or any(not isinstance(v, str) or not v.strip() for v in evidence["source_ids"])
                    or any(v is not None and _value(evidence, k) is None for k, v in evidence["values"].items())
                    or _value(evidence, item["metric"]) != item["prior_value"]):
                raise ValueError("invalid journal")
            fetched, snapshot, stored = [_instant(evidence[k]) for k in ("fetched_at", "snapshot_at", "stored_at")]
            if (None in (fetched, snapshot, stored)
                    or not datetime.fromisoformat(f"{day}T15:00:00+08:00") <= fetched <= snapshot <= stored <= written):
                raise ValueError("invalid journal")
    if len({i["metric"] for i in payload}) != len(payload):
        raise ValueError("invalid journal")
    return {"revision": revision, "items": payload}


def _read_plans(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    try:
        with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as conn:
            rows = conn.execute("SELECT trade_date, revision, payload FROM plans").fetchall()
        return {day: _validate_plan(day, revision, json.loads(raw)) for day, revision, raw in rows}
    except (sqlite3.Error, ValueError, KeyError, TypeError) as exc:
        raise JournalError("验证记录不可读取，已停止操作") from exc


def _fact(day: str, as_of: datetime) -> dict | None:
    # Store's legacy read API initializes a missing database. Do not call it in
    # that case: GET and a condition save must not activate fact ingestion.
    if not facts_store.resolve_db_path().is_file():
        return None
    try:
        record = facts_store.load_final_fact_record(day)
    except facts_store.FactStoreError:
        return None
    return _fact_record(record, day, as_of)


def _fact_record(record: dict | None, day: str, as_of: datetime) -> dict | None:
    """Qualify one already-read record without I/O; shared by archive inspection."""
    if record is None:
        return None
    stored = _instant(record["stored_at"])
    if stored is None or stored > as_of:
        return None
    env = record["envelope"]
    if not isinstance(env, dict):
        return None
    section = env.get("sections", {}).get("facts") if isinstance(env.get("sections"), dict) else None
    if not isinstance(section, dict):
        return None
    for layer in (env, section):
        if (layer.get("trade_date") != day or layer.get("session") != "final"
                or layer.get("is_final") is not True or layer.get("status") != "normal"
                or not isinstance(layer.get("source_ids"), list) or not layer["source_ids"]
                or any(not isinstance(v, str) or not v.strip() for v in layer["source_ids"])):
            return None
        fetched, snapshot = _instant(layer.get("fetched_at")), _instant(layer.get("snapshot_at"))
        if (fetched is None or snapshot is None or fetched > snapshot or snapshot > as_of or snapshot > stored
                or fetched < datetime.fromisoformat(f"{day}T15:00:00+08:00")):
            return None
    if (env.get("schema_version") not in ("short-term-daily-facts-v0.1", "short-term-daily-facts-v0.2")
            or section.get("schema_version") != "short-term-market-facts-v0.1"):
        return None
    values = section.get("facts")
    if not isinstance(values, dict):
        return None
    return {"values": {metric: _value({"values": values}, metric) for metric in LEGACY_METRICS}, "source_ids": section["source_ids"],
            "fetched_at": section["fetched_at"], "snapshot_at": section["snapshot_at"], "stored_at": record["stored_at"]}


def _value(fact: dict | None, metric: str) -> float | int | None:
    value = fact["values"].get(metric) if fact else None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or abs(value) > 2 ** 53 - 1 or not math.isfinite(value):
        return None
    if METRICS[metric]["unit"] in ("家", "板"):
        return value if isinstance(value, int) and value >= 0 else None
    if METRICS[metric]["unit"] == "百分点":
        return value if -100 <= value <= 10000 else None
    return value if 0 <= value <= 1 else None


def _direction(before: float | None, after: float | None, metric: str) -> str | None:
    if before is None or after is None:
        return None
    diff = after - before
    return "flat" if abs(diff) <= METRICS[metric]["epsilon"] + 1e-9 else "up" if diff > 0 else "down"


def _history_days(day: str) -> list[str]:
    days = [day]
    for _ in range(BASELINE_SESSIONS):
        previous = trade_calendar.previous_trade_date(days[-1])
        if previous is None:
            break
        days.append(previous)
    return list(reversed(days))


def _capture(day: str, items: list[Condition], now: datetime) -> list[dict]:
    days = _history_days(day)
    facts = [_fact(d, now) for d in days]
    result = []
    current_research = research_observation.read_current(day, lambda: _stamp(_now())) if any(i.metric not in LEGACY_METRICS for i in items) else None
    for item in items:
        if item.metric not in LEGACY_METRICS:
            observed = current_research["snapshot_observed_at"] if current_research else _stamp(now)
            if _instant(observed) < now:
                raise VerificationError("读取时钟回退，未保存")
            result.append({**item.model_dump(), "written_at": observed,
                "prior_value": _value(current_research, item.metric), "prior_evidence": current_research,
                "baseline": {"rate": None, "samples": 0, "possible_pairs": 0, "coverage": None,
                             "from": day, "through": day, "as_of": observed, "minimum_samples": MIN_SAMPLES}})
            continue
        counts = dict.fromkeys(("up", "down", "flat"), 0)
        values = [_value(f, item.metric) for f in facts]
        for before, after in zip(values, values[1:]):
            direction = _direction(before, after, item.metric)
            if direction is not None:
                counts[direction] += 1
        samples = sum(counts.values())
        possible = max(0, len(days) - 1)
        result.append({**item.model_dump(), "written_at": _stamp(now),
                       "prior_value": values[-1], "prior_evidence": facts[-1],
                       "baseline": {"rate": counts[item.direction] / samples if samples >= MIN_SAMPLES else None,
                                    "samples": samples, "possible_pairs": possible,
                                    "coverage": samples / possible if possible else None,
                                    "from": days[0], "through": day,
                                    "as_of": _stamp(now), "minimum_samples": MIN_SAMPLES}})
    return result


def replace_plan(day: str, body: SavePlan) -> dict:
    """Single write gate: no backdating, imports, row edits, or alternate delete."""
    body = SavePlan.model_validate(body)
    if len({i.metric for i in body.items}) != len(body.items):
        raise VerificationError("每个读数只能写一个条件")
    if _boundary(day, _now())["state"] != "OPEN":
        raise VerificationError("仅可在该交易日收盘后、下一交易日 09:15 前保存；日历未知时停止写入")
    path = journal_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with sqlite3.connect(path, timeout=10) as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("CREATE TABLE IF NOT EXISTS plans (trade_date TEXT PRIMARY KEY, revision INTEGER NOT NULL, payload TEXT NOT NULL)")
            now = _now()  # after obtaining the write lock, not request arrival
            if _boundary(day, now)["state"] != "OPEN":
                raise VerificationError("下一交易日已封存或日历未知，不能保存、更改或删除")
            row = conn.execute("SELECT revision, payload FROM plans WHERE trade_date=?", (day,)).fetchone()
            revision = row[0] if row else 0
            if revision != body.revision:
                raise VerificationError("记录已改变，请重新读取后再保存")
            try:
                old_items = _validate_plan(day, row[0], json.loads(row[1]))["items"] if row else []
            except (ValueError, KeyError, TypeError) as exc:
                raise JournalError("验证记录损坏，已停止写入") from exc
            existing = {i["metric"]: i for i in old_items}
            captured = _capture(day, body.items, now)
            items = []
            for item in captured:
                old = existing.get(item["metric"])
                unchanged = old and all(old[k] == item[k] for k in ("metric", "direction", "reason"))
                items.append(old if unchanged else item)
            # Fact reads can take time. Recheck immediately before the only write.
            if _boundary(day, _now())["state"] != "OPEN":
                raise VerificationError("读取期间已到封存时间，未保存任何修改")
            conn.execute("INSERT INTO plans VALUES (?, ?, ?) ON CONFLICT(trade_date) DO UPDATE SET revision=excluded.revision, payload=excluded.payload",
                         (day, revision + 1, json.dumps(items, ensure_ascii=False, allow_nan=False)))
    except sqlite3.Error as exc:
        raise JournalError("验证记录不可写入，未保存修改") from exc
    return view(day)


def _results(day: str, plan: dict, now: datetime) -> list[dict]:
    boundary = _boundary(day, now)
    target = boundary["next_trade_date"]
    completed = trade_calendar.completed_trade_date_at(_stamp(now))
    mature = target is not None and completed is not None and completed >= target
    fact = _fact(target, now) if mature else None
    research_fact = research_observation.read_current(target, lambda: _stamp(_now())) if mature and any(i["metric"] not in LEGACY_METRICS for i in plan["items"]) else None
    results = []
    for item in plan["items"]:
        written = _instant(item["written_at"])
        seal = _instant(boundary["seals_at"])
        prior_valid = written is not None and seal is not None and written < seal
        current_fact = fact if item["metric"] in LEGACY_METRICS else research_fact
        value = _value(current_fact, item["metric"])
        actual = _direction(item["prior_value"], value, item["metric"]) if prior_valid and mature else None
        state = "CALENDAR_UNKNOWN" if target is None else "INVALID_PRIOR_TIME" if not prior_valid else "PENDING_CLOSE" if not mature else "NO_EVIDENCE" if actual is None else "VERIFIED"
        results.append({**item, "target_date": target, "state": state,
                        "current_value": value, "current_evidence": current_fact,
                        "actual": actual, "verified": None if actual is None else actual == item["direction"]})
    return results


def _summary(results: list[dict]) -> dict:
    decided = [r for r in results if r["verified"] is not None]
    hit = sum(r["verified"] for r in decided)
    covered = [r for r in decided if r["baseline"]["rate"] is not None]
    expected = sum(r["baseline"]["rate"] for r in covered) / len(covered) if covered else None
    return {"total": len(results), "decided": len(decided), "hit": hit,
            "unknown": len(results) - len(decided),
            "rate": hit / len(decided) if decided else None,
            "coverage": len(decided) / len(results) if results else None,
            "baseline_covered": len(covered), "expected_rate": expected,
            "edge": sum(r["verified"] for r in covered) / len(covered) - expected if covered else None}


def view(day: str) -> dict:
    now = _now()
    boundary = _boundary(day, now)
    plans = _read_plans(journal_path())
    plan = plans.get(day, {"revision": 0, "items": []})
    results = _results(day, plan, now)
    # Calendar-derived window preserves missing days instead of pairing across them.
    window = _history_days(day)[-60:] if boundary["next_trade_date"] else []
    history = []
    for d in window:
        if d in plans:
            history.extend(_results(d, plans[d], now))
    return {"schema_version": SCHEMA_VERSION, "research_only": True, "trade_date": day,
            **boundary, "revision": plan["revision"], "items": results,
            "metrics": [{"key": key, **value} for key, value in METRICS.items()],
            "summary": _summary(results), "history": {"from": window[0] if window else None,
                "through": day, "summary": _summary(history)},
            "generated_at": _stamp(_now()), "limitations": LIMITATIONS}
