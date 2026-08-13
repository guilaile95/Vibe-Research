"""Current Market Overview Runtime v0.1 专项测试（P0-MO1）。

覆盖 §17 targeted（normal/partial/unavailable/zero vs unavailable/stale/intraday/
final/timestamp/trade_date preservation/immutability/determinism）+ adversarial
（missing/malformed/NaN/inf/negative/inconsistent/source partial/unavailable/
old snapshot）+ §5.1 temporal state + 零 I/O 纯净扫描。

facts envelope 由 ``short_term_market_facts.compute_short_term_market_facts``
（既有 producer authority）从 fixture snapshot 生成——runtime 不重算事实。
"""
from __future__ import annotations

import inspect

import pytest

import market_overview_runtime as overview
import short_term_market_facts as facts_authority

SCHEMA = "short-term-market-facts-v0.1"


def _facts_snapshot(**overrides) -> dict:
    """构造 compute_short_term_market_facts 的输入 snapshot（normal 基线，与既有
    test_short_term_market_facts._base_snapshot 同格式）。"""
    snapshot = {
        "trade_date": "2026-08-10",
        "session": "final",
        "is_final": True,
        "source_ids": ["eastmoney_limit_pool", "eastmoney_market_breadth"],
        "fetched_at": "2026-08-10T07:30:00.000000Z",
        "snapshot_at": "2026-08-10T07:35:00.000000Z",
        "universe": {},
        "breadth": {
            "advance_count": 3000,
            "decline_count": 1500,
            "flat_count": 500,
            "suspended_count": 100,
            "eligible_count": 5100,
        },
        "limit_activity": {
            "limit_up_count": 40,
            "limit_down_count": 3,
            "failed_limit_up_count": 10,
        },
        "data_health": {
            "transport_success": True,
            "parse_success": True,
            "required_field_present": True,
            "data_array_present": True,
            "trade_date_match": True,
            "row_count": 7,
            "legal_zero": False,
            "upstream_null": False,
            "unexplained_empty": False,
            "coverage_warning": False,
        },
        "limitations": ["single-source, not cross-validated"],
        "reason_codes": [],
    }
    snapshot.update(overrides)
    return snapshot


def _facts(**snapshot_overrides) -> dict:
    return facts_authority.compute_short_term_market_facts(
        _facts_snapshot(**snapshot_overrides))


def _overview(**snapshot_overrides) -> dict:
    return overview.build_market_overview(_facts(**snapshot_overrides))


# ---------------------------------------------------------------------------
# Targeted: normal full snapshot
# ---------------------------------------------------------------------------

def test_normal_full_snapshot():
    o = _overview()
    assert o["schema_version"] == overview.SCHEMA_VERSION
    assert o["data_state"] == overview.DATA_STATE_AVAILABLE
    assert o["temporal_state"] == overview.TEMPORAL_STATE_AFTER_CLOSE_FINAL
    assert o["trade_date"] == "2026-08-10"
    assert o["session"] == "final"
    assert o["is_final"] is True
    assert o["fetched_at"] == "2026-08-10T07:30:00.000000Z"
    assert o["snapshot_at"] == "2026-08-10T07:35:00.000000Z"
    # breadth（facts authority 透传）
    assert o["breadth"]["advance_count"] == 3000
    assert o["breadth"]["decline_count"] == 1500
    assert o["breadth"]["valid_count"] == 5000
    assert o["breadth"]["up_ratio"] == 0.6
    assert o["breadth"]["breadth_state"] == "中性"  # 0.6 <= 0.60 边界
    # limit activity
    assert o["limit_activity"]["limit_up_count"] == 40
    assert o["limit_activity"]["failed_board_rate"] == 0.2
    assert o["limit_activity"]["seal_rate"] == 0.8
    assert o["limit_activity"]["speculation_activity"] == "普通"  # 30 <= 40 < 60


def test_breadth_label_boundaries():
    """label 阈值与 market.py:_breadth_label 一致（冰点/偏弱/中性/偏强/普涨）。
    up_ratio 由 producer 从 advance/valid 派生（valid = advance+decline+flat）；
    advance 变化须同步 eligible_count 保持 sum 恒等（否则 producer fail-closed）。"""
    base = _facts_snapshot()["breadth"]
    cases = [
        (480, "冰点"),   # 480/2480 ≈ 0.19
        (500, "冰点"),   # 0.20
        (780, "偏弱"),   # 0.28
        (800, "偏弱"),   # 0.29
        (2000, "中性"),  # 0.50
        (3000, "中性"),  # 0.60（<=0.60 边界）
        (4000, "偏强"),  # 0.67
        (6000, "偏强"),  # 0.75（<=0.75 边界）
        (7000, "普涨"),  # 0.78
    ]
    for advance, label in cases:
        eligible = advance + base["decline_count"] + base["flat_count"] + base["suspended_count"]
        o = _overview(**{"breadth": {**base, "advance_count": advance,
                                     "eligible_count": eligible}})
        assert o["breadth"]["breadth_state"] == label, f"advance={advance}"


