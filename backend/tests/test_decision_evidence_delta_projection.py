"""Decision Evidence Delta Projection Core v0.1 专项测试（P0-EC1）。

覆盖工作单 §REQUIRED TEST MATRIX 27 项 + 三个重要 case（retrieved-later-but-
effective-earlier / effective-unknown / campaign isolation）+ fail-closed 输入
契约 + 确定性/零突变/deep isolation + 源码纯净扫描。全部纯函数调用：不联网、
不落库、不读时钟、不写用户数据。
"""
from __future__ import annotations

import inspect
from dataclasses import replace

import pytest

import decision_evidence_delta_projection as ddp

T_UTC = "2026-08-10T04:00:00.000000Z"  # decision_boundary
SECURITY = "600519"
STRATEGY = "SWING"
CAMPAIGN_A = "campaign_" + "a" * 32
CAMPAIGN_B = "campaign_" + "b" * 32
DECISION_ID = "decision_" + "c" * 32


def _context(
    *,
    security_code: str = SECURITY,
    strategy: str = STRATEGY,
    campaign_id: str = CAMPAIGN_A,
    decision_id: str = DECISION_ID,
    boundary: str = T_UTC,
) -> ddp.DecisionContext:
    return ddp.DecisionContext(
        security_code=security_code,
        strategy=strategy,
        campaign_id=campaign_id,
        decision_id=decision_id,
        decision_boundary_at=boundary,
    )


def _evidence(
    *,
    evidence_id: str = "e" * 32,
    scope_kind: str = ddp.SCOPE_SECURITY,
    scope_id: str = SECURITY,
    effective_at: str | None = "2026-08-11T00:00:00.000000Z",
    retrieved_at: str | None = None,
    time_semantics: str = ddp.TIME_SEMANTICS_AUTHORITATIVE,
    authority_refs: tuple[str, ...] = ("authority-1",),
) -> ddp.NormalizedEvidenceItem:
    return ddp.NormalizedEvidenceItem(
        evidence_id=evidence_id,
        scope_kind=scope_kind,
        scope_id=scope_id,
        effective_at=effective_at,
        retrieved_at=retrieved_at,
        time_semantics=time_semantics,
        authority_refs=authority_refs,
    )


def _project(items):
    return ddp.project_decision_evidence_delta(
        context=_context(), evidence_items=tuple(items))


# ---------------------------------------------------------------------------
# 时间分类矩阵（§1-6）+ 三个重要 case
# ---------------------------------------------------------------------------

def test_effective_after_boundary_new():
    """1. effective_at > boundary → NEW_AFTER_DECISION。"""
    item = _evidence(effective_at="2026-08-11T00:00:00.000000Z")
    assert ddp.classify_evidence_item(_context(), item) == ddp.NEW_AFTER_DECISION
    d = _project([item])
    assert d.new_evidence == ("e" * 32,)
    assert d.has_new_evidence is True


def test_effective_equal_boundary_preexisting():
    """2. effective_at == boundary → PREEXISTING（boundary 视为已包含）。"""
    item = _evidence(effective_at=T_UTC)
    assert ddp.classify_evidence_item(_context(), item) == ddp.PREEXISTING_AT_DECISION


def test_effective_before_boundary_preexisting():
    """3. effective_at < boundary → PREEXISTING。"""
    item = _evidence(effective_at="2026-07-01T00:00:00.000000Z")
    assert ddp.classify_evidence_item(_context(), item) == ddp.PREEXISTING_AT_DECISION


def test_retrieved_later_but_effective_earlier_preexisting():
    """IMPORTANT CASE 1：retrieved 晚于 boundary 但 effective 早 → PREEXISTING。

    今天抓到两个月前公告 ≠ decision 之后的新证据（retrieval != fact time）。
    """
    item = _evidence(effective_at="2026-07-01T00:00:00.000000Z",
                     retrieved_at="2026-08-11T00:00:00.000000Z")
    assert ddp.classify_evidence_item(_context(), item) == ddp.PREEXISTING_AT_DECISION
    d = _project([item])
    assert d.preexisting_evidence == ("e" * 32,)
    assert d.new_evidence == ()
    assert d.has_new_evidence is False


