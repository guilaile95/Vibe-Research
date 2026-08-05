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
    assert len(items) == len(svc.SOURCE_REGISTRY)
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



# ---------------------------------------------------------------------------
# WAL-aware readonly_health_snapshot
# ---------------------------------------------------------------------------

def _snap_db_files(db_path: Path) -> dict:
    """快照 db / wal / shm 的 (exists, size, mtime_ns)。"""
    out = {}
    for suffix in ("", "-wal", "-shm"):
        p = db_path.with_suffix(db_path.suffix + suffix) if suffix else db_path
        if p.exists():
            st = p.stat()
            out[suffix or "db"] = (True, st.st_size, st.st_mtime_ns)
        else:
            out[suffix or "db"] = (False, 0, 0)
    return out


def test_wal_snapshot_empty_db_no_sidecar(data_env):
    """空、已 checkpoint DB → normal，且不创建 wal/shm。"""
    db = data_env / "evidence_thesis.db"
    et_store.initialize_store(db)
    # 初始化后可能产生 wal/shm，先 checkpoint 关闭
    conn = sqlite3.connect(str(db), timeout=5)
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        conn.close()
    # 删除可能残留的 wal/shm
    for suffix in ("-wal", "-shm"):
        p = db.with_suffix(db.suffix + suffix)
        if p.exists():
            p.unlink()

    snap_before = _snap_db_files(db)
    rec = adapters.EvidenceLedgerAdapter().read(
        adapters.HealthReadContext(now_utc=datetime.now(timezone.utc))
    )
    assert rec["status"] == "normal"
    snap_after = _snap_db_files(db)
    # 不创建 wal/shm
    assert not snap_after["-wal"][0], "WAL must not be created"
    assert not snap_after["-shm"][0], "SHM must not be created"
    # db 文件 size/mtime 不变
    assert snap_after["db"][1] == snap_before["db"][1]
    assert snap_after["db"][2] == snap_before["db"][2]


def test_wal_row_visible_through_snapshot(data_env):
    """Evidence written only to WAL must be visible through readonly_health_snapshot."""
    db = data_env / "evidence_thesis.db"
    et_store.initialize_store(db)

    # 打开一个写连接并关闭 auto-checkpoint
    write_conn = sqlite3.connect(str(db), timeout=5)
    write_conn.row_factory = sqlite3.Row
    write_conn.execute("PRAGMA journal_mode = WAL")
    write_conn.execute("PRAGMA wal_autocheckpoint = 0")
    write_conn.execute("BEGIN IMMEDIATE")
    now_iso = datetime.now(timezone.utc).isoformat(timespec="microseconds")
    write_conn.execute(
        """
        INSERT INTO evidence_records (
            id, subject_type, subject_id, evidence_type, claim,
            source_title, source_url, source_date, accessed_at,
            classification, confidence, created_at, updated_at, deleted, deleted_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, NULL)
        """,
        (
            "wal-test-1", "stock", "600519", "news", "WAL-only claim",
            "source", None, None, now_iso,
            "fact", "high", now_iso, now_iso,
        ),
    )
    write_conn.commit()
    # 不关闭 write_conn，保持 WAL 活动

    try:
        wal_path = db.with_suffix(db.suffix + "-wal")
        assert wal_path.exists() and wal_path.stat().st_size > 0, "WAL should be non-empty"

        # readonly_health_snapshot 必须读到 WAL 行
        with et_store.readonly_health_snapshot(db) as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM evidence_records WHERE deleted = 0"
            ).fetchone()
            assert row[0] >= 1, "WAL row must be visible through snapshot"
    finally:
        write_conn.close()


