"""Campaign Re-entry Lineage Domain Core v0.1 专项测试。

覆盖工作单 §30 测试矩阵 + §19 hash 契约 + §28 序列化 + §27 fail-closed +
§29 纯性 + R1 独立审查 P1-A/B/C/D（strategy 链级一致 / 投影预校验 /
transition 身份绑定 / 严格 from_dict）+ 时间微秒精度 + builder history 路径 +
Campaign 契约 parity。
全部纯函数调用：不联网、不落库、不读时钟、不写用户数据。
"""
from __future__ import annotations

import inspect
import os
import subprocess
import sys

import pytest

import campaign_lineage as cl
from campaign_lineage import (
    CampaignLineageRecord,
    LineageIntegrityError,
    LineageValidationError,
    ancestors,
    build_lineage_record,
    compute_lineage_hash,
    derive_parent_closed_at,
    descendants,
    new_lineage_id,
    validate_campaign_snapshot,
    validate_lineage_set,
)

PID_A = "campaign_" + "a" * 32
PID_B = "campaign_" + "b" * 32
PID_C = "campaign_" + "c" * 32
PID_D = "campaign_" + "d" * 32
CODE = "600519"
# canonical UTC 微秒（对齐 Campaign Core `_TIMESTAMP_RE` 的 6 位精度）
T0 = "2026-07-01T00:00:00.000000Z"
T1 = "2026-07-02T00:00:00.000000Z"
T2 = "2026-07-03T00:00:00.000000Z"
T3 = "2026-07-04T00:00:00.000000Z"
CREATED = "2026-07-05T00:00:00.000000Z"
T4 = "2026-07-05T00:00:00.000000Z"


def _campaign(cid: str, status: str, strategy: str = "SHORT", code: str = CODE,
              created: str = T1) -> dict:
    return {
        "campaign_id": cid,
        "security_code": code,
        "strategy": strategy,
        "status": status,
        "created_at": created,
    }


def _closed_short_parent(cid: str = PID_A, created: str = T0, code: str = CODE,
                         strategy: str = "SHORT") -> dict:
    return _campaign(cid, "CLOSED", strategy, code, created)


def _draft_child(cid: str = PID_B, strategy: str = "SHORT", created: str = T2,
                 code: str = CODE) -> dict:
    return _campaign(cid, "DRAFT", strategy, code, created)


def _make(parent: dict | None = None, child: dict | None = None, reason: str = "重新入场",
          closed_at: str = T1, created_at: str = CREATED, lineage_id: str | None = None,
          relation: str = cl.RELATION_RE_ENTRY) -> CampaignLineageRecord:
    return build_lineage_record(
        parent_campaign=parent if parent is not None else _closed_short_parent(),
        child_campaign=child if child is not None else _draft_child(),
        parent_closed_at=closed_at,
        reason=reason,
        created_at=created_at,
        relation_type=relation,
        lineage_id=lineage_id,
    )


# ---------------------------------------------------------------------------
# §30.1-2 有效 RE_ENTRY（含 strategy 独立）
# ---------------------------------------------------------------------------

def test_closed_short_to_draft_short_valid():
    record = _make()
    assert record.relation_type == "RE_ENTRY"
    assert record.parent_strategy == "SHORT" and record.child_strategy == "SHORT"
    assert record.security_code == CODE


def test_closed_short_to_draft_medium_valid_parent_strategy_unchanged():
    record = _make(child=_draft_child(strategy="MEDIUM"))
    assert record.child_strategy == "MEDIUM"
    assert record.parent_strategy == "SHORT"  # 父策略不变（re-entry 不 mutate 父）
    assert record.parent_campaign_id == PID_A


# ---------------------------------------------------------------------------
# §30.3-6 父状态拒绝
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("status", ["ACTIVE", "REDUCING", "REJECTED", "EXPIRED",
                                    "DRAFT", "RESEARCHING", "PRE-ENTRY"])
def test_parent_non_closed_rejected(status):
    parent = _campaign(PID_A, status, "SHORT")
    with pytest.raises(LineageValidationError):
        _make(parent=parent)


# ---------------------------------------------------------------------------
# §30.7 相同 campaign id
# ---------------------------------------------------------------------------

def test_same_campaign_id_rejected():
    parent = _closed_short_parent(PID_A)
    child = _draft_child(PID_A)  # 复用父 id
    with pytest.raises(LineageValidationError):
        _make(parent=parent, child=child)


# ---------------------------------------------------------------------------
# §30.8 不同 security
# ---------------------------------------------------------------------------

def test_different_security_rejected():
    child = _draft_child(code="000001")
    with pytest.raises(LineageValidationError):
        _make(child=child)


# ---------------------------------------------------------------------------
# §30.9 child 已 ACTIVE（v0.1 拒绝）
# ---------------------------------------------------------------------------

def test_child_active_rejected_v01():
    child = _campaign(PID_B, "ACTIVE", "SHORT")
    with pytest.raises(LineageValidationError):
        _make(child=child)


