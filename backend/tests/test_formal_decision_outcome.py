"""P0-O1 正式决策结果来源投影核心测试：纯领域逻辑，无 I/O。"""
from __future__ import annotations

import inspect
import re
import sqlite3
from datetime import datetime, timedelta

import pytest

import formal_decision_outcome as fdo
import frozen_decision_store as fd_store
from formal_trade_attribution import (
    AttributionConflictError,
    AttributionValidationError,
    create_attribution,
)
from formal_decision_outcome import (
    EXECUTION_SUMMARY_STATES,
    PERFORMANCE_EVIDENCE_STATES,
    REASON_NO_EXECUTED_TRADE,
    REASON_NO_PERFORMANCE_EVIDENCE,
    FormalDecisionOutcome,
    OutcomeEvidenceConflictError,
    OutcomeValidationError,
    PerformanceEvidence,
    project_outcome,
    validate_evidence,
)

COMMITTED_AT = "2026-08-10T06:00:00.000000Z"
TRADE_CREATED_AT = "2026-08-10T06:30:00.000000+00:00"
TRADE_EXECUTED_AT = "2026-08-10T06:45:00.000000+00:00"
REVIEW_BY = "2026-08-25T00:00:00.000000Z"
ATTRIBUTION_CREATED_AT = "2026-08-10T07:00:00.000000Z"
MEASUREMENT_START = "2026-08-10T08:00:00.000000Z"
MEASUREMENT_END = "2026-08-10T09:00:00.000000Z"
AS_OF = "2026-08-10T09:30:00.000000Z"

DECISION_ID = "decision_" + "a" * 32
CAMPAIGN_ID = "campaign_" + "d" * 32
THESIS_ID = "e" * 32
SECURITY = "600519"


# ---------------------------------------------------------------------------
# 构造 helpers（与 TB1 测试同形；decision 为 FD1 服务产物形状）
# ---------------------------------------------------------------------------

def _snapshot(**overrides) -> dict:
    snapshot = {
        "snapshot_schema_version": fd_store.SCHEMA_VERSION,
        "decision_id": DECISION_ID,
        "security_code": SECURITY,
        "strategy": "SWING",
        "campaign_id": CAMPAIGN_ID,
        "committed_at": COMMITTED_AT,
        "thesis_id": THESIS_ID,
        "thesis_revision": 2,
        "asset_view": {"label": "贵州茅台", "pe": 30.5},
        "trade_view": {"entry_zone": [1400, 1450], "size_pct": 0.1},
        "portfolio_view": {"target_weight": 0.15},
        "next_best_action": "BUY SMALL",
        "action_envelope": {"max_size": 0.1, "min_size": 0.05},
        "maintain_conditions": ["营收增速保持"],
        "upgrade_conditions": ["站稳年线"],
        "downgrade_conditions": ["跌破 60 日线"],
        "invalidation_conditions": ["业绩暴雷"],
        "strategy_horizon": "2 至 4 周",
        "review_by": REVIEW_BY,
        "key_assumptions": ["宏观流动性宽松"],
        "event_invalidation_conditions": ["减持公告"],
        "validity_status_at_commit": "CURRENT",
        "risk_policy_version": "risk-policy-v0.1",
        "opportunity_policy_version": "opp-policy-v0.1",
        "decision_policy_version": "decision-policy-v0.1",
        "behavior_model_version": "behavior-v0.1",
        "data_quality": {"grade": "high"},
        "evidence_confidence": 0.8,
        "inference_confidence": "medium",
        "decision_confidence": None,
        "evidence_refs": ["ev_123"],
        "risk_refs": [],
        "source_refs": ["src_1"],
    }
    snapshot.update(overrides)
    return snapshot


def make_decision(**overrides) -> dict:
    snapshot = _snapshot(**{k: v for k, v in overrides.items() if k in fd_store.SNAPSHOT_KEYS})
    frozen = {
        **snapshot,
        "snapshot_json": fd_store.canonical_json(snapshot),
        "snapshot_hash": fd_store.snapshot_hash(snapshot),
        "user_confirmed": True,
        "created_at": "2026-08-10T05:00:00.000000Z",
    }
    frozen.update({k: v for k, v in overrides.items() if k not in fd_store.SNAPSHOT_KEYS})
    return frozen


