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
from concurrent.futures import ThreadPoolExecutor

import pytest

import campaign_store
from campaign_store import (
    CampaignAlreadyExistsError,
    CampaignNotFoundError,
    CampaignStoreCorruptedError,
    CampaignStoreInputError,
    CampaignThesisBindingConflictError,
    CampaignTransitionConflictError,
    bind_campaign_thesis,
    create_campaign,
    get_campaign,
    get_campaign_thesis_binding,
    list_campaigns,
    list_campaign_transitions,
    transition_campaign,
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


# ---------------------------------------------------------------------------
# S2B. Transition Engine（P0-S2B 冻结 graph）
# ---------------------------------------------------------------------------

def _transition(db_path, cid, expected, to, tid=None, ts=_TS):
    return transition_campaign(
        campaign_id=cid,
        expected_status=expected,
        to_status=to,
        transition_id=tid or f"campaign_transition_{uuid.uuid4().hex}",
        transitioned_at=ts,
    )


def _new_campaign(db_path, **kw) -> dict:
    return _create(**kw)


# A. Forward Transitions（graph 全正例）
@pytest.mark.parametrize(
    ("chain",),
    [
        (("DRAFT", "RESEARCHING"),),
        (("DRAFT", "REJECTED"),),
        (("DRAFT", "EXPIRED"),),
        (("RESEARCHING", "PRE-ENTRY"),),
        (("RESEARCHING", "REJECTED"),),
        (("RESEARCHING", "EXPIRED"),),
        (("PRE-ENTRY", "ACTIVE"),),
        (("PRE-ENTRY", "REJECTED"),),
        (("PRE-ENTRY", "EXPIRED"),),
        (("ACTIVE", "REDUCING"),),
        (("ACTIVE", "CLOSED"),),
        (("REDUCING", "CLOSED"),),
    ],
)
def test_forward_transition_allowed(db_path, chain):
    """冻结 graph 全部 12 条正边。"""
    rec = _new_campaign(db_path, status="DRAFT")
    # 走到 chain 的起点
    if chain[0] != "DRAFT":
        path = {
            "RESEARCHING": ("DRAFT", "RESEARCHING"),
            "PRE-ENTRY": ("DRAFT", "RESEARCHING", "PRE-ENTRY"),
            "ACTIVE": ("DRAFT", "RESEARCHING", "PRE-ENTRY", "ACTIVE"),
            "REDUCING": ("DRAFT", "RESEARCHING", "PRE-ENTRY", "ACTIVE", "REDUCING"),
        }[chain[0]]
        for s in range(len(path) - 1):
            _transition(db_path, rec["campaign_id"], path[s], path[s + 1])
    campaign, tr = _transition(db_path, rec["campaign_id"], chain[0], chain[1])
    assert campaign["status"] == chain[1]
    assert tr["from_status"] == chain[0]
    assert tr["to_status"] == chain[1]
    assert tr["campaign_id"] == rec["campaign_id"]
    assert get_campaign(rec["campaign_id"])["status"] == chain[1]


# B. Illegal / Backward
@pytest.mark.parametrize(
    ("chain",),
    [
        (("DRAFT", "ACTIVE"),),
        (("RESEARCHING", "ACTIVE"),),
        (("PRE-ENTRY", "DRAFT"),),
        (("ACTIVE", "PRE-ENTRY"),),
        (("REDUCING", "ACTIVE"),),
        (("CLOSED", "ACTIVE"),),
        (("REJECTED", "DRAFT"),),
        (("EXPIRED", "RESEARCHING"),),
    ],
)
def test_illegal_transition_rejected(db_path, chain):
    """反向/跳级 transition → explicit conflict，status 不变，无 audit。"""
    rec = _new_campaign(db_path, status=chain[0])
    with pytest.raises(CampaignTransitionConflictError):
        _transition(db_path, rec["campaign_id"], chain[0], chain[1])
    assert get_campaign(rec["campaign_id"])["status"] == chain[0]
    assert list_campaign_transitions(rec["campaign_id"]) == []


def test_same_state_transition_rejected(db_path):
    for status in ("DRAFT", "ACTIVE", "CLOSED"):
        rec = _new_campaign(db_path, status=status)
        with pytest.raises(CampaignTransitionConflictError):
            _transition(db_path, rec["campaign_id"], status, status)
        assert get_campaign(rec["campaign_id"])["status"] == status


# C. Terminal
@pytest.mark.parametrize("terminal", ["CLOSED", "REJECTED", "EXPIRED"])
def test_terminal_state_no_outgoing(db_path, terminal):
    rec = _new_campaign(db_path, status=terminal)
    for target in ("DRAFT", "RESEARCHING", "PRE-ENTRY", "ACTIVE", "REDUCING"):
        with pytest.raises(CampaignTransitionConflictError):
            _transition(db_path, rec["campaign_id"], terminal, target)
    assert list_campaign_transitions(rec["campaign_id"]) == []


# D. CAS / Concurrency
def test_expected_status_mismatch_explicit_conflict(db_path):
    rec = _new_campaign(db_path, status="DRAFT")
    _transition(db_path, rec["campaign_id"], "DRAFT", "RESEARCHING")
    with pytest.raises(CampaignTransitionConflictError):
        _transition(db_path, rec["campaign_id"], "DRAFT", "REJECTED")  # stale expected
    assert get_campaign(rec["campaign_id"])["status"] == "RESEARCHING"


def test_two_stale_writers_only_first_succeeds(db_path):
    """两个客户端都看到 DRAFT；A 成功迁移后，B 的 CAS 必须失败。"""
    rec = _new_campaign(db_path, status="DRAFT")
    _transition(db_path, rec["campaign_id"], "DRAFT", "RESEARCHING")  # A wins
    with pytest.raises(CampaignTransitionConflictError):
        _transition(db_path, rec["campaign_id"], "DRAFT", "REJECTED")  # B stale
    assert get_campaign(rec["campaign_id"])["status"] == "RESEARCHING"
    history = list_campaign_transitions(rec["campaign_id"])
    assert len(history) == 1 and history[0]["to_status"] == "RESEARCHING"


def test_concurrent_writers_exactly_one_succeeds(db_path):
    """真实并发：BEGIN IMMEDIATE 串行化 → 恰好一个成功一个 conflict。

    胜者不确定（先获得锁者胜），但结果必须确定：一成功一冲突、
    最终 status = 胜者目标、audit 恰一条。
    """
    rec = _new_campaign(db_path, status="DRAFT")
    targets = ["RESEARCHING", "REJECTED"]

    def worker(to_status):
        try:
            _transition(db_path, rec["campaign_id"], "DRAFT", to_status)
            return "ok"
        except CampaignTransitionConflictError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(worker, targets))
    assert sorted(results) == ["conflict", "ok"]  # 恰好一成功一冲突
    winner = targets[results.index("ok")]
    assert get_campaign(rec["campaign_id"])["status"] == winner
    history = list_campaign_transitions(rec["campaign_id"])
    assert len(history) == 1 and history[0]["to_status"] == winner