def test_child_reducing_or_closed_rejected():
    for status in ("REDUCING", "CLOSED"):
        child = _campaign(PID_B, status, "SHORT")
        with pytest.raises(LineageValidationError):
            _make(child=child)


# ---------------------------------------------------------------------------
# §30.10 child 早于 parent close
# ---------------------------------------------------------------------------

def test_child_created_before_parent_closed_rejected():
    parent = _closed_short_parent(PID_A, created=T0)
    child = _draft_child(PID_B, created=T0)  # child 与 parent close 同刻
    with pytest.raises(LineageValidationError):
        _make(parent=parent, child=child, closed_at=T1)


def test_equal_timestamps_rejected_strict():
    # 严格 parent_closed_at < child_created_at：相等拒绝
    parent = _closed_short_parent(PID_A, created=T0)
    child = _draft_child(PID_B, created=T1)
    with pytest.raises(LineageValidationError):
        _make(parent=parent, child=child, closed_at=T1)


# ---------------------------------------------------------------------------
# §30.11 同 child 两父
# ---------------------------------------------------------------------------

def test_same_child_two_parents_rejected():
    r1 = _make(parent=_closed_short_parent(PID_A, created=T0),
               child=_draft_child(PID_B, created=T2), closed_at=T1)
    r2 = _make(parent=_closed_short_parent(PID_C, created=T1),
               child=_draft_child(PID_B, created=T2), closed_at=T1, reason="另一父")
    with pytest.raises(LineageIntegrityError):
        validate_lineage_set([r1, r2])


# ---------------------------------------------------------------------------
# §30.12 A→B→C 有效确定链
# ---------------------------------------------------------------------------

def test_chain_abc_valid():
    # 严格递增：A created T0 → A closed T1 → B created T2 → B closed T3 → C created T4
    r_ab = _make(parent=_closed_short_parent(PID_A, created=T0),
                 child=_draft_child(PID_B, created=T2), closed_at=T1)
    r_bc = _make(parent=_closed_short_parent(PID_B, created=T2),
                 child=_draft_child(PID_C, created=T4), closed_at=T3)
    validate_lineage_set([r_ab, r_bc])
    # C 的祖先链 = [r_ab, r_bc]（时间序 old→new）
    anc = ancestors(PID_C, [r_ab, r_bc])
    assert [r.child_campaign_id for r in anc] == [PID_B, PID_C]
    assert [r.lineage_id for r in anc] == [r_ab.lineage_id, r_bc.lineage_id]


# ---------------------------------------------------------------------------
# §30.13 A→B + B→A 环
# ---------------------------------------------------------------------------

def test_cycle_rejected():
    r_ab = _make(parent=_closed_short_parent(PID_A, created=T0),
                 child=_draft_child(PID_B, created=T2), closed_at=T1)
    r_ba = _make(parent=_closed_short_parent(PID_B, created=T2),
                 child=_draft_child(PID_A, created=T3), closed_at=T2, reason="反向")
    with pytest.raises(LineageIntegrityError):
        validate_lineage_set([r_ab, r_ba])


# ---------------------------------------------------------------------------
# §30.14 输入乱序 → 相同投影
# ---------------------------------------------------------------------------

def test_input_order_independent_projection():
    r_ab = _make(parent=_closed_short_parent(PID_A, created=T0),
                 child=_draft_child(PID_B, created=T2), closed_at=T1)
    r_bc = _make(parent=_closed_short_parent(PID_B, created=T2),
                 child=_draft_child(PID_C, created=T4), closed_at=T3)
    asc = ancestors(PID_C, [r_ab, r_bc])
    shuffled = ancestors(PID_C, [r_bc, r_ab])
    assert [r.lineage_id for r in asc] == [r.lineage_id for r in shuffled]
    assert [r.child_campaign_id for r in asc] == [PID_B, PID_C]


# ---------------------------------------------------------------------------
# §30.15 hash 篡改
# ---------------------------------------------------------------------------

def test_hash_tamper_rejected():
    record = _make()
    tampered = record.to_dict()
    tampered["lineage_hash"] = "0" * 64
    with pytest.raises(LineageIntegrityError):
        CampaignLineageRecord.from_dict(tampered)


def test_semantic_field_change_changes_hash():
    r1 = _make(reason="原因A")
    r2 = _make(reason="原因B")
    assert r1.lineage_hash != r2.lineage_hash  # 受保护语义改变 → hash 改变


def test_lineage_id_and_created_at_not_in_hash():
    r1 = _make(lineage_id="lineage_" + "1" * 32, created_at=T1)
    r2 = _make(lineage_id="lineage_" + "2" * 32, created_at=T2)
    assert r1.lineage_hash == r2.lineage_hash  # 审计元数据不参与 hash


# ---------------------------------------------------------------------------
# §30.16 未知 schema
# ---------------------------------------------------------------------------