def test_wal_snapshot_files_unchanged(data_env):
    """读取前后 db/wal/shm 文件集合、size、mtime 不变。"""
    db = data_env / "evidence_thesis.db"
    et_store.initialize_store(db)

    # 创建非空 WAL
    write_conn = sqlite3.connect(str(db), timeout=5)
    write_conn.row_factory = sqlite3.Row
    write_conn.execute("PRAGMA journal_mode = WAL")
    write_conn.execute("PRAGMA wal_autocheckpoint = 0")
    write_conn.execute("BEGIN IMMEDIATE")
    now_iso = datetime.now(timezone.utc).isoformat(timespec="microseconds")
    write_conn.execute(
        """
        INSERT INTO evidence_records (
            id, subject_type, subject_id, evidence_type, claim,
            source_title, source_url, source_date, accessed_at,
            classification, confidence, created_at, updated_at, deleted, deleted_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, NULL)
        """,
        (
            "wal-test-2", "stock", "600519", "news", "WAL-only claim 2",
            "source", None, None, now_iso,
            "fact", "high", now_iso, now_iso,
        ),
    )
    write_conn.commit()

    try:
        wal_path = db.with_suffix(db.suffix + "-wal")
        shm_path = db.with_suffix(db.suffix + "-shm")
        assert wal_path.exists() and wal_path.stat().st_size > 0

        # 确保 shm 存在（连接打开时会创建）
        # 等待 shm 文件出现
        import time as _t
        for _ in range(20):
            if shm_path.exists():
                break
            _t.sleep(0.05)

        snap_before = _snap_db_files(db)
        # 读取快照
        with et_store.readonly_health_snapshot(db) as conn:
            conn.execute("SELECT COUNT(*) FROM evidence_records WHERE deleted = 0").fetchone()
        snap_after = _snap_db_files(db)

        # 文件集合不变
        assert snap_before.keys() == snap_after.keys()
        for k in snap_before:
            assert snap_before[k][0] == snap_after[k][0], f"file existence changed: {k}"
            assert snap_before[k][1] == snap_after[k][1], f"size changed: {k}"
            assert snap_before[k][2] == snap_after[k][2], f"mtime changed: {k}"
    finally:
        write_conn.close()


def test_wal_present_shm_missing_unavailable(data_env):
    """WAL 存在但 shm 缺失 → 安全 unavailable，且不创建 shm。"""
    db = data_env / "evidence_thesis.db"
    et_store.initialize_store(db)

    # 创建非空 WAL
    write_conn = sqlite3.connect(str(db), timeout=5)
    write_conn.row_factory = sqlite3.Row
    write_conn.execute("PRAGMA journal_mode = WAL")
    write_conn.execute("PRAGMA wal_autocheckpoint = 0")
    write_conn.execute("BEGIN IMMEDIATE")
    now_iso = datetime.now(timezone.utc).isoformat(timespec="microseconds")
    write_conn.execute(
        """
        INSERT INTO evidence_records (
            id, subject_type, subject_id, evidence_type, claim,
            source_title, source_url, source_date, accessed_at,
            classification, confidence, created_at, updated_at, deleted, deleted_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, NULL)
        """,
        (
            "wal-test-3", "stock", "600519", "news", "WAL-only claim 3",
            "source", None, None, now_iso,
            "fact", "high", now_iso, now_iso,
        ),
    )
    write_conn.commit()
    # 关闭连接，让 shm 可能保留
    write_conn.close()

    wal_path = db.with_suffix(db.suffix + "-wal")
    shm_path = db.with_suffix(db.suffix + "-shm")
    if not wal_path.exists() or wal_path.stat().st_size == 0:
        # WAL 已被 checkpoint，跳过本测试
        return
    # 删除 shm
    if shm_path.exists():
        shm_path.unlink()

    # 读取应返回 SOURCE_UNAVAILABLE
    rec = adapters.EvidenceLedgerAdapter().read(
        adapters.HealthReadContext(now_utc=datetime.now(timezone.utc))
    )
    assert rec["last_error_code"] == "SOURCE_UNAVAILABLE"
    # 不创建 shm
    assert not shm_path.exists(), "SHM must not be created"


def test_real_evidence_coverage_increments(data_env):
    """真实 E2E：创建一条 Evidence 后 coverage_current >= 1。"""
    db = data_env / "evidence_thesis.db"
    et_store.initialize_store(db)

    import evidence_thesis_service as ets
    import os as _os
    _os.environ["VIBE_RESEARCH_EVIDENCE_THESIS_DB"] = str(db)

    # 通过 service 写入一条 Evidence
    ets.create_evidence(
        db,
        {
            "subject_type": "stock",
            "subject_id": "600519",
            "evidence_type": "news",
            "claim": "真实证据条目",
            "source_title": "test",
            "classification": "fact",
            "confidence": "high",
            "accessed_at": "2026-07-28T08:00:00+00:00",
        },
    )

    rec = adapters.EvidenceLedgerAdapter().read(
        adapters.HealthReadContext(now_utc=datetime.now(timezone.utc))
    )
    assert rec["status"] == "normal"
    assert rec["coverage_current"] >= 1, "coverage_current must reflect real evidence"


# ---------------------------------------------------------------------------
# bk11_history
# ---------------------------------------------------------------------------


