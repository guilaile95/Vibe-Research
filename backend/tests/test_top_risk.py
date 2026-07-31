"""顶部风险分析：引擎、评估器、追踪适配、服务、决策追踪过滤、Data Health、API。

所有测试均非 live（不访问真实行情/估值/资金接口）：
- engine / evaluators 用合成 TopRiskFact；
- trace / service 用临时 VR_DATA_DIR 隔离 SQLite 与事件文件；
- API 测试对 analyze_top_risk 打桩，避免取数。
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

import top_risk_service as trs
import top_risk_evaluators as ev
import top_risk_trace_service as trace_svc
import decision_trace_store as store
from top_risk_engine import TopRiskEngine
from top_risk_schema import (
    SCHEMA_VERSION,
    TopRiskData,
    TopRiskEnvelope,
    TopRiskFact,
    TopRiskStepResult,
    TopRiskStepTrace,
)

import data_health_adapters as adapters
import data_health_event_store as dh_store
import data_health_service as dh_svc
import decision_evidence_service as des


@pytest.fixture(autouse=True)
def _clear_top_risk_cache():
    # 隔离模块级缓存：测试通过 stub _build_facts 注入不同事实，
    # 若不清缓存，(code, days, config_hash) 键会跨测试串味导致状态错判。
    trs._CACHE.clear()
    yield


# ---------------------------------------------------------------------------
# 合成 Fact 构造
# ---------------------------------------------------------------------------
def _fact(code="600519", price=None, vol=None, valuation=None, margin=None):
    return TopRiskFact(
        code=code,
        name="测试股",
        trade_date="2026-07-27",
        price_history=price,
        volume_history=vol,
        valuation=valuation,
        fund_flow=None,
        margin_trading=margin,
        events=None,
        sentiment_series=None,
    )


def _high_risk_fact():
    # 60 点价格：10 → 19.8，再冲高至 20 后回落至 16.4（强拉升 + 冲顶乏力）
    prices = [10 + i * 0.2 for i in range(50)] + [20 - j * 0.4 for j in range(10)]
    vol = [200] * 40 + [60] * 20
    valuation = {"pe_ttm": {"percentile": 95.0}, "pb": {"percentile": 95.0}}
    margin = [{"rzye": 100 + k * 2} for k in range(20)]  # 融资余额 +38% → 拥挤
    return _fact(price=prices, vol=vol, valuation=valuation, margin=margin)


def _low_risk_fact():
    prices = [10 + i * 0.03 for i in range(60)]  # 温和上涨
    vol = [100] * 60
    valuation = {"pe_ttm": {"percentile": 30.0}, "pb": {"percentile": 30.0}}
    margin = [{"rzye": 100 - k * 1.5} for k in range(20)]  # 融资余额 -29.5% → 安全
    return _fact(price=prices, vol=vol, valuation=valuation, margin=margin)


def _partial_fact():
    # 有价格（可出 runup），但缺估值/融资 → 估值步骤 data_missing → partial
    prices = [10 + i * 0.2 for i in range(60)]
    vol = [100] * 60
    return _fact(price=prices, vol=vol, valuation=None, margin=None)


# ---------------------------------------------------------------------------
# 引擎：状态与分数（Phase 1 已知来源缺口不降级）
# ---------------------------------------------------------------------------
def test_engine_high_risk_is_normal_with_high_score():
    eng = TopRiskEngine.from_yaml(trs._CONFIG_PATH)
    enabled_count = len([s for s in eng.steps if s.get("enabled", True) is not False])
    r = eng.run(_high_risk_fact())
    assert r.status == "normal"
    assert r.risk_score is not None and r.risk_score > 0
    # disabled 步骤不进入 coverage 分母；全部 enabled 步骤成功 → total == completed == enabled_count
    assert r.coverage["completed"] == enabled_count and r.coverage["total"] == enabled_count
    assert any(s.direction == "RISK" for s in r.steps)


def test_engine_low_risk_is_normal_with_zero_score():
    eng = TopRiskEngine.from_yaml(trs._CONFIG_PATH)
    r = eng.run(_low_risk_fact())
    assert r.status == "normal"
    assert r.risk_score == 0


def test_engine_partial_when_core_data_missing():
    eng = TopRiskEngine.from_yaml(trs._CONFIG_PATH)
    r = eng.run(_partial_fact())
    assert r.status == "partial"
    assert r.risk_score is not None


def test_engine_unavailable_when_no_valid_steps():
    eng = TopRiskEngine.from_yaml(trs._CONFIG_PATH)
    r = eng.run(_fact(price=None, vol=None, valuation=None, margin=None))
    assert r.status == "unavailable"
    assert r.risk_score is None
    assert r.coverage["completed"] == 0


def test_engine_score_clamped_0_100():
    eng = TopRiskEngine.from_yaml(trs._CONFIG_PATH)
    r = eng.run(_high_risk_fact())
    assert 0 <= r.risk_score <= 100


@pytest.mark.parametrize(
    "weight",
    ["not-a-number", 0, -1, float("nan"), float("inf"), float("-inf")],
)
def test_engine_rejects_non_positive_or_non_finite_step_weight(weight):
    with pytest.raises(ValueError, match="weight"):
        TopRiskEngine([{"id": "invalid-weight", "weight": weight}])


def test_engine_accepts_missing_weight_as_default_one():
    engine = TopRiskEngine([
        {"id": "default-weight", "label": "缺省权重", "evaluator": "missing"}
    ])

    result = engine.run(_fact())

    assert result.steps[0].weight == 1.0


def test_engine_overrides_successful_evaluator_metadata_from_step_config(monkeypatch):
    seen_params = []

    def wrong_metadata_evaluator(_facts, params):
        seen_params.append(params)
        return TopRiskStepResult(
            step_id="hard-coded-wrong-id",
            label="错误标签",
            direction="RISK",
            weight=1.0,
            step_risk=0.5,
            confidence=80.0,
            skipped=False,
        )

    monkeypatch.setitem(ev.EVALUATORS, "wrong_metadata", wrong_metadata_evaluator)
    eng = TopRiskEngine([
        {
            "id": "configured-id",
            "label": "配置标签",
            "evaluator": "wrong_metadata",
            "weight": 2.5,
            "params": {"weight": 9},
        }
    ])

    result = eng.run(_fact())

    assert seen_params == [{"weight": 9}]
    assert len(result.steps) == 1
    assert result.steps[0].step_id == "configured-id"
    assert result.steps[0].label == "配置标签"
    assert result.steps[0].weight == 2.5


def test_engine_aggregates_with_top_level_weights_not_params_weights(monkeypatch):
    def configured_signal(_facts, params):
        return TopRiskStepResult(
            step_id="hard-coded-wrong-id",
            label="错误标签",
            direction="RISK" if params["risk"] else "NEUTRAL",
            weight=float(params["weight"]),
            step_risk=float(params["risk"]),
            confidence=float(params["confidence"]),
            skipped=False,
        )

    monkeypatch.setitem(ev.EVALUATORS, "configured_signal", configured_signal)
    eng = TopRiskEngine([
        {
            "id": "dominant",
            "label": "主步骤",
            "evaluator": "configured_signal",
            "weight": 3,
            "params": {"weight": 9, "risk": 1, "confidence": 90},
        },
        {
            "id": "secondary",
            "label": "次步骤",
            "evaluator": "configured_signal",
            "weight": 1,
            "params": {"weight": 9, "risk": 0, "confidence": 30},
        },
    ])

    result = eng.run(_fact())

    assert [(step.step_id, step.label, step.weight) for step in result.steps] == [
        ("dominant", "主步骤", 3.0),
        ("secondary", "次步骤", 1.0),
    ]
    assert result.risk_score == 75
    assert result.confidence == 75


@pytest.mark.parametrize("bad_result", [None, {"direction": "RISK"}])
def test_engine_isolates_evaluator_returning_wrong_type(monkeypatch, bad_result):
    monkeypatch.setitem(
        ev.EVALUATORS,
        "wrong_return_type",
        lambda _facts, _params: bad_result,
    )
    engine = TopRiskEngine([
        {
            "id": "configured-id",
            "label": "配置标签",
            "evaluator": "wrong_return_type",
            "weight": 2.5,
        }
    ])

    result = engine.run(_fact())

    assert result.status == "unavailable"
    assert len(result.steps) == 1
    assert result.steps[0].step_id == "configured-id"
    assert result.steps[0].label == "配置标签"
    assert result.steps[0].weight == 2.5
    assert result.steps[0].skipped is True
    assert result.steps[0].skip_reason == "分析步骤执行失败"
    assert result.limitations == [{
        "field": "configured-id",
        "reason_code": "EVALUATOR_ERROR",
        "detail": "分析步骤执行失败。",
    }]


def test_engine_isolates_evaluator_exception(monkeypatch):
    def raises(_facts, _params):
        raise RuntimeError("boom")

    monkeypatch.setitem(ev.EVALUATORS, "raises", raises)
    engine = TopRiskEngine([
        {
            "id": "configured-id",
            "label": "配置标签",
            "evaluator": "raises",
            "weight": 2,
        }
    ])

    result = engine.run(_fact())

    assert result.status == "unavailable"
    assert result.steps[0].skipped is True
    assert result.limitations[0]["reason_code"] == "EVALUATOR_ERROR"


def test_engine_overrides_skipped_evaluator_metadata_from_step_config(monkeypatch):
    def skipped_with_wrong_metadata(_facts, _params):
        return TopRiskStepResult(
            step_id="hard-coded-wrong-id",
            label="错误标签",
            direction="NEUTRAL",
            weight=9,
            step_risk=0,
            confidence=0,
            skipped=True,
            skip_reason="测试跳过",
        )

    monkeypatch.setitem(ev.EVALUATORS, "skipped_wrong_metadata", skipped_with_wrong_metadata)
    engine = TopRiskEngine([
        {
            "id": "configured-id",
            "label": "配置标签",
            "evaluator": "skipped_wrong_metadata",
            "weight": 2.5,
        }
    ])

    result = engine.run(_fact())

    assert result.steps[0].step_id == "configured-id"
    assert result.steps[0].label == "配置标签"
    assert result.steps[0].weight == 2.5
    assert result.steps[0].skipped is True


# ---------------------------------------------------------------------------
# 配置驱动步骤语义（Phase 1：情绪背离 / 事件兑现未启用，不计入评分分母）
# ---------------------------------------------------------------------------
def test_disabled_steps_drop_from_coverage_and_emit_limitation():
    eng = TopRiskEngine.from_yaml(trs._CONFIG_PATH)
    disabled = [s for s in eng.steps if s.get("enabled", True) is False]
    assert len(disabled) == 2  # narrative_divergence, catalyst_priced_in
    assert {s.get("id") for s in disabled} == {"narrative_divergence", "catalyst_priced_in"}

    enabled_count = len(eng.steps) - len(disabled)
    r = eng.run(_high_risk_fact())
    # disabled 步骤产生 CAPABILITY_NOT_ENABLED limitation，且不进入 coverage 分母
    cap_lims = [l for l in r.limitations if l.get("reason_code") == "CAPABILITY_NOT_ENABLED"]
    assert len(cap_lims) == 2
    assert r.coverage["total"] == enabled_count
    assert r.coverage["completed"] == enabled_count
    assert r.status == "normal"


def test_make_input_fingerprint_stable_and_distinct():
    f = _high_risk_fact()
    fp1 = trs.make_input_fingerprint(f)
    fp2 = trs.make_input_fingerprint(f)
    assert fp1 == fp2  # 相同输入 → 稳定指纹（不依赖请求时间/路径/异常）
    assert fp1.startswith("inp_")
    other = _low_risk_fact()
    assert trs.make_input_fingerprint(other) != fp1  # 不同输入 → 不同指纹


def test_make_input_fingerprint_ignores_fund_flow_input_order():
    """资金流记录必须先确定性排序，再进入输入指纹。"""
    rows = [
        {"date": "2026-07-30", "main_net": 1, "marker": "same-date-b"},
        {"main_net": 3, "marker": "missing-date"},
        {"date": "2026-07-29", "main_net": 2, "marker": "older"},
        {"date": "2026-07-30", "main_net": 4, "marker": "same-date-a"},
    ]
    forward = _fact()
    reverse = _fact()
    forward.fund_flow = rows
    reverse.fund_flow = list(reversed(rows))

    assert trs.make_input_fingerprint(forward) == trs.make_input_fingerprint(reverse)


def test_decision_run_id_idempotent_and_input_dependent():
    fp = "inp_abc123"
    cfg = "cfg_xyz789"
    id_a = trace_svc.make_decision_run_id("600519", "2026-07-27", fp, cfg)
    id_b = trace_svc.make_decision_run_id("600519", "2026-07-27", fp, cfg)
    assert id_a == id_b  # 相同逻辑输入 → 同一身份（幂等，不随请求时间变化）
    assert id_a.startswith("tr_")
    # 任一逻辑输入变化 → 不同身份
    assert trace_svc.make_decision_run_id("600519", "2026-07-28", fp, cfg) != id_a
    assert trace_svc.make_decision_run_id("600519", "2026-07-27", "inp_other", cfg) != id_a
    assert trace_svc.make_decision_run_id("600519", "2026-07-27", fp, "cfg_other") != id_a


# ---------------------------------------------------------------------------
# 评估器：方向与数据缺失语义
# ---------------------------------------------------------------------------
def test_crowding_risk_via_margin_rise():
    f = _fact(margin=[{"rzye": 100}, {"rzye": 140}])
    r = ev.crowding(f, {"margin_window": 20, "margin_rise_threshold": 0.25,
                        "turnover_z_threshold": 2.0, "weight": 1.0})
    assert r.skipped is False
    assert r.direction == "RISK"


def test_crowding_skipped_when_no_volume_and_no_margin():
    f = _fact(price=[1, 2, 3], vol=None, margin=None)
    r = ev.crowding(f, {"weight": 1.0})
    assert r.skipped is True


def test_crowding_single_valid_margin_point_without_volume_is_skipped():
    result = ev.crowding(
        _fact(vol=None, margin=[{"rzye": 100}]),
        {"margin_window": 20, "weight": 1.0},
    )

    assert result.skipped is True
    assert result.details == {
        "volume_points": 0,
        "recent_volume_points": 0,
        "margin_points": 1,
    }


def test_crowding_does_not_pull_old_valid_volume_into_empty_recent_window():
    volumes = [100] * 15 + [None] * 5

    result = ev.crowding(_fact(vol=volumes, margin=None), {"weight": 1.0})

    assert result.skipped is True
    assert result.details["volume_points"] == 15
    assert result.details["recent_volume_points"] == 0
    assert result.details["margin_points"] == 0


def test_crowding_skips_when_recent_volume_and_margin_are_both_insufficient():
    volumes = [100] * 15 + [None, 200, None, 200, None]
    margin = [{"rzye": 100}, {"rzye": None}]

    result = ev.crowding(_fact(vol=volumes, margin=margin), {"weight": 1.0})

    assert result.skipped is True
    assert result.details["volume_points"] == 17
    assert result.details["recent_volume_points"] == 2
    assert result.details["margin_points"] == 1


def test_crowding_uses_valid_margin_when_recent_volume_is_insufficient():
    volumes = [100] * 15 + [None, 200, None, 200, None]
    margin = [
        {"rzye": 10},
        {"rzye": 20},
        {"rzye": 100},
        {"rzye": 120},
        {"rzye": 140},
    ]

    result = ev.crowding(
        _fact(vol=volumes, margin=margin),
        {"margin_window": 3, "margin_rise_threshold": 0.25, "weight": 1.0},
    )

    assert result.skipped is False
    assert result.direction == "RISK"
    assert result.details["volume_points"] == 17
    assert result.details["recent_volume_points"] == 2
    assert result.details["margin_points"] == 3
    assert result.details["margin_rise_ratio"] == 0.4


def test_crowding_recent_volume_filtering_does_not_cross_raw_window_boundary():
    volumes = [100] * 20 + [None, None, 300, 400, 500]

    result = ev.crowding(
        _fact(vol=volumes, margin=None),
        {"turnover_z_threshold": 2.0, "weight": 1.0},
    )

    assert result.skipped is False
    assert result.direction == "RISK"
    assert result.details["volume_points"] == 23
    assert result.details["recent_volume_points"] == 3


@pytest.mark.parametrize(
    ("margin_values", "expected_points"),
    [([0, 100], 2), ([-100, -140], 0)],
)
def test_crowding_skips_when_margin_has_no_positive_base(
    margin_values, expected_points
):
    margin = [{"rzye": value} for value in margin_values]

    result = ev.crowding(_fact(vol=None, margin=margin), {"weight": 1.0})

    assert result.skipped is True
    assert result.details["margin_points"] == expected_points


def test_crowding_excludes_infinite_volume_and_margin_points():
    volumes = [100] * 10 + [float("inf")] * 5
    margin = [{"rzye": 100}, {"rzye": float("inf")}]

    result = ev.crowding(_fact(vol=volumes, margin=margin), {"weight": 1.0})

    assert result.skipped is True
    assert result.details == {
        "volume_points": 10,
        "recent_volume_points": 0,
        "margin_points": 1,
    }


def test_crowding_allows_margin_to_fall_from_positive_base_to_zero():
    margin = [{"rzye": 100}, {"rzye": 0}]

    result = ev.crowding(
        _fact(vol=None, margin=margin),
        {"margin_rise_threshold": 0.25, "weight": 1.0},
    )

    assert result.skipped is False
    assert result.direction == "SAFE"
    assert result.details["margin_points"] == 2
    assert result.details["margin_rise_ratio"] == -1.0


def test_crowding_keeps_constant_finite_volume_available():
    result = ev.crowding(_fact(vol=[100] * 10, margin=None), {"weight": 1.0})

    assert result.skipped is False
    assert result.direction == "NEUTRAL"
    assert result.details["volume_points"] == 10
    assert result.details["recent_volume_points"] == 5


def test_engine_is_partial_when_optional_crowding_has_no_usable_subsignal():
    prices = [10 + index * 0.1 for index in range(20)]
    volumes = [100] * 15 + [None] * 5
    engine = TopRiskEngine([
        {
            "id": "crowding",
            "label": "拥挤度",
            "evaluator": "crowding",
            "required": False,
            "weight": 1,
            "params": {},
        },
        {
            "id": "runup_exhaustion",
            "label": "涨幅耗竭",
            "evaluator": "runup_exhaustion",
            "required": True,
            "weight": 1,
            "params": {"window": 20},
        },
        {
            "id": "valuation_cap",
            "label": "估值天花板",
            "evaluator": "valuation_cap",
            "required": False,
            "weight": 1,
            "params": {},
        },
    ])
    facts = _fact(
        price=prices,
        vol=volumes,
        valuation={"pe_ttm": {"percentile": 50}, "pb": {"percentile": 50}},
        margin=None,
    )

    result = engine.run(facts)

    assert result.status == "partial"
    assert result.coverage == {"completed": 2, "total": 3, "ratio": 0.667}
    assert any(
        limitation["field"] == "crowding"
        and limitation["reason_code"] == "OPTIONAL_DATA_MISSING"
        for limitation in result.limitations
    )


def test_valuation_cap_risk_at_high_percentile():
    f = _fact(valuation={"pe_ttm": {"percentile": 95.0}, "pb": {"percentile": 95.0}})
    r = ev.valuation_cap(f, {"weight": 1.0})
    assert r.direction == "RISK"


def test_valuation_cap_safe_at_low_percentile():
    f = _fact(valuation={"pe_ttm": {"percentile": 30.0}, "pb": {"percentile": 30.0}})
    r = ev.valuation_cap(f, {"weight": 1.0})
    assert r.direction == "SAFE"


def test_valuation_cap_skipped_when_missing():
    f = _fact(valuation=None)
    r = ev.valuation_cap(f, {"weight": 1.0})
    assert r.skipped is True


def test_narrative_always_skipped_phase1():
    r = ev.narrative_divergence(_fact(), {"sentiment_required": True, "weight": 1.0})
    assert r.skipped is True


def test_catalyst_always_skipped_phase1():
    r = ev.catalyst_priced_in(_fact(), {"events_required": True, "weight": 1.0})
    assert r.skipped is True


def test_runup_exhaustion_splits_volume_by_original_time_positions():
    """缺量点保留位置：先按原时间区间切分，再在各区间过滤 None。"""
    prices = [10, 11, 12, 13, 14, 15, 16, 17, 18, 20, 19, 18]
    volumes = [100, None, 100, None, 50, None, 50, None, None, 10, None, 10]
    result = ev.runup_exhaustion(
        _fact(price=prices, vol=volumes),
        {
            "window": 12,
            "runup_strong": 0.5,
            "runup_medium": 0.25,
            "vol_shrink_ratio": 0.7,
            "weight": 1.0,
        },
    )

    assert result.details["late_early_vol_ratio"] == 0.1
    assert result.direction == "RISK"


def test_runup_exhaustion_window_ignores_prefix_extremes_and_keeps_alignment():
    """window 只评估尾部同位区间，窗口外价格/量能极值不得污染 60 日结果。"""
    tail_prices = [10 + i * 0.1 for i in range(60)]
    tail_volumes = [200] * 20 + [100] * 20 + [50] * 20
    params = {
        "window": 60,
        "runup_strong": 0.5,
        "runup_medium": 0.25,
        "vol_shrink_ratio": 0.7,
        "weight": 1.0,
    }

    low_prefix = ev.runup_exhaustion(
        _fact(price=[1] * 60 + tail_prices, vol=[10000] * 60 + tail_volumes),
        params,
    )
    high_prefix = ev.runup_exhaustion(
        _fact(price=[1000] * 60 + tail_prices, vol=[1] * 60 + tail_volumes),
        params,
    )

    assert low_prefix.details == high_prefix.details
    assert low_prefix.details["price_points"] == 60
    assert low_prefix.details["runup_ratio"] == 0.59
    assert low_prefix.details["peak_off_ratio"] == 0.0
    assert low_prefix.details["late_early_vol_ratio"] == 0.25


# ---------------------------------------------------------------------------
# 追踪适配：复用 decision_trace_store，不建第二套账本
# ---------------------------------------------------------------------------
def _env(status, code="600519", trade_date="2026-07-27", config_hash="cfg_test"):
    steps = [TopRiskStepTrace(
        step_id="crowding", label="拥挤度", direction="RISK", weight=1.0,
        step_risk=0.5, confidence=80, skipped=False, reasons=["x"], details={},
    )]
    data = TopRiskData(name="测试", completed_steps=1, total_steps=1,
                       risk_drivers=["拥挤度"], safety_signals=[], narrative="n")
    return TopRiskEnvelope(
        schema_version=SCHEMA_VERSION, code=code, trade_date=trade_date,
        fetched_at=datetime.now(timezone.utc).isoformat(timespec="microseconds"),
        status=status, risk_score=50, confidence=80,
        coverage={"completed": 1, "total": 1, "ratio": 0.2},
        config_hash=config_hash, decision_run_id=None, trace_archive_status=None,
        limitations=[], data=data, trace=steps,
    )


def test_trace_archive_normal_writes_run_and_evidence(tmp_path):
    db = str(tmp_path / "dt.sqlite3")
    env = _env("normal")
    rid, status = trace_svc.archive_top_risk(env, db_path=db)
    assert status == "archived"
    assert rid and rid.startswith("tr_")
    rec = store.get_decision_run(rid, db_path=db)
    assert rec is not None
    assert rec["decision_run"]["result_type"] == "top_risk_analysis"
    keys = {e["evidence_key"] for e in rec["evidence_items"]}
    assert "top_risk.crowding" in keys
    assert "top_risk.summary" in keys
    assert len(rec["explanation_items"]) == 1


def test_trace_unavailable_explicitly_not_archived(tmp_path):
    db = str(tmp_path / "dt.sqlite3")
    env = _env("unavailable")
    rid, status = trace_svc.archive_top_risk(env, db_path=db)
    assert rid is None
    assert status == "skipped"
    assert store.get_decision_run("tr_anything", db_path=db) is None


def test_trace_different_stocks_unique_ids(tmp_path):
    db = str(tmp_path / "dt.sqlite3")
    r1, _ = trace_svc.archive_top_risk(_env("normal", code="600519"), db_path=db)
    r2, _ = trace_svc.archive_top_risk(_env("normal", code="000001"), db_path=db)
    assert r1 != r2


def test_trace_no_collision_with_portfolio_advice(tmp_path):
    db = str(tmp_path / "dt.sqlite3")
    rid, _ = trace_svc.archive_top_risk(
        _env("normal", code="600519", trade_date="2026-07-27"), db_path=db
    )
    pa_id = des.generate_decision_run_id("2026-07-27", "2026-07-27T08:00:00+00:00")
    assert rid != pa_id


def test_trace_archive_failure_is_safe(tmp_path, monkeypatch):
    db = str(tmp_path / "dt.sqlite3")

    def boom(*a, **k):
        raise RuntimeError("db down")

    monkeypatch.setattr(trace_svc.store, "save_decision_run_bundle", boom)
    rid, status = trace_svc.archive_top_risk(_env("normal"), db_path=db)
    assert rid is None
    assert status == "failed"


# ---------------------------------------------------------------------------
# 决策追踪：result_type 可选筛选（旧行为不变）
# ---------------------------------------------------------------------------
def test_decision_trace_result_type_filter(tmp_path):
    db = str(tmp_path / "dt.sqlite3")
    trace_svc.archive_top_risk(
        _env("normal", code="600519", trade_date="2026-07-27"), db_path=db
    )
    pa_id = des.generate_decision_run_id("2026-07-27", "2026-07-27T08:00:00+00:00")
    store.save_decision_run_bundle(
        {
            "decision_run_id": pa_id, "trade_date": "2026-07-27",
            "generated_at": "2026-07-27T08:00:00+00:00", "result_type": "portfolio_advice",
            "schema_version": "x", "market_status": "normal",
            "source_fingerprint": None, "trace_status": "archived",
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
        [{
            "evidence_id": pa_id + ":ev", "decision_run_id": pa_id, "scope": "stock",
            "code": "600519", "evidence_key": "pa.summary", "value_json": {"x": 1},
            "unit": None, "source_module": "portfolio_advice", "observed_at": None,
            "quality_status": "valid", "source_ref_json": None,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }],
        [],
        db_path=db,
    )

    all_items = store.list_evidence_items(db_path=db)["items"]
    # top_risk 归档含 1 步证据 + 1 汇总证据 = 2 条；portfolio_advice = 1 条
    assert len(all_items) == 3
    tr_only = store.list_evidence_items(result_type="top_risk_analysis", db_path=db)["items"]
    assert len(tr_only) == 2
    assert tr_only[0]["result_type"] == "top_risk_analysis"
    pa_only = store.list_evidence_items(result_type="portfolio_advice", db_path=db)["items"]
    assert len(pa_only) == 1
    assert pa_only[0]["result_type"] == "portfolio_advice"


# ---------------------------------------------------------------------------
# Data Health：完整注册 + 状态映射
# ---------------------------------------------------------------------------
def test_top_risk_adapter_registered_and_count_matches():
    ids = [ad.source_id for ad in adapters.build_adapters()]
    assert "top_risk_analysis" in ids
    assert len(adapters.build_adapters()) == len(dh_svc.SOURCE_REGISTRY)


def test_top_risk_adapter_status_mapping(tmp_path, monkeypatch):
    monkeypatch.setenv("VR_DATA_DIR", str(tmp_path))
    adapters.reset_adapters_for_tests()

    now = datetime.now(timezone.utc)

    dh_store.record_success("top_risk_analysis")
    rec = adapters.TopRiskAnalysisAdapter().read(
        adapters.HealthReadContext(now_utc=now, events=dh_store.load_events_readonly())
    )
    assert rec["status"] == "normal"

    dh_store.record_partial("top_risk_analysis")
    rec = adapters.TopRiskAnalysisAdapter().read(
        adapters.HealthReadContext(now_utc=now, events=dh_store.load_events_readonly())
    )
    assert rec["status"] == "partial"

    dh_store.record_failure("top_risk_analysis", "SOURCE_UNAVAILABLE")
    rec = adapters.TopRiskAnalysisAdapter().read(
        adapters.HealthReadContext(now_utc=now, events=dh_store.load_events_readonly())
    )
    assert rec["status"] == "unavailable"


# ---------------------------------------------------------------------------
# 服务层：analyze_top_risk（打桩取数，避免 live）
# ---------------------------------------------------------------------------
def test_analyze_top_risk_normal_and_archived(tmp_path, monkeypatch):
    monkeypatch.setenv("VR_DATA_DIR", str(tmp_path))
    db = str(tmp_path / "decision_trace.sqlite3")
    monkeypatch.setattr(trs, "_build_facts", lambda code, days: (_high_risk_fact(), []))
    env = trs.analyze_top_risk("600519")
    assert env.status == "normal"
    assert env.decision_run_id and env.decision_run_id.startswith("tr_")
    assert env.trace_archive_status == "archived"
    assert env.signal == "unknown"
    assert env.signal_eligible is False
    rec = store.get_decision_run(env.decision_run_id, db_path=db)
    assert rec is not None
    assert rec["decision_run"]["result_type"] == "top_risk_analysis"


def test_analyze_top_risk_unavailable_skips_archive(tmp_path, monkeypatch):
    monkeypatch.setenv("VR_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(
        trs,
        "_build_facts",
        lambda code, days: (
            _fact(price=None, vol=None, valuation=None, margin=None),
            [{"field": "x", "reason_code": "SOURCE_UNAVAILABLE", "detail": "t"}],
        ),
    )
    env = trs.analyze_top_risk("600519")
    assert env.status == "unavailable"
    assert env.decision_run_id is None
    assert env.trace_archive_status == "skipped"
    assert env.signal == "unknown"


@pytest.mark.parametrize(
    ("now_bj", "trade_date", "expected_stale"),
    [
        pytest.param(
            datetime(2026, 8, 1, 12, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
            "2026-07-31",
            False,
            id="weekend-uses-friday",
        ),
        pytest.param(
            datetime(2026, 8, 3, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
            "2026-07-31",
            False,
            id="monday-preopen-uses-friday",
        ),
        pytest.param(
            datetime(2026, 8, 3, 15, 15, tzinfo=ZoneInfo("Asia/Shanghai")),
            "2026-07-31",
            False,
            id="close-grace-allows-friday",
        ),
        pytest.param(
            datetime(2026, 8, 3, 15, 31, tzinfo=ZoneInfo("Asia/Shanghai")),
            "2026-07-31",
            True,
            id="after-close-requires-monday",
        ),
    ],
)
def test_analyze_top_risk_uses_authoritative_cn_trade_clock(
    tmp_path, monkeypatch, now_bj, trade_date, expected_stale
):
    """四类权威时点都必须经成功 analyze 信封产生 freshness 结果。"""
    monkeypatch.setenv("VR_DATA_DIR", str(tmp_path))
    facts = _high_risk_fact()
    facts.trade_date = trade_date
    monkeypatch.setattr(trs, "_build_facts", lambda code, days: (facts, []))

    calls = []
    now_utc = now_bj.astimezone(timezone.utc)
    monkeypatch.setattr(
        trs,
        "_now_utc",
        lambda: calls.append(now_utc) or now_utc,
    )

    env = trs.analyze_top_risk("600519")

    assert calls == [now_utc]
    assert env.status == "normal"
    assert env.trade_date == trade_date
    assert env.is_stale is expected_stale


@pytest.mark.parametrize(
    ("before_bj", "after_bj"),
    [
        pytest.param(
            datetime(2026, 8, 3, 9, 29, tzinfo=ZoneInfo("Asia/Shanghai")),
            datetime(2026, 8, 3, 9, 30, tzinfo=ZoneInfo("Asia/Shanghai")),
            id="cross-0930",
        ),
        pytest.param(
            datetime(2026, 8, 3, 15, 29, tzinfo=ZoneInfo("Asia/Shanghai")),
            datetime(2026, 8, 3, 15, 30, tzinfo=ZoneInfo("Asia/Shanghai")),
            id="cross-1530",
        ),
    ],
)
def test_analyze_top_risk_cache_hit_recomputes_freshness_without_pollution(
    tmp_path, monkeypatch, before_bj, after_bj
):
    """缓存命中跨交易边界时重算 stale，且不修改旧信封或缓存原始字典。"""
    monkeypatch.setenv("VR_DATA_DIR", str(tmp_path))
    facts = _high_risk_fact()
    facts.trade_date = "2026-07-31"  # Friday
    build_calls = []
    monkeypatch.setattr(
        trs,
        "_build_facts",
        lambda code, days: build_calls.append((code, days)) or (facts, []),
    )
    monkeypatch.setattr(trs, "archive_top_risk", lambda _envelope: (None, "skipped"))
    monkeypatch.setattr(trs, "_record_health", lambda _status: None)
    current = {"now": before_bj.astimezone(timezone.utc)}
    monkeypatch.setattr(trs, "_now_utc", lambda: current["now"])

    before = trs.analyze_top_risk("600519")
    current["now"] = after_bj.astimezone(timezone.utc)
    after = trs.analyze_top_risk("600519")

    assert len(build_calls) == 1  # 第二次必须真实命中 cache
    assert before.is_stale is False
    assert after.is_stale is True
    assert before.is_stale is False  # cache hit 不得回写污染旧返回对象
    cache_payload = next(iter(trs._CACHE.values()))[1]
    assert cache_payload["is_stale"] is False


def test_public_unavailable_envelope_is_stale_and_fail_closed():
    """service 的真实 unavailable 信封在无交易日时必须陈旧并禁止信号。"""
    env = trs.unavailable_envelope(
        "600519",
        [{"field": "test", "reason_code": "TEST", "detail": "测试"}],
    )

    assert env.status == "unavailable"
    assert env.trade_date is None
    assert env.is_stale is True
    assert env.signal_eligible is False


# ---------------------------------------------------------------------------
# API：GET /api/market/top-risk（打桩 analyze，验证信封含追踪身份）
# ---------------------------------------------------------------------------
def test_api_top_risk_endpoint_returns_trace_identity(tmp_path, monkeypatch):
    monkeypatch.setenv("VR_DATA_DIR", str(tmp_path))

    def fake(code, days=120):
        e = _env("normal", code=code, trade_date="2026-07-27")
        e.decision_run_id = "tr_api_test"
        e.trace_archive_status = "archived"
        return e

    monkeypatch.setattr(trs, "analyze_top_risk", fake)
    from fastapi.testclient import TestClient

    import app as app_module

    client = TestClient(app_module.app)
    resp = client.get("/api/market/top-risk?code=600519")
    assert resp.status_code == 200
    d = resp.json()["data"]
    assert d["status"] == "normal"
    assert d["decision_run_id"].startswith("tr_")
    assert d["trace_archive_status"] == "archived"
    assert "risk_score" in d and "coverage" in d


def test_api_top_risk_runtime_error_returns_fail_closed_envelope(tmp_path, monkeypatch):
    """路由兜底不得因 service 异常再触发 AttributeError/500。"""
    monkeypatch.setenv("VR_DATA_DIR", str(tmp_path))

    def boom(*_args, **_kwargs):
        raise RuntimeError("upstream failed")

    monkeypatch.setattr(trs, "analyze_top_risk", boom)
    from fastapi.testclient import TestClient

    import app as app_module

    client = TestClient(app_module.app, raise_server_exceptions=False)
    resp = client.get("/api/market/top-risk?code=600519")

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["status"] == "unavailable"
    assert data["trade_date"] is None
    assert data["is_stale"] is True
    assert data["signal_eligible"] is False


def test_api_top_risk_empty_code_rejected():
    from fastapi.testclient import TestClient

    import app as app_module

    client = TestClient(app_module.app)
    resp = client.get("/api/market/top-risk?code=")
    # 空 code 被 FastAPI Query(min_length=1) 拦截 → 422（标准校验错误）
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# K 线标准化（确定性、去重、排序、volume 语义）
# ---------------------------------------------------------------------------
def test_kline_normalize_datetime_field_input():
    """K 线 bar 使用 datetime（而非 date）字段时应被正确解析。"""
    bars = [
        {"datetime": "2026-07-27 15:00:00", "close": 10.0, "volume": 1000},
        {"datetime": "2026-07-28 15:00:00", "close": 10.2, "volume": 1100},
        {"datetime": "2026-07-29 15:00:00", "close": 10.5, "volume": 1200},
    ]
    prices, vols, tdate = trs._normalize_kline(bars)
    assert prices == [10.0, 10.2, 10.5]
    assert vols == [1000.0, 1100.0, 1200.0]
    assert tdate == "2026-07-29"


def test_kline_normalize_date_field_input():
    """K 线 bar 使用 date 字段时应被正确解析。"""
    bars = [
        {"date": "2026-07-27", "close": 10.0, "volume": 1000},
        {"date": "2026-07-28", "close": 10.2, "volume": 1100},
    ]
    prices, vols, tdate = trs._normalize_kline(bars)
    assert prices == [10.0, 10.2]
    assert vols == [1000.0, 1100.0]
    assert tdate == "2026-07-28"


def test_kline_normalize_reverse_order_returns_ascending():
    """倒序 K 线输入应被标准化为升序，infer 时间方向不依赖上游顺序。"""
    bars = [
        {"date": "2026-07-29", "close": 10.5, "volume": 1200},
        {"date": "2026-07-28", "close": 10.2, "volume": 1100},
        {"date": "2026-07-27", "close": 10.0, "volume": 1000},
    ]
    prices, vols, tdate = trs._normalize_kline(bars)
    assert prices == [10.0, 10.2, 10.5]
    assert vols == [1000.0, 1100.0, 1200.0]
    assert tdate == "2026-07-29"


def test_kline_normalize_reverse_and_forward_same_result():
    """倒序与正序输入结果一致（确定性）。"""
    forward = [
        {"date": "2026-07-27", "close": 10.0, "volume": 1000},
        {"date": "2026-07-28", "close": 10.2, "volume": 1100},
        {"date": "2026-07-29", "close": 10.5, "volume": 1200},
    ]
    reverse = list(reversed(forward))
    p1, v1, t1 = trs._normalize_kline(forward)
    p2, v2, t2 = trs._normalize_kline(reverse)
    assert p1 == p2
    assert v1 == v2
    assert t1 == t2


def test_kline_normalize_duplicate_date_priority_is_input_order_independent():
    """同日优先有效量、较晚完整 datetime，再以数值 tie-break；正反序结果一致。"""
    bars = [
        {"date": "2026-07-29", "close": 10.0, "volume": 100},
        {"date": "2026-07-30", "close": 12.0, "amount": 999999},
        {"datetime": "2026-07-30 14:00:00", "close": 13.0, "volume": 130},
        {"datetime": "2026-07-30 15:00:00", "close": 11.0, "volume": 110},
        {"date": "2026-07-31", "close": 14.0, "volume": 140},
    ]

    forward = trs._normalize_kline(bars)
    reverse = trs._normalize_kline(list(reversed(bars)))

    assert forward == reverse
    assert forward == (
        [10.0, 11.0, 14.0],
        [100.0, 110.0, 140.0],
        "2026-07-31",
    )


def test_kline_normalize_dedup_by_date():
    """相同日期的重复 bar 去重（仅保留首次出现）。"""
    bars = [
        {"date": "2026-07-27", "close": 10.0, "volume": 1000},
        {"date": "2026-07-27", "close": 9.5, "volume": 900},  # duplicate date
        {"date": "2026-07-28", "close": 10.2, "volume": 1100},
    ]
    prices, vols, tdate = trs._normalize_kline(bars)
    assert prices == [10.0, 10.2]
    assert vols == [1000.0, 1100.0]
    assert tdate == "2026-07-28"


def test_kline_normalize_missing_volume_stays_none():
    """缺失 volume 保留 None，严禁转换为 0。"""
    bars = [
        {"date": "2026-07-27", "close": 10.0, "volume": None},
        {"date": "2026-07-28", "close": 10.2},  # no volume key at all
    ]
    prices, vols, tdate = trs._normalize_kline(bars)
    assert prices == [10.0, 10.2]
    assert vols == [None, None]
    assert tdate == "2026-07-28"


def test_kline_normalize_only_amount_no_fallback():
    """仅存在 amount 时绝不回退到 amount，volume 为 None。"""
    bars = [
        {"date": "2026-07-27", "close": 10.0, "amount": 1e8},
        {"date": "2026-07-28", "close": 10.2, "amount": 1.1e8},
    ]
    prices, vols, tdate = trs._normalize_kline(bars)
    assert prices == [10.0, 10.2]
    # amount 绝不能作为 volume 的回退
    assert vols == [None, None]


def test_kline_normalize_missing_volume_not_becomes_zero():
    """明确验证：缺失 volume 不得转为 0（0 会错误传递信号）。"""
    bars = [
        {"date": "2026-07-27", "close": 10.0},
        {"date": "2026-07-28", "close": 10.2, "volume": 0},
    ]
    prices, vols, tdate = trs._normalize_kline(bars)
    # 0 是合法的 volume 值，保留为 0.0；缺失 → None
    assert vols[0] is None  # 缺失
    assert vols[1] == 0.0   # 显式 0


def test_build_facts_normalizes_real_astock_wiring_and_feeds_analyze(
    tmp_path, monkeypatch
):
    """单次 analyze 完整走 astock→build facts→engine→信封/指纹。"""
    import astock

    monkeypatch.setenv("VR_DATA_DIR", str(tmp_path))
    bars = [
        {"date": "2026-07-31", "close": 13, "volume": 300},
        {"date": "2026-07-30", "close": 12, "amount": 999999},
        {"date": "2026-07-30", "close": 11, "volume": 110},
        {"datetime": "2026-07-29 15:00:00", "close": 10, "amount": 777777},
    ]
    fund_flow = [
        {"date": "2026-07-31", "main_net": 30, "marker": "same-b"},
        {"main_net": 40, "marker": "missing-b"},
        {"date": "2026-07-30", "main_net": 10, "marker": "older"},
        {"date": "2026-07-31", "main_net": 20, "marker": "same-a"},
        {"main_net": 0, "marker": "missing-a"},
    ]
    margin = [
        {"date": "2026-07-31", "rzye": 140, "marker": "same-b"},
        {"rzye": None, "marker": "missing"},
        {"date": "2026-07-30", "rzye": 100, "marker": "older"},
        {"date": "2026-07-31", "rzye": 120, "marker": "same-a"},
    ]

    monkeypatch.setattr(
        astock, "tencent_quote", lambda codes: {codes[0]: {"name": "接线测试股"}}
    )
    monkeypatch.setattr(astock, "kline", lambda *_args, **_kwargs: bars)
    monkeypatch.setattr(
        astock,
        "valuation_percentile",
        lambda _code: {
            "metrics": {
                "pe_ttm": {"percentile": 50},
                "pb": {"percentile": 50},
            }
        },
    )
    monkeypatch.setattr(astock, "stock_fund_flow_120d", lambda _code: fund_flow)
    monkeypatch.setattr(astock, "margin_trading", lambda *_args, **_kwargs: margin)
    monkeypatch.setattr(trs, "archive_top_risk", lambda _envelope: (None, "skipped"))
    monkeypatch.setattr(trs, "_record_health", lambda _status: None)
    fixed_now = datetime(
        2026, 7, 31, 15, 31, tzinfo=ZoneInfo("Asia/Shanghai")
    ).astimezone(timezone.utc)
    monkeypatch.setattr(trs, "_now_utc", lambda: fixed_now)

    engine = trs._get_engine()
    real_run = engine.run
    captured_facts = []

    def capture_and_run(facts):
        captured_facts.append(facts)
        return real_run(facts)

    monkeypatch.setattr(engine, "run", capture_and_run)
    envelope = trs.analyze_top_risk("600519")

    assert len(captured_facts) == 1
    facts = captured_facts[0]
    assert facts.price_history == [10.0, 11.0, 13.0]
    assert facts.volume_history == [None, 110.0, 300.0]
    assert facts.trade_date == "2026-07-31"
    assert [row["marker"] for row in facts.fund_flow] == [
        "older", "same-a", "same-b", "missing-a", "missing-b"
    ]
    assert [row["marker"] for row in facts.margin_trading] == [
        "older", "same-a", "same-b", "missing"
    ]
    assert len(facts.fund_flow) == len(fund_flow)
    assert len(facts.margin_trading) == len(margin)

    crowding_step = next(step for step in envelope.trace if step.step_id == "crowding")

    assert crowding_step.direction == "RISK"
    assert crowding_step.details["margin_rise_ratio"] == 0.4
    assert envelope.input_fingerprint == trs.make_input_fingerprint(facts)


# ---------------------------------------------------------------------------
# 融资融券 & 资金流排序
# ---------------------------------------------------------------------------
def test_margin_sorted_ascending_before_engine():
    """margin_trading 按日期升序排序（正确方向推断）。"""
    margin_raw = [
        {"date": "2026-07-30", "rzye": 140},
        {"date": "2026-07-29", "rzye": 120},
        {"date": "2026-07-28", "rzye": 100},
    ]
    sorted_rows = trs._sort_by_date(margin_raw)
    assert [r["rzye"] for r in sorted_rows] == [100, 120, 140]


def test_margin_rising_sequence_yields_risk():
    """融资余额上升 → margin_rise 为正 → RISK。"""
    from top_risk_evaluators import crowding

    # 构建已按日期升序排列的事实
    margin_asc = [
        {"date": "2026-07-28", "rzye": 100},
        {"date": "2026-07-29", "rzye": 120},
        {"date": "2026-07-30", "rzye": 140},
    ]
    f = _fact(margin=margin_asc)
    r = crowding(f, {"margin_window": 3, "margin_rise_threshold": 0.25,
                     "turnover_z_threshold": 2.0, "weight": 1.0})
    assert r.skipped is False
    assert r.direction == "RISK"


def test_margin_falling_sequence_yields_safe():
    """融资余额下降 → SAFE（方向正确，非反向判断）。"""
    from top_risk_evaluators import crowding

    margin_desc = [
        {"date": "2026-07-28", "rzye": 140},
        {"date": "2026-07-29", "rzye": 120},
        {"date": "2026-07-30", "rzye": 100},
    ]
    f = _fact(margin=margin_desc)
    r = crowding(f, {"margin_window": 3, "margin_rise_threshold": 0.25,
                     "turnover_z_threshold": 2.0, "weight": 1.0})
    assert r.direction == "SAFE"


def test_fund_flow_sorted_for_deterministic_fingerprint():
    """fund_flow 按日期排序保证指纹确定性——上游返回顺序不影响身份。"""
    ff_a = [
        {"date": "2026-07-30", "main_net": 1},
        {"date": "2026-07-29", "main_net": 2},
        {"date": "2026-07-28", "main_net": 3},
    ]
    ff_b = [
        {"date": "2026-07-28", "main_net": 3},
        {"date": "2026-07-29", "main_net": 2},
        {"date": "2026-07-30", "main_net": 1},
    ]
    assert trs._sort_by_date(ff_a) == trs._sort_by_date(ff_b)


def test_sort_by_date_is_deterministic_with_duplicate_and_missing_dates():
    """相同记录任意重排都得到同一顺序，重复/缺日期记录均不得丢失。"""
    rows = [
        {"date": "2026-07-30", "main_net": 3, "marker": "same-date-b"},
        {"main_net": 4, "marker": "missing-b"},
        {"date": "2026-07-29", "main_net": 2, "marker": "older"},
        {"date": "2026-07-30", "main_net": 1, "marker": "same-date-a"},
        {"main_net": 0, "marker": "missing-a"},
    ]

    sorted_forward = trs._sort_by_date(rows)
    sorted_reverse = trs._sort_by_date(list(reversed(rows)))

    assert sorted_forward == sorted_reverse
    assert len(sorted_forward) == len(rows)
    assert {row["marker"] for row in sorted_forward} == {row["marker"] for row in rows}


def test_same_date_business_tie_ignores_marker_for_fingerprint_and_margin_direction():
    """无关 marker 与输入反转不得改变业务投影顺序、指纹或融资方向。"""
    margin_a = [
        {"date": "2026-07-29", "rzye": 100, "marker": "base"},
        {"date": "2026-07-30", "rzye": 100, "marker": "z"},
        {"date": "2026-07-30", "rzye": 140, "marker": "a"},
    ]
    margin_b = [
        {"date": "2026-07-30", "rzye": 140, "marker": "z"},
        {"date": "2026-07-30", "rzye": 100, "marker": "a"},
        {"date": "2026-07-29", "rzye": 100, "marker": "changed-base"},
    ]
    fund_a = [
        {"date": "2026-07-30", "main_net": 20, "marker": "z"},
        {"date": "2026-07-30", "main_net": 10, "marker": "a"},
    ]
    fund_b = [
        {"date": "2026-07-30", "main_net": 10, "marker": "z"},
        {"date": "2026-07-30", "main_net": 20, "marker": "a"},
    ]

    facts_a = _fact(margin=margin_a)
    facts_b = _fact(margin=margin_b)
    facts_a.fund_flow = fund_a
    facts_b.fund_flow = fund_b

    assert trs.make_input_fingerprint(facts_a) == trs.make_input_fingerprint(facts_b)
    sorted_a = trs._sort_by_date(margin_a, tie_fields=("rzye", "rzmre", "rzche"))
    sorted_b = trs._sort_by_date(margin_b, tie_fields=("rzye", "rzmre", "rzche"))
    assert [row["rzye"] for row in sorted_a] == [100, 100, 140]
    assert [row["rzye"] for row in sorted_b] == [100, 100, 140]

    result_a = ev.crowding(
        _fact(margin=sorted_a),
        {"margin_window": 3, "margin_rise_threshold": 0.25,
         "turnover_z_threshold": 2.0, "weight": 1.0},
    )
    result_b = ev.crowding(
        _fact(margin=sorted_b),
        {"margin_window": 3, "margin_rise_threshold": 0.25,
         "turnover_z_threshold": 2.0, "weight": 1.0},
    )
    assert result_a.direction == result_b.direction == "RISK"


# ---------------------------------------------------------------------------
# 时间合同：UTC ISO-8601 格式 + 陈旧判断
# ---------------------------------------------------------------------------
def test_utc_now_format():
    """_utc_now() 产出的时间戳必须是 ISO-8601 可解析格式，禁止 ...00.Z。"""
    ts = trs._utc_now()
    # 包含正确微秒
    assert ts.endswith("Z")
    # 无 ...00.Z 缺陷（微秒不足 6 位时的尾部 0）
    # 格式：2026-07-30T09:30:12.123456Z
    assert "." in ts
    dot_idx = ts.index(".")
    frac = ts[dot_idx + 1 : -1]  # 去掉 Z
    assert len(frac) == 6, f"fractional seconds must be 6 digits, got {len(frac)}"
    # 必须是 ISO parseable
    parsed = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    assert parsed.tzinfo is not None


def test_is_stale_recent_trade_date_false():
    """最近有效交易日 → is_stale=False。"""
    from datetime import timedelta
    from zoneinfo import ZoneInfo

    BEIJING = ZoneInfo("Asia/Shanghai")
    now_bj = datetime.now(BEIJING)
    today_str = now_bj.strftime("%Y-%m-%d")
    assert trs._compute_is_stale(today_str) is False


def test_is_stale_expired_trade_date_true():
    """明显过期交易日 → is_stale=True。"""
    assert trs._compute_is_stale("2020-01-01") is True


def test_is_stale_none_trade_date_true():
    """trade_date=None → is_stale=True（不得伪装为新鲜）。"""
    assert trs._compute_is_stale(None) is True


def test_is_stale_cn_trade_date_weekend_uses_friday():
    saturday = datetime(
        2026, 8, 1, 12, 0, tzinfo=ZoneInfo("Asia/Shanghai")
    ).astimezone(timezone.utc)
    assert trs._compute_is_stale("2026-07-31", now_utc=saturday) is False
    assert trs._compute_is_stale("2026-07-30", now_utc=saturday) is True


def test_is_stale_cn_trade_date_monday_preopen_uses_friday():
    monday_preopen = datetime(
        2026, 8, 3, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai")
    ).astimezone(timezone.utc)
    assert trs._compute_is_stale("2026-07-31", now_utc=monday_preopen) is False
    assert trs._compute_is_stale("2026-07-30", now_utc=monday_preopen) is True


def test_is_stale_cn_trade_date_close_grace_allows_friday():
    monday_grace = datetime(
        2026, 8, 3, 15, 15, tzinfo=ZoneInfo("Asia/Shanghai")
    ).astimezone(timezone.utc)
    assert trs._compute_is_stale("2026-07-31", now_utc=monday_grace) is False
    assert trs._compute_is_stale("2026-07-30", now_utc=monday_grace) is True


def test_is_stale_cn_trade_date_after_close_requires_monday():
    monday_after_close = datetime(
        2026, 8, 3, 15, 31, tzinfo=ZoneInfo("Asia/Shanghai")
    ).astimezone(timezone.utc)
    assert trs._compute_is_stale("2026-07-31", now_utc=monday_after_close) is True
    assert trs._compute_is_stale("2026-08-03", now_utc=monday_after_close) is False


# ---------------------------------------------------------------------------
# 公共 service 函数：unavailable_envelope + attach_trace_and_archive
# ---------------------------------------------------------------------------
def test_public_unavailable_envelope_returns_fail_closed():
    """公共 unavailable_envelope 函数返回完整的 fail-closed 信封。"""
    env = trs.unavailable_envelope(
        "600519",
        [{"field": "test", "reason_code": "TEST", "detail": "测试"}],
        name="测试",
    )
    assert env.status == "unavailable"
    assert env.risk_score is None
    assert env.trace_archive_status == "skipped"
    assert env.code == "600519"


def test_public_attach_trace_and_archive_returns_envelope(tmp_path, monkeypatch):
    """公共 attach_trace_and_archive 函数归档并回填追踪身份。"""
    monkeypatch.setenv("VR_DATA_DIR", str(tmp_path))
    env = trs.unavailable_envelope(
        "600519",
        [{"field": "test", "reason_code": "TEST", "detail": "测试"}],
    )
    result = trs.attach_trace_and_archive(env)
    assert result is env
    assert result.trace_archive_status == "skipped"
    assert result.decision_run_id is None