def test_unknown_schema_rejected():
    record = _make()
    data = record.to_dict()
    data["schema_version"] = "campaign_lineage.v9.9"
    with pytest.raises(LineageValidationError):
        CampaignLineageRecord.from_dict(data)


# ---------------------------------------------------------------------------
# §19 hash 契约 / §28 序列化 round-trip
# ---------------------------------------------------------------------------

def test_hash_deterministic():
    r1 = _make()
    r2 = _make()
    assert r1.lineage_hash == r2.lineage_hash
    assert len(r1.lineage_hash) == 64


def test_to_dict_from_dict_round_trip():
    record = _make()
    restored = CampaignLineageRecord.from_dict(record.to_dict())
    assert restored == record
    assert restored.lineage_hash == record.lineage_hash


def test_from_dict_rejects_unknown_and_missing_fields():
    record = _make().to_dict()
    with pytest.raises(LineageValidationError):
        CampaignLineageRecord.from_dict({**record, "bogus": 1})
    for key in ("lineage_id", "relation_type", "parent_campaign_id", "security_code",
                "parent_strategy", "child_strategy", "parent_closed_at",
                "child_created_at", "reason", "schema_version", "lineage_hash"):
        with pytest.raises(LineageValidationError):
            CampaignLineageRecord.from_dict({k: v for k, v in record.items() if k != key})


# ---------------------------------------------------------------------------
# §15 父 CLOSED 时间推导（transition 历史）
# ---------------------------------------------------------------------------

def _transitions(*steps: tuple[str, str, str], campaign_id: str = PID_A) -> list[dict]:
    return [{"transition_id": f"campaign_transition_{i:032x}", "campaign_id": campaign_id,
             "from_status": frm, "to_status": to, "transitioned_at": at}
            for i, (frm, to, at) in enumerate(steps)]


def test_derive_parent_closed_at_from_history():
    history = _transitions(("DRAFT", "RESEARCHING", T0), ("RESEARCHING", "PRE-ENTRY", T0),
                           ("PRE-ENTRY", "ACTIVE", T1), ("ACTIVE", "REDUCING", T1),
                           ("REDUCING", "CLOSED", T1))
    assert derive_parent_closed_at(PID_A, history) == T1


def test_derive_parent_closed_at_not_closed_returns_none():
    history = _transitions(("DRAFT", "RESEARCHING", T0), ("RESEARCHING", "PRE-ENTRY", T0))
    assert derive_parent_closed_at(PID_A, history) is None  # 未到 CLOSED → fail closed


def test_derive_parent_closed_at_rejected_expired_returns_none():
    history = _transitions(("DRAFT", "REJECTED", T0))
    assert derive_parent_closed_at(PID_A, history) is None


def test_derive_parent_closed_at_invalid_history_returns_none():
    # 非法推进（DRAFT→CLOSED 不在 graph）
    history = _transitions(("DRAFT", "CLOSED", T0))
    assert derive_parent_closed_at(PID_A, history) is None
    # 非连续推进
    history2 = _transitions(("DRAFT", "RESEARCHING", T0), ("ACTIVE", "CLOSED", T1))
    assert derive_parent_closed_at(PID_A, history2) is None


def test_derive_parent_closed_at_input_not_mutated():
    history = _transitions(("DRAFT", "RESEARCHING", T0), ("RESEARCHING", "PRE-ENTRY", T0),
                           ("PRE-ENTRY", "ACTIVE", T1), ("ACTIVE", "REDUCING", T1),
                           ("REDUCING", "CLOSED", T1))
    before = [dict(t) for t in history]
    derive_parent_closed_at(PID_A, history)
    assert history == before  # 输入不可变


# ---------------------------------------------------------------------------
# P1-C：derive 绑定 parent 身份 + transition_id 校验 + (time, id) 确定性排序
# ---------------------------------------------------------------------------

def test_derive_wrong_campaign_id_rejected():
    history = _transitions(("DRAFT", "RESEARCHING", T0), ("RESEARCHING", "PRE-ENTRY", T0),
                           ("PRE-ENTRY", "ACTIVE", T1), ("ACTIVE", "REDUCING", T1),
                           ("REDUCING", "CLOSED", T1), campaign_id=PID_B)  # 别的 Campaign
    assert derive_parent_closed_at(PID_A, history) is None


def test_derive_mixed_campaign_ids_rejected():
    history = _transitions(("DRAFT", "RESEARCHING", T0), ("RESEARCHING", "PRE-ENTRY", T0),
                           ("PRE-ENTRY", "ACTIVE", T1), ("ACTIVE", "REDUCING", T1),
                           ("REDUCING", "CLOSED", T1))
    history[2]["campaign_id"] = PID_B  # 混入其它 Campaign 的 transition
    assert derive_parent_closed_at(PID_A, history) is None


def test_derive_duplicate_transition_id_rejected():
    history = _transitions(("DRAFT", "RESEARCHING", T0), ("RESEARCHING", "PRE-ENTRY", T0),
                           ("PRE-ENTRY", "ACTIVE", T1), ("ACTIVE", "REDUCING", T1),
                           ("REDUCING", "CLOSED", T1))
    history[1]["transition_id"] = history[0]["transition_id"]  # 重复 id
    assert derive_parent_closed_at(PID_A, history) is None