def test_speculation_label_boundaries():
    """label 阈值与 market.py:_speculation_label 一致（冰点/普通/活跃/亢奋）。"""
    cases = [(10, "冰点"), (29, "冰点"), (30, "普通"), (59, "普通"),
             (60, "活跃"), (99, "活跃"), (100, "亢奋"), (120, "亢奋")]
    for count, label in cases:
        o = _overview(**{"limit_activity": {
            **_facts_snapshot()["limit_activity"], "limit_up_count": count}})
        assert o["limit_activity"]["speculation_activity"] == label, f"count={count}"


# ---------------------------------------------------------------------------
# Targeted: partial / unavailable / zero vs unavailable
# ---------------------------------------------------------------------------

def _partial_facts() -> dict:
    """producer 判定 partial：breadth identity 不一致（eligible_count 破坏恒等）。"""
    snap = _facts_snapshot()
    snap["breadth"]["eligible_count"] = 9999
    return facts_authority.compute_short_term_market_facts(snap)


def test_partial_breadth_state():
    """partial status → data_state=PARTIAL（不伪装 COMPLETE）。"""
    facts = _partial_facts()
    assert facts["status"] == "partial"
    o = overview.build_market_overview(facts)
    assert o["data_state"] == overview.DATA_STATE_PARTIAL
    assert any("PARTIAL" in c for c in o["reason_codes"])


def test_partial_limit_activity_state():
    """limit_activity=None（部分覆盖）→ partial。"""
    snap = _facts_snapshot()
    snap["limit_activity"] = None
    facts = facts_authority.compute_short_term_market_facts(snap)
    assert facts["status"] == "partial"
    o = overview.build_market_overview(facts)
    assert o["data_state"] == overview.DATA_STATE_PARTIAL


def test_source_unavailable_state():
    """unavailable → data_state=UNAVAILABLE；facts 数值不伪造（None 透传）。"""
    o = overview.build_market_overview(facts_authority.compute_short_term_market_facts(
        {"schema_version": SCHEMA}))
    assert o["data_state"] == overview.DATA_STATE_UNAVAILABLE
    assert o["temporal_state"] == overview.TEMPORAL_STATE_UNAVAILABLE
    assert o["breadth"]["up_ratio"] is None  # 未知 ≠ 0
    assert o["limit_activity"]["limit_up_count"] is None  # 未知 ≠ 0


def test_zero_is_real_zero():
    """真实 0（legal zero）≠ unavailable。"""
    o = _overview(**{"limit_activity": {
        **_facts_snapshot()["limit_activity"], "limit_up_count": 0}})
    assert o["limit_activity"]["limit_up_count"] == 0  # 真实零
    assert o["limit_activity"]["speculation_activity"] == "冰点"
    assert o["data_state"] == overview.DATA_STATE_AVAILABLE  # 仍 AVAILABLE


def test_zero_vs_unavailable_distinct():
    """0 limit_up ≠ limit_up data unavailable（不可混淆）。"""
    zero = _overview(**{"limit_activity": {
        **_facts_snapshot()["limit_activity"], "limit_up_count": 0}})
    unavailable = overview.build_market_overview(
        facts_authority.compute_short_term_market_facts(
            {"schema_version": SCHEMA}))
    assert zero["limit_activity"]["limit_up_count"] == 0
    assert unavailable["limit_activity"]["limit_up_count"] is None
    assert zero["data_state"] != unavailable["data_state"]


# ---------------------------------------------------------------------------
# Targeted: stale / intraday / final / timestamp preservation
# ---------------------------------------------------------------------------

def test_intraday_snapshot_temporal_state():
    o = _overview(session="morning_session", is_final=False)
    assert o["temporal_state"] == overview.TEMPORAL_STATE_INTRADAY
    assert o["is_final"] is False
    assert o["session"] == "morning_session"


def test_final_close_temporal_state():
    o = _overview(session="final", is_final=True)
    assert o["temporal_state"] == overview.TEMPORAL_STATE_AFTER_CLOSE_FINAL


def test_old_snapshot_never_looks_current():
    """旧快照不伪装 current：session/is_final/fetched_at 全保留（上层可判 stale）。"""
    o = _overview(trade_date="2026-08-03", fetched_at="2026-08-03T15:30:00.000000Z")
    assert o["trade_date"] == "2026-08-03"
    assert o["fetched_at"] == "2026-08-03T15:30:00.000000Z"
    assert o["session"] == "final"  # 原样保留


