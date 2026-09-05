"""Native weekly fetch/report policy. Executed by the existing Intel fetch loop."""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any

import native_intel_store as store

LOCAL = timezone(timedelta(hours=8))
PRESETS = ("always_on", "morning_evening", "office_hours", "night_owl", "custom")
MODES = ("CURRENT", "DAILY", "INCREMENTAL")


def _slot(name: str, start: str, end: str, mode: str, days: list[int] | None = None,
          report: bool = True, once: bool = True) -> dict[str, Any]:
    return {"name": name, "start": start, "end": end, "days": days or list(range(1, 8)),
            "fetch": True, "report": report, "mode": mode, "once": once}


def preset_policy(preset: str) -> dict[str, Any]:
    default = {"fetch": True, "report": False, "mode": "CURRENT", "once": False}
    segments: list[dict[str, Any]] = []
    if preset == "always_on":
        default.update(report=True, mode="INCREMENTAL")
    elif preset == "morning_evening":
        default["report"] = True
        segments = [_slot("晚间汇总", "20:00", "22:00", "DAILY")]
    elif preset == "office_hours":
        segments = [_slot("到岗速览", "09:00", "11:00", "CURRENT", [1, 2, 3, 4, 5]),
                    _slot("午间热点", "13:00", "15:00", "CURRENT", [1, 2, 3, 4, 5]),
                    _slot("收工汇总", "17:00", "19:00", "DAILY", [1, 2, 3, 4, 5]),
                    _slot("周末自由", "08:00", "23:00", "INCREMENTAL", [6, 7], once=False)]
    elif preset == "night_owl":
        segments = [_slot("午后速览", "15:00", "17:00", "CURRENT"),
                    _slot("深夜汇总", "22:00", "01:00", "DAILY")]
    elif preset == "custom":
        segments = [_slot("夜间采集", "23:00", "06:00", "CURRENT", report=False),
                    _slot("工作日早间", "08:00", "10:00", "INCREMENTAL", [1, 2, 3, 4, 5]),
                    _slot("周末早间", "10:00", "12:00", "DAILY", [6, 7]),
                    _slot("晚间汇总", "19:00", "21:00", "DAILY")]
    else:
        raise ValueError("未知 timeline preset")
    return {"default": default, "segments": segments}


def get_policy(path: str | None = None) -> dict[str, Any]:
    value = store.get_meta("native_intel_timeline", path)
    return json.loads(value) if value else {"enabled": False, "preset": "morning_evening",
                                           "custom": preset_policy("custom")}


def _minute(value: Any) -> int:
    if not isinstance(value, str) or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value):
        raise ValueError("时间必须为合法 HH:MM")
    hour, minute = map(int, value.split(":"))
    return hour * 60 + minute


def _minutes(segment: dict[str, Any]) -> set[int]:
    start, end = _minute(segment["start"]), _minute(segment["end"])
    if start == end:
        raise ValueError("时间段起止不能相同")
    return {m % 1440 for m in range(start, end if end > start else end + 1440)}


def save_policy(payload: dict[str, Any], path: str | None = None) -> dict[str, Any]:
    if set(payload) - {"enabled", "preset", "custom"}:
        raise ValueError("timeline 包含未知字段")
    cfg = {**get_policy(path), **payload}
    if type(cfg["enabled"]) is not bool or cfg["preset"] not in PRESETS:
        raise ValueError("timeline enabled/preset 非法")
    custom = cfg["custom"]
    if not isinstance(custom, dict) or set(custom) != {"default", "segments"}:
        raise ValueError("custom 需要 default 与 segments")
    segments = custom["segments"]
    if not isinstance(segments, list) or len(segments) > 32:
        raise ValueError("custom segments 最多 32 个")
    names: set[str] = set()
    occupied = {day: set() for day in range(1, 8)}
    for index, segment in enumerate([custom["default"], *segments]):
        fields = {"fetch", "report", "mode", "once"}
        if index:
            fields |= {"name", "start", "end", "days"}
        if not isinstance(segment, dict) or set(segment) != fields:
            raise ValueError("timeline 行为字段不完整或包含未知字段")
        if any(type(segment[k]) is not bool for k in ("fetch", "report", "once")) or segment["mode"] not in MODES:
            raise ValueError("timeline 行为必须使用布尔开关及合法报告模式")
        if not index:
            continue
        name = segment["name"]
        if not isinstance(name, str) or not name.strip() or len(name) > 60 or name in names:
            raise ValueError("时间段需要唯一名称（1–60 字符）")
        names.add(name)
        days = segment["days"]
        if not isinstance(days, list) or not days or any(type(d) is not int or d not in occupied for d in days):
            raise ValueError("days 必须是 1–7 的星期列表")
        minutes = _minutes(segment)
        for day in set(days):
            if occupied[day] & minutes:
                raise ValueError("时间段重叠，包括跨午夜区间")
            occupied[day].update(minutes)
    store.set_meta("native_intel_timeline", json.dumps(cfg, ensure_ascii=False), path)
    return cfg