def test_derive_invalid_transition_id_shape_rejected():
    history = _transitions(("DRAFT", "RESEARCHING", T0), ("RESEARCHING", "PRE-ENTRY", T0),
                           ("PRE-ENTRY", "ACTIVE", T1), ("ACTIVE", "REDUCING", T1),
                           ("REDUCING", "CLOSED", T1))
    history[0]["transition_id"] = "not-canonical"
    assert derive_parent_closed_at(PID_A, history) is None


def test_derive_equal_timestamps_shuffled_input_identical():
    """同 transitioned_at、不同 transition_id：按 (time, id) 确定性排序，输入顺序无关。

    transition_id 字典序 = 合法推进顺序（id0..id4）；输入乱序后结果必须一致。
    """
    close_t = "2026-07-02T10:00:00.000000Z"
    steps = [
        ("DRAFT", "RESEARCHING", "2026-07-01T09:00:00.000000Z", "campaign_transition_" + "0" * 31 + "0"),
        ("RESEARCHING", "PRE-ENTRY", close_t, "campaign_transition_" + "0" * 31 + "1"),
        ("PRE-ENTRY", "ACTIVE", close_t, "campaign_transition_" + "0" * 31 + "2"),
        ("ACTIVE", "REDUCING", close_t, "campaign_transition_" + "0" * 31 + "3"),
        ("REDUCING", "CLOSED", close_t, "campaign_transition_" + "0" * 31 + "4"),
    ]
    ordered = [{"transition_id": tid, "campaign_id": PID_A, "from_status": frm,
                "to_status": to, "transitioned_at": at} for frm, to, at, tid in steps]
    shuffled = list(reversed([dict(t) for t in ordered]))
    assert derive_parent_closed_at(PID_A, ordered) == close_t
    assert derive_parent_closed_at(PID_A, shuffled) == close_t  # 顺序无关
    assert derive_parent_closed_at(PID_A, ordered) == derive_parent_closed_at(PID_A, shuffled)


# ---------------------------------------------------------------------------
# §21-23 链级规则：self-edge / 重复冲突 / 多子 / security 跨链 / 时间倒转
# ---------------------------------------------------------------------------

def test_self_edge_rejected():
    record = _make()
    bad = CampaignLineageRecord(
        lineage_id="lineage_" + "1" * 32,
        relation_type="RE_ENTRY",
        parent_campaign_id=PID_A,
        child_campaign_id=PID_A,
        security_code=CODE,
        parent_strategy="SHORT",
        child_strategy="SHORT",
        parent_closed_at=T1,
        child_created_at=T2,
        reason="自环",
        created_at=CREATED,
        schema_version=cl.SCHEMA_VERSION,
        lineage_hash="",
    )
    with pytest.raises(LineageValidationError):
        validate_lineage_set([record, bad])


def test_duplicate_conflicting_edge_rejected():
    r1 = _make()
    r2 = _make(reason="同边不同 reason")  # 同 (parent,child)，语义不同
    with pytest.raises(LineageIntegrityError):
        validate_lineage_set([r1, r2])


def test_multiple_children_allowed():
    r_ab = _make(parent=_closed_short_parent(PID_A, created=T0),
                 child=_draft_child(PID_B, created=T2), closed_at=T1)
    r_ac = _make(parent=_closed_short_parent(PID_A, created=T0),
                 child=_draft_child(PID_C, created=T3), closed_at=T1, reason="另一轮")
    validate_lineage_set([r_ab, r_ac])  # 同父多子（不同子 Campaign）合法


def test_cross_chain_security_mismatch_rejected():
    """两条记录各自同 security，但共享 Campaign B 的 security 跨链不一致 → 链级拒绝。"""
    r_ab = _make(parent=_closed_short_parent(PID_A, created=T0, code="600519"),
                 child=_draft_child(PID_B, created=T2, code="600519"), closed_at=T1)
    r_bc = _make(parent=_closed_short_parent(PID_B, created=T1, code="000001"),
                 child=_draft_child(PID_C, created=T3, code="000001"), closed_at=T2,
                 reason="错 security")
    with pytest.raises(LineageIntegrityError):
        validate_lineage_set([r_ab, r_bc])


def test_timestamp_inversion_rejected():
    # child_created_at < parent_closed_at 的直接记录（构造绕过 builder 校验 → from_dict 必须拒绝）
    bad = {
        "lineage_id": "lineage_" + "1" * 32,
        "relation_type": "RE_ENTRY",
        "parent_campaign_id": PID_A,
        "child_campaign_id": PID_B,
        "security_code": CODE,
        "parent_strategy": "SHORT",
        "child_strategy": "SHORT",
        "parent_closed_at": T2,   # close 晚于 child
        "child_created_at": T1,
        "reason": "时间倒转",
        "created_at": CREATED,
        "schema_version": cl.SCHEMA_VERSION,
        "lineage_hash": "",
    }
    with pytest.raises(LineageValidationError):
        CampaignLineageRecord.from_dict(bad)


