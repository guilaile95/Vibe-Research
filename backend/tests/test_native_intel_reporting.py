"""Wave 4 acceptance: real SQLite facts, report cursors and deterministic rules."""
from datetime import datetime, timedelta, timezone
import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import native_intel_reporting as reports
import native_intel_router as router
import native_intel_service as service
import native_intel_store as store
import native_intel_timeline as timeline

NOW = datetime(2026, 9, 5, 12, tzinfo=timezone.utc)


def seed(path, when, entries, *, failed=()):
    """entries: (source, item key, title, real rank or None, optional publication)."""
    source_ids = set(e[0] for e in entries) | set(failed)
    sources = [{"source_id": s, "name": s, "url": "https://example.test/feed", "hint": "research",
                "source_type": "rss" if s.startswith("rss") else "hotlist",
                "has_real_rank": not s.startswith("rss")} for s in source_ids]
    store.upsert_sources(sources, path)
    run_id = reports._iso(when)
    store.start_run(run_id, "fixture", len(sources), path)
    ids = []
    for source, key, title, rank, *published in entries:
        pub = published[0] if published else reports._iso(when)
        item = {"item_key": key, "title": title, "title_key": title, "url": "https://example.test/" + key,
                "published_at": pub, "rank": rank, "summary": ""}
        iid, _ = store.upsert_observation(run_id, source, item, observed_at=reports._iso(when),
                                          has_real_rank=not source.startswith("rss"), db_path=path)
        ids.append(iid)
    for source in sources:
        sid = source["source_id"]
        store.record_source_run(run_id, sid, status="failed" if sid in failed else "ok",
                                item_count=sum(e[0] == sid for e in entries), db_path=path)
    store.finish_run(run_id, status="partial" if failed else "ok", source_ok=len(sources)-len(failed),
                     source_failed=len(failed), item_seen=len(entries), item_new=len(entries), db_path=path)
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE intel_fetch_runs SET started_at=?, finished_at=? WHERE run_id=?",
                     (reports._iso(when), reports._iso(when), run_id))
    return ids


def items(report):
    return [i for section in report["sections"] for i in section["items"]]


def test_current_daily_boundaries_and_rss_rank(tmp_path):
    path = tmp_path / "native_intel.sqlite3"
    day = NOW.astimezone(reports.LOCAL).replace(hour=0, minute=0, second=0)
    seed(path, day-timedelta(seconds=1), [("weibo", "old", "昨天机器人", 1)])
    seed(path, day, [("weibo", "open", "零点机器人", 9)])
    seed(path, NOW-timedelta(minutes=1), [("weibo", "new", "当前机器人", 8), ("rss-a", "rss", "订阅机器人", 3)])
    current = reports.generate_report(str(path), now=NOW)
    assert {i["title"] for i in items(current)} == {"当前机器人", "订阅机器人"}
    assert next(i for i in items(current) if i["source_type"] == "rss")["rank"] is None
    assert next(i for i in items(current) if i["title"] == "当前机器人")["highlight"] is False
    assert {i["title"] for i in items(reports.generate_report(str(path), mode="DAILY", now=NOW))} == {"零点机器人", "当前机器人", "订阅机器人"}
    assert len(items(reports.generate_report(str(path), now=NOW, rank_threshold=10))) == 2


