"""Campaign 服务层 v0.1 专项测试（P0-S2A，确定性 Mock，不联网）。

覆盖：create → DRAFT / ID 稳定唯一 / 多 Campaign 并存 / Strategy 结构性不可变
（无 update 路径、无 silent normalization）/ 非法入参 fail-closed / 查询契约。
"""
from __future__ import annotations

import os
import re
import uuid

import pytest

import campaign_service
from campaign_service import (
    CampaignConflictError,
    CampaignInputError,
    CampaignNotFoundError,
    CampaignTransitionConflictError,
    create_campaign,
    get_campaign,
    list_campaigns,
    list_campaign_transitions,
    transition_campaign,
)

_ID_RE = re.compile(r"^campaign_[0-9a-f]{32}$")


@pytest.fixture(autouse=True)
def db_path(tmp_path, monkeypatch):
    path = tmp_path / "campaigns.sqlite3"
    monkeypatch.setenv("VIBE_RESEARCH_CAMPAIGN_DB", str(path))
    return path


# ---------------------------------------------------------------------------
# A. Identity
# ---------------------------------------------------------------------------
def test_create_success_all_strategies():
    for strategy in ("SHORT", "SWING", "MEDIUM"):
        rec = create_campaign("600519", strategy)
        assert _ID_RE.fullmatch(rec["campaign_id"])
        assert rec["security_code"] == "600519"
        assert rec["strategy"] == strategy
        assert rec["status"] == "DRAFT"


def test_consecutive_creates_distinct_ids():
    a = create_campaign("600519", "SHORT")
    b = create_campaign("600519", "SHORT")
    assert a["campaign_id"] != b["campaign_id"]
    assert get_campaign(a["campaign_id"]) == a
    assert get_campaign(b["campaign_id"]) == b


# ---------------------------------------------------------------------------
# B. Strategy Boundary
# ---------------------------------------------------------------------------
def test_invalid_strategy_fail_closed():
    for bad in ("MEDIUM2", "", "SHORT2", 5, None):
        with pytest.raises(CampaignInputError):
            create_campaign("600519", bad)
    assert list_campaigns() == []


def test_lowercase_strategy_not_silently_normalized():
    """仓库无统一 normalize 契约 → lowercase/typo 必须显式失败，不变成 SHORT。"""
    for bad in ("short", "swing ", "Medium"):
        with pytest.raises(CampaignInputError):
            create_campaign("600519", bad)
    assert list_campaigns() == []


def test_no_strategy_mutation_path():
    """service 层不存在任何 update/delete/patch 能力（结构性不可变）。"""
    for name in ("update_campaign", "patch_campaign", "delete_campaign",
                 "change_strategy", "set_strategy", "update_status"):
        assert not hasattr(campaign_service, name), f"forbidden path: {name}"


def test_store_no_silent_strategy_mutation():
    import campaign_store

    for name in ("update_campaign", "patch_campaign", "delete_campaign",
                 "change_strategy", "update_status"):
        assert not hasattr(campaign_store, name), f"forbidden path: {name}"


def test_invalid_security_code_fail_closed():
    for bad in ("12345", "abcdef", "6005191", "", None):
        with pytest.raises(CampaignInputError):
            create_campaign(bad, "SHORT")
    assert list_campaigns() == []


# ---------------------------------------------------------------------------
# C. Multi-Campaign
# ---------------------------------------------------------------------------
def test_same_security_different_strategies_coexist():
    a = create_campaign("600519", "MEDIUM")
    b = create_campaign("600519", "SWING")
    assert {a["strategy"], b["strategy"]} == {"MEDIUM", "SWING"}
    assert get_campaign(a["campaign_id"]) == a
    assert get_campaign(b["campaign_id"]) == b


def test_second_campaign_does_not_change_first():
    a = create_campaign("600519", "SHORT")
    before = get_campaign(a["campaign_id"])
    create_campaign("600519", "SHORT")  # 同 security 同 strategy 再建
    assert get_campaign(a["campaign_id"]) == before  # 第一条字节级不变


# ---------------------------------------------------------------------------
# D. Status
# ---------------------------------------------------------------------------
def test_create_status_is_always_draft():
    assert create_campaign("600519", "SWING")["status"] == "DRAFT"


def test_service_has_no_status_parameter():
    """create 不接受 status：客户端无法通过 service 伪造 ACTIVE/CLOSED。"""
    with pytest.raises(TypeError):
        create_campaign("600519", "SWING", status="ACTIVE")


# ---------------------------------------------------------------------------
# E. Query
# ---------------------------------------------------------------------------
def test_get_unknown_raises_not_found():
    with pytest.raises(CampaignNotFoundError):
        get_campaign(f"campaign_{uuid.uuid4().hex}")


def test_get_invalid_id_format_raises_input_error():
    for bad in ("", "abc", "campaign_xyz"):
        with pytest.raises(CampaignInputError):
            get_campaign(bad)


def test_list_deterministic_and_filters():
    create_campaign("600519", "MEDIUM")
    create_campaign("600519", "SWING")
    create_campaign("000001", "SHORT")
    recs = list_campaigns()
    # 确定性全序：created_at ASC, campaign_id ASC
    keys = [(r["created_at"], r["campaign_id"]) for r in recs]
    assert keys == sorted(keys)
    assert len(list_campaigns(security_code="600519")) == 2
    assert len(list_campaigns(strategy="SHORT")) == 1
    assert len(list_campaigns(status="DRAFT")) == 3
    assert list_campaigns(security_code="999999") == []