# ---------------------------------------------------------------------------
# §24-25 投影（ancestors / descendants）
# ---------------------------------------------------------------------------

def test_descendants_projection():
    r_ab = _make(parent=_closed_short_parent(PID_A, created=T0),
                 child=_draft_child(PID_B, created=T2), closed_at=T1)
    r_bc = _make(parent=_closed_short_parent(PID_B, created=T2),
                 child=_draft_child(PID_C, created=T4), closed_at=T3)
    desc = descendants(PID_A, [r_ab, r_bc])
    assert [r.child_campaign_id for r in desc] == [PID_B, PID_C]


def test_ancestors_root_empty():
    assert ancestors(PID_A, []) == []


def test_invalid_campaign_id_in_projection():
    with pytest.raises(LineageValidationError):
        ancestors("not-a-campaign", [])


# ---------------------------------------------------------------------------
# §27 fail-closed：字段缺失 / bool 冒充 / 未知枚举 / 非法 code / NaN
# ---------------------------------------------------------------------------

def test_campaign_mapping_missing_field_rejected():
    parent = _closed_short_parent()
    del parent["status"]
    with pytest.raises(LineageValidationError):
        _make(parent=parent)


def test_bool_where_string_expected_rejected():
    parent = _closed_short_parent()
    parent["strategy"] = True
    with pytest.raises(LineageValidationError):
        _make(parent=parent)


def test_unknown_strategy_rejected():
    child = _draft_child(strategy="ULTRA")
    with pytest.raises(LineageValidationError):
        _make(child=child)


def test_unknown_status_rejected():
    child = _draft_child()
    child["status"] = "SOMETHING"
    with pytest.raises(LineageValidationError):
        _make(child=child)


def test_invalid_security_code_rejected():
    child = _draft_child(code="60A519")
    with pytest.raises(LineageValidationError):
        _make(child=child)


def test_naive_timestamp_rejected():
    parent = _closed_short_parent()
    parent["created_at"] = "2026-07-01 00:00:00"  # 无时区
    with pytest.raises(LineageValidationError):
        _make(parent=parent)


def test_empty_reason_rejected():
    with pytest.raises(LineageValidationError):
        _make(reason="   ")


# ---------------------------------------------------------------------------
# §29 纯性：零 filesystem 副作用 + 不 import store/service/router
# ---------------------------------------------------------------------------

def test_module_imports_no_campaign_store_or_service():
    import re
    source = inspect.getsource(cl)
    # 行级 import 语句检查（docstring 提及模块名不算 import）
    import_lines = [l for l in source.splitlines() if re.match(r"^\s*(import|from)\s+\S", l)]
    for line in import_lines:
        assert "campaign_store" not in line, f"lineage 模块不得 import campaign_store: {line}"
        assert "campaign_service" not in line, f"lineage 模块不得 import campaign_service: {line}"
        assert "campaign_router" not in line, f"lineage 模块不得 import campaign_router: {line}"


def test_module_import_zero_filesystem_side_effects():
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    watch_dir = os.environ["VR_DATA_DIR"]  # conftest 指向 mkdtemp
    script = (
        "import os, sys\n"
        "sys.path.insert(0, r'%s')\n"
        "watch = r'%s'\n"
        "before = set(os.listdir(watch))\n"
        "import campaign_lineage\n"
        "after = set(os.listdir(watch))\n"
        "assert not (after - before), 'import 产生文件副作用'\n"
        "print('CLEAN_IMPORT')\n"
    ) % (backend_dir, watch_dir)
    env = dict(os.environ)
    proc = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True,
                          env=env, timeout=120, cwd=backend_dir)
    assert proc.returncode == 0, proc.stderr
    assert "CLEAN_IMPORT" in proc.stdout


def test_record_is_immutable_frozen_dataclass():
    record = _make()
    with pytest.raises(Exception):
        record.parent_strategy = "MEDIUM"  # frozen dataclass 拒绝 setattr


def test_no_mutation_of_inputs():
    parent = _closed_short_parent()
    child = _draft_child()
    before_p = dict(parent)
    before_c = dict(child)
    _make(parent=parent, child=child)
    assert parent == before_p and child == before_c


# ---------------------------------------------------------------------------
# P1-A：strategy 链级一致性（一个 campaign_id 只能映射一个 Strategy）
# ---------------------------------------------------------------------------

def test_strategy_chain_child_flip_rejected():
    """A SHORT→B MEDIUM 且 B SHORT→C SHORT：B 从 MEDIUM 变 SHORT → 拒绝。"""
    r_ab = _make(parent=_closed_short_parent(PID_A, created=T0),
                 child=_draft_child(PID_B, strategy="SHORT", created=T2), closed_at=T1)
    r_bc = _make(parent=_closed_short_parent(PID_B, strategy="MEDIUM", created=T1),
                 child=_draft_child(PID_C, created=T3), closed_at=T2)
    # B 在 r_ab 中=SHORT，在 r_bc 中=MEDIUM → 链级 strategy 冲突
    with pytest.raises(LineageIntegrityError):
        validate_lineage_set([r_ab, r_bc])