def test_incremental_success_failure_and_genuine_delta(tmp_path, monkeypatch):
    path = tmp_path / "native_intel.sqlite3"
    row = ("weibo", "same", "机器人新闻", 5, reports._iso(NOW-timedelta(minutes=3)))
    seed(path, NOW-timedelta(minutes=3), [row])
    first = reports.generate_report(str(path), mode="INCREMENTAL", now=NOW)
    assert first["cursor_advanced"] and first["total"] == 1
    second = reports.generate_report(str(path), mode="INCREMENTAL", now=NOW+timedelta(seconds=1))
    assert second["total"] == 0
    seed(path, NOW+timedelta(minutes=1), [row])
    assert reports.generate_report(str(path), mode="INCREMENTAL", now=NOW+timedelta(minutes=2))["total"] == 0
    seed(path, NOW+timedelta(minutes=3), [("weibo", "same", "机器人新闻", 2), ("rss-a", "new", "新增机器人", None)])
    cursor_before = store.read_report_cursor(first["baseline"]["report_key"], path) if first["baseline"] else second["baseline"]
    with sqlite3.connect(path) as conn:
        before = conn.execute("SELECT * FROM intel_report_cursors").fetchall()
    with monkeypatch.context() as patch:
        patch.setattr(reports, "_display_order", lambda *_: (_ for _ in ()).throw(RuntimeError("fixture failure")))
        with pytest.raises(RuntimeError):
            reports.generate_report(str(path), mode="INCREMENTAL", now=NOW+timedelta(minutes=4))
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT * FROM intel_report_cursors").fetchall() == before
    third = reports.generate_report(str(path), mode="INCREMENTAL", now=NOW+timedelta(minutes=4))
    assert {i["change_kind"] for i in items(third)} == {"CHANGED", "NEWLY_OBSERVED"}
    assert third["observation_boundary"] > cursor_before["observation_boundary"]


def test_profile_grouping_order_caps_freshness_and_interest_scope(tmp_path):
    path = tmp_path / "native_intel.sqlite3"
    seed(path, NOW-timedelta(minutes=1), [("rss-a", "old", "机器人过期", None, reports._iso(NOW-timedelta(days=8))),
        ("rss-a", "a", "机器人芯片", None), ("rss-a", "b", "机器人订单", None),
        ("rss-a", "c", "机器人生产", None), ("rss-a", "noise", "娱乐资讯", None)])
    service.update_filter_profile("default", {"keyword_rules": {"global_excludes": ["娱乐"], "filter_terms": ["谣言"],
        "groups": [{"name": "芯片", "includes": ["芯片"], "required": ["机器人"]},
                   {"name": "机器人", "includes": ["机器人"], "max_count": 1}]}}, str(path))
    store.update_native_intel_config({"rss_freshness_enabled": True, "rss_global_max_age_days": 1}, path)
    result = reports.generate_report(str(path), scope="my_interests", now=NOW, sort_by_position_first=True)
    assert [s["name"] for s in result["sections"]] == ["芯片", "机器人"]
    assert {i["title"] for i in items(result)} == {"机器人芯片", "机器人订单"}
    assert store.count_items(path) == 5
    assert reports.generate_report(str(path), now=NOW)["total"] == 4
    default_order = reports.generate_report(str(path), scope="my_interests", now=NOW)
    assert default_order["sections"][0]["name"] == "机器人"
    assert default_order["sections"][0]["count"] == 2 and len(default_order["sections"][0]["items"]) == 1
    # Per-feed policy changes must create an eligible baseline, not consume excluded history.
    first = reports.generate_report(str(path), mode="INCREMENTAL", now=NOW)
    store.update_source("rss-a", max_age_days=0, db_path=path)
    expanded = reports.generate_report(str(path), mode="INCREMENTAL", now=NOW)
    assert first["total"] == 4 and expanded["total"] == 5 and expanded["baseline"] is None


@pytest.mark.parametrize("preset,instant,active,mode", [
    ("always_on", "2026-09-07T02:00:00+08:00", True, "INCREMENTAL"),
    ("morning_evening", "2026-09-07T20:00:00+08:00", True, "DAILY"),
    ("office_hours", "2026-09-07T11:00:00+08:00", False, "CURRENT"),
    ("office_hours", "2026-09-06T12:00:00+08:00", True, "INCREMENTAL"),
    ("night_owl", "2026-09-07T00:30:00+08:00", True, "DAILY"),
    ("custom", "2026-09-07T08:00:00+08:00", True, "INCREMENTAL"),
])
def test_pinned_presets(tmp_path, preset, instant, active, mode):
    path = str(tmp_path / "native_intel.sqlite3")
    timeline.save_policy({"preset": preset, "enabled": True}, path)
    result = timeline.resolve_policy(path, now=datetime.fromisoformat(instant))
    assert result["active"] is active and result["mode"] == mode
    assert datetime.fromisoformat(result["next_transition"]) > datetime.fromisoformat(instant)


