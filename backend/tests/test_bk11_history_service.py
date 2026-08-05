"""BK-11 短线市场历史只读查询服务测试。

全部使用临时目录（tmp_path），不触碰真实 VR_DATA_DIR / 用户目录。
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, "backend")

import short_term_fact_store as store  # noqa: E402
import bk11_history_service as service  # noqa: E402


def _facts_section(limit_up_count=10, advance_count=100):
    return {
        "schema_version": "short-term-market-facts-v0.1",
        "status": "normal",
        "facts": {
            "advance_count": advance_count,
            "decline_count": 50,
            "flat_count": 20,
            "suspended_count": 3,
            "eligible_count": 173,
            "valid_count": 170,
            "up_ratio": 0.6,
            "limit_up_count": limit_up_count,
            "limit_down_count": 1,
            "failed_limit_up_count": 2,
            "touched_limit_up_count": 12,
            "sealed_limit_up_count": limit_up_count,
            "seal_rate": 0.8,
            "failed_board_rate": 0.2,
        },
    }


def _ladder_section(max_boards=6):
    return {
        "schema_version": "short-term-limit-up-ladder-v0.1",
        "status": "normal",
        "metrics": {
            "max_boards": max_boards,
            "lianban_count": 3,
            "ladder": [
                {"boards": 2, "count": 8},
                {"boards": 3, "count": 4},
                {"boards": 6, "count": 1},
            ],
        },
    }


def _gap_section(gap_levels=1):
    return {
        "schema_version": "short-term-ladder-gap-v0.1",
        "status": "normal",
        "metrics": {
            "gap_level_count": gap_levels,
            "gap_segment_count": 1,
            "largest_gap_width": 2,
            "first_gap_board": 4,
            "is_continuous": False,
        },
    }


def _envelope(
    trade_date="2026-07-30",
    session="final",
    status="normal",
    **overrides,
):
    envelope = {
        "schema_version": "short-term-daily-facts-v0.1",
        "trade_date": trade_date,
        "session": session,
        "is_final": session == "final",
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
            "facts": _facts_section(),
            "ladder": _ladder_section(),
            "gap": _gap_section(),
        },
    }
    envelope.update(overrides)
    return envelope


def _seed(db: Path, *dates: str) -> None:
    for d in dates:
        store.save_daily_facts(_envelope(trade_date=d), db_path=db)


def _snapshot_fs(root: Path) -> dict:
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


class TestQueryHistory:
    def test_db_missing_returns_empty_and_creates_nothing(self, tmp_path):
        db = tmp_path / "short_term_facts.sqlite3"
        before = _snapshot_fs(tmp_path)
        result = service.query_history(days=5, db_path=db)
        assert result["status"] == "empty"
        assert result["latest"] is None
        assert result["delta"] is None
        assert result["snapshots"] == []
        assert result["reason_codes"] == ["SOURCE_NOT_INITIALIZED"]
        assert _snapshot_fs(tmp_path) == before
        assert not db.exists()

    def test_db_exists_without_rows_returns_empty(self, tmp_path):
        db = tmp_path / "facts.sqlite3"
        store.init_db(db)
        result = service.query_history(days=5, db_path=db)
        assert result["status"] == "empty"

    def test_multi_day_normal(self, tmp_path):
        db = tmp_path / "facts.sqlite3"
        _seed(db, "2026-07-28", "2026-07-29", "2026-07-30")
        result = service.query_history(days=5, db_path=db)
        assert result["status"] == "normal"
        assert result["trade_date"] == "2026-07-30"
        assert result["data_time"] == "2026-07-30T15:10:00.000000Z"
        assert result["window"] == {"requested": 5, "snapshot_count": 3}
        assert [s["trade_date"] for s in result["snapshots"]] == [
            "2026-07-28", "2026-07-29", "2026-07-30",
        ]
        assert result["latest"]["trade_date"] == "2026-07-30"
        assert result["delta"] is not None
        assert result["delta"]["previous_trade_date"] == "2026-07-29"
        assert result["delta"]["current_trade_date"] == "2026-07-30"
        assert result["summary"]["window"]["count"] == 3
        assert result["digest"]["digest_text"]
        assert result["reason_codes"] == []

    def test_window_is_bounded_and_sorted(self, tmp_path):
        db = tmp_path / "facts.sqlite3"
        dates = [f"2026-07-{d:02d}" for d in range(20, 31)]
        _seed(db, *dates)
        result = service.query_history(days=3, db_path=db)
        assert result["window"] == {"requested": 3, "snapshot_count": 3}
        assert [s["trade_date"] for s in result["snapshots"]] == [
            "2026-07-28", "2026-07-29", "2026-07-30",
        ]
        assert result["summary"]["window"] == {
            "count": 3,
            "first_trade_date": "2026-07-28",
            "last_trade_date": "2026-07-30",
        }
        # delta 使用最近前序（不受窗口缩小影响）
        assert result["delta"]["previous_trade_date"] == "2026-07-29"

    def test_single_day_does_not_forge_delta(self, tmp_path):
        db = tmp_path / "facts.sqlite3"
        _seed(db, "2026-07-30")
        result = service.query_history(days=5, db_path=db)
        assert result["status"] == "normal"
        assert result["delta"] is None
        assert result["summary"]["window"]["count"] == 1
        assert result["digest"]["digest_text"]

    def test_partial_latest(self, tmp_path):
        db = tmp_path / "facts.sqlite3"
        store.save_daily_facts(
            _envelope(trade_date="2026-07-29"), db_path=db)
        store.save_daily_facts(
            _envelope(trade_date="2026-07-30", status="partial"),
            db_path=db,
        )
        result = service.query_history(days=5, db_path=db)
        assert result["status"] == "partial"
        assert result["reason_codes"] == ["SOURCE_PARTIAL"]
        assert "部分可用" in result["limitations"][0]

    def test_unavailable_latest(self, tmp_path):
        db = tmp_path / "facts.sqlite3"
        store.save_daily_facts(
            _envelope(trade_date="2026-07-30", status="unavailable"),
            db_path=db,
        )
        result = service.query_history(days=5, db_path=db)
        assert result["status"] == "unavailable"
        assert result["reason_codes"] == ["SOURCE_UNAVAILABLE"]

    def test_corrupted_json_fails_closed(self, tmp_path):
        db = tmp_path / "facts.sqlite3"
        _seed(db, "2026-07-29", "2026-07-30")
        conn = sqlite3.connect(str(db))
        try:
            conn.execute(
                "UPDATE fact_snapshots SET envelope_json = ? "
                "WHERE trade_date = '2026-07-30'",
                ("{not json",),
            )
            conn.commit()
        finally:
            conn.close()
        result = service.query_history(days=5, db_path=db)
        assert result["status"] == "error"
        assert result["latest"] is None
        assert result["reason_codes"] == ["SOURCE_CORRUPTED"]
        assert "Traceback" not in json.dumps(result)
        assert str(tmp_path) not in json.dumps(result)

    def test_invalid_stored_envelope_fails_closed(self, tmp_path):
        db = tmp_path / "facts.sqlite3"
        _seed(db, "2026-07-30")
        conn = sqlite3.connect(str(db))
        try:
            conn.execute(
                "UPDATE fact_snapshots SET envelope_json = ? "
                "WHERE trade_date = '2026-07-30'",
                (json.dumps({"schema_version": "short-term-daily-facts-v0.1"}),
                 ),
            )
            conn.commit()
        finally:
            conn.close()
        result = service.query_history(days=5, db_path=db)
        assert result["status"] == "error"

    def test_previous_corrupt_fails_closed(self, tmp_path):
        db = tmp_path / "facts.sqlite3"
        _seed(db, "2026-07-29", "2026-07-30")
        conn = sqlite3.connect(str(db))
        try:
            conn.execute(
                "UPDATE fact_snapshots SET envelope_json = ? "
                "WHERE trade_date = '2026-07-29'",
                ("{broken",),
            )
            conn.commit()
        finally:
            conn.close()
        result = service.query_history(days=5, db_path=db)
        assert result["status"] == "error"

    def test_query_is_readonly(self, tmp_path):
        db = tmp_path / "facts.sqlite3"
        _seed(db, "2026-07-28", "2026-07-29", "2026-07-30")
        before_stat = db.stat()
        service.query_history(days=5, db_path=db)
        service.query_history(days=2, db_path=db)
        # 主数据库文件不得被改写；数据行不变（SQLite WAL 读连接可能产生
        # -shm/-wal 边车文件，属 store 已批准读路径的运行时工件）
        after_stat = db.stat()
        assert (after_stat.st_size, after_stat.st_mtime_ns) == (
            before_stat.st_size, before_stat.st_mtime_ns)
        assert [s["trade_date"] for s in store.list_snapshots(db)] == [
            "2026-07-28", "2026-07-29", "2026-07-30",
        ]

    def test_deterministic_repeat(self, tmp_path):
        db = tmp_path / "facts.sqlite3"
        _seed(db, "2026-07-28", "2026-07-29", "2026-07-30")
        first = service.query_history(days=5, db_path=db)
        second = service.query_history(days=5, db_path=db)
        assert first == second

    def test_output_does_not_share_store_reference(self, tmp_path):
        db = tmp_path / "facts.sqlite3"
        _seed(db, "2026-07-30")
        result = service.query_history(days=5, db_path=db)
        result["latest"]["sections"]["facts"]["facts"]["limit_up_count"] = 999
        again = service.query_history(days=5, db_path=db)
        assert again["latest"]["sections"]["facts"]["facts"]["limit_up_count"] == 10

    def test_keyboard_interrupt_propagates(self, tmp_path, monkeypatch):
        db = tmp_path / "facts.sqlite3"
        _seed(db, "2026-07-30")

        def boom(*_args, **_kwargs):
            raise KeyboardInterrupt

        monkeypatch.setattr(store, "list_snapshots", boom)
        with pytest.raises(KeyboardInterrupt):
            service.query_history(days=5, db_path=db)

    def test_explicit_path_wins_over_env(self, tmp_path, monkeypatch):
        env_db = tmp_path / "env" / "short_term_facts.sqlite3"
        env_db.parent.mkdir()
        _seed(env_db, "2026-07-30")
        monkeypatch.setenv("VR_DATA_DIR", str(tmp_path / "env"))
        explicit = tmp_path / "explicit.sqlite3"
        result = service.query_history(days=5, db_path=explicit)
        assert result["status"] == "empty"
        result = service.query_history(days=5)
        assert result["status"] == "normal"
        assert result["trade_date"] == "2026-07-30"
