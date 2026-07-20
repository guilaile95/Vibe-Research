"""review_store SQLite 快照存储离线测试（tmp_path，不写仓库、不联网）。"""
from __future__ import annotations

import copy
import json
import sqlite3
from pathlib import Path

import pytest

from review_store import (
    get_daily_review_snapshot,
    get_latest_daily_review_snapshot,
    initialize_review_store,
    list_daily_review_snapshots,
    save_daily_review_snapshot,
)


def _review(**overrides) -> dict:
    base = {
        "schema_version": "daily-review-v0.1",
        "generated_at": "2026-07-21 15:30:00",
        "trade_date": "2026-07-21",
        "data_cutoff": None,
        "status": "normal",
        "warnings": ["提示：中文"],
        "data_health": {
            "components": {
                "indices": "normal",
                "breadth": "normal",
                "emotion": "normal",
            }
        },
        "market_environment": {
            "breadth": {
                "status": "normal",
                "data": {
                    "up_count": 3000,
                    "down_count": 1800,
                    "up_ratio": 0.6122,
                    "total_amount": 0,
                },
            }
        },
        "sector_rotation": {
            "industry": {
                "status": "normal",
                "data": {"top": [{"name": "半导体", "change_pct": 2.5}]},
            }
        },
        "short_term_emotion": {
            "status": "normal",
            "data": {"zt_count": 80, "dt_count": 0},
        },
        "capital_activity": {
            "total_amount": 0.0,
            "amount_top": None,
        },
    }
    base.update(overrides)
    return base


def _count(db_path: Path) -> int:
    conn = sqlite3.connect(str(db_path))
    try:
        return conn.execute("SELECT COUNT(*) FROM daily_review_snapshots").fetchone()[0]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 1. 初始化幂等
# ---------------------------------------------------------------------------

def test_initialize_idempotent(tmp_path):
    db = tmp_path / "review.db"
    initialize_review_store(db)
    initialize_review_store(db)
    conn = sqlite3.connect(str(db))
    try:
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='daily_review_snapshots'"
        ).fetchall()
        assert len(tables) == 1
        idxs = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()
        }
        assert "idx_daily_review_snapshots_trade_date" in idxs
        assert "idx_daily_review_snapshots_generated_at" in idxs
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 2. 父目录创建
# ---------------------------------------------------------------------------

def test_creates_parent_directories(tmp_path):
    db = tmp_path / "nested" / "a" / "b" / "store.db"
    assert not db.parent.exists()
    initialize_review_store(db)
    assert db.parent.is_dir()
    assert db.exists()


# ---------------------------------------------------------------------------
# 3–4. 保存与按 ID 读取
# ---------------------------------------------------------------------------

def test_save_and_get_by_id(tmp_path):
    db = tmp_path / "r.db"
    review = _review()
    result = save_daily_review_snapshot(review, db)
    assert result["inserted"] is True
    assert isinstance(result["id"], int) and result["id"] >= 1
    assert result["trade_date"] == "2026-07-21"
    assert result["schema_version"] == "daily-review-v0.1"
    assert result["generated_at"] == "2026-07-21 15:30:00"
    assert result["status"] == "normal"
    assert result["payload_hash"]
    assert result["created_at"]

    loaded = get_daily_review_snapshot(result["id"], db)
    assert loaded is not None
    assert loaded["id"] == result["id"]
    assert loaded["trade_date"] == review["trade_date"]
    assert loaded["schema_version"] == review["schema_version"]
    assert loaded["generated_at"] == review["generated_at"]
    assert loaded["data_cutoff"] is None
    assert loaded["status"] == "normal"
    assert loaded["payload_hash"] == result["payload_hash"]
    assert "review" in loaded
    assert "payload_json" not in loaded
    assert loaded["review"]["warnings"] == ["提示：中文"]
    assert loaded["review"] == review


# ---------------------------------------------------------------------------
# 5. 重复内容去重（仅 generated_at 变化）
# ---------------------------------------------------------------------------