def test_list_invalid_filter_fail_closed():
    for kw in ({"security_code": "123"}, {"strategy": "SWING2"}, {"status": "CLOSED2"}):
        with pytest.raises(CampaignInputError):
            list_campaigns(**kw)


# ---------------------------------------------------------------------------
# 防御性冲突映射（服务端生成 ID 碰撞不应发生，但必须显式而非覆盖）
# ---------------------------------------------------------------------------
def test_conflict_is_explicit_not_overwrite(monkeypatch):
    import campaign_store as cs

    def boom(**kw):
        raise cs.CampaignAlreadyExistsError("dup")

    monkeypatch.setattr(cs, "create_campaign", boom)
    with pytest.raises(CampaignConflictError):
        create_campaign("600519", "SHORT")


# ---------------------------------------------------------------------------
# S2B. Transition（service 层）
# ---------------------------------------------------------------------------
def test_transition_success_returns_campaign_and_transition():
    rec = create_campaign("600519", "SWING")
    campaign, tr = transition_campaign(rec["campaign_id"], "DRAFT", "RESEARCHING")
    assert campaign["status"] == "RESEARCHING"
    assert campaign["strategy"] == "SWING"
    assert tr["transition_id"].startswith("campaign_transition_")
    assert tr["from_status"] == "DRAFT" and tr["to_status"] == "RESEARCHING"
    assert tr["campaign_id"] == rec["campaign_id"]


def test_pre_entry_activation_requires_trade_authority():
    """研究迁移保持 strategy；PRE-ENTRY 不能再由普通 lifecycle 激活。"""
    rec = create_campaign("600519", "SWING")
    for frm, to in (
        ("DRAFT", "RESEARCHING"), ("RESEARCHING", "PRE-ENTRY"),
    ):
        campaign, tr = transition_campaign(rec["campaign_id"], frm, to)
        assert tr["to_status"] == to
        assert campaign["strategy"] == "SWING"
    with pytest.raises(CampaignTransitionConflictError):
        transition_campaign(rec["campaign_id"], "PRE-ENTRY", "ACTIVE")
    assert get_campaign(rec["campaign_id"])["status"] == "PRE-ENTRY"
    assert get_campaign(rec["campaign_id"])["strategy"] == "SWING"


def test_transition_invalid_enum_input_error():
    rec = create_campaign("600519", "SHORT")
    for bad in ("DRAFT2", "ACTIVE2", "short"):
        with pytest.raises(CampaignInputError):
            transition_campaign(rec["campaign_id"], bad, "RESEARCHING")
        with pytest.raises(CampaignInputError):
            transition_campaign(rec["campaign_id"], "DRAFT", bad)


def test_transition_unknown_campaign_not_found():
    with pytest.raises(CampaignNotFoundError):
        transition_campaign(f"campaign_{uuid.uuid4().hex}", "DRAFT", "RESEARCHING")


def test_transition_cas_mismatch_conflict():
    rec = create_campaign("600519", "SHORT")
    transition_campaign(rec["campaign_id"], "DRAFT", "RESEARCHING")
    with pytest.raises(CampaignTransitionConflictError):
        transition_campaign(rec["campaign_id"], "DRAFT", "REJECTED")  # stale CAS
    assert get_campaign(rec["campaign_id"])["status"] == "RESEARCHING"


def test_transition_illegal_edge_conflict():
    rec = create_campaign("600519", "SHORT")
    with pytest.raises(CampaignTransitionConflictError):
        transition_campaign(rec["campaign_id"], "DRAFT", "ACTIVE")
    with pytest.raises(CampaignTransitionConflictError):
        transition_campaign(rec["campaign_id"], "DRAFT", "DRAFT")
    assert get_campaign(rec["campaign_id"])["status"] == "DRAFT"


def test_transition_terminal_conflict():
    rec = create_campaign("600519", "SHORT")
    for frm, to in (("DRAFT", "REJECTED"),):
        transition_campaign(rec["campaign_id"], frm, to)
    for target in ("DRAFT", "RESEARCHING", "ACTIVE"):
        with pytest.raises(CampaignTransitionConflictError):
            transition_campaign(rec["campaign_id"], "REJECTED", target)


def test_transition_history_service():
    rec = create_campaign("600519", "MEDIUM")
    _, tr1 = transition_campaign(rec["campaign_id"], "DRAFT", "RESEARCHING")
    _, tr2 = transition_campaign(rec["campaign_id"], "RESEARCHING", "PRE-ENTRY")
    history = list_campaign_transitions(rec["campaign_id"])
    assert [h["transition_id"] for h in history] == [tr1["transition_id"], tr2["transition_id"]]
    assert list_campaign_transitions(f"campaign_{uuid.uuid4().hex}") == []
    with pytest.raises(CampaignInputError):
        list_campaign_transitions("bad-id")


def test_service_no_generic_status_mutation_path():
    """service 层仍不存在 set_status / update / generic 写路径。"""
    for name in ("set_status", "update_campaign", "patch_campaign",
                 "delete_campaign", "generic_update"):
        assert not hasattr(campaign_service, name), f"forbidden path: {name}"