def test_trade_date_preserved():
    assert _overview(trade_date="2026-08-07")["trade_date"] == "2026-08-07"


# ---------------------------------------------------------------------------
# Determinism / immutability
# ---------------------------------------------------------------------------

def test_deterministic_output():
    a = _overview()
    b = _overview()
    assert a == b


def test_input_immutability():
    snap = _facts_snapshot()
    before = dict(snap)
    facts = facts_authority.compute_short_term_market_facts(snap)
    overview.build_market_overview(facts)
    assert snap == before


def test_output_detached():
    o = _overview()
    o["breadth"]["advance_count"] = 999999
    o2 = _overview()
    assert o2["breadth"]["advance_count"] == 3000


# ---------------------------------------------------------------------------
# Adversarial: fail closed
# ---------------------------------------------------------------------------

def test_adversarial_missing_field_not_fabricated():
    """producer 缺字段场景：runtime 不伪造（unavailable envelope 全 None 已覆盖）；
    facts 缺失 → None 透传，不崩溃。"""
    facts = _facts()
    facts["facts"]["advance_count"] = None  # producer 语义：未知
    o = overview.build_market_overview(facts)
    assert o["breadth"]["advance_count"] is None  # 未知不伪造


def test_adversarial_malformed_timestamp_rejected():
    """snapshot 层 malformed timestamp → producer fail-closed（partial/unavailable），
    绝不伪装 current（data_state != AVAILABLE）。"""
    o = overview.build_market_overview(_facts(fetched_at="not-a-time"))
    assert o["data_state"] != overview.DATA_STATE_AVAILABLE
    assert o["data_state"] in (overview.DATA_STATE_PARTIAL, overview.DATA_STATE_UNAVAILABLE)


def test_adversarial_nan_inf_rejected():
    import math
    facts = _facts()
    facts["facts"]["up_ratio"] = math.nan
    with pytest.raises(overview.MarketOverviewInputError):
        overview.build_market_overview(facts)
    facts2 = _facts()
    facts2["facts"]["seal_rate"] = float("inf")
    with pytest.raises(overview.MarketOverviewInputError):
        overview.build_market_overview(facts2)


def test_adversarial_negative_counts_rejected():
    facts = _facts()
    facts["facts"]["advance_count"] = -5
    with pytest.raises(overview.MarketOverviewInputError):
        overview.build_market_overview(facts)


def test_adversarial_inconsistent_breadth_identities_rejected():
    """breadth identity 不一致（sum ≠ eligible）→ producer fail-closed（partial）。"""
    snap = _facts_snapshot()
    snap["breadth"]["advance_count"] = 999999  # 破坏 sum 恒等
    facts = facts_authority.compute_short_term_market_facts(snap)
    assert facts["status"] == "partial"  # producer 已 fail-closed（不产生 normal）
    o = overview.build_market_overview(facts)
    assert o["data_state"] == overview.DATA_STATE_PARTIAL


def test_adversarial_source_partial_preserved():
    """source partial → producer 判 partial → data_state=PARTIAL（reason 保留）。"""
    facts = _partial_facts()
    o = overview.build_market_overview(facts)
    assert o["status"] == "partial"
    assert o["data_state"] == overview.DATA_STATE_PARTIAL
    assert any("PARTIAL" in c for c in o["reason_codes"])


def test_adversarial_unknown_schema_rejected():
    with pytest.raises(overview.MarketOverviewInputError):
        overview.build_market_overview({"schema_version": "other.v1"})


def test_adversarial_old_snapshot_masquerade_impossible():
    """旧快照伪装 current 被阻止：temporal_state 反映 session/is_final，非墙钟。"""
    o = _overview(session="final", is_final=True, trade_date="2026-01-05")
    assert o["temporal_state"] == overview.TEMPORAL_STATE_AFTER_CLOSE_FINAL
    assert o["trade_date"] == "2026-01-05"  # 用户可见真实日期


# ---------------------------------------------------------------------------
# 纯净扫描（零 I/O / 无 AI / 无墙钟）
# ---------------------------------------------------------------------------

def test_runtime_no_io_no_clock_no_ai():
    source = inspect.getsource(overview)
    for marker in ("sqlite3", "requests", "datetime.now", "date.today",
                   "time.time", "open(", "fastapi", "astock", "gstock"):
        assert marker not in source, f"runtime 包含禁止内容: {marker!r}"


def test_runtime_no_investment_actions():
    o = _overview()
    text = str(o)
    for token in ("BUY", "SELL", "REDUCE", "EXIT", "market_regime",
                  "risk_appetite", "recommended_exposure", "BUY_ALLOWED"):
        assert token not in text
