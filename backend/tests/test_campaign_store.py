"""Campaign Store v0.1 专项测试（P0-S2A，全部确定性 Mock，不联网）。

覆盖：身份持久化 / 重启可恢复 / duplicate 显式冲突不覆盖 / 非法 strategy/status
fail-closed（不自动转 DRAFT）/ 非法 code/ID/时间戳 / 确定性排序与过滤 /
schema 损坏 / 行损坏 / 无关表 fail-closed / import 零副作用 / 原子创建。
"""
from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import uuid

import pytest

import campaign_store
from campaign_store import (
    CampaignAlreadyExistsError,
    CampaignStoreCorruptedError,
    CampaignStoreInputError,
    create_campaign,
    get_campaign,
    list_campaigns,
)

_TS = "2026-08-01T03:04:05.123456Z"


def _id() -> str:
    return f"campaign_{uuid.uuid4().hex}"


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    path = tmp_path / "campaigns.sqlite3"
    monkeypatch.setenv("VIBE_RESEARCH_CAMPAIGN_DB", str(path))
    return path


def _create(**kw) -> dict:
    defaults = {
        "campaign_id": _id(),
        "security_code": "600519",
        "strategy": "SHORT",
        "status": "DRAFT",
        "created_at": _TS,
    }
    defaults.update(kw)
    return create_campaign(**defaults)


# ---------------------------------------------------------------------------
# A. Identity
# ---------------------------------------------------------------------------
def test_create_get_roundtrip(db_path):
    rec = _create()
    assert rec["campaign_id"].startswith("campaign_")
    got = get_campaign(rec["campaign_id"])
    assert got == rec
    assert set(got) == {"campaign_id", "security_code", "strategy", "status", "created_at"}


def test_create_all_three_strategies(db_path):
    for strategy in ("SHORT", "SWING", "MEDIUM"):
        rec = _create(strategy=strategy)
        assert get_campaign(rec["campaign_id"])["strategy"] == strategy


def test_restart_reopen_persistence(db_path):
    """重启/reopen store → Campaign 仍存在（每次调用独立连接 + 文件落盘）。"""
    rec = _create()
    assert db_path.is_file()
    # 独立的新连接再次读取
    assert get_campaign(rec["campaign_id"]) == rec
    # 与 campaign 域无关的新 Python 进程也能读到（真·restart-safe）
    code = (
        "import os, sys; sys.path.insert(0, r'"
        + os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        + "');"
        "import campaign_store;"
        "r = campaign_store.get_campaign(%r);"
        "print('OK', r is not None)" % rec["campaign_id"]
    )
    env = dict(os.environ, VIBE_RESEARCH_CAMPAIGN_DB=str(db_path))
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, env=env
    )
    assert out.returncode == 0, out.stderr
    assert "OK True" in out.stdout


# ---------------------------------------------------------------------------
# B. Strategy Boundary（store 层）
# ---------------------------------------------------------------------------
def test_invalid_strategy_fail_closed(db_path):
    with pytest.raises(CampaignStoreInputError):
        _create(strategy="MEDIUM2")
    assert list_campaigns() == []


def test_lowercase_strategy_not_normalized(db_path):
    with pytest.raises(CampaignStoreInputError):
        _create(strategy="short")
    assert list_campaigns() == []


def test_db_check_rejects_invalid_strategy(db_path):
    """DB 层 CHECK 约束独立生效：绕过 API 直插非法 strategy 也会被拒绝。"""
    _create()
    with sqlite3.connect(str(db_path)) as raw:
        with pytest.raises(sqlite3.IntegrityError):
            raw.execute(
                "INSERT INTO campaigns VALUES (?, '600519', 'BOGUS', 'DRAFT', ?)",
                (_id(), _TS),
            )