def test_strategy_chain_parent_flip_rejected():
    """A SHORT→B 且 A MEDIUM→C：A 不能有两个 Strategy → 拒绝。"""
    r_ab = _make(parent=_closed_short_parent(PID_A, created=T0),
                 child=_draft_child(PID_B, created=T2), closed_at=T1)
    r_ac = _make(parent=_closed_short_parent(PID_A, strategy="MEDIUM", created=T0),
                 child=_draft_child(PID_C, created=T3), closed_at=T1, reason="另一轮")
    with pytest.raises(LineageIntegrityError):
        validate_lineage_set([r_ab, r_ac])


def test_strategy_chain_consistent_across_edges_valid():
    """A SHORT→B MEDIUM、B MEDIUM→C SHORT：各 campaign 单一 Strategy → 合法。"""
    r_ab = _make(parent=_closed_short_parent(PID_A, created=T0),
                 child=_draft_child(PID_B, strategy="MEDIUM", created=T2), closed_at=T1)
    r_bc = _make(parent=_closed_short_parent(PID_B, strategy="MEDIUM", created=T2),
                 child=_draft_child(PID_C, strategy="SHORT", created=T4), closed_at=T3)
    validate_lineage_set([r_ab, r_bc])  # 合法：A 恒 SHORT，B 恒 MEDIUM，C 恒 SHORT


# ---------------------------------------------------------------------------
# P1-B：投影入口预校验（不投影未验证 lineage）
# ---------------------------------------------------------------------------

def test_projection_rejects_multi_parent():
    r_ac = _make(parent=_closed_short_parent(PID_A, created=T0),
                 child=_draft_child(PID_C, created=T2), closed_at=T1)
    r_bc = _make(parent=_closed_short_parent(PID_B, created=T0),
                 child=_draft_child(PID_C, created=T2), closed_at=T1, reason="另一父")
    with pytest.raises(LineageIntegrityError):
        ancestors(PID_C, [r_ac, r_bc])


def test_projection_rejects_multi_parent_reversed_order():
    r_ac = _make(parent=_closed_short_parent(PID_A, created=T0),
                 child=_draft_child(PID_C, created=T2), closed_at=T1)
    r_bc = _make(parent=_closed_short_parent(PID_B, created=T0),
                 child=_draft_child(PID_C, created=T2), closed_at=T1, reason="另一父")
    with pytest.raises(LineageIntegrityError):
        ancestors(PID_C, [r_bc, r_ac])  # 反序同样拒绝


def test_projection_rejects_hash_tamper():
    from dataclasses import replace
    record = _make()
    tampered = replace(record, lineage_hash="0" * 64)  # 构造 hash 漂移记录（跳过 from_dict）
    with pytest.raises(LineageIntegrityError):
        ancestors(PID_B, [tampered])  # projection 入口预校验检测 hash 漂移


def test_projection_rejects_cross_security_inconsistent():
    r_ab = _make(parent=_closed_short_parent(PID_A, created=T0, code="600519"),
                 child=_draft_child(PID_B, created=T2, code="600519"), closed_at=T1)
    r_bc = _make(parent=_closed_short_parent(PID_B, created=T1, code="000001"),
                 child=_draft_child(PID_C, created=T3, code="000001"), closed_at=T2,
                 reason="错 security")
    with pytest.raises(LineageIntegrityError):
        ancestors(PID_C, [r_ab, r_bc])


def test_projection_rejects_cycle():
    r_ab = _make(parent=_closed_short_parent(PID_A, created=T0),
                 child=_draft_child(PID_B, created=T2), closed_at=T1)
    r_ba = _make(parent=_closed_short_parent(PID_B, created=T2),
                 child=_draft_child(PID_A, created=T3), closed_at=T2, reason="反向")
    with pytest.raises(LineageIntegrityError):
        ancestors(PID_B, [r_ab, r_ba])


def test_projection_valid_shuffled_identical():
    r_ab = _make(parent=_closed_short_parent(PID_A, created=T0),
                 child=_draft_child(PID_B, created=T2), closed_at=T1)
    r_bc = _make(parent=_closed_short_parent(PID_B, created=T2),
                 child=_draft_child(PID_C, created=T4), closed_at=T3)
    assert [r.lineage_id for r in ancestors(PID_C, [r_ab, r_bc])] == \
           [r.lineage_id for r in ancestors(PID_C, [r_bc, r_ab])]
    assert [r.lineage_id for r in descendants(PID_A, [r_ab, r_bc])] == \
           [r.lineage_id for r in descendants(PID_A, [r_bc, r_ab])]


# ---------------------------------------------------------------------------
# Temporal precision：canonical UTC 保留微秒，同毫秒内可区分
# ---------------------------------------------------------------------------