def test_retrieved_later_effective_unknown_unknown_relation():
    """IMPORTANT CASE 2：effective=UNKNOWN + retrieved 晚 → UNKNOWN_TEMPORAL_RELATION。

    绝不根据 retrieval time 猜 NEW。
    """
    item = _evidence(effective_at=None, retrieved_at="2026-08-11T00:00:00.000000Z",
                     time_semantics=ddp.TIME_SEMANTICS_UNKNOWN)
    assert ddp.classify_evidence_item(_context(), item) == \
        ddp.UNKNOWN_TEMPORAL_RELATION
    d = _project([item])
    assert d.unknown_temporal_evidence == ("e" * 32,)
    assert d.new_evidence == ()
    assert d.temporal_coverage_complete is False


def test_effective_newer_retrieved_earlier_classified_by_effective():
    """6. effective 新 + retrieved 早 → 仍按 effective_at 分类（NEW）。"""
    item = _evidence(effective_at="2026-08-11T00:00:00.000000Z",
                     retrieved_at="2026-08-09T00:00:00.000000Z")
    assert ddp.classify_evidence_item(_context(), item) == ddp.NEW_AFTER_DECISION


# ---------------------------------------------------------------------------
# Scope / identity（§7-11、15）+ IMPORTANT CASE 3
# ---------------------------------------------------------------------------

def test_security_scoped_matching_included():
    """7. security-scoped 匹配 security → included。"""
    item = _evidence(scope_kind=ddp.SCOPE_SECURITY, scope_id=SECURITY,
                     effective_at="2026-08-11T00:00:00.000000Z")
    d = _project([item])
    assert d.new_evidence == ("e" * 32,)


def test_security_scoped_different_security_out_of_scope():
    """8. security-scoped 不同 security → OUT_OF_SCOPE。"""
    item = _evidence(scope_kind=ddp.SCOPE_SECURITY, scope_id="000001",
                     effective_at="2026-08-11T00:00:00.000000Z")
    assert ddp.classify_evidence_item(_context(), item) == ddp.OUT_OF_SCOPE
    d = _project([item])
    assert d.out_of_scope_evidence == ("e" * 32,)
    assert d.has_new_evidence is False


def test_campaign_scoped_matching_included():
    """9. campaign-scoped 匹配 campaign → included。"""
    item = _evidence(scope_kind=ddp.SCOPE_CAMPAIGN, scope_id=CAMPAIGN_A,
                     effective_at="2026-08-11T00:00:00.000000Z")
    d = _project([item])
    assert d.new_evidence == ("e" * 32,)


def test_campaign_scoped_sibling_out_of_scope():
    """IMPORTANT CASE 3 + 10：campaign-scoped 兄弟 campaign → OUT_OF_SCOPE。"""
    item = _evidence(scope_kind=ddp.SCOPE_CAMPAIGN, scope_id=CAMPAIGN_A,
                     effective_at="2026-08-11T00:00:00.000000Z")
    ctx_b = _context(campaign_id=CAMPAIGN_B)
    assert ddp.classify_evidence_item(ctx_b, item) == ddp.OUT_OF_SCOPE
    d = ddp.project_decision_evidence_delta(
        context=ctx_b, evidence_items=(item,))
    assert d.out_of_scope_evidence == ("e" * 32,)


def test_same_security_same_strategy_different_campaign_isolation():
    """11. 同 security 同 strategy 不同 campaign → 隔离保持。"""
    item = _evidence(scope_kind=ddp.SCOPE_CAMPAIGN, scope_id=CAMPAIGN_A,
                     effective_at="2026-08-11T00:00:00.000000Z")
    ctx_b = _context(campaign_id=CAMPAIGN_B)
    da = ddp.project_decision_evidence_delta(
        context=_context(), evidence_items=(item,))
    db = ddp.project_decision_evidence_delta(
        context=ctx_b, evidence_items=(item,))
    assert da.new_evidence == ("e" * 32,)      # A 看到
    assert db.out_of_scope_evidence == ("e" * 32,)  # B 隔离
    assert db.new_evidence == ()


def test_unknown_scope_fail_closed():
    """15. 未知 scope_kind → fail closed。"""
    with pytest.raises(ddp.EvidenceDeltaInputError):
        _evidence(scope_kind="sector")


# ---------------------------------------------------------------------------
# Fail-closed 输入契约（§12-14）
# ---------------------------------------------------------------------------