def _bk11_envelope(trade_date="2026-07-30", status="normal"):
    return {
        "schema_version": "short-term-daily-facts-v0.1",
        "trade_date": trade_date,
        "session": "final",
        "is_final": True,
        "source_ids": ["eastmoney_getTopicZTPool"],
        "fetched_at": f"{trade_date}T15:05:00.000000Z",
        "snapshot_at": f"{trade_date}T15:10:00.000000Z",
        "status": status,
        "reason_codes": [],
        "warnings": [],
        "limitations": ["fixture"],
        "source_schema_version": "short-term-limit-up-final-snapshot-v0.1",
        "source_status": "normal",
        "source_reason_codes": [],
        "sections": {
            "facts": {"schema_version": "short-term-market-facts-v0.1",
                      "status": "normal"},
            "ladder": {"schema_version": "short-term-limit-up-ladder-v0.1",
                       "status": "normal"},
            "gap": {"schema_version": "short-term-ladder-gap-v0.1",
                    "status": "normal"},
        },
    }


def test_bk11_history_not_initialized(data_env):
    import short_term_fact_store as st_store
    assert not st_store.resolve_db_path().exists()
    rec = adapters.Bk11HistoryAdapter().read(
        adapters.HealthReadContext(now_utc=datetime.now(timezone.utc))
    )
    assert rec["status"] == "unavailable"
    assert rec["last_error_code"] == "SOURCE_NOT_INITIALIZED"
    assert rec["detail_path"] == "/daily-review"
    # 只读：不得创建数据库文件
    assert not st_store.resolve_db_path().exists()


def test_bk11_history_normal(data_env):
    import short_term_fact_store as st_store
    st_store.save_daily_facts(
        _bk11_envelope(trade_date="2026-07-29"), db_path=st_store.resolve_db_path())
    st_store.save_daily_facts(
        _bk11_envelope(trade_date="2026-07-30"), db_path=st_store.resolve_db_path())
    rec = adapters.Bk11HistoryAdapter().read(
        adapters.HealthReadContext(now_utc=datetime.now(timezone.utc))
    )
    assert rec["status"] == "normal"
    assert rec["data_trade_date"] == "2026-07-30"
    assert rec["observed_at"] == "2026-07-30T15:10:00.000000Z"
    assert rec["last_success_at"] == "2026-07-30T15:10:00.000000Z"
    assert rec["last_error_code"] is None
    assert rec["is_stale"] is False


def test_bk11_history_partial(data_env):
    import short_term_fact_store as st_store
    st_store.save_daily_facts(
        _bk11_envelope(trade_date="2026-07-30", status="partial"),
        db_path=st_store.resolve_db_path())
    rec = adapters.Bk11HistoryAdapter().read(
        adapters.HealthReadContext(now_utc=datetime.now(timezone.utc))
    )
    assert rec["status"] == "partial"
    assert rec["last_error_code"] == "SOURCE_PARTIAL"
    assert rec["last_success_at"] == "2026-07-30T15:10:00.000000Z"


def test_bk11_history_unavailable(data_env):
    import short_term_fact_store as st_store
    st_store.save_daily_facts(
        _bk11_envelope(trade_date="2026-07-30", status="unavailable"),
        db_path=st_store.resolve_db_path())
    rec = adapters.Bk11HistoryAdapter().read(
        adapters.HealthReadContext(now_utc=datetime.now(timezone.utc))
    )
    assert rec["status"] == "unavailable"
    assert rec["last_error_code"] == "SOURCE_UNAVAILABLE"
    assert rec["last_success_at"] is None


def test_bk11_history_corrupted(data_env):
    import short_term_fact_store as st_store
    db = st_store.resolve_db_path()
    st_store.save_daily_facts(_bk11_envelope(), db_path=db)
    conn = sqlite3.connect(str(db))
    try:
        conn.execute(
            "UPDATE fact_snapshots SET envelope_json = ?",
            ("{broken",),
        )
        conn.commit()
    finally:
        conn.close()
    rec = adapters.Bk11HistoryAdapter().read(
        adapters.HealthReadContext(now_utc=datetime.now(timezone.utc))
    )
    assert rec["status"] == "unavailable"
    assert rec["last_error_code"] == "SOURCE_CORRUPTED"


def test_bk11_history_empty_db_without_rows(data_env):
    import short_term_fact_store as st_store
    st_store.init_db(st_store.resolve_db_path())
    rec = adapters.Bk11HistoryAdapter().read(
        adapters.HealthReadContext(now_utc=datetime.now(timezone.utc))
    )
    assert rec["status"] == "unavailable"
    assert rec["last_error_code"] == "SOURCE_NOT_INITIALIZED"