def test_dedupe_ignores_generated_at(tmp_path):
    db = tmp_path / "r.db"
    r1 = _review(generated_at="2026-07-21 15:00:00")
    r2 = _review(generated_at="2026-07-21 16:00:00")
    a = save_daily_review_snapshot(r1, db)
    b = save_daily_review_snapshot(r2, db)
    assert a["inserted"] is True
    assert b["inserted"] is False
    assert b["id"] == a["id"]
    assert _count(db) == 1


# ---------------------------------------------------------------------------
# 6. 内容变化 → 新快照
# ---------------------------------------------------------------------------

def test_content_change_inserts_new(tmp_path):
    db = tmp_path / "r.db"
    a = save_daily_review_snapshot(_review(status="normal"), db)
    b = save_daily_review_snapshot(
        _review(status="partial", warnings=["[概念板块] timeout"]),
        db,
    )
    assert b["inserted"] is True
    assert b["id"] != a["id"]
    assert _count(db) == 2

    c = save_daily_review_snapshot(
        _review(
            status="normal",
            market_environment={
                "breadth": {
                    "status": "normal",
                    "data": {"up_count": 100, "down_count": 4000, "up_ratio": 0.02},
                }
            },
        ),
        db,
    )
    assert c["inserted"] is True
    assert _count(db) == 3


# ---------------------------------------------------------------------------
# 7. 不同交易日
# ---------------------------------------------------------------------------

def test_different_trade_dates_are_separate(tmp_path):
    db = tmp_path / "r.db"
    a = save_daily_review_snapshot(_review(trade_date="2026-07-21"), db)
    b = save_daily_review_snapshot(
        _review(trade_date="2026-07-22", generated_at="2026-07-22 15:00:00"),
        db,
    )
    assert a["id"] != b["id"]
    assert _count(db) == 2


# ---------------------------------------------------------------------------
# 8. 最新快照（同日）
# ---------------------------------------------------------------------------

def test_latest_by_trade_date(tmp_path):
    db = tmp_path / "r.db"
    save_daily_review_snapshot(
        _review(generated_at="2026-07-21 10:00:00", warnings=["old"]),
        db,
    )
    newer = save_daily_review_snapshot(
        _review(generated_at="2026-07-21 16:00:00", warnings=["new"]),
        db,
    )
    latest = get_latest_daily_review_snapshot(db, trade_date="2026-07-21")
    assert latest is not None
    assert latest["id"] == newer["id"]
    assert latest["review"]["warnings"] == ["new"]


# ---------------------------------------------------------------------------
# 9. 全库最新（交易日优先）
# ---------------------------------------------------------------------------

def test_latest_global_prefers_newer_trade_date(tmp_path):
    db = tmp_path / "r.db"
    save_daily_review_snapshot(
        _review(trade_date="2026-07-20", generated_at="2026-07-20 18:00:00"),
        db,
    )
    late = save_daily_review_snapshot(
        _review(trade_date="2026-07-22", generated_at="2026-07-22 09:00:00"),
        db,
    )
    save_daily_review_snapshot(
        _review(trade_date="2026-07-21", generated_at="2026-07-21 23:00:00"),
        db,
    )
    latest = get_latest_daily_review_snapshot(db)
    assert latest is not None
    assert latest["id"] == late["id"]
    assert latest["trade_date"] == "2026-07-22"


# ---------------------------------------------------------------------------
# 10–13. 列表排序、分页、无 review、日期筛选
# ---------------------------------------------------------------------------