def test_duplicate_evidence_id_fail_closed():
    """12. duplicate evidence_id → fail closed。"""
    a = _evidence(effective_at="2026-08-11T00:00:00.000000Z")
    b = _evidence(evidence_id="e" * 32, scope_kind=ddp.SCOPE_CAMPAIGN,
                  scope_id=CAMPAIGN_A, effective_at="2026-08-11T00:00:00.000000Z")
    with pytest.raises(ddp.EvidenceDeltaInputError):
        _project([a, b])


def test_malformed_effective_at_fail_closed():
    """13. malformed effective_at → fail closed（不是 UNKNOWN）。"""
    with pytest.raises(ddp.EvidenceDeltaInputError):
        _evidence(effective_at="not-a-time")
    with pytest.raises(ddp.EvidenceDeltaInputError):
        _evidence(effective_at="2026-02-31T00:00:00.000000Z")  # 不可能日期
    with pytest.raises(ddp.EvidenceDeltaInputError):
        _evidence(effective_at="2026-08-11T00:00:00Z")  # 非 6 位微秒


def test_authoritative_without_effective_at_fail_closed():
    """AUTHORITATIVE 语义缺 effective_at → fail closed（不静默降级 UNKNOWN）。"""
    with pytest.raises(ddp.EvidenceDeltaInputError):
        _evidence(effective_at=None)


def test_unknown_semantics_with_effective_at_fail_closed():
    """UNKNOWN 语义携带 effective_at → fail closed。"""
    with pytest.raises(ddp.EvidenceDeltaInputError):
        _evidence(effective_at="2026-08-11T00:00:00.000000Z",
                  time_semantics=ddp.TIME_SEMANTICS_UNKNOWN)


def test_malformed_context_fail_closed():
    """campaign/strategy/boundary malformed → fail closed。"""
    with pytest.raises(ddp.EvidenceDeltaInputError):
        _context(campaign_id="not-a-campaign")
    with pytest.raises(ddp.EvidenceDeltaInputError):
        _context(strategy="LONG")
    with pytest.raises(ddp.EvidenceDeltaInputError):
        _context(boundary="2026-08-10")  # 非 canonical UTC


# ---------------------------------------------------------------------------
# Coverage / mixture（§16-18）
# ---------------------------------------------------------------------------

def test_new_plus_unknown_mixture():
    """16. new + unknown 混合 → has_new=true + coverage=false。"""
    new = _evidence(evidence_id="f" * 32,
                    effective_at="2026-08-11T00:00:00.000000Z")
    unknown = _evidence(evidence_id="d" * 32,
                        effective_at=None, retrieved_at="2026-08-11T00:00:00.000000Z",
                        time_semantics=ddp.TIME_SEMANTICS_UNKNOWN)
    d = _project([new, unknown])
    assert d.has_new_evidence is True
    assert d.temporal_coverage_complete is False
    assert d.new_evidence == ("f" * 32,)
    assert d.unknown_temporal_evidence == ("d" * 32,)


def test_all_candidates_temporally_known_coverage_true():
    """17. 全部 scope-valid 有可靠 effective_at → coverage=true。"""
    a = _evidence(evidence_id="a" * 32, effective_at="2026-08-11T00:00:00.000000Z")
    b = _evidence(evidence_id="b" * 32, effective_at="2026-07-01T00:00:00.000000Z")
    d = _project([a, b])
    assert d.temporal_coverage_complete is True


def test_no_evidence():
    """18. 无证据 → has_new=false + coverage 语义显式。"""
    d = _project([])
    assert d.has_new_evidence is False
    assert d.temporal_coverage_complete is True  # 无 scope-valid candidate → 无 UNKNOWN
    assert d.new_evidence == () and d.preexisting_evidence == ()
    assert d.unknown_temporal_evidence == () and d.out_of_scope_evidence == ()


# ---------------------------------------------------------------------------
# Determinism / mutation / isolation（§19-22）
# ---------------------------------------------------------------------------

def test_input_order_variation_deterministic():
    """19. 输入顺序变化 → 语义与输出相同（确定性稳定排序）。"""
    items = (
        _evidence(evidence_id="c" * 32, effective_at="2026-08-11T00:00:00.000000Z"),
        _evidence(evidence_id="a" * 32, effective_at="2026-08-11T00:00:00.000000Z"),
        _evidence(evidence_id="b" * 32, effective_at="2026-07-01T00:00:00.000000Z"),
    )
    d1 = _project(items)
    d2 = _project(tuple(reversed(items)))
    assert d1 == d2
    assert d1.new_evidence == ("a" * 32, "c" * 32)  # 按 evidence_id 排序