def test_canonical_utc_preserves_microseconds():
    close = "2026-07-02T10:00:00.123456Z"
    child = _draft_child(PID_B, created="2026-07-02T10:00:00.200000Z")
    record = _make(child=child, closed_at=close)
    assert record.parent_closed_at == "2026-07-02T10:00:00.123456Z"  # 不截断毫秒


def test_same_millisecond_different_microseconds_ordering_valid():
    """parent close 与 child create 同毫秒但微秒不同 → 仍可区分严格序。"""
    close = "2026-07-02T10:00:00.123456Z"
    child = _draft_child(PID_B, created="2026-07-02T10:00:00.123999Z")  # 同毫秒，晚 543μs
    record = _make(child=child, closed_at=close)
    assert record.parent_closed_at == close
    assert record.child_created_at == "2026-07-02T10:00:00.123999Z"
    assert cl._parse_utc(record.parent_closed_at) < cl._parse_utc(record.child_created_at)


def test_from_dict_rejects_millisecond_only_timestamps():
    record = _make().to_dict()
    record["parent_closed_at"] = "2026-07-02T00:00:00.000Z"  # 3 位毫秒（非 canonical 6 位）
    with pytest.raises(LineageValidationError):
        CampaignLineageRecord.from_dict(record)


# ---------------------------------------------------------------------------
# P1-D：from_dict 严格类型（拒绝 silent 归一化）
# ---------------------------------------------------------------------------

def test_from_dict_rejects_non_str_fields():
    record = _make().to_dict()
    for key, bad in (("security_code", 600519), ("reason", 123), ("parent_strategy", True),
                     ("lineage_id", b"lineage_bytes"), ("child_created_at", 1750000000000)):
        mutated = dict(record)
        mutated[key] = bad
        with pytest.raises(LineageValidationError):
            CampaignLineageRecord.from_dict(mutated)


def test_from_dict_rejects_noncanonical_timestamp_text():
    record = _make().to_dict()
    record["child_created_at"] = "2026-07-03T00:00:00+00:00"  # 合法 ISO 但非 canonical 形式
    with pytest.raises(LineageValidationError):
        CampaignLineageRecord.from_dict(record)


# ---------------------------------------------------------------------------
# Builder + transition history 绑定
# ---------------------------------------------------------------------------

def test_builder_with_matching_transition_history_ok():
    history = _transitions(("DRAFT", "RESEARCHING", T0), ("RESEARCHING", "PRE-ENTRY", T0),
                           ("PRE-ENTRY", "ACTIVE", T1), ("ACTIVE", "REDUCING", T1),
                           ("REDUCING", "CLOSED", T1))
    record = build_lineage_record(
        parent_campaign=_closed_short_parent(PID_A, created=T0),
        child_campaign=_draft_child(PID_B, created=T2),
        parent_closed_at=T1,
        reason="重新入场",
        created_at=CREATED,
        parent_transitions=history,
    )
    assert record.parent_closed_at == T1


def test_builder_rejects_unrelated_close_timestamp_with_history():
    history = _transitions(("DRAFT", "RESEARCHING", T0), ("RESEARCHING", "PRE-ENTRY", T0),
                           ("PRE-ENTRY", "ACTIVE", T1), ("ACTIVE", "REDUCING", T1),
                           ("REDUCING", "CLOSED", T1))
    with pytest.raises(LineageValidationError):
        build_lineage_record(
            parent_campaign=_closed_short_parent(PID_A, created=T0),
            child_campaign=_draft_child(PID_B, created=T2),
            parent_closed_at=T2,  # 与历史推导的 T1 不一致 → 拒绝
            reason="重新入场",
            created_at=CREATED,
            parent_transitions=history,
        )


def test_builder_with_wrong_campaign_history_rejected():
    history = _transitions(("DRAFT", "RESEARCHING", T0), ("RESEARCHING", "PRE-ENTRY", T0),
                           ("PRE-ENTRY", "ACTIVE", T1), ("ACTIVE", "REDUCING", T1),
                           ("REDUCING", "CLOSED", T1), campaign_id=PID_B)
    with pytest.raises(LineageValidationError):
        build_lineage_record(
            parent_campaign=_closed_short_parent(PID_A, created=T0),
            child_campaign=_draft_child(PID_B, created=T2),
            parent_closed_at=T1,
            reason="重新入场",
            created_at=CREATED,
            parent_transitions=history,
        )


def test_builder_explicit_close_without_history_documented_path():
    # 无 transition 历史的最小路径：显式 parent_closed_at（文档已标注区分）
    record = _make(parent=_closed_short_parent(PID_A, created=T0),
                   child=_draft_child(PID_B, created=T2), closed_at=T1)
    assert record.parent_closed_at == T1


# ---------------------------------------------------------------------------
# P2 parity：Campaign 契约（STRATEGIES / STATUSES / TRANSITION_GRAPH）对照权威源
# ---------------------------------------------------------------------------