def make_trade(**overrides) -> dict:
    trade = {
        "trade_id": "1" * 32,
        "code": SECURITY,
        "name": "贵州茅台",
        "operation": "buy",
        "execution_status": "full",
        "planned_price": 1500.0,
        "planned_quantity": 100,
        "actual_price": 1500.0,
        "actual_quantity": 100,
        "executed_at": TRADE_EXECUTED_AT,
        "fee": 0.0,
        "other_cost": 0.0,
        "unexecuted_reason": None,
        "note": None,
        "advice_trade_date": None,
        "advice_generated_at": None,
        "advice_snapshot": None,
        "thesis_id": THESIS_ID,
        "thesis_revision": 2,
        "created_at": TRADE_CREATED_AT,
        "voided_at": None,
        "void_reason": None,
    }
    trade.update(overrides)
    return trade


def _attribution(
    trade: dict | None = None,
    decision: dict | None = None,
    attribution_id: str = "trade_attribution_" + "1" * 32,
) -> dict:
    return create_attribution(
        decision or make_decision(),
        trade or make_trade(),
        attribution_id=attribution_id,
        created_at=ATTRIBUTION_CREATED_AT,
    )


def _evidence(
    trade_ids=("1" * 32,),
    evidence_id: str = "e" * 32,
    security_code: str = SECURITY,
    measurement_start: str = MEASUREMENT_START,
    measurement_end: str = MEASUREMENT_END,
    as_of: str = AS_OF,
    metrics: dict | None = None,
    source: str = "performance_attribution.v2",
) -> PerformanceEvidence:
    return PerformanceEvidence(
        evidence_id=evidence_id,
        security_code=security_code,
        trade_ids=tuple(sorted(trade_ids)),
        measurement_start=measurement_start,
        measurement_end=measurement_end,
        as_of=as_of,
        metrics=metrics or {"realized_pnl": 1234.5, "total_fees": 10.0},
        source=source,
    )


def _default_window():
    return dict(measurement_start=MEASUREMENT_START, measurement_end=MEASUREMENT_END, as_of=AS_OF)


# ---------------------------------------------------------------------------
# 正常投影
# ---------------------------------------------------------------------------

class TestProjectionHappyPath:
    def test_single_trade_with_evidence(self):
        outcome = project_outcome(
            make_decision(),
            [_attribution()],
            [_evidence()],
            **_default_window(),
        )
        d = outcome.to_dict()
        assert d["schema_version"] == fdo.SCHEMA_VERSION
        assert d["decision_id"] == DECISION_ID
        assert d["security_code"] == SECURITY
        assert d["strategy"] == "SWING"
        assert d["campaign_id"] == CAMPAIGN_ID
        assert d["thesis_id"] == THESIS_ID
        assert d["thesis_revision"] == 2
        assert d["decision_committed_at"] == COMMITTED_AT
        assert d["decision_review_by"] == REVIEW_BY
        assert d["decision_next_best_action"] == "BUY SMALL"
        assert d["attribution_ids"] == ["trade_attribution_" + "1" * 32]
        assert d["trade_ids"] == ["1" * 32]
        assert d["execution_summary"]["state"] == "EXECUTED_TRADE"
        assert d["performance_evidence_state"] == "MEASURED"
        assert len(d["evidences"]) == 1
        assert d["evidences"][0]["metrics"]["realized_pnl"] == 1234.5
        assert d["measurement"] == {
            "measurement_start": MEASUREMENT_START,
            "measurement_end": MEASUREMENT_END,
            "as_of": AS_OF,
        }
        assert d["reason_codes"] == []

    def test_multi_trade_provenance_preserved(self):
        # buy full + add partial + reduce full：逐交易保留，不合成
        attributions = [
            _attribution(
                trade=make_trade(trade_id="1" * 32, operation="buy", execution_status="full"),
                attribution_id="trade_attribution_" + "1" * 32,
            ),
            _attribution(
                trade=make_trade(
                    trade_id="2" * 32, operation="add", execution_status="partial",
                    actual_price=1520.0, actual_quantity=50,
                ),
                attribution_id="trade_attribution_" + "2" * 32,
            ),
            _attribution(
                trade=make_trade(trade_id="3" * 32, operation="reduce"),
                attribution_id="trade_attribution_" + "3" * 32,
            ),
        ]
        outcome = project_outcome(
            make_decision(), attributions, [_evidence(trade_ids=("1" * 32, "2" * 32, "3" * 32))],
            **_default_window(),
        )
        assert outcome.trade_ids == ("1" * 32, "2" * 32, "3" * 32)
        assert outcome.execution_summary["executed_trade_ids"] == ["1" * 32, "2" * 32, "3" * 32]
        assert len(outcome.behavior_deviations) == 3
        assert outcome.behavior_deviations[0] == {
            "trade_id": "1" * 32,
            "decision_next_best_action": "BUY SMALL",
            "trade_operation": "buy",
        }

    def test_cross_decision_attribution_excluded(self):
        # 集合含其他决策的归属 → 本决策投影只含本决策交易
        other_decision = make_decision(decision_id="decision_" + "f" * 32)
        attributions = [
            _attribution(),
            create_attribution(
                other_decision, make_trade(trade_id="2" * 32),
                attribution_id="trade_attribution_" + "2" * 32,
                created_at=ATTRIBUTION_CREATED_AT,
            ),
        ]
        outcome = project_outcome(
            make_decision(), attributions, [_evidence()], **_default_window(),
        )
        assert outcome.trade_ids == ("1" * 32,)
        assert "2" * 32 not in outcome.trade_ids

    def test_no_evidence_not_measured(self):
        outcome = project_outcome(make_decision(), [_attribution()], [], **_default_window())
        assert outcome.performance_evidence_state == "NOT_MEASURED"
        assert outcome.reason_codes == (REASON_NO_PERFORMANCE_EVIDENCE,)

    def test_all_not_executed_no_executed_trade(self):
        trade = make_trade(
            execution_status="not_executed", executed_at=None,
            actual_price=None, actual_quantity=0, unexecuted_reason="涨停封板",
        )
        outcome = project_outcome(make_decision(), [_attribution(trade=trade)], [], **_default_window())
        assert outcome.execution_summary["state"] == "NO_EXECUTED_TRADE"
        assert outcome.execution_summary["not_executed_trade_ids"] == ["1" * 32]
        assert outcome.execution_summary["executed_trade_ids"] == []
        # 不是 0% 收益，而是未测量
        assert outcome.performance_evidence_state == "NOT_MEASURED"
        assert REASON_NO_EXECUTED_TRADE in outcome.reason_codes


