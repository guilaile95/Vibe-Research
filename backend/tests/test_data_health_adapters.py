"""11 个 Adapter 只读测试。"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import data_health_adapters as adapters
import data_health_event_store as store
import data_health_service as svc
import evidence_thesis_store as et_store


def _snapshot_fs(root: Path) -> dict:
    """目录/文件集合 + size + mtime。"""
    files = {}
    dirs = set()
    if not root.exists():
        return {"dirs": dirs, "files": files}
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = os.path.relpath(dirpath, root)
        dirs.add(rel_dir)
        for fn in filenames:
            fp = Path(dirpath) / fn
            rel = os.path.relpath(fp, root)
            st = fp.stat()
            files[rel] = (st.st_size, st.st_mtime_ns)
    return {"dirs": dirs, "files": files}


def _sqlite_tables(db_path: Path) -> set[str]:
    if not db_path.exists():
        return set()
    uri = f"{db_path.resolve().as_uri()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        return {r[0] for r in rows}
    finally:
        conn.close()


@pytest.fixture()
def data_env(tmp_path, monkeypatch):
    monkeypatch.setenv("VR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("VR_REPORTS_DIR", str(tmp_path / "myreports"))
    monkeypatch.setenv("VIBE_RESEARCH_EVIDENCE_THESIS_DB", str(tmp_path / "evidence_thesis.db"))
    monkeypatch.setenv("VIBE_RESEARCH_NEWS_RADAR_CACHE", str(tmp_path / "radar.json"))
    import portfolio as pf
    monkeypatch.setattr(pf, "PF_FILE", str(tmp_path / "portfolio.json"))
    monkeypatch.setattr(pf, "CACHE_DIR", str(tmp_path))
    import watchlist_store as wl
    monkeypatch.setattr(wl, "_CACHE_DIR", str(tmp_path))
    import myreports
    monkeypatch.setattr(myreports, "REPORTS_DIR", tmp_path / "myreports")
    adapters.reset_adapters_for_tests()
    return tmp_path


def test_all_not_initialized(data_env):
    now = datetime(2026, 7, 28, 4, 0, tzinfo=timezone.utc)
    items = adapters.collect_all_records(now_utc=now)
    assert len(items) == 11
    for it in items:
        assert set(it.keys()) >= {
            "source_id", "module", "display_name", "status", "is_stale",
            "blocks_advice", "block_reason",
        }
        assert it["blocks_advice"] is False or it["source_id"] == "portfolio_advice_gate"
        if it["source_id"] != "portfolio_advice_gate":
            assert it["blocks_advice"] is False
            assert it["block_reason"] is None


def test_readonly_no_side_effects(data_env):
    root = data_env
    before = _snapshot_fs(root)
    # also ensure no event file created
    adapters.get_health_overview()
    after = _snapshot_fs(root)
    assert before == after
    assert not (root / "data_health_events.json").exists()


def test_daily_review_from_disk(data_env, monkeypatch):
    import daily_review_cache as drc
    review = {
        "status": "normal",
        "trade_date": "2026-07-25",
        "generated_at": "2026-07-25 16:00",
        "data_health": {"components": {"indices": "normal", "breadth": "normal"}},
    }
    assert drc.save_latest_review(review, saved_at="2026-07-25T08:00:00+00:00")
    # clear memory cache
    import daily_review as dr
    dr._review_cache.clear()
    now = datetime(2026, 7, 28, 8, 0, tzinfo=timezone.utc)
    rec = adapters.DailyReviewAdapter().read(adapters.HealthReadContext(now_utc=now))
    assert rec["status"] == "normal"
    assert rec["is_cached"] is True
    assert rec["data_trade_date"] == "2026-07-25"


def test_daily_review_missing(data_env):
    rec = adapters.DailyReviewAdapter().read(
        adapters.HealthReadContext(now_utc=datetime.now(timezone.utc))
    )
    assert rec["last_error_code"] == "SOURCE_NOT_INITIALIZED"


def test_event_adapters_partial_stale_null_coverage(data_env):
    frozen = datetime(2026, 7, 20, 0, 0, tzinfo=timezone.utc)
    store.record_partial("quotes", now=frozen)
    store.record_success("announcements", now=frozen)
    events = store.load_events_readonly()
    # 2026-07-28 03:00 UTC = 北京 11:00，处于 A 股交易时段
    ctx = adapters.HealthReadContext(
        now_utc=datetime(2026, 7, 28, 3, 0, tzinfo=timezone.utc),
        events=events,
    )
    q = adapters.QuotesAdapter().read(ctx)
    assert q["status"] == "partial"
    assert q["is_degraded"] is False
    assert q["coverage_current"] is None
    assert q["coverage_expected"] is None
    assert q["is_stale"] is True
    # announcements continuous 86400
    a = adapters.AnnouncementsAdapter().read(ctx)
    assert a["status"] == "normal"
    assert a["is_stale"] is True
    assert a["is_cached"] is None  # 无 cache 证明


def test_gate_block_semantics(data_env):
    frozen = datetime.now(timezone.utc)
    store.record_gate_blocked("HOLDING_QUOTES_UNAVAILABLE", now=frozen)
    events = store.load_events_readonly()
    ctx = adapters.HealthReadContext(now_utc=frozen, events=events)
    rec = adapters.PortfolioAdviceGateAdapter().read(ctx)
    assert rec["status"] == "normal"
    assert rec["blocks_advice"] is True
    assert rec["last_error_code"] == "HOLDING_QUOTES_UNAVAILABLE"
    assert rec["block_reason"]


def test_gate_not_evaluated(data_env):
    ctx = adapters.HealthReadContext(now_utc=datetime.now(timezone.utc), events={})
    rec = adapters.PortfolioAdviceGateAdapter().read(ctx)
    assert rec["status"] == "unavailable"
    assert rec["last_error_code"] == "SOURCE_NOT_INITIALIZED"
    assert rec["blocks_advice"] is False


def test_gate_runtime_failure(data_env):
    store.record_gate_failure("SOURCE_TIMEOUT")
    events = store.load_events_readonly()
    rec = adapters.PortfolioAdviceGateAdapter().read(
        adapters.HealthReadContext(now_utc=datetime.now(timezone.utc), events=events)
    )
    assert rec["status"] == "unavailable"
    assert rec["blocks_advice"] is False


def test_news_radar_stale(data_env, monkeypatch):
    cache_file = data_env / "radar.json"
    old = (datetime.now(timezone.utc) - timedelta(days=3)).astimezone(
        timezone(timedelta(hours=8))
    ).strftime("%Y-%m-%d %H:%M")
    payload = {
        "generated_at": old,
        "recent_days": 7,
        "industries": [{"key": "x", "name": "x", "items": []}],
        "stats": {"industries": 1, "total_sources": 10, "failed_sources": 2},
    }
    cache_file.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setenv("VIBE_RESEARCH_NEWS_RADAR_CACHE", str(cache_file))
    rec = adapters.NewsRadarAdapter().read(
        adapters.HealthReadContext(now_utc=datetime.now(timezone.utc))
    )
    assert rec["status"] == "partial"
    assert rec["is_stale"] is True
    assert rec["is_cached"] is True


def test_news_radar_missing(data_env, monkeypatch):
    monkeypatch.setenv(
        "VIBE_RESEARCH_NEWS_RADAR_CACHE", str(data_env / "nope" / "radar.json")
    )
    rec = adapters.NewsRadarAdapter().read(
        adapters.HealthReadContext(now_utc=datetime.now(timezone.utc))
    )
    assert rec["last_error_code"] == "SOURCE_NOT_INITIALIZED"


def test_my_reports_empty_index(data_env):
    import myreports
    # re-bind paths already via env; create empty index
    myreports.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    idx = myreports._index_path()
    idx.write_text("[]", encoding="utf-8")
    rec = adapters.MyReportsAdapter().read(
        adapters.HealthReadContext(now_utc=datetime.now(timezone.utc))
    )
    assert rec["status"] == "normal"
    assert rec["coverage_current"] == 0


def test_my_reports_corrupted(data_env):
    import myreports
    myreports.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    myreports._index_path().write_text("{bad", encoding="utf-8")
    rec = adapters.MyReportsAdapter().read(
        adapters.HealthReadContext(now_utc=datetime.now(timezone.utc))
    )
    assert rec["last_error_code"] == "SOURCE_CORRUPTED"


def test_watchlist_portfolio_not_init(data_env, monkeypatch):
    import portfolio as pf
    monkeypatch.setattr(pf, "PF_FILE", str(data_env / "portfolio.json"))
    import watchlist_store as wl
    monkeypatch.setattr(wl, "_CACHE_DIR", str(data_env))
    rec = adapters.WatchlistPortfolioStorageAdapter().read(
        adapters.HealthReadContext(now_utc=datetime.now(timezone.utc))
    )
    assert rec["last_error_code"] == "SOURCE_NOT_INITIALIZED"


def test_watchlist_valid_empty_portfolio_file(data_env, monkeypatch):
    import portfolio as pf
    pf_path = data_env / "portfolio.json"
    pf_path.write_text(json.dumps({"holdings": [], "last_refresh": None}), encoding="utf-8")
    monkeypatch.setattr(pf, "PF_FILE", str(pf_path))
    import watchlist_store as wl
    monkeypatch.setattr(wl, "_CACHE_DIR", str(data_env))
    # watchlist missing → partial (one valid one missing)
    rec = adapters.WatchlistPortfolioStorageAdapter().read(
        adapters.HealthReadContext(now_utc=datetime.now(timezone.utc))
    )
    assert rec["status"] == "partial"


def test_evidence_ledger_not_init(data_env):
    rec = adapters.EvidenceLedgerAdapter().read(
        adapters.HealthReadContext(now_utc=datetime.now(timezone.utc))
    )
    assert rec["last_error_code"] == "SOURCE_NOT_INITIALIZED"


def test_evidence_ledger_empty_db_readonly(data_env):
    db = data_env / "evidence_thesis.db"
    et_store.initialize_store(db)
    tables_before = _sqlite_tables(db)
    snap = db.stat()
    rec = adapters.EvidenceLedgerAdapter().read(
        adapters.HealthReadContext(now_utc=datetime.now(timezone.utc))
    )
    assert rec["status"] == "normal"
    assert rec["coverage_current"] == 0
    assert _sqlite_tables(db) == tables_before
    assert db.stat().st_size == snap.st_size
    assert db.stat().st_mtime_ns == snap.st_mtime_ns


def test_corrupted_events_only_affect_event_sources(data_env, monkeypatch):
    monkeypatch.setenv(
        "VIBE_RESEARCH_NEWS_RADAR_CACHE", str(data_env / "no-radar.json")
    )
    path = Path(store.events_path())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("NOTJSON", encoding="utf-8")
    # write a daily review so one direct adapter works
    import daily_review_cache as drc
    import daily_review as dr
    dr._review_cache.clear()
    drc.save_latest_review(
        {
            "status": "normal",
            "trade_date": "2026-07-25",
            "generated_at": "2026-07-25 16:00",
            "data_health": {"components": {"indices": "normal"}},
        },
        saved_at="2026-07-25T08:00:00+00:00",
    )
    items = adapters.collect_all_records()
    by_id = {it["source_id"]: it for it in items}
    assert by_id["daily_review"]["status"] == "normal"
    assert by_id["quotes"]["last_error_code"] == "SOURCE_CORRUPTED"
    assert by_id["portfolio_advice_gate"]["last_error_code"] == "SOURCE_CORRUPTED"


def test_only_gate_sets_blocks_advice(data_env):
    store.record_failure("quotes", "SOURCE_UNAVAILABLE")
    store.record_partial("portfolio_quotes")
    items = adapters.collect_all_records()
    for it in items:
        if it["source_id"] != "portfolio_advice_gate":
            assert it["blocks_advice"] is False
            assert it["block_reason"] is None


def test_utc_conversion_beijing_generated_at(data_env, monkeypatch):
    cache_file = data_env / "radar.json"
    cache_file.write_text(
        json.dumps({
            "generated_at": "2026-07-28 12:00",
            "industries": [],
            "stats": {"total_sources": 1, "failed_sources": 0},
        }),
        encoding="utf-8",
    )
    monkeypatch.setenv("VIBE_RESEARCH_NEWS_RADAR_CACHE", str(cache_file))
    rec = adapters.NewsRadarAdapter().read(
        adapters.HealthReadContext(now_utc=datetime(2026, 7, 28, 4, 30, tzinfo=timezone.utc))
    )
    assert rec["observed_at"] is not None
    assert rec["observed_at"].endswith("Z")
    # 12:00 BJ = 04:00 UTC
    assert rec["observed_at"].startswith("2026-07-28T04:00:00")


def test_my_reports_partial_coverage(data_env, monkeypatch):
    import myreports
    myreports.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    # 合法 index 两条，仅一条文件存在
    entries = [
        {
            "id": "r1",
            "name": "a.pdf",
            "ext": ".pdf",
            "size": 1,
            "ts": 1,
            "industry": "",
            "title": "A",
            "institution": "",
            "publish_date": "",
            "sector_keys": [],
            "source_url": "",
            "source_kind": "",
            "file_sha256": "a" * 64,
            "imported_at": "2026-07-28T01:00:00+00:00",
            "source_provider": "",
            "external_id": "",
            "info_code": "",
            "report_scope": "",
            "report_type": "",
        },
        {
            "id": "r2",
            "name": "b.pdf",
            "ext": ".pdf",
            "size": 1,
            "ts": 2,
            "industry": "",
            "title": "B",
            "institution": "",
            "publish_date": "",
            "sector_keys": [],
            "source_url": "",
            "source_kind": "",
            "file_sha256": "b" * 64,
            "imported_at": "2026-07-28T02:00:00+00:00",
            "source_provider": "",
            "external_id": "",
            "info_code": "",
            "report_scope": "",
            "report_type": "",
        },
    ]
    # use strict schema via direct write if validate is strict - write via module
    (myreports.REPORTS_DIR / "r1.pdf").write_bytes(b"%PDF-1.4")
    myreports._index_path().write_text(
        json.dumps(entries, ensure_ascii=False), encoding="utf-8"
    )
    rec = adapters.MyReportsAdapter().read(
        adapters.HealthReadContext(now_utc=datetime.now(timezone.utc))
    )
    assert rec["status"] == "partial"
    assert rec["coverage_expected"] == 2
    assert rec["coverage_current"] == 1


def test_evidence_ledger_mtime_strict(data_env):
    db = data_env / "evidence_thesis.db"
    et_store.initialize_store(db)
    tables_before = _sqlite_tables(db)
    snap = db.stat()
    rec = adapters.EvidenceLedgerAdapter().read(
        adapters.HealthReadContext(now_utc=datetime.now(timezone.utc))
    )
    assert rec["status"] == "normal"
    assert _sqlite_tables(db) == tables_before
    assert db.stat().st_size == snap.st_size
    assert db.stat().st_mtime_ns == snap.st_mtime_ns