def test_custom_persistence_overlap_and_api_validation(tmp_path, monkeypatch):
    path = str(tmp_path / "native_intel.sqlite3")
    cfg = timeline.get_policy(path)
    cfg["custom"]["segments"][1]["start"] = "07:15"
    timeline.save_policy(cfg, path)
    assert timeline.get_policy(path) == cfg
    app = FastAPI()
    app.include_router(router.router)
    monkeypatch.setenv("VIBE_NATIVE_INTEL_DB", path)
    client = TestClient(app)
    cfg["custom"]["segments"][1]["start"] = "05:00"
    assert client.put("/api/native-intel/timeline", json=cfg).status_code == 422
    cfg["custom"]["segments"][1]["start"] = "25:00"
    assert client.put("/api/native-intel/timeline", json=cfg).status_code == 422
    assert client.get("/api/native-intel/timeline").json()["config"]["custom"]["segments"][1]["start"] == "07:15"


def test_daily_counts_rank_isolation_platforms_cooccurrence_and_similar(tmp_path):
    path = str(tmp_path / "native_intel.sqlite3")
    service.update_filter_profile("default", {"keyword_rules": {"groups": [
        {"name": "机器人", "includes": ["机器人"]}, {"name": "芯片", "includes": ["芯片"]}]}}, path)
    for offset in range(7):
        seed(path, NOW-timedelta(days=6-offset, minutes=10), [("weibo", "a", "机器人芯片获得新订单", 18-offset),
             ("baidu", "b", "机器人芯片获得新订单", 9-offset), ("rss-a", "c", "机器人芯片获得订单报道", None)])
    seed(path, NOW-timedelta(minutes=1), [("weibo", "a", "机器人芯片获得新订单", 4)])
    result = reports.analyze_topic(path, topic="机器人", now=NOW)
    assert [b["mention_count"] for b in result["trend"]] == [3]*7
    assert result["trend"][-1]["source_count"] == 3 and result["trend"][-1]["platform_count"] == 2
    paths = {r["source_id"]: r["points"] for r in result["rank_timeline"]}
    assert paths["weibo"][0]["rank"] == 18 and paths["weibo"][-1]["rank"] == 4
    assert paths["baidu"][-1]["rank"] == 3
    assert len(paths) == 2
    assert result["cooccurrence"][0]["count"] == 3
    hot_samples = [r for r in result["cooccurrence"][0]["sample_items"] if r["source_type"] == "hotlist"]
    assert len({r["title"] for r in hot_samples}) == 1
    assert len({r["item_id"] for r in hot_samples}) == 2  # Same story, distinct Native Intel identities.
    assert {p["source_id"] for p in result["platforms"]} == {"weibo", "baidu", "rss-a", "rss-group:research"}
    rss = next(p for p in result["platforms"] if p["source_id"] == "rss-a")
    assert rss["item_count"] == 7 and rss["ranked_visibility"] == 0 and rss["mean_observed_rank"] is None
    group = next(p for p in result["platforms"] if p["source_id"] == "rss-group:research")
    assert group["source_ids"] == ["rss-a"] and group["item_count"] == 7
    reference = result["rank_timeline"][0]["item_id"]
    similar = reports.similar_items(reference, path, now=NOW)
    assert similar["similar_items"][0]["similarity_score"] > 0.6


def test_rule_thresholds_are_exact_and_missing_coverage_unknown():
    assert reports.summarize_counts([4, 4, 4, 0, 2, 2, 2])["lifecycle"]["status"] == "稳定期"
    assert reports.summarize_counts([4, 4, 4, 0, 1, 2, 2])["lifecycle"]["status"] == "衰退期"
    assert reports.summarize_counts([0, 4])["viral"]["detected"] is False
    assert reports.summarize_counts([0, 5])["viral"]["detected"] is True
    assert reports.summarize_counts([2, 5])["viral"]["detected"] is False
    assert reports.summarize_counts([2, 6])["viral"]["detected"] is True
    assert reports.summarize_counts([8, 10, 13])["prediction"]["direction"] == "未触发"
    assert reports.summarize_counts([8, 10, 14])["prediction"]["direction"] == "上升"
    assert reports.summarize_counts([0, 5], complete=False)["viral"]["detected"] is None