# ---------------------------------------------------------------------------
# 归属权威复用与交易成员资格
# ---------------------------------------------------------------------------

class TestTradeMembership:
    def test_invalid_attribution_set_fails_closed(self):
        # TB1 权威：同 attribution_id 冲突内容 → 集合拒绝
        a = _attribution()
        conflict = a.to_dict()
        conflict["trade_operation"] = "sell"
        from formal_trade_attribution import compute_attribution_hash
        conflict["attribution_hash"] = compute_attribution_hash(conflict)
        with pytest.raises(AttributionConflictError):
            project_outcome(make_decision(), [a, conflict], [], **_default_window())

    def test_cross_decision_trade_evidence_rejected(self):
        # 证据引用归属到另一决策的交易 → 拒绝
        with pytest.raises(OutcomeValidationError):
            project_outcome(
                make_decision(),
                [_attribution()],
                [_evidence(trade_ids=("2" * 32,))],
                **_default_window(),
            )

    def test_unknown_trade_evidence_rejected(self):
        with pytest.raises(OutcomeValidationError):
            project_outcome(
                make_decision(),
                [_attribution()],
                [_evidence(trade_ids=("9" * 32,))],
                **_default_window(),
            )

    def test_cross_security_evidence_rejected(self):
        with pytest.raises(OutcomeValidationError):
            project_outcome(
                make_decision(),
                [_attribution()],
                [_evidence(security_code="000858")],
                **_default_window(),
            )

    def test_half_bound_evidence_rejected(self):
        with pytest.raises(OutcomeValidationError):
            project_outcome(
                make_decision(),
                [_attribution()],
                [_evidence(trade_ids=())],
                **_default_window(),
            )

    def test_evidence_for_wrong_decision_snapshot_rejected_by_membership(self):
        # 伪造决策见证（哈希错）→ 见证验证阶段拒绝（TB1 权威异常）
        bad_decision = make_decision(snapshot_hash="0" * 64)
        with pytest.raises(AttributionValidationError):
            project_outcome(bad_decision, [_attribution()], [], **_default_window())


# ---------------------------------------------------------------------------
# 归属 ≠ 合规
# ---------------------------------------------------------------------------