# ---------------------------------------------------------------------------
# C. Multi-Campaign
# ---------------------------------------------------------------------------
def test_same_security_different_strategies_coexist(db_path):
    a = _create(security_code="600519", strategy="MEDIUM")
    b = _create(security_code="600519", strategy="SWING")
    assert a["campaign_id"] != b["campaign_id"]
    assert get_campaign(a["campaign_id"]) == a
    assert get_campaign(b["campaign_id"]) == b


def test_same_security_same_strategy_two_ids(db_path):
    a = _create(security_code="600519", strategy="SWING")
    b = _create(security_code="600519", strategy="SWING")
    assert a["campaign_id"] != b["campaign_id"]
    assert get_campaign(a["campaign_id"]) == a  # 第一条记录字节级不变
    assert get_campaign(b["campaign_id"]) == b


# ---------------------------------------------------------------------------
# D. Status
# ---------------------------------------------------------------------------
def test_create_status_draft(db_path):
    assert _create()["status"] == "DRAFT"


def test_store_accepts_other_frozen_statuses(db_path):
    """存储层持久化任意合法冻结状态（生命周期迁移由后续 Slice 控制）。"""
    rec = _create(status="ACTIVE")
    assert get_campaign(rec["campaign_id"])["status"] == "ACTIVE"


def test_invalid_status_fail_closed_no_auto_draft(db_path):
    with pytest.raises(CampaignStoreInputError):
        _create(status="ACTIVE2")
    with pytest.raises(CampaignStoreInputError):
        _create(status="DRAFT2")
    assert list_campaigns() == []  # 不自动转 DRAFT 落库


# ---------------------------------------------------------------------------
# 输入校验（store 层）
# ---------------------------------------------------------------------------
def test_invalid_security_code_fail_closed(db_path):
    for bad in ("12345", "abcdef", "6005191"):
        with pytest.raises(CampaignStoreInputError):
            _create(security_code=bad)
    assert list_campaigns() == []


def test_security_code_whitespace_stripped(db_path):
    """代码两侧空白属正常 hygiene（strip 后校验），与 strategy 的语义不同。"""
    rec = _create(security_code=" 600519 ")
    assert get_campaign(rec["campaign_id"])["security_code"] == "600519"


def test_invalid_campaign_id_fail_closed(db_path):
    for bad in ("", "campaign_xyz", "abc", "campaign_123"):
        with pytest.raises(CampaignStoreInputError):
            _create(campaign_id=bad)
    assert list_campaigns() == []


def test_invalid_created_at_fail_closed(db_path):
    for bad in ("2026-08-01 03:04:05", "garbage", "2026-13-99T00:00:00.000000Z"):
        with pytest.raises(CampaignStoreInputError):
            _create(created_at=bad)
    assert list_campaigns() == []


# ---------------------------------------------------------------------------
# E. Query
# ---------------------------------------------------------------------------
def test_get_unknown_returns_none(db_path):
    assert get_campaign(_id()) is None


def test_list_deterministic_order_created_at_asc(db_path):
    _create(created_at="2026-08-01T00:00:00.000000Z")
    _create(created_at="2026-08-02T00:00:00.000000Z")
    _create(created_at="2026-08-03T00:00:00.000000Z")
    dates = [r["created_at"] for r in list_campaigns()]
    assert dates == sorted(dates)


def test_list_deterministic_order_campaign_id_tiebreak(db_path):
    """created_at 相同 → campaign_id ASC 全序，保证确定性。"""
    ids = [_id() for _ in range(3)]
    for cid in ids:
        _create(campaign_id=cid, created_at="2026-08-01T00:00:00.000000Z")
    got = [r["campaign_id"] for r in list_campaigns()]
    assert got == sorted(ids)


def test_list_filters(db_path):
    _create(security_code="600519", strategy="MEDIUM", status="ACTIVE")
    _create(security_code="600519", strategy="SWING", status="DRAFT")
    _create(security_code="000001", strategy="SHORT", status="DRAFT")
    assert {r["strategy"] for r in list_campaigns(security_code="600519")} == {
        "MEDIUM", "SWING",
    }
    assert [r["security_code"] for r in list_campaigns(strategy="SHORT")] == ["000001"]
    assert len(list_campaigns(status="DRAFT")) == 2
    assert len(list_campaigns(security_code="600519", strategy="SWING")) == 1
    assert list_campaigns(security_code="999999") == []