def test_new_region_distinguishes_first_local_rss_from_new_on_list(tmp_path):
    path = str(tmp_path / "native_intel.sqlite3")
    seed(path, NOW-timedelta(minutes=1), [("weibo", "hot", "机器人热榜", 2), ("rss-a", "old-rss", "机器人旧文", None,
          reports._iso(NOW-timedelta(days=30)))])
    result = reports.generate_report(path, now=NOW, commit=False)
    assert {r["new_kind"] for r in result["new_items"]} == {"NEW_ON_LIST", "NEWLY_OBSERVED"}
    assert not result["cursor_advanced"]


def test_cursor_schema_upgrade_preserves_facts(tmp_path):
    path = str(tmp_path / "native_intel.sqlite3")
    seed(path, NOW-timedelta(minutes=1), [("rss-a", "a", "机器人", None)])
    with sqlite3.connect(path) as conn:
        conn.execute("DROP TABLE intel_report_cursors")
    store.initialize_store(path)
    assert store.count_items(path) == 1
    assert reports.generate_report(path, now=NOW)["cursor_advanced"]


def test_new_on_list_skips_failed_run_and_uses_previous_success(tmp_path, monkeypatch):
    path = str(tmp_path / "native_intel.sqlite3")
    row = ("weibo", "a", "机器人再上榜", 2)
    seed(path, NOW-timedelta(minutes=4), [row])
    seed(path, NOW-timedelta(minutes=3), [("weibo", "b", "其他新闻", 1)])
    seed(path, NOW-timedelta(minutes=2), [], failed=("weibo",))
    seed(path, NOW-timedelta(minutes=1), [row])
    assert items(reports.generate_report(path, now=NOW, commit=False))[0]["new_kind"] == "NEW_ON_LIST"
    monkeypatch.setenv("VIBE_NATIVE_INTEL_DB", path)
    monkeypatch.setattr(reports, "_now", lambda value: NOW.astimezone(reports.LOCAL))
    app = FastAPI()
    app.include_router(router.router)
    response = TestClient(app).get("/api/native-intel/new-items")
    assert response.status_code == 200
    assert [(i["title"], i["new_kind"]) for i in response.json()["items"]] == [(row[2], "NEW_ON_LIST")]


def test_new_on_list_not_false_positive_after_failed_run(tmp_path, monkeypatch):
    path = str(tmp_path / "native_intel.sqlite3")
    row = ("weibo", "a", "机器人持续在榜", 2)
    iid = seed(path, NOW-timedelta(minutes=3), [row])[0]
    seed(path, NOW-timedelta(minutes=2), [], failed=("weibo",))
    assert store.get_item_rank_state(iid, path, now=NOW)["current_state"] == "UNKNOWN"
    seed(path, NOW-timedelta(minutes=1), [row])
    assert items(reports.generate_report(path, now=NOW, commit=False))[0]["new_kind"] is None
    monkeypatch.setenv("VIBE_NATIVE_INTEL_DB", path)
    monkeypatch.setattr(reports, "_now", lambda value: NOW.astimezone(reports.LOCAL))
    app = FastAPI()
    app.include_router(router.router)
    response = TestClient(app).get("/api/native-intel/new-items")
    assert response.status_code == 200 and response.json()["items"] == []