def test_list_sort_pagination_and_filter(tmp_path):
    db = tmp_path / "r.db"
    # 同日两条（内容不同）+ 另一日
    save_daily_review_snapshot(
        _review(trade_date="2026-07-20", generated_at="2026-07-20 10:00:00", warnings=["a"]),
        db,
    )
    save_daily_review_snapshot(
        _review(trade_date="2026-07-21", generated_at="2026-07-21 10:00:00", warnings=["b1"]),
        db,
    )
    save_daily_review_snapshot(
        _review(trade_date="2026-07-21", generated_at="2026-07-21 12:00:00", warnings=["b2"]),
        db,
    )
    save_daily_review_snapshot(
        _review(trade_date="2026-07-22", generated_at="2026-07-22 09:00:00", warnings=["c"]),
        db,
    )

    all_rows = list_daily_review_snapshots(db, limit=30, offset=0)
    assert len(all_rows) == 4
    dates = [r["trade_date"] for r in all_rows]
    assert dates == sorted(dates, reverse=True)
    # 同日 generated_at 倒序
    day21 = [r for r in all_rows if r["trade_date"] == "2026-07-21"]
    assert day21[0]["generated_at"] >= day21[1]["generated_at"]

    for item in all_rows:
        assert "review" not in item
        assert "payload_json" not in item
        assert "payload_hash" in item

    page = list_daily_review_snapshots(db, limit=2, offset=1)
    assert len(page) == 2
    assert page[0]["id"] == all_rows[1]["id"]

    filtered = list_daily_review_snapshots(db, trade_date="2026-07-21")
    assert len(filtered) == 2
    assert all(r["trade_date"] == "2026-07-21" for r in filtered)


# ---------------------------------------------------------------------------
# 14. 无记录
# ---------------------------------------------------------------------------

def test_empty_store(tmp_path):
    db = tmp_path / "empty.db"
    initialize_review_store(db)
    assert get_daily_review_snapshot(1, db) is None
    assert get_latest_daily_review_snapshot(db) is None
    assert get_latest_daily_review_snapshot(db, trade_date="2026-07-21") is None
    assert list_daily_review_snapshots(db) == []


# ---------------------------------------------------------------------------
# 15–16. 非法类型与字段
# ---------------------------------------------------------------------------

def test_review_must_be_dict(tmp_path):
    db = tmp_path / "r.db"
    with pytest.raises(TypeError, match="review 必须是字典"):
        save_daily_review_snapshot([], db)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "overrides,exc,match",
    [
        ({"schema_version": None}, ValueError, "schema_version"),
        ({}, ValueError, "schema_version"),  # 删除字段
        ({"trade_date": None}, ValueError, "trade_date"),
        ({"trade_date": ""}, ValueError, "trade_date"),
        ({"trade_date": "20260721"}, ValueError, "trade_date"),
        ({"trade_date": "2026-13-01"}, ValueError, "trade_date|有效日期"),
        ({"trade_date": "2026-02-30"}, ValueError, "trade_date|有效日期"),
        ({"generated_at": "2026-07-21"}, ValueError, "generated_at"),
        ({"generated_at": "bad"}, ValueError, "generated_at"),
        ({"status": "ok"}, ValueError, "status"),
        ({"status": "NORMAL"}, ValueError, "status"),
    ],
)
def test_invalid_fields(tmp_path, overrides, exc, match):
    db = tmp_path / "r.db"
    if overrides == {} and "schema_version" not in overrides:
        # 缺失 schema_version
        review = _review()
        del review["schema_version"]
    else:
        review = _review(**overrides)
    with pytest.raises(exc, match=match):
        save_daily_review_snapshot(review, db)


def test_data_cutoff_invalid_type(tmp_path):
    db = tmp_path / "r.db"
    with pytest.raises(TypeError, match="data_cutoff"):
        save_daily_review_snapshot(_review(data_cutoff=123), db)


def test_data_cutoff_string_ok(tmp_path):
    db = tmp_path / "r.db"
    r = save_daily_review_snapshot(_review(data_cutoff="2026-07-21 15:00:00"), db)
    loaded = get_daily_review_snapshot(r["id"], db)
    assert loaded["data_cutoff"] == "2026-07-21 15:00:00"


# ---------------------------------------------------------------------------
# 17–18. 非 JSON / NaN / Inf
# ---------------------------------------------------------------------------