def test_repeated_call_identical():
    """20. 重复调用 → 完全一致。"""
    items = (_evidence(effective_at="2026-08-11T00:00:00.000000Z"),)
    assert _project(items) == _project(items)


def test_input_zero_mutation():
    """21. 输入零突变（frozen dataclass + 不修改任何传入对象）。"""
    item = _evidence(effective_at="2026-08-11T00:00:00.000000Z")
    before = item.__dict__
    _project([item])
    assert item.__dict__ == before


def test_output_deep_isolated():
    """22. 输出非别名（to_dict 是独立新 list；重复调用不共享嵌套状态）。"""
    d1 = _project([_evidence(effective_at="2026-08-11T00:00:00.000000Z")])
    data1 = d1.to_dict()
    data1["new_evidence"].append("tampered")
    d2 = _project([_evidence(effective_at="2026-08-11T00:00:00.000000Z")])
    assert d2.new_evidence == ("e" * 32,)  # 不受 tamper 影响
    assert d1.new_evidence == ("e" * 32,)  # dataclass 自身也不变


# ---------------------------------------------------------------------------
# 边界：不输出投资语义（§23-25）
# ---------------------------------------------------------------------------

def test_no_material_critical_output():
    """23. 输出无 MATERIAL/CRITICAL（serialized 检查）。"""
    d = _project([_evidence(effective_at="2026-08-11T00:00:00.000000Z")])
    assert "MATERIAL" not in str(d.to_dict())
    assert "CRITICAL" not in str(d.to_dict())
    assert not any(k in d.to_dict() for k in (
        "material_change_state", "material", "critical"))


def test_no_review_required():
    """24. 无 REVIEW_REQUIRED。"""
    d = _project([_evidence(effective_at="2026-08-11T00:00:00.000000Z")])
    assert "REVIEW_REQUIRED" not in str(d.to_dict())


def test_no_buy_sell_exit():
    """25. 无 BUY/SELL/EXIT。"""
    d = _project([_evidence(effective_at="2026-08-11T00:00:00.000000Z")])
    text = str(d.to_dict())
    for token in ("BUY", "SELL", "EXIT", "REDUCE", "HOLD"):
        assert token not in text


# ---------------------------------------------------------------------------
# 纯净化 + 无墙钟（§26-27）
# ---------------------------------------------------------------------------

def test_no_wall_clock_imports():
    """26. core 无 wall clock 依赖。"""
    source = inspect.getsource(ddp)
    for marker in ("datetime.now", "date.today", "time.time"):
        assert marker not in source


def test_no_io_imports():
    """27. core 无 I/O imports（DB/fs/network/API）。"""
    source = inspect.getsource(ddp)
    forbidden = (
        "sqlite3", "open(", "requests", "fastapi", "Path(", "os.", "subprocess",
    )
    for marker in forbidden:
        assert marker not in source, f"core 包含禁止 I/O 内容: {marker!r}"


# ---------------------------------------------------------------------------
# 输出契约 round-trip + 严格校验
# ---------------------------------------------------------------------------

def test_output_round_trip_exact():
    d = _project([
        _evidence(evidence_id="f" * 32, effective_at="2026-08-11T00:00:00.000000Z"),
        _evidence(evidence_id="d" * 32, effective_at=None, retrieved_at="2026-08-11T00:00:00.000000Z",
                  time_semantics=ddp.TIME_SEMANTICS_UNKNOWN),
    ])
    restored = ddp.DecisionEvidenceDelta.from_dict(d.to_dict())
    assert restored == d


def test_output_from_dict_rejects_drift():
    d = _project([])
    data = d.to_dict()
    data["schema_version"] = "other.v1"
    with pytest.raises(ddp.EvidenceDeltaInputError):
        ddp.DecisionEvidenceDelta.from_dict(data)
    data2 = d.to_dict()
    data2["new_evidence"] = ["x", "x"]
    with pytest.raises(ddp.EvidenceDeltaInputError):
        ddp.DecisionEvidenceDelta.from_dict(data2)