def test_campaign_contract_parity():
    import campaign_store as store
    assert tuple(cl.STRATEGIES) == tuple(store.STRATEGIES)
    assert tuple(cl.STATUSES) == tuple(store.STATUSES)
    assert cl.TRANSITION_GRAPH == store._TRANSITION_GRAPH  # 冻结 graph 漂移检测


def test_transition_id_shape_matches_campaign_store_contract():
    import re as _re
    assert _re.fullmatch(r"^campaign_transition_[0-9a-f]{32}$",
                         _transitions(("DRAFT", "RESEARCHING", T0))[0]["transition_id"])


# ---------------------------------------------------------------------------
# R2：Campaign cross-edge temporal identity（A–E blocking tests）
# ---------------------------------------------------------------------------

def test_r2_a_close_before_create_chain_rejected():
    """A closes T1 → B created T3；B closes T2 → C created T4；T2<T3 →
    B 在创建前已关闭 → validate_lineage_set / ancestors / descendants 全拒绝。"""
    r_ab = _make(parent=_closed_short_parent(PID_A, created=T0),
                 child=_draft_child(PID_B, created=T3), closed_at=T1)
    r_bc = _make(parent=_closed_short_parent(PID_B, created=T3, strategy="MEDIUM"),
                 child=_draft_child(PID_C, created=T4), closed_at=T2)
    # 单边均合法（T1<T3、T2<T4），但 B created T3 > closed T2 → 链级拒绝
    with pytest.raises(LineageIntegrityError):
        validate_lineage_set([r_ab, r_bc])
    with pytest.raises(LineageIntegrityError):
        ancestors(PID_C, [r_ab, r_bc])
    with pytest.raises(LineageIntegrityError):
        descendants(PID_A, [r_ab, r_bc])


def test_r2_b_multiple_close_times_same_campaign_rejected():
    """A closed T1 → B；A closed T2 → C；T1!=T2 → 同一 campaign 多个 CLOSED 锚点拒绝。"""
    r_ab = _make(parent=_closed_short_parent(PID_A, created=T0),
                 child=_draft_child(PID_B, created=T2), closed_at=T1)
    r_ac = _make(parent=_closed_short_parent(PID_A, created=T0),
                 child=_draft_child(PID_C, created=T3), closed_at=T2, reason="另一轮")
    with pytest.raises(LineageIntegrityError):
        validate_lineage_set([r_ab, r_ac])


def test_r2_c_valid_strict_lifecycle_chain_passes():
    """A closes T1 → B created T2；B closes T3 → C created T4；T1<T2<T3<T4 → PASS。"""
    r_ab = _make(parent=_closed_short_parent(PID_A, created=T0),
                 child=_draft_child(PID_B, created=T2), closed_at=T1)
    r_bc = _make(parent=_closed_short_parent(PID_B, created=T2),
                 child=_draft_child(PID_C, created=T4), closed_at=T3)
    validate_lineage_set([r_ab, r_bc])
    assert [r.lineage_id for r in ancestors(PID_C, [r_ab, r_bc])] == \
           [r_ab.lineage_id, r_bc.lineage_id]


def test_r2_d_shuffled_valid_same_projection():
    r_ab = _make(parent=_closed_short_parent(PID_A, created=T0),
                 child=_draft_child(PID_B, created=T2), closed_at=T1)
    r_bc = _make(parent=_closed_short_parent(PID_B, created=T2),
                 child=_draft_child(PID_C, created=T4), closed_at=T3)
    asc = ancestors(PID_C, [r_ab, r_bc])
    shuffled = ancestors(PID_C, [r_bc, r_ab])
    assert [r.lineage_id for r in asc] == [r.lineage_id for r in shuffled]
    assert [r.lineage_id for r in descendants(PID_A, [r_ab, r_bc])] == \
           [r.lineage_id for r in descendants(PID_A, [r_bc, r_ab])]


def test_r2_e_microsecond_chain_ordering():
    """B created ...123456Z、B closed ...123457Z（微秒级严格序）→ PASS；反转 → REJECT。"""
    b_created = "2026-07-03T10:00:00.123456Z"
    b_closed = "2026-07-03T10:00:00.123457Z"
    r_ab = _make(parent=_closed_short_parent(PID_A, created=T0),
                 child=_draft_child(PID_B, created=b_created), closed_at=T1)
    r_bc = _make(parent=_closed_short_parent(PID_B, created=b_created),
                 child=_draft_child(PID_C, created=T4), closed_at=b_closed)
    validate_lineage_set([r_ab, r_bc])  # created(123456) < closed(123457) → 合法
    # 反转：B closed 早于 created → 拒绝
    r_bc_bad = _make(parent=_closed_short_parent(PID_B, created=b_created),
                     child=_draft_child(PID_C, created=T4),
                     closed_at="2026-07-03T10:00:00.123455Z")
    with pytest.raises(LineageIntegrityError):
        validate_lineage_set([r_ab, r_bc_bad])
