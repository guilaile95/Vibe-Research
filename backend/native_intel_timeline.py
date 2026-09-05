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
          report: bool = True, once: bool = True,
          ai_analysis: bool = False, ai_mode: str | None = None, ai_once: bool = True) -> dict[str, Any]:
    return {
        "name": name, "start": start, "end": end, "days": days or list(range(1, 8)),
        "fetch": True, "report": report, "mode": mode, "once": once,
        "ai_analysis": ai_analysis, "ai_mode": ai_mode or mode, "ai_once": ai_once,
    }


def _migrate_segment(segment: dict[str, Any]) -> dict[str, Any]:
    """保证旧版 timeline segment 平滑升级，自动填入合法 AI 字段默认值。"""
    seg = dict(segment)
    if "ai_analysis" not in seg:
        seg["ai_analysis"] = False
    if "ai_mode" not in seg:
        seg["ai_mode"] = seg.get("mode", "CURRENT")
    if "ai_once" not in seg:
        seg["ai_once"] = True
    return seg


def preset_policy(preset: str) -> dict[str, Any]:
    default = {
        "fetch": True, "report": False, "mode": "CURRENT", "once": False,
        "ai_analysis": False, "ai_mode": "CURRENT", "ai_once": True,
    }
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
    if not value:
        return {"enabled": False, "preset": "morning_evening", "custom": preset_policy("custom")}
    raw = json.loads(value)
    # legacy config migration
    if "custom" in raw and isinstance(raw["custom"], dict):
        custom = raw["custom"]
        if "default" in custom and isinstance(custom["default"], dict):
            custom["default"] = _migrate_segment(custom["default"])
        if "segments" in custom and isinstance(custom["segments"], list):
            custom["segments"] = [_migrate_segment(s) for s in custom["segments"] if isinstance(s, dict)]
    return raw


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
        # 平滑补齐缺失的 AI 字段
        if "ai_analysis" not in segment:
            segment["ai_analysis"] = False
        if "ai_mode" not in segment:
            segment["ai_mode"] = segment.get("mode", "CURRENT")
        if "ai_once" not in segment:
            segment["ai_once"] = True

        fields = {"fetch", "report", "mode", "once", "ai_analysis", "ai_mode", "ai_once"}
        if index:
            fields |= {"name", "start", "end", "days"}
        if not isinstance(segment, dict) or set(segment) != fields:
            raise ValueError("timeline 行为字段不完整或包含未知字段")
        if any(type(segment[k]) is not bool for k in ("fetch", "report", "once", "ai_analysis", "ai_once")) or segment["mode"] not in MODES or segment["ai_mode"] not in MODES:
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
    # 确保 policy 内部的 segment 也有默认 AI 字段
    if "default" in policy:
        policy["default"] = _migrate_segment(policy["default"])
    if "segments" in policy:
        policy["segments"] = [_migrate_segment(s) for s in policy["segments"]]

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
        behavior = {
            "fetch": True, "report": False, "mode": "CURRENT", "once": False,
            "ai_analysis": False, "ai_mode": "CURRENT", "ai_once": True,
        }
    return {"preset": cfg["preset"], "enabled": cfg["enabled"],
            "current_segment": selected["name"] if selected and cfg["enabled"] else "默认",
            "segment_start": start.isoformat(), "segment_end": end.isoformat(),
            "active": bool(behavior["report"]), "next_transition": min(transitions).isoformat(),
            **behavior, "timezone": "Asia/Shanghai", "config": cfg,
            "last_scheduled_report": json.loads(store.get_meta("native_intel_last_scheduled_report", path) or "null"),
            "last_scheduled_ai": json.loads(store.get_meta("native_intel_last_scheduled_ai", path) or "null"),
            "usage_boundary": "observation_only_not_an_investment_authority"}


def scheduled_tick(path: str | None = None, *, now: datetime | None = None, ai_runner: Any = None) -> None:
    from native_intel_service import run_fetch
    from native_intel_reporting import generate_report
    import native_intel_ai as ai_engine

    when = (now or datetime.now(timezone.utc)).astimezone(LOCAL)
    status = resolve_policy(path, now=when)
    if status["fetch"]:
        run_fetch("scheduled", path)
    if not status["active"] and not status.get("ai_analysis"):
        return

    execution_key = "timeline:" + status["preset"] + ":" + status["current_segment"]
    previous = store.read_report_cursor(execution_key, path)

    if status["active"]:
        # The reference once rule is keyed by local date, including midnight resets.
        can_run = True
        if status["once"] and previous and datetime.fromisoformat(previous["generated_at"].replace("Z", "+00:00")).astimezone(LOCAL).date() == when.date():
            can_run = False

        if can_run:
            result = generate_report(path, mode=status["mode"], report_profile="scheduled", now=now)
            if result["cursor_advanced"]:
                store.advance_report_cursor(execution_key, "default", status["mode"], result["generated_at"],
                                            result["observation_boundary"], previous, path)
                store.set_meta("native_intel_last_scheduled_report", json.dumps({
                    "generated_at": result["generated_at"], "mode": result["mode"], "item_count": result["total"],
                    "status": result["status"], "segment": status["current_segment"]}), path)

    # Scheduled AI Analysis with Failure Isolation
    if status.get("ai_analysis"):
        ai_execution_key = "timeline_ai:" + status["preset"] + ":" + status["current_segment"]
        ai_previous = store.read_report_cursor(ai_execution_key, path)
        can_run_ai = True
        if status.get("ai_once", True) and ai_previous and datetime.fromisoformat(ai_previous["generated_at"].replace("Z", "+00:00")).astimezone(LOCAL).date() == when.date():
            can_run_ai = False

        if can_run_ai:
            ai_mode = status.get("ai_mode") or status["mode"]
            try:
                # 预览报告（commit=False），绝不消耗或推进 INCREMENTAL report baseline
                preview_report = generate_report(path, mode=ai_mode, report_profile="scheduled_preview", now=now, commit=False)
                ai_res = ai_engine.analyze_report(
                    preview_report,
                    scope="all",
                    model_runner=ai_runner,
                    path=path,
                )
                ai_status = ai_res.get("status", "SUCCESS")
                ai_error = ai_res.get("error")
                if ai_status == "SUCCESS":
                    store.advance_report_cursor(
                        ai_execution_key, "default", ai_mode, when.strftime("%Y-%m-%dT%H:%M:%SZ"), 0, ai_previous, path
                    )
                store.set_meta("native_intel_last_scheduled_ai", json.dumps({
                    "generated_at": when.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "mode": ai_mode,
                    "status": ai_status,
                    "segment": status["current_segment"],
                    "artifact_id": ai_res.get("artifact_id", ""),
                    "error": ai_error,
                }), path)
            except Exception as e:
                # Failure Isolation：AI 异常绝不能破坏本次 tick 或让正常抓取/报告被标记失败
                store.set_meta("native_intel_last_scheduled_ai", json.dumps({
                    "generated_at": when.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "mode": ai_mode,
                    "status": "ERROR",
                    "segment": status["current_segment"],
                    "error": str(e)[:200],
                }), path)