class TestAttributionNotCompliance:
    def test_wait_to_buy_preserved(self):
        decision = make_decision(next_best_action="WAIT")
        outcome = project_outcome(decision, [_attribution(decision=decision)], [], **_default_window())
        assert outcome.decision_next_best_action == "WAIT"
        assert outcome.behavior_deviations[0]["trade_operation"] == "buy"
        assert outcome.behavior_deviations[0]["decision_next_best_action"] == "WAIT"
        assert outcome.execution_summary["state"] == "EXECUTED_TRADE"

    def test_exit_to_add_preserved(self):
        decision = make_decision(next_best_action="EXIT")
        trade = make_trade(operation="add", execution_status="partial", actual_quantity=50)
        outcome = project_outcome(decision, [_attribution(decision=decision, trade=trade)], [], **_default_window())
        assert outcome.decision_next_best_action == "EXIT"
        assert outcome.behavior_deviations[0]["trade_operation"] == "add"

    def test_no_fake_validity_status(self):
        outcome = project_outcome(make_decision(), [_attribution()], [_evidence()], **_default_window())
        d = outcome.to_dict()
        for key in d:
            assert "validity" not in key and "EXPIRED" not in str(d[key])
        assert "decision_review_by" in d  # 仅保留证据

    def test_review_by_past_not_a_deadline(self):
        decision = make_decision(review_by="2026-08-09T00:00:00.000000Z")
        outcome = project_outcome(decision, [_attribution(decision=decision)], [_evidence()], **_default_window())
        assert outcome.decision_review_by == "2026-08-09T00:00:00.000000Z"

    def test_voided_after_attribution_fact_preserved(self):
        # 规范 17：不发明 void 传播规则；外部证据显式标记已作废 → 事实原样保留
        evidence = _evidence(metrics={
            "realized_pnl": -800.0,
            "voided_trade_ids": ["1" * 32],
            "void_reason": "历史冲正后作废（外部权威标记）",
        })
        outcome = project_outcome(make_decision(), [_attribution()], [evidence], **_default_window())
        # 历史归属不被删除
        assert outcome.trade_ids == ("1" * 32,)
        assert outcome.execution_summary["executed_trade_ids"] == ["1" * 32]
        # 作废事实由证据原样携带（不静默纳入/排除，不重算）
        assert outcome.evidences[0]["metrics"]["voided_trade_ids"] == ["1" * 32]

    def test_thesis_state_not_inferred_from_pnl(self):
        # 亏损证据不推断 thesis 失效；投影不含任何 thesis 状态/有效性字段
        evidence = _evidence(metrics={"realized_pnl": -5000.0})
        outcome = project_outcome(make_decision(), [_attribution()], [evidence], **_default_window())
        d = outcome.to_dict()
        for key in d:
            assert "thesis_status" not in key
            assert "thesis_invalidated" not in str(d[key])
            assert "validity_status" not in key
        assert outcome.thesis_id == THESIS_ID  # 仅保留身份锚


# ---------------------------------------------------------------------------
# 时间纪律
# ---------------------------------------------------------------------------

class TestTemporalDiscipline:
    def test_measurement_before_decision_commit_rejected(self):
        with pytest.raises(OutcomeValidationError):
            project_outcome(
                make_decision(),
                [_attribution()],
                [_evidence()],
                measurement_start="2026-08-10T05:00:00.000000Z",
                measurement_end="2026-08-10T06:00:00.000000Z",
                as_of="2026-08-10T06:00:00.000000Z",
            )

    def test_reversed_window_rejected(self):
        with pytest.raises(OutcomeValidationError):
            project_outcome(
                make_decision(),
                [_attribution()],
                [_evidence()],
                measurement_start=MEASUREMENT_END,
                measurement_end=MEASUREMENT_START,
                as_of=AS_OF,
            )

    def test_as_of_before_window_start_rejected(self):
        with pytest.raises(OutcomeValidationError):
            project_outcome(
                make_decision(),
                [_attribution()],
                [_evidence()],
                measurement_start=MEASUREMENT_START,
                measurement_end=MEASUREMENT_END,
                as_of="2026-08-10T07:30:00.000000Z",
            )

    def test_evidence_measurement_before_commit_rejected(self):
        with pytest.raises(OutcomeValidationError):
            project_outcome(
                make_decision(),
                [_attribution()],
                [_evidence(measurement_start="2026-08-10T05:30:00.000000Z",
                           measurement_end="2026-08-10T06:30:00.000000Z")],
                **_default_window(),
            )

    def test_evidence_reversed_window_rejected(self):
        with pytest.raises(OutcomeValidationError):
            project_outcome(
                make_decision(),
                [_attribution()],
                [_evidence(measurement_start=MEASUREMENT_END,
                           measurement_end=MEASUREMENT_START)],
                **_default_window(),
            )

    def test_evidence_as_of_before_start_rejected(self):
        with pytest.raises(OutcomeValidationError):
            project_outcome(
                make_decision(),
                [_attribution()],
                [_evidence(as_of="2026-08-10T07:00:00.000000Z")],
                **_default_window(),
            )

    def test_malformed_timestamp_rejected(self):
        with pytest.raises(AttributionValidationError):
            project_outcome(
                make_decision(),
                [_attribution()],
                [_evidence()],
                measurement_start="明天",
                measurement_end=MEASUREMENT_END,
                as_of=AS_OF,
            )

    def test_plus_offset_window_normalized(self):
        # 显式 UTC（+00:00 形式）→ 规范化为 canonical Z 形式
        outcome = project_outcome(
            make_decision(),
            [_attribution()],
            [_evidence(measurement_start="2026-08-10T08:00:00+00:00")],
            measurement_start="2026-08-10T08:00:00+00:00",
            measurement_end="2026-08-10T09:00:00+00:00",
            as_of="2026-08-10T09:30:00+00:00",
        )
        assert outcome.measurement["measurement_start"] == MEASUREMENT_START

    def test_non_zero_offset_window_rejected(self):
        # 非零偏移时间戳（+08:00）→ 拒绝（与 TB1 时区纪律一致，不做时区换算）
        with pytest.raises(AttributionValidationError):
            project_outcome(
                make_decision(),
                [_attribution()],
                [_evidence()],
                measurement_start="2026-08-10T16:00:00+08:00",
                measurement_end="2026-08-10T17:00:00+08:00",
                as_of="2026-08-10T17:30:00+08:00",
            )


