"""顶部风险分析：引擎、评估器、追踪适配、服务、决策追踪过滤、Data Health、API。

所有测试均非 live（不访问真实行情/估值/资金接口）：
- engine / evaluators 用合成 TopRiskFact；
- trace / service 用临时 VR_DATA_DIR 隔离 SQLite 与事件文件；
- API 测试对 analyze_top_risk 打桩，避免取数。
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

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


def test_api_top_risk_empty_code_rejected():
    from fastapi.testclient import TestClient

    import app as app_module

    client = TestClient(app_module.app)
    resp = client.get("/api/market/top-risk?code=")
    # 空 code 被 FastAPI Query(min_length=1) 拦截 → 422（标准校验错误）
    assert resp.status_code == 422