def test_failed_transition_produces_no_audit(db_path):
    rec = _new_campaign(db_path, status="DRAFT")
    with pytest.raises(CampaignTransitionConflictError):
        _transition(db_path, rec["campaign_id"], "DRAFT", "ACTIVE")  # 非法边
    with pytest.raises(CampaignTransitionConflictError):
        _transition(db_path, rec["campaign_id"], "ACTIVE", "RESEARCHING")  # CAS 失败
    assert list_campaign_transitions(rec["campaign_id"]) == []


def test_transition_unknown_campaign_not_found(db_path):
    with pytest.raises(CampaignNotFoundError):
        _transition(db_path, f"campaign_{uuid.uuid4().hex}", "DRAFT", "RESEARCHING")


# E. Audit
def test_audit_record_durable_and_fields(db_path):
    rec = _new_campaign(db_path, status="DRAFT")
    campaign, tr = _transition(db_path, rec["campaign_id"], "DRAFT", "RESEARCHING")
    assert tr["transition_id"].startswith("campaign_transition_")
    assert tr["from_status"] == "DRAFT" and tr["to_status"] == "RESEARCHING"
    assert tr["transitioned_at"] == _TS
    assert campaign["status"] == "RESEARCHING"


def test_audit_survives_reopen_subprocess(db_path):
    """restart / reopen 后 history 仍存在（独立进程验证）。"""
    rec = _new_campaign(db_path, status="DRAFT")
    _transition(db_path, rec["campaign_id"], "DRAFT", "RESEARCHING")
    code = (
        "import os, sys; sys.path.insert(0, r'"
        + os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        + "');"
        "import campaign_store;"
        "h = campaign_store.list_campaign_transitions(%r);"
        "print('HISTORY', len(h), h[0]['to_status'] if h else None)" % rec["campaign_id"]
    )
    env = dict(os.environ, VIBE_RESEARCH_CAMPAIGN_DB=str(db_path))
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, env=env
    )
    assert out.returncode == 0, out.stderr
    assert "HISTORY 1 RESEARCHING" in out.stdout