# ---------------------------------------------------------------------------
# 证据集合语义
# ---------------------------------------------------------------------------

class TestEvidenceSetSemantics:
    def test_exact_duplicate_idempotent(self):
        outcome = project_outcome(
            make_decision(), [_attribution()], [_evidence(), _evidence()],
            **_default_window(),
        )
        assert len(outcome.evidences) == 1

    def test_conflicting_same_id_rejected(self):
        a = _evidence()
        b = _evidence(metrics={"realized_pnl": 999.0})
        with pytest.raises(OutcomeEvidenceConflictError):
            project_outcome(make_decision(), [_attribution()], [a, b], **_default_window())

    def test_order_independent(self):
        ev_a = _evidence(evidence_id="1" * 32, trade_ids=("1" * 32,))
        ev_b = _evidence(evidence_id="2" * 32, trade_ids=("1" * 32,), metrics={"realized_pnl": 1.0})
        out1 = project_outcome(make_decision(), [_attribution()], [ev_a, ev_b], **_default_window())
        out2 = project_outcome(make_decision(), [_attribution()], [ev_b, ev_a], **_default_window())
        assert out1 == out2

    def test_mapping_evidence_accepted(self):
        evidence_dict = _evidence().to_dict()
        outcome = project_outcome(
            make_decision(), [_attribution()], [evidence_dict], **_default_window(),
        )
        assert outcome.performance_evidence_state == "MEASURED"

    def test_evidence_wrong_fields_rejected(self):
        bad = _evidence().to_dict()
        del bad["metrics"]
        with pytest.raises(OutcomeValidationError):
            validate_evidence(bad)

    def test_evidence_metrics_nan_rejected(self):
        bad = _evidence(metrics={"x": float("nan")})
        with pytest.raises(OutcomeValidationError):
            validate_evidence(bad)


# ---------------------------------------------------------------------------
# 确定性 / 纯核心
# ---------------------------------------------------------------------------

class TestDeterminismAndPurity:
    def test_same_inputs_same_projection(self):
        kwargs = dict(**_default_window())
        out1 = project_outcome(make_decision(), [_attribution()], [_evidence()], **kwargs)
        out2 = project_outcome(make_decision(), [_attribution()], [_evidence()], **kwargs)
        assert out1 == out2
        assert out1.to_dict() == out2.to_dict()

    def test_attribution_order_independent(self):
        attr_ab = [
            _attribution(
                trade=make_trade(trade_id="1" * 32, operation="buy"),
                attribution_id="trade_attribution_" + "1" * 32,
            ),
            _attribution(
                trade=make_trade(trade_id="2" * 32, operation="sell"),
                attribution_id="trade_attribution_" + "2" * 32,
            ),
        ]
        attr_ba = [attr_ab[1], attr_ab[0]]
        out1 = project_outcome(
            make_decision(), attr_ab,
            [_evidence(trade_ids=("1" * 32, "2" * 32))], **_default_window(),
        )
        out2 = project_outcome(
            make_decision(), attr_ba,
            [_evidence(trade_ids=("1" * 32, "2" * 32))], **_default_window(),
        )
        assert out1 == out2

    def test_module_has_no_io_imports(self):
        source = inspect.getsource(fdo)
        for forbidden in ("import sqlite3", "import os", "import socket", "requests", "urllib"):
            assert forbidden not in source
        assert "datetime.now" not in source
        assert "uuid" not in source


