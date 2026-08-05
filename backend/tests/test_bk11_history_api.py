"""BK-11 短线市场历史只读 API 测试。"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

sys.path.insert(0, "backend")

import short_term_fact_store as store  # noqa: E402


def _envelope(trade_date="2026-07-30", status="normal"):
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
            "facts": {
                "schema_version": "short-term-market-facts-v0.1",
                "status": "normal",
                "facts": {
                    "advance_count": 100,
                    "limit_up_count": 10,
                },
            },
            "ladder": {
                "schema_version": "short-term-limit-up-ladder-v0.1",
                "status": "normal",
                "metrics": {"max_boards": 6, "lianban_count": 3,
                            "ladder": [{"boards": 2, "count": 8}]},
            },
            "gap": {
                "schema_version": "short-term-ladder-gap-v0.1",
                "status": "normal",
                "metrics": {"gap_level_count": 1, "gap_segment_count": 1,
                            "largest_gap_width": 2, "first_gap_board": 4,
                            "is_continuous": False},
            },
        },
    }


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("VR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("VR_REPORTS_DIR", str(tmp_path / "myreports"))
    monkeypatch.setenv(
        "VIBE_RESEARCH_EVIDENCE_THESIS_DB", str(tmp_path / "evidence_thesis.db"))
    monkeypatch.setenv(
        "VIBE_RESEARCH_NEWS_RADAR_CACHE", str(tmp_path / "radar.json"))
    from fastapi.testclient import TestClient
    import app as app_mod
    return TestClient(app_mod.app), tmp_path


def _snapshot_fs(root: Path) -> dict:
    files = {}
    dirs = set()
    if not root.exists():
        return {"dirs": dirs, "files": files}
    for dirpath, dirnames, filenames in os.walk(root):
        dirs.add(os.path.relpath(dirpath, root))
        for fn in filenames:
            fp = Path(dirpath) / fn
            st = fp.stat()
            files[os.path.relpath(fp, root)] = (st.st_size, st.st_mtime_ns)
    return {"dirs": dirs, "files": files}


def test_empty_store_returns_empty_without_creating_db(client):
    c, root = client
    before = _snapshot_fs(root)
    r = c.get("/api/market/bk11-history")
    assert r.status_code == 200
    body = r.json()["data"]
    assert body["status"] == "empty"
    assert body["latest"] is None
    assert body["schema_version"] == "bk11-history-query-v0.1"
    assert _snapshot_fs(root) == before
    assert not (root / "short_term_facts.sqlite3").exists()


def test_multi_day(client, tmp_path):
    c, _ = client
    db = tmp_path / "short_term_facts.sqlite3"
    for d in ("2026-07-28", "2026-07-29", "2026-07-30"):
        store.save_daily_facts(_envelope(trade_date=d), db_path=db)
    r = c.get("/api/market/bk11-history?days=5")
    assert r.status_code == 200
    body = r.json()["data"]
    assert body["status"] == "normal"
    assert body["trade_date"] == "2026-07-30"
    assert body["delta"]["previous_trade_date"] == "2026-07-29"
    assert body["summary"]["window"]["count"] == 3
    assert body["digest"]["digest_text"]
    assert len(body["snapshots"]) == 3


def test_days_zero_rejected(client):
    c, _ = client
    r = c.get("/api/market/bk11-history?days=0")
    assert r.status_code == 400


def test_days_negative_rejected(client):
    c, _ = client
    r = c.get("/api/market/bk11-history?days=-3")
    assert r.status_code == 400


def test_days_over_max_rejected(client):
    c, _ = client
    r = c.get("/api/market/bk11-history?days=61")
    assert r.status_code == 400


def test_days_non_int_rejected(client):
    c, _ = client
    r = c.get("/api/market/bk11-history?days=abc")
    assert r.status_code == 422


def test_days_bool_rejected_at_router():
    import bk11_history_router as router
    with pytest.raises(HTTPException) as exc:
        router.get_bk11_history(days=True)
    assert exc.value.status_code == 400


def test_corrupted_db_returns_200_error_without_leak(client, tmp_path):
    c, _ = client
    db = tmp_path / "short_term_facts.sqlite3"
    store.save_daily_facts(_envelope(trade_date="2026-07-30"), db_path=db)
    import sqlite3
    conn = sqlite3.connect(str(db))
    try:
        conn.execute(
            "UPDATE fact_snapshots SET envelope_json = ?",
            ("not-json-at-all",),
        )
        conn.commit()
    finally:
        conn.close()
    r = c.get("/api/market/bk11-history")
    assert r.status_code == 200
    body = r.json()["data"]
    assert body["status"] == "error"
    assert body["reason_codes"] == ["SOURCE_CORRUPTED"]
    text = r.text
    assert "Traceback" not in text
    assert "sqlite3" not in text
    assert str(tmp_path) not in text


def test_get_is_readonly(client, tmp_path):
    c, _ = client
    db = tmp_path / "short_term_facts.sqlite3"
    store.save_daily_facts(_envelope(trade_date="2026-07-30"), db_path=db)
    before_stat = db.stat()
    c.get("/api/market/bk11-history")
    c.get("/api/market/bk11-history?days=2")
    after_stat = db.stat()
    assert (after_stat.st_size, after_stat.st_mtime_ns) == (
        before_stat.st_size, before_stat.st_mtime_ns)
    assert store.load_daily_facts(
        "2026-07-30", "final", db_path=db) is not None


def test_data_health_includes_bk11_source(client, tmp_path):
    c, _ = client
    db = tmp_path / "short_term_facts.sqlite3"
    store.save_daily_facts(_envelope(trade_date="2026-07-30"), db_path=db)
    r = c.get("/api/data-health")
    assert r.status_code == 200
    items = r.json()["data"]["items"]
    by = {it["source_id"]: it for it in items}
    assert by["bk11_history"]["status"] == "normal"
    assert by["bk11_history"]["data_trade_date"] == "2026-07-30"
    assert by["bk11_history"]["display_name"] == "BK-11 短线历史"