def test_scheduled_fetch_report_once_and_disabled_segment(tmp_path, monkeypatch):
    path = str(tmp_path / "native_intel.sqlite3")
    seed(path, NOW-timedelta(minutes=1), [("rss-a", "a", "机器人", None)])
    calls = []
    monkeypatch.setattr(service, "run_fetch", lambda reason, db: calls.append((reason, db)))
    timeline.save_policy({"enabled": True, "preset": "morning_evening"}, path)
    timeline.scheduled_tick(path, now=NOW)
    status = timeline.resolve_policy(path, now=NOW)
    assert status["last_scheduled_report"]["item_count"] == 1
    timeline.scheduled_tick(path, now=NOW+timedelta(minutes=1))
    assert timeline.resolve_policy(path, now=NOW)["last_scheduled_report"] == status["last_scheduled_report"]
    assert len(calls) == 2  # once limits report generation, not collection.
    timeline.save_policy({"preset": "custom", "custom": {"default":
        {"fetch": False, "report": False, "mode": "CURRENT", "once": False}, "segments": []}}, path)
    timeline.scheduled_tick(path, now=NOW)
    assert len(calls) == 2


def test_backup_restores_cursor_and_custom_policy(tmp_path, monkeypatch):
    import vibe_data_backup as backup
    from test_vibe_data_backup import _minimal_data_root
    data = _minimal_data_root(tmp_path, monkeypatch)
    path = data / "native_intel.sqlite3"
    seed(path, NOW-timedelta(minutes=1), [("rss-a", "a", "机器人", None)])
    timeline.save_policy({"enabled": True, "preset": "custom"}, str(path))
    generated = reports.generate_report(str(path), mode="INCREMENTAL", now=NOW)
    archive = tmp_path / "wave4.zip"
    backup.create_bundle(archive, quiescent_probe=lambda: backup.QUIESCENT)
    assert backup.verify_bundle(archive)["status"] == "OK"
    restored = tmp_path / "restored"
    backup.restore_bundle(archive, restored)
    restored_db = next(restored.rglob("native_intel.sqlite3"))
    assert timeline.get_policy(str(restored_db))["preset"] == "custom"
    result = reports.generate_report(str(restored_db), mode="INCREMENTAL", now=NOW+timedelta(seconds=1))
    assert result["total"] == 0 and result["baseline"]["observation_boundary"] == generated["observation_boundary"]


def test_large_history_reports_and_14_30_day_aggregates(tmp_path):
    path = str(tmp_path / "native_intel.sqlite3")
    first = NOW.astimezone(reports.LOCAL).replace(hour=0, minute=0, second=0) - timedelta(days=59)
    sources = ("weibo", "baidu", "rss-a")
    entries = [(s, f"{s}-{i}", f"机器人芯片{i}", i+1 if s != "rss-a" else None)
               for s in sources for i in range(50)]
    ids = seed(path, first, entries)
    # 432,000 short observations, bulk inserted; no network or production DB.
    instants = [first + timedelta(days=d, minutes=15*n) for d in range(60) for n in range(48)]
    with sqlite3.connect(path) as conn:
        conn.executemany("INSERT INTO intel_fetch_runs (run_id,started_at,finished_at,status,trigger,source_total,source_ok) "
                         "VALUES (?,?,?,'ok','fixture',3,3)",
                         ((reports._iso(t),)*3 for t in instants[1:]))
        conn.executemany("INSERT INTO intel_source_runs (run_id,source_id,status,item_count) VALUES (?,?,'ok',50)",
                         ((reports._iso(t), s) for t in instants[1:] for s in sources))
        conn.executemany("INSERT INTO intel_observations (run_id,item_id,source_id,observed_at,rank,observed_title,published_at) "
                         "VALUES (?,?,?,?,?,?,?)",
                         ((reports._iso(t), iid, row[0], reports._iso(t), row[3], row[2], reports._iso(first))
                          for t in instants[1:] for iid, row in zip(ids, entries)))
        conn.execute("UPDATE intel_items SET observation_count=2880, last_seen_at=?", (reports._iso(instants[-1]),))
        assert conn.execute("SELECT COUNT(*) FROM intel_observations").fetchone()[0] == 432000
    service.update_filter_profile("default", {"keyword_rules": {"groups": [
        {"name": "机器人", "includes": ["机器人"]}, {"name": "芯片", "includes": ["芯片"]}]}}, path)
    for mode in ("CURRENT", "DAILY", "INCREMENTAL"):
        result = reports.generate_report(path, mode=mode, now=NOW)
        assert result["total"] == result["unique_item_count"] == 150
        assert sum(i["observation_count"] for i in items(result)) == 48*150
        assert next(i for i in items(result) if i["source_id"] == "weibo" and i["rank"] == 1)["display_order_score"] == 100
    assert reports.generate_report(path, mode="INCREMENTAL", now=NOW)["total"] == 0
    for days in (14, 30):
        result = reports.analyze_topic(path, topic="机器人", days=days, now=NOW)
        assert [b["mention_count"] for b in result["trend"]] == [150]*days
        assert all(b["source_count"] == 3 and b["platform_count"] == 2 and b["unique_item_count"] == 150 for b in result["trend"])
        assert result["cross_source_visibility"] == 3 and result["cooccurrence"][0]["count"] == 150
        for p in result["platforms"]:
            assert p["item_count"] == p["topic_hit_count"] == p["previous_item_count"] == days*50
            assert p["unique_item_count"] == 50 and p["updates"] == days*48
            assert p["activity_change"] == 0 and p["new_item_count"] == 0
            assert p["ranked_visibility"] == (days*48*50 if p["source_type"] == "hotlist" else 0)
            assert p["mean_observed_rank"] == (25.5 if p["source_type"] == "hotlist" else None)
        assert result["rank_timeline_sample"]["total_points"] == days*48*100
        assert result["rank_timeline_sample"]["truncated"] is True
        assert sum(len(t["points"]) for t in result["rank_timeline"]) == reports.RANK_TIMELINE_POINT_LIMIT