def test_audit_history_deterministic_order(db_path):
    rec = _new_campaign(db_path, status="DRAFT")
    _transition(db_path, rec["campaign_id"], "DRAFT", "RESEARCHING", ts="2026-08-01T00:00:00.000000Z")
    _transition(db_path, rec["campaign_id"], "RESEARCHING", "PRE-ENTRY", ts="2026-08-01T00:00:01.000000Z")
    _transition(db_path, rec["campaign_id"], "PRE-ENTRY", "ACTIVE", ts="2026-08-01T00:00:02.000000Z")
    history = list_campaign_transitions(rec["campaign_id"])
    keys = [(h["transitioned_at"], h["transition_id"]) for h in history]
    assert keys == sorted(keys)  # transitioned_at ASC, transition_id ASC 全序
    assert [h["to_status"] for h in history] == ["RESEARCHING", "PRE-ENTRY", "ACTIVE"]


def test_audit_history_tiebreak_by_transition_id(db_path):
    """transitioned_at 相同 → transition_id ASC 全序（确定性）。"""
    rec = _new_campaign(db_path, status="DRAFT")
    tid1 = f"campaign_transition_{uuid.uuid4().hex}"
    tid2 = f"campaign_transition_{uuid.uuid4().hex}"
    _transition(db_path, rec["campaign_id"], "DRAFT", "RESEARCHING", tid=tid1, ts="2026-08-01T00:00:00.000000Z")
    _transition(db_path, rec["campaign_id"], "RESEARCHING", "PRE-ENTRY", tid=tid2, ts="2026-08-01T00:00:00.000000Z")
    history = list_campaign_transitions(rec["campaign_id"])
    assert [h["transition_id"] for h in history] == sorted([tid1, tid2])


def test_second_transition_does_not_modify_first_history(db_path):
    rec = _new_campaign(db_path, status="DRAFT")
    c1, tr1 = _transition(db_path, rec["campaign_id"], "DRAFT", "RESEARCHING", ts="2026-08-01T00:00:00.000000Z")
    _transition(db_path, rec["campaign_id"], "RESEARCHING", "PRE-ENTRY", ts="2026-08-01T00:00:01.000000Z")
    history = list_campaign_transitions(rec["campaign_id"])
    assert len(history) == 2
    assert history[0] == tr1  # 第一条 audit 字节级不变


# F. Atomicity
def test_duplicate_transition_id_conflict_status_unchanged(db_path):
    """audit INSERT 失败（duplicate transition_id）→ 显式 conflict，status 不变化。"""
    rec = _new_campaign(db_path, status="DRAFT")
    tid = f"campaign_transition_{uuid.uuid4().hex}"
    _transition(db_path, rec["campaign_id"], "DRAFT", "RESEARCHING", tid=tid)
    with pytest.raises(CampaignAlreadyExistsError):
        _transition(db_path, rec["campaign_id"], "RESEARCHING", "PRE-ENTRY", tid=tid)
    assert get_campaign(rec["campaign_id"])["status"] == "RESEARCHING"  # 未推进
    assert len(list_campaign_transitions(rec["campaign_id"])) == 1  # 无 half record