# ---------------------------------------------------------------------------
# 现有权威 parity（不重算、不建第二套系统）
# ---------------------------------------------------------------------------

class TestExistingAuthorityParity:
    def test_performance_attribution_output_reused_as_evidence(self, tmp_path):
        """现有 performance_attribution 的真实输出作为 metrics payload 被绑定引用。"""
        import trade_ledger_store as tl_store
        import performance_attribution_service as perf_svc

        db = tmp_path / "trade_ledger.sqlite3"
        tl_store.insert_record(db, {
            "trade_id": "1" * 32,
            "code": SECURITY,
            "name": "贵州茅台",
            "operation": "buy",
            "execution_status": "full",
            "actual_price": 1500.0,
            "actual_quantity": 100,
            "executed_at": "2026-08-10T06:45:00+00:00",
            "created_at": "2026-08-10T06:30:00+00:00",
        })
        tl_store.insert_record(db, {
            "trade_id": "2" * 32,
            "code": SECURITY,
            "name": "贵州茅台",
            "operation": "sell",
            "execution_status": "full",
            "actual_price": 1600.0,
            "actual_quantity": 50,
            "executed_at": "2026-08-10T08:30:00+00:00",
            "created_at": "2026-08-10T08:25:00+00:00",
        })
        result = perf_svc.compute_attribution(
            trade_db_path=db, date_from="2026-08-10", date_to="2026-08-10"
        )
        positions = {p["code"]: p for p in result["positions"]}
        assert positions[SECURITY]["realized_pnl"] > 0  # 现有权威确实算了

        # 现有输出本身按 code 聚合、不含 trade_ids（精确缺口）：
        # 作为证据必须显式提供 trade 绑定，否则拒绝
        half_bound = {"metrics": positions[SECURITY]}
        with pytest.raises(OutcomeValidationError):
            validate_evidence(half_bound)

        # 显式绑定交易集后，现有输出作为证据被引用（不重算）
        attributions = [
            _attribution(trade=make_trade(trade_id="1" * 32, operation="buy")),
            _attribution(
                trade=make_trade(trade_id="2" * 32, operation="sell"),
                attribution_id="trade_attribution_" + "2" * 32,
            ),
        ]
        evidence = PerformanceEvidence(
            evidence_id="e" * 32,
            security_code=SECURITY,
            trade_ids=("1" * 32, "2" * 32),
            measurement_start=MEASUREMENT_START,
            measurement_end=MEASUREMENT_END,
            as_of=AS_OF,
            metrics=positions[SECURITY],
            source="performance_attribution.v2",
        )
        outcome = project_outcome(
            make_decision(), attributions, [evidence], **_default_window(),
        )
        assert outcome.performance_evidence_state == "MEASURED"
        assert outcome.evidences[0]["metrics"]["realized_pnl"] == positions[SECURITY]["realized_pnl"]
        assert outcome.evidences[0]["source"] == "performance_attribution.v2"

    def test_decision_feedback_contract_reusable(self):
        """现有 decision_feedback 的结果枚举可作为证据 metrics 被引用。"""
        import decision_feedback_service as feedback_svc

        assert feedback_svc.OUTCOME_STATUSES == {
            "better_than_expected", "as_expected", "worse_than_expected", "not_evaluated",
        }
        evidence = _evidence(
            metrics={
                "adoption_status": "followed",
                "outcome_status": "better_than_expected",
                "note": "复用现有 feedback 契约",
            },
            source="decision_feedback.v1",
        )
        outcome = project_outcome(
            make_decision(), [_attribution()], [evidence], **_default_window(),
        )
        assert outcome.evidences[0]["metrics"]["outcome_status"] == "better_than_expected"

    def test_no_pnl_reimplementation_in_module(self):
        # 模块不包含任何收益公式/基准公式
        source = inspect.getsource(fdo)
        for forbidden in ("realized_pnl =", "return =", "benchmark", "avg_cost"):
            assert forbidden not in source
