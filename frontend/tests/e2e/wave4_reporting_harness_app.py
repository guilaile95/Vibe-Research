"""Wave 4 only: real Native Intel router + isolated SQLite, no network or AI."""
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[3] / "backend"
sys.path[:0] = [str(BACKEND), str(BACKEND / "tests")]
from fastapi import FastAPI
import native_intel_reporting as reports
import native_intel_router
import native_intel_service as service
import native_intel_store as store
from test_native_intel_reporting import seed

DB = os.environ["VIBE_NATIVE_INTEL_DB"]  # Required: never fall back to Owner data.
CLOCK = datetime.now(timezone.utc).replace(second=0, microsecond=0)
reports._now = lambda value: (value or CLOCK).astimezone(reports.LOCAL)
app = FastAPI()
app.include_router(native_intel_router.router)


@app.on_event("startup")
def setup():
    service.update_filter_profile("default", {"method": "keyword", "keyword_rules": {"groups": [
        {"name": "机器人", "includes": ["机器人"]}, {"name": "芯片", "includes": ["芯片"]}]}}, DB)
    for offset in range(7):
        seed(DB, CLOCK-timedelta(days=6-offset, minutes=2), [
            ("weibo", "robot-w", "机器人芯片获得新订单", 18-offset),
            ("baidu", "robot-b", "机器人芯片获得大订单", 9-offset),
            ("rss-a", "robot-r", "机器人芯片产业新闻", None)])
    seed(DB, CLOCK-timedelta(minutes=1), [("weibo", "robot-w", "机器人芯片获得新订单", 4),
        ("weibo", "today", "今日机器人芯片新品", 6),
        ("rss-a", "archived", "首次采集的机器人旧文", None, reports._iso(CLOCK-timedelta(days=30)))])
    store.update_native_intel_config({"regions_enabled": {"hotlist": False, "rss": False,
        "standalone": False, "new_items": True}, "region_order": ["new_items"]}, DB)
    # Labels are registry metadata; observations above still use the real service path.
    with store._connect(DB) as conn:
        conn.execute("UPDATE intel_sources SET name='微博' WHERE source_id='weibo'")
        conn.execute("UPDATE intel_sources SET name='百度' WHERE source_id='baidu'")


@app.get("/healthz")
def health():
    return {"status": "ok"}


@app.post("/__test/new-observation")
def new_observation():
    global CLOCK
    CLOCK += timedelta(minutes=1)
    seed(DB, CLOCK, [("weibo", "after-baseline", "基线后的唯一机器人新增", 2)])
    return {"title": "基线后的唯一机器人新增"}


@app.get("/api/profile")
def profile():
    return {"data": {}}


@app.get("/api/radar")
def radar():
    return {"generated_at": None, "recent_days": 3, "industries": [],
            "stats": {"industries": 0, "total_sources": 0}}