def test_campaign_update_failure_rolls_back_audit(db_path):
    """（R3 #32）audit INSERT 成功后的 status UPDATE 失败 → 整个事务回滚：
    1. Campaign.status 保持原值；2. campaign_transitions 不留下刚 INSERT 的 audit；
    3. 绝不出现「audit exists + status old」的 half-transition。

    方法：在 test DB 建 test-only SQLite trigger（BEFORE UPDATE OF status 强制
    RAISE(ABORT)）。trigger 只存在于测试库，不修改 production schema。
    """
    rec = _new_campaign(db_path, status="DRAFT")
    cid = rec["campaign_id"]
    assert list_campaign_transitions(cid) == []

    # test-only trigger：任何 campaigns.status UPDATE 直接失败
    with sqlite3.connect(str(db_path)) as raw:
        raw.execute(
            "CREATE TRIGGER test_force_update_failure "
            "BEFORE UPDATE OF status ON campaigns "
            "BEGIN SELECT RAISE(ABORT, 'forced update failure for atomicity test'); END"
        )

    with pytest.raises(sqlite3.Error):  # UPDATE 被 trigger 强制失败
        _transition(db_path, cid, "DRAFT", "RESEARCHING")

    # 1. status 回滚到原值（DRAFT）
    assert get_campaign(cid)["status"] == "DRAFT"
    # 2. audit 不留下（INSERT 与 UPDATE 同事务，整体回滚）
    assert list_campaign_transitions(cid) == []
    # 3. 无 half-transition：status 与 audit 必须一致
    assert get_campaign(cid)["status"] == "DRAFT"
    assert list_campaign_transitions(cid) == []

    # trigger 移除后 store 仍可正常工作（trigger 是测试副作用，不影响后续契约）
    with sqlite3.connect(str(db_path)) as raw:
        raw.execute("DROP TRIGGER test_force_update_failure")
    campaign, tr = _transition(db_path, cid, "DRAFT", "RESEARCHING")
    assert campaign["status"] == "RESEARCHING"
    assert len(list_campaign_transitions(cid)) == 1


def test_invalid_transition_inputs_fail_closed(db_path):
    rec = _new_campaign(db_path, status="DRAFT")
    with pytest.raises(CampaignStoreInputError):
        transition_campaign(
            campaign_id=rec["campaign_id"], expected_status="DRAFT2",
            to_status="RESEARCHING", transition_id=f"campaign_transition_{uuid.uuid4().hex}",
            transitioned_at=_TS,
        )
    with pytest.raises(CampaignStoreInputError):
        transition_campaign(
            campaign_id=rec["campaign_id"], expected_status="DRAFT",
            to_status="RESEARCHING", transition_id="bad_id", transitioned_at=_TS,
        )
    with pytest.raises(CampaignStoreInputError):
        _transition(db_path, rec["campaign_id"], "DRAFT", "RESEARCHING", ts="garbage")
    assert get_campaign(rec["campaign_id"])["status"] == "DRAFT"
    assert list_campaign_transitions(rec["campaign_id"]) == []


# G. Identity / Strategy Regression
def test_transition_preserves_identity_and_strategy(db_path):
    rec = _new_campaign(db_path, security_code="600519", strategy="SWING", status="DRAFT")
    snapshot_before = dict(rec)
    campaign, _ = _transition(db_path, rec["campaign_id"], "DRAFT", "RESEARCHING")
    assert campaign["campaign_id"] == snapshot_before["campaign_id"]
    assert campaign["security_code"] == snapshot_before["security_code"]
    assert campaign["strategy"] == snapshot_before["strategy"] == "SWING"
    assert campaign["created_at"] == snapshot_before["created_at"]
    # 走完剩余合法路径后 strategy 仍不变
    for frm, to in (
        ("RESEARCHING", "PRE-ENTRY"), ("PRE-ENTRY", "ACTIVE"),
        ("ACTIVE", "REDUCING"), ("REDUCING", "CLOSED"),
    ):
        campaign, _ = _transition(db_path, rec["campaign_id"], frm, to)
        assert campaign["strategy"] == "SWING"
        assert campaign["campaign_id"] == snapshot_before["campaign_id"]
    assert campaign["status"] == "CLOSED"


def test_multi_campaign_transitions_independent(db_path):
    a = _new_campaign(db_path, security_code="600519", strategy="MEDIUM", status="DRAFT")
    b = _new_campaign(db_path, security_code="600519", strategy="SWING", status="DRAFT")
    _transition(db_path, a["campaign_id"], "DRAFT", "RESEARCHING")
    _transition(db_path, b["campaign_id"], "DRAFT", "REJECTED")
    assert get_campaign(a["campaign_id"])["status"] == "RESEARCHING"
    assert get_campaign(b["campaign_id"])["status"] == "REJECTED"
    assert len(list_campaign_transitions(a["campaign_id"])) == 1
    assert len(list_campaign_transitions(b["campaign_id"])) == 1
    assert list_campaign_transitions(a["campaign_id"])[0]["to_status"] == "RESEARCHING"