def test_non_json_object_rejected(tmp_path):
    db = tmp_path / "r.db"
    review = _review()
    review["bad"] = object()
    with pytest.raises(ValueError, match="JSON"):
        save_daily_review_snapshot(review, db)
    assert _count(db) == 0 if db.exists() else True
    # 确保无有效记录
    initialize_review_store(db)
    assert _count(db) == 0


def test_nan_inf_rejected(tmp_path):
    db = tmp_path / "r.db"
    for bad in (float("nan"), float("inf"), float("-inf")):
        review = _review()
        review["market_environment"] = {"x": bad}
        with pytest.raises(ValueError):
            save_daily_review_snapshot(review, db)
    initialize_review_store(db)
    assert _count(db) == 0


# ---------------------------------------------------------------------------
# 19. 输入不被修改
# ---------------------------------------------------------------------------

def test_input_not_mutated(tmp_path):
    db = tmp_path / "r.db"
    review = _review()
    before = copy.deepcopy(review)
    save_daily_review_snapshot(review, db)
    assert review == before


# ---------------------------------------------------------------------------
# 20. 真实 0 和 None 保留
# ---------------------------------------------------------------------------

def test_zero_and_none_preserved(tmp_path):
    db = tmp_path / "r.db"
    review = _review()
    review["capital_activity"] = {
        "total_amount": 0,
        "amount_valid_count": 0.0,
        "amount_top": None,
    }
    review["data_cutoff"] = None
    result = save_daily_review_snapshot(review, db)
    loaded = get_daily_review_snapshot(result["id"], db)
    assert loaded["review"]["capital_activity"]["total_amount"] == 0
    assert loaded["review"]["capital_activity"]["amount_valid_count"] == 0.0
    assert loaded["review"]["capital_activity"]["amount_top"] is None
    assert loaded["data_cutoff"] is None


# ---------------------------------------------------------------------------
# 21. 非法 snapshot_id
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad_id", [0, -1, 1.5, "1", True])
def test_invalid_snapshot_id(tmp_path, bad_id):
    db = tmp_path / "r.db"
    initialize_review_store(db)
    with pytest.raises(ValueError, match="snapshot_id"):
        get_daily_review_snapshot(bad_id, db)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 22. 非法列表参数
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("kwargs", [
    {"limit": 0},
    {"limit": 101},
    {"offset": -1},
])
def test_invalid_list_params(tmp_path, kwargs):
    db = tmp_path / "r.db"
    initialize_review_store(db)
    with pytest.raises(ValueError):
        list_daily_review_snapshots(db, **kwargs)


# ---------------------------------------------------------------------------
# 23. 参数化 / 注入式非法日期不破坏结构
# ---------------------------------------------------------------------------

def test_sql_injection_like_date_rejected(tmp_path):
    db = tmp_path / "r.db"
    save_daily_review_snapshot(_review(), db)
    evil = "2026-07-21'; DROP TABLE daily_review_snapshots;--"
    with pytest.raises(ValueError, match="trade_date"):
        save_daily_review_snapshot(_review(trade_date=evil), db)
    with pytest.raises(ValueError, match="trade_date"):
        list_daily_review_snapshots(db, trade_date=evil)
    with pytest.raises(ValueError, match="trade_date"):
        get_latest_daily_review_snapshot(db, trade_date=evil)
    # 表仍在且原记录在
    assert _count(db) == 1
    conn = sqlite3.connect(str(db))
    try:
        name = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='daily_review_snapshots'"
        ).fetchone()
        assert name is not None
    finally:
        conn.close()


def test_memory_db_no_directory(tmp_path):
    """:memory: 可初始化且不尝试创建文件系统目录。"""
    initialize_review_store(":memory:")
    # 同连接内 schema+写入在 save 中完成（:memory: 跨连接不共享）
    r = save_daily_review_snapshot(_review(), ":memory:")
    assert r["inserted"] is True
    assert r["id"] >= 1


def test_missing_schema_version_explicit(tmp_path):
    db = tmp_path / "r.db"
    review = _review()
    del review["schema_version"]
    with pytest.raises(ValueError, match="schema_version"):
        save_daily_review_snapshot(review, db)