def test_daily_preserves_fact_but_latest_source_failure_is_unknown(tmp_path):
    path = str(tmp_path / "native_intel.sqlite3")
    day = NOW.astimezone(reports.LOCAL).replace(hour=0, minute=0, second=0)
    seed(path, day+timedelta(hours=9), [("weibo", "a", "机器人新闻", 1), ("rss-a", "b", "机器人文章", None)])
    seed(path, day+timedelta(hours=11), [], failed=("weibo", "rss-a"))
    when = day+timedelta(hours=12)
    daily = items(reports.generate_report(path, mode="DAILY", now=when, commit=False))
    assert len(daily) == 2 and all(i["latest_source_status"] == "FAILED" for i in daily)
    hot = next(i for i in daily if i["source_type"] == "hotlist")
    assert hot["current_state"] == store.get_item_rank_state(hot["item_id"], path, now=when)["current_state"] == "UNKNOWN"
    rss = next(i for i in daily if i["source_type"] == "rss")
    assert rss["rank"] is None and rss["current_state"] == "NO_RANK_SEMANTICS"
    assert reports.generate_report(path, mode="CURRENT", now=when, commit=False)["total"] == 0


def test_analytics_reenable_eligibility_preserves_raw_history(tmp_path, monkeypatch):
    path = str(tmp_path / "native_intel.sqlite3")
    seed(path, NOW-timedelta(hours=2), [("weibo", "a", "机器人新闻", 1)])
    monkeypatch.setattr(store, "utc_now_iso", lambda: reports._iso(NOW-timedelta(hours=1)))
    store.update_source("weibo", enabled=False, db_path=path)
    store.update_source("weibo", enabled=True, db_path=path)
    def count(basis):
        return sum(b["mention_count"] for b in reports.analyze_topic(path, topic="机器人", data_basis=basis, now=NOW)["trend"])
    assert count("RAW_HISTORY") == 1 and count("CURRENT_ELIGIBLE") == 0
    assert reports.generate_report(path, now=NOW, commit=False)["total"] == 0
    seed(path, NOW-timedelta(minutes=1), [("weibo", "a", "机器人新闻", 2)])
    assert count("RAW_HISTORY") == count("CURRENT_ELIGIBLE") == 1
    assert reports.generate_report(path, now=NOW, commit=False)["total"] == 1
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM intel_observations").fetchone()[0] == 2