def test_list_transitions_unknown_campaign_empty(db_path):
    assert list_campaign_transitions(f"campaign_{uuid.uuid4().hex}") == []


def test_list_transitions_invalid_id_fail_closed(db_path):
    with pytest.raises(CampaignStoreInputError):
        list_campaign_transitions("abc")


# ---------------------------------------------------------------------------
# S2C. Thesis Binding（store 层）
# ---------------------------------------------------------------------------

def _thesis_id(seed: int = 0) -> str:
    return f"{seed:032x}"


def _bind(db_path, cid, tid, revision=3, strategy="SWING", ts=_TS):
    return bind_campaign_thesis(
        campaign_id=cid,
        thesis_id=tid,
        thesis_revision_at_bind=revision,
        campaign_strategy_at_bind=strategy,
        bound_at=ts,
    )


def test_binding_roundtrip(db_path):
    rec = _create(security_code="600519", strategy="SWING", status="DRAFT")
    binding = _bind(db_path, rec["campaign_id"], _thesis_id(1))
    assert binding == {
        "campaign_id": rec["campaign_id"],
        "thesis_id": _thesis_id(1),
        "thesis_revision_at_bind": 3,
        "campaign_strategy_at_bind": "SWING",
        "bound_at": _TS,
    }
    assert get_campaign_thesis_binding(rec["campaign_id"]) == binding


def test_binding_durable_reopen_subprocess(db_path):
    """restart/reopen → binding 仍存在（独立进程验证）。"""
    rec = _create(security_code="600519", strategy="SWING", status="DRAFT")
    _bind(db_path, rec["campaign_id"], _thesis_id(1))
    code = (
        "import os, sys; sys.path.insert(0, r'"
        + os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        + "');"
        "import campaign_store;"
        "b = campaign_store.get_campaign_thesis_binding(%r);"
        "print('BINDING', b is not None, b['thesis_id'] if b else None)" % rec["campaign_id"]
    )
    env = dict(os.environ, VIBE_RESEARCH_CAMPAIGN_DB=str(db_path))
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, env=env
    )
    assert out.returncode == 0, out.stderr
    assert f"BINDING True {_thesis_id(1)}" in out.stdout


def test_binding_get_unbound_returns_none(db_path):
    assert get_campaign_thesis_binding(f"campaign_{uuid.uuid4().hex}") is None


def test_binding_unknown_campaign_not_found(db_path):
    with pytest.raises(CampaignNotFoundError):
        _bind(db_path, f"campaign_{uuid.uuid4().hex}", _thesis_id(1))


def test_binding_same_campaign_second_conflict(db_path):
    rec = _create(security_code="600519", strategy="SWING", status="DRAFT")
    first = _bind(db_path, rec["campaign_id"], _thesis_id(1))
    with pytest.raises(CampaignThesisBindingConflictError):
        _bind(db_path, rec["campaign_id"], _thesis_id(2))
    assert get_campaign_thesis_binding(rec["campaign_id"]) == first  # 未覆盖


def test_binding_thesis_already_bound_elsewhere_conflict(db_path):
    a = _create(security_code="600519", strategy="SWING", status="DRAFT")
    b = _create(security_code="600519", strategy="MEDIUM", status="DRAFT")
    _bind(db_path, a["campaign_id"], _thesis_id(1))
    with pytest.raises(CampaignThesisBindingConflictError):
        _bind(db_path, b["campaign_id"], _thesis_id(1))
    assert get_campaign_thesis_binding(b["campaign_id"]) is None