def test_list_invalid_filter_fail_closed(db_path):
    for kw in ({"security_code": "123"}, {"strategy": "SHORT2"}, {"status": "ACTIVE2"}):
        with pytest.raises(CampaignStoreInputError):
            list_campaigns(**kw)


# ---------------------------------------------------------------------------
# F. Storage Safety
# ---------------------------------------------------------------------------
def test_duplicate_campaign_id_explicit_conflict_no_overwrite(db_path):
    rec = _create()
    with pytest.raises(CampaignAlreadyExistsError):
        create_campaign(
            campaign_id=rec["campaign_id"],
            security_code="000001",
            strategy="MEDIUM",
            status="ACTIVE",
            created_at="2026-08-02T00:00:00.000000Z",
        )
    assert get_campaign(rec["campaign_id"]) == rec  # 未被覆盖
    assert len(list_campaigns()) == 1  # 无 half record


def test_atomic_create_failure_leaves_no_half_record(db_path):
    """事务失败 → 无部分行（duplicate 路径验证行数不变）。"""
    rec = _create()
    try:
        _create(campaign_id=rec["campaign_id"])
    except CampaignAlreadyExistsError:
        pass
    rows = list_campaigns()
    assert len(rows) == 1 and rows[0] == rec


def test_corrupted_schema_fail_closed(db_path):
    _create()
    with sqlite3.connect(str(db_path)) as raw:
        raw.execute("DROP TABLE campaigns")
    with pytest.raises(CampaignStoreCorruptedError):
        _create()
    with pytest.raises(CampaignStoreCorruptedError):
        list_campaigns()


def test_wrong_schema_version_fail_closed(db_path):
    _create()
    with sqlite3.connect(str(db_path)) as raw:
        raw.execute(
            "UPDATE schema_meta SET value = 'campaign-store.v9.9' WHERE key = 'schema_version'"
        )
    with pytest.raises(CampaignStoreCorruptedError):
        _create()
    with pytest.raises(CampaignStoreCorruptedError):
        list_campaigns()


def test_unrelated_table_fail_closed(db_path):
    """库内存在无关表 → 不初始化、不迁移，直接 fail-closed。"""
    raw_path = str(db_path)
    parent = os.path.dirname(raw_path)
    os.makedirs(parent, exist_ok=True)
    with sqlite3.connect(raw_path) as raw:
        raw.execute("CREATE TABLE unrelated (x TEXT)")
    with pytest.raises(CampaignStoreCorruptedError):
        _create()


def test_corrupted_row_fail_closed(db_path):
    """行数据不可信（created_at 非法）→ 读取 fail-closed，不解释为空。"""
    rec = _create()
    with sqlite3.connect(str(db_path)) as raw:
        raw.execute(
            "UPDATE campaigns SET created_at = 'garbage' WHERE campaign_id = ?",
            (rec["campaign_id"],),
        )
    with pytest.raises(CampaignStoreCorruptedError):
        get_campaign(rec["campaign_id"])
    with pytest.raises(CampaignStoreCorruptedError):
        list_campaigns()


def test_import_has_no_filesystem_side_effect(tmp_path, monkeypatch):
    """模块 import 不创建目录/文件；只有写操作才建库。"""
    target = tmp_path / "sub" / "campaigns.sqlite3"
    env = dict(os.environ, VIBE_RESEARCH_CAMPAIGN_DB=str(target))
    code = (
        "import os, sys;"
        "sys.path.insert(0, r'"
        + os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        + "');"
        "import campaign_store;"
        "print('EXISTS', os.path.exists(r'%s'))" % str(target)
    )
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, env=env
    )
    assert out.returncode == 0, out.stderr
    assert "EXISTS False" in out.stdout  # import 后文件仍未创建