def resolve_policy(path: str | None = None, *, now: datetime | None = None) -> dict[str, Any]:
    cfg = get_policy(path)
    now = (now or datetime.now(timezone.utc)).astimezone(LOCAL)
    policy = cfg["custom"] if cfg["preset"] == "custom" else preset_policy(cfg["preset"])
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    selected = None
    for segment in policy["segments"]:
        if now.isoweekday() in segment["days"] and now.hour * 60 + now.minute in _minutes(segment):
            selected = segment
            break
    behavior = selected or policy["default"]
    start, end = midnight, midnight + timedelta(days=1)
    if selected:
        start = midnight + timedelta(minutes=_minute(selected["start"]))
        end = midnight + timedelta(minutes=_minute(selected["end"]))
        if end < start:
            if now < end:
                start -= timedelta(days=1)
            else:
                end += timedelta(days=1)
    transitions = [midnight + timedelta(days=1)]
    for offset in range(8):
        date = midnight + timedelta(days=offset)
        for segment in policy["segments"]:
            if date.isoweekday() in segment["days"]:
                for field in ("start", "end"):
                    point = date + timedelta(minutes=_minute(segment[field]))
                    if point > now:
                        transitions.append(point)
    if not cfg["enabled"]:
        behavior = {"fetch": True, "report": False, "mode": "CURRENT", "once": False}
    return {"preset": cfg["preset"], "enabled": cfg["enabled"],
            "current_segment": selected["name"] if selected and cfg["enabled"] else "默认",
            "segment_start": start.isoformat(), "segment_end": end.isoformat(),
            "active": bool(behavior["report"]), "next_transition": min(transitions).isoformat(),
            **behavior, "timezone": "Asia/Shanghai", "config": cfg,
            "last_scheduled_report": json.loads(store.get_meta("native_intel_last_scheduled_report", path) or "null"),
            "usage_boundary": "observation_only_not_an_investment_authority"}


def scheduled_tick(path: str | None = None, *, now: datetime | None = None) -> None:
    from native_intel_service import run_fetch
    from native_intel_reporting import generate_report

    when = (now or datetime.now(timezone.utc)).astimezone(LOCAL)
    status = resolve_policy(path, now=when)
    if status["fetch"]:
        run_fetch("scheduled", path)
    if not status["active"]:
        return
    execution_key = "timeline:" + status["preset"] + ":" + status["current_segment"]
    previous = store.read_report_cursor(execution_key, path)
    # The reference once rule is keyed by local date, including midnight resets.
    if status["once"] and previous and datetime.fromisoformat(previous["generated_at"].replace("Z", "+00:00")).astimezone(LOCAL).date() == when.date():
        return
    result = generate_report(path, mode=status["mode"], report_profile="scheduled", now=now)
    if result["cursor_advanced"]:
        store.advance_report_cursor(execution_key, "default", status["mode"], result["generated_at"],
                                    result["observation_boundary"], previous, path)
        store.set_meta("native_intel_last_scheduled_report", json.dumps({
            "generated_at": result["generated_at"], "mode": result["mode"], "item_count": result["total"],
            "status": result["status"], "segment": status["current_segment"]}), path)