def test_binding_invalid_inputs_fail_closed(db_path):
    rec = _create(security_code="600519", strategy="SWING", status="DRAFT")
    with pytest.raises(CampaignStoreInputError):
        _bind(db_path, rec["campaign_id"], "not-a-thesis-id")
    with pytest.raises(CampaignStoreInputError):
        bind_campaign_thesis(
            campaign_id=rec["campaign_id"], thesis_id=_thesis_id(1),
            thesis_revision_at_bind=0, campaign_strategy_at_bind="SWING", bound_at=_TS,
        )
    with pytest.raises(CampaignStoreInputError):
        bind_campaign_thesis(
            campaign_id=rec["campaign_id"], thesis_id=_thesis_id(1),
            thesis_revision_at_bind=-1, campaign_strategy_at_bind="SWING", bound_at=_TS,
        )
    with pytest.raises(CampaignStoreInputError):
        bind_campaign_thesis(
            campaign_id=rec["campaign_id"], thesis_id=_thesis_id(1),
            thesis_revision_at_bind=True, campaign_strategy_at_bind="SWING", bound_at=_TS,
        )
    with pytest.raises(CampaignStoreInputError):
        _bind(db_path, rec["campaign_id"], _thesis_id(1), strategy="MEDIUM2")
    with pytest.raises(CampaignStoreInputError):
        _bind(db_path, rec["campaign_id"], _thesis_id(1), ts="garbage")
    assert get_campaign_thesis_binding(rec["campaign_id"]) is None


def test_binding_concurrent_writers_exactly_one_succeeds(db_path):
    """C1 未绑定；两个 writer 同时 bind T1/T2 → 恰好一个成功，另一个 conflict。"""
    rec = _create(security_code="600519", strategy="SWING", status="DRAFT")
    tid1, tid2 = _thesis_id(1), _thesis_id(2)

    def worker(tid):
        try:
            _bind(db_path, rec["campaign_id"], tid)
            return "ok"
        except CampaignThesisBindingConflictError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(worker, [tid1, tid2]))
    assert sorted(results) == ["conflict", "ok"]
    binding = get_campaign_thesis_binding(rec["campaign_id"])
    assert binding is not None and binding["thesis_id"] in (tid1, tid2)


def test_binding_insert_failure_rolls_back(db_path):
    """binding INSERT 失败（test-only trigger RAISE ABORT）→ 无半条 binding。

    INSERT 失败被 store 映射为显式 Conflict；核心断言是回滚语义：
    不留下 binding、Campaign 无连带副作用。
    """
    rec = _create(security_code="600519", strategy="SWING", status="DRAFT")
    with sqlite3.connect(str(db_path)) as raw:
        raw.execute(
            "CREATE TRIGGER test_force_binding_insert_failure "
            "BEFORE INSERT ON campaign_thesis_bindings "
            "BEGIN SELECT RAISE(ABORT, 'forced binding insert failure'); END"
        )
    with pytest.raises(CampaignThesisBindingConflictError):
        _bind(db_path, rec["campaign_id"], _thesis_id(1))
    assert get_campaign_thesis_binding(rec["campaign_id"]) is None
    assert get_campaign(rec["campaign_id"])["status"] == "DRAFT"  # 无连带副作用


def test_binding_row_corruption_fail_closed(db_path):
    rec = _create(security_code="600519", strategy="SWING", status="DRAFT")
    _bind(db_path, rec["campaign_id"], _thesis_id(1))
    with sqlite3.connect(str(db_path)) as raw:
        raw.execute(
            "UPDATE campaign_thesis_bindings SET bound_at = 'garbage' "
            "WHERE campaign_id = ?",
            (rec["campaign_id"],),
        )
    with pytest.raises(CampaignStoreCorruptedError):
        get_campaign_thesis_binding(rec["campaign_id"])


def test_binding_table_dropped_schema_corrupted(db_path):
    _create(security_code="600519", strategy="SWING", status="DRAFT")
    with sqlite3.connect(str(db_path)) as raw:
        raw.execute("DROP TABLE campaign_thesis_bindings")
    with pytest.raises(CampaignStoreCorruptedError):
        _create()
    with pytest.raises(CampaignStoreCorruptedError):
        _bind(db_path, f"campaign_{uuid.uuid4().hex}", _thesis_id(1))


def test_store_has_no_binding_mutation_path():
    """binding 不可修改/替换/删除（store 层无任何 update/delete 路径）。"""
    for name in ("update_campaign_thesis_binding", "replace_campaign_thesis",
                 "set_current_thesis", "delete_campaign_thesis_binding"):
        assert not hasattr(campaign_store, name), f"forbidden path: {name}"
