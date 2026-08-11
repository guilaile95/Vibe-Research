"""P0-O1-R1 正式决策结果来源投影核心测试：纯领域逻辑 + PA1 权威重集成。"""
from __future__ import annotations

import inspect
import re
from datetime import datetime, timedelta

import pytest

import formal_decision_outcome as fdo
import frozen_decision_store as fd_store
import performance_attribution_service as perf_svc
import trade_ledger_store as tl_store
from formal_trade_attribution import (
    AttributionConflictError,
    AttributionValidationError,
    create_attribution,
)
from formal_decision_outcome import (
    EXECUTION_SUMMARY_STATES,
    FEEDBACK_EVIDENCE_STATES,
    PERFORMANCE_EVIDENCE_STATES,
    PA1_AUTHORITY_VERSION,
    REASON_NO_EXECUTED_TRADE,
    REASON_NO_PERFORMANCE_EVIDENCE,
    FeedbackEvidence,
    FormalDecisionOutcome,
    OutcomeEvidenceConflictError,
    OutcomeValidationError,
    PerformanceEvidence,
    build_performance_evidence,
    performance_evidence_from_dict,
    project_outcome,
    validate_feedback_evidence,
    validate_pa1_result,
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
# 构造 helpers
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


def _pa1_result(tmp_path, trades, price_map=None) -> dict:
    """用真实 PA1 权威计算生成结果（测试即 parity：消费权威输出本身）。"""
    db = tmp_path / "trade_ledger.sqlite3"
    for t in trades:
        tl_store.insert_record(db, t)
    return perf_svc.compute_attribution(
        trade_db_path=db, price_map=price_map
    )


def _pa1_position(pa1_result: dict, code: str) -> dict:
    for pos in pa1_result["positions"]:
        if pos["code"] == code:
            return pos
    raise AssertionError(f"position {code} not found in PA1 result")


def _build_evidence(pa1_result: dict, code: str = SECURITY, **window) -> PerformanceEvidence:
    position = _pa1_position(pa1_result, code)
    return build_performance_evidence(pa1_result, position, **window)


def _window(**overrides) -> dict:
    w = dict(measurement_start=MEASUREMENT_START, measurement_end=MEASUREMENT_END, as_of=AS_OF)
    w.update(overrides)
    return w


def _feedback(evidence_id: str = "f" * 32, security_code: str = SECURITY, **overrides) -> FeedbackEvidence:
    data = {
        "evidence_id": evidence_id,
        "security_code": security_code,
        "metrics": {
            "adoption_status": "followed",
            "outcome_status": "better_than_expected",
        },
        "as_of": AS_OF,
    }
    data.update(overrides)
    return validate_feedback_evidence(data)


# ---------------------------------------------------------------------------
# PA1 结果权威校验
# ---------------------------------------------------------------------------

class TestPa1ResultValidation:
    def test_real_pa1_output_accepted(self, tmp_path):
        result = _pa1_result(tmp_path, [make_trade()])
        validated = validate_pa1_result(result)
        assert validated["authority_version"] == PA1_AUTHORITY_VERSION
        assert validated["selected_trade_ids"] == ["1" * 32]

    def test_d_wrong_authority_version_rejected(self, tmp_path):
        result = _pa1_result(tmp_path, [make_trade()])
        result["authority_version"] = "performance_attribution.v1"
        with pytest.raises(OutcomeValidationError):
            validate_pa1_result(result)

    def test_selected_count_mismatch_rejected(self, tmp_path):
        result = _pa1_result(tmp_path, [make_trade()])
        result["selected_trade_count"] = 99
        with pytest.raises(OutcomeValidationError):
            validate_pa1_result(result)

    def test_c_tampered_input_trade_ids_rejected(self, tmp_path):
        """调用方篡改 position.input_trade_ids（自报附加）→ 内部一致性校验拒绝。"""
        result = _pa1_result(tmp_path, [make_trade()])
        result["positions"][0]["input_trade_ids"] = ["1" * 32, "9" * 32]
        with pytest.raises(OutcomeValidationError):
            validate_pa1_result(result)

    def test_c_no_self_asserted_trade_ids_parameter(self, tmp_path):
        """证据构造签名不接受调用方 trade_ids（自报绑定在 API 层即不可能）。"""
        result = _pa1_result(tmp_path, [make_trade()])
        with pytest.raises(TypeError):
            build_performance_evidence(
                result,
                _pa1_position(result, SECURITY),
                trade_ids=["9" * 32],
                **_window(),
            )


# ---------------------------------------------------------------------------
# 绩效证据构造与序列化
# ---------------------------------------------------------------------------

class TestPerformanceEvidenceConstruction:
    def test_derived_from_pa1(self, tmp_path):
        result = _pa1_result(tmp_path, [make_trade()])
        evidence = _build_evidence(result, **_window())
        assert evidence.authority_version == PA1_AUTHORITY_VERSION
        assert evidence.computation_fingerprint == result["computation_fingerprint"]
        assert evidence.input_trade_ids == ("1" * 32,)
        assert evidence.metrics["code"] == SECURITY
        assert re.fullmatch(r"[0-9a-f]{64}", evidence.evidence_id)

    def test_evidence_id_deterministic_and_security_scoped(self, tmp_path):
        result = _pa1_result(
            tmp_path,
            [make_trade(), make_trade(trade_id="2" * 32, code="000858", name="五粮液")],
        )
        ev_600519 = _build_evidence(result, SECURITY, **_window())
        ev_000858 = _build_evidence(result, "000858", **_window())
        assert ev_600519.evidence_id != ev_000858.evidence_id
        again = _build_evidence(result, SECURITY, **_window())
        assert ev_600519.evidence_id == again.evidence_id
        assert ev_600519 == again

    def test_strict_serialization_roundtrip(self, tmp_path):
        result = _pa1_result(tmp_path, [make_trade()])
        evidence = _build_evidence(result, **_window())
        restored = performance_evidence_from_dict(evidence.to_dict())
        assert restored == evidence

    def test_from_dict_tampered_identity_rejected(self, tmp_path):
        result = _pa1_result(tmp_path, [make_trade()])
        evidence = _build_evidence(result, **_window())
        d = evidence.to_dict()
        d["evidence_id"] = "0" * 64
        with pytest.raises(OutcomeValidationError):
            performance_evidence_from_dict(d)
        d = evidence.to_dict()
        d["authority_version"] = "x"
        with pytest.raises(OutcomeValidationError):
            performance_evidence_from_dict(d)


# ---------------------------------------------------------------------------
# 正常投影
# ---------------------------------------------------------------------------

class TestProjectionHappyPath:
    def test_single_trade_with_pa1_evidence(self, tmp_path):
        outcome = project_outcome(
            make_decision(),
            [_attribution()],
            [_pa1_result(tmp_path, [make_trade()])],
            **_window(),
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
        assert len(d["performance_evidences"]) == 1
        perf = d["performance_evidences"][0]
        assert perf["authority_version"] == PA1_AUTHORITY_VERSION
        assert perf["input_trade_ids"] == ["1" * 32]
        assert perf["metrics"]["realized_pnl"] == 0.0
        assert d["measurement"] == {
            "measurement_start": MEASUREMENT_START,
            "measurement_end": MEASUREMENT_END,
            "as_of": AS_OF,
        }
        assert d["reason_codes"] == []

    def test_multi_trade_provenance_preserved(self, tmp_path):
        attributions = [
            _attribution(
                trade=make_trade(trade_id="1" * 32, operation="buy"),
                attribution_id="trade_attribution_" + "1" * 32,
            ),
            _attribution(
                trade=make_trade(trade_id="2" * 32, operation="add", execution_status="partial"),
                attribution_id="trade_attribution_" + "2" * 32,
            ),
            _attribution(
                trade=make_trade(trade_id="3" * 32, operation="reduce"),
                attribution_id="trade_attribution_" + "3" * 32,
            ),
        ]
        outcome = project_outcome(
            make_decision(),
            attributions,
            [_pa1_result(tmp_path, [make_trade(trade_id=t) for t in ("1" * 32, "2" * 32, "3" * 32)])],
            **_window(),
        )
        assert outcome.trade_ids == ("1" * 32, "2" * 32, "3" * 32)
        assert outcome.execution_summary["executed_trade_ids"] == ["1" * 32, "2" * 32, "3" * 32]
        assert len(outcome.behavior_deviations) == 3
        assert outcome.performance_evidences[0]["input_trade_ids"] == [
            "1" * 32, "2" * 32, "3" * 32,
        ]

    def test_no_evidence_not_measured(self, tmp_path):
        outcome = project_outcome(make_decision(), [_attribution()], [], **_window())
        assert outcome.performance_evidence_state == "NOT_MEASURED"
        assert outcome.reason_codes == (REASON_NO_PERFORMANCE_EVIDENCE,)

    def test_all_not_executed_no_executed_trade(self, tmp_path):
        trade = make_trade(
            execution_status="not_executed", executed_at=None,
            actual_price=None, actual_quantity=0, unexecuted_reason="涨停封板",
        )
        outcome = project_outcome(make_decision(), [_attribution(trade=trade)], [], **_window())
        assert outcome.execution_summary["state"] == "NO_EXECUTED_TRADE"
        assert outcome.performance_evidence_state == "NOT_MEASURED"
        assert REASON_NO_EXECUTED_TRADE in outcome.reason_codes


# ---------------------------------------------------------------------------
# 阻塞测试：绑定与混合拒绝
# ---------------------------------------------------------------------------

class TestBlockingBinding:
    def test_a_pa1_t1_only_decision_t1_accepted(self, tmp_path):
        """PA1 结果恰含 T1，决策归属 T1 → 绩效证据接受。"""
        result = _pa1_result(tmp_path, [make_trade(trade_id="1" * 32)])
        outcome = project_outcome(
            make_decision(), [_attribution()], [result], **_window(),
        )
        assert outcome.performance_evidence_state == "MEASURED"
        assert outcome.performance_evidences[0]["input_trade_ids"] == ["1" * 32]

    def test_b_mixed_t1_t2_rejected(self, tmp_path):
        """PA1 结果含 T1 + 无关 T2（同证券），决策只归属 T1 → 拒绝。"""
        result = _pa1_result(
            tmp_path,
            [
                make_trade(trade_id="1" * 32, executed_at="2026-08-10T06:45:00+00:00"),
                make_trade(trade_id="2" * 32, executed_at="2026-08-10T07:00:00+00:00"),
            ],
        )
        with pytest.raises(OutcomeValidationError):
            project_outcome(make_decision(), [_attribution()], [result], **_window())

    def test_c_self_asserted_trade_ids_cannot_override(self, tmp_path):
        """调用方附加的自报 trade_ids 无法覆盖 PA1 输入集（构造签名拒绝 + 校验拒绝）。"""
        result = _pa1_result(tmp_path, [make_trade(trade_id="1" * 32)])
        with pytest.raises(TypeError):
            build_performance_evidence(result, _pa1_position(result, SECURITY), trade_ids=["2" * 32], **_window())
        # 篡改 PA1 结果的 input_trade_ids → 内部一致性校验拒绝
        tampered = {**result, "positions": [dict(p) for p in result["positions"]]}
        tampered["positions"][0]["input_trade_ids"] = ["2" * 32]
        with pytest.raises(OutcomeValidationError):
            validate_pa1_result(tampered)

    def test_cross_security_position_ignored_not_rejected(self, tmp_path):
        """PA1 结果含其他证券 position → 不参与本决策投影（不拒绝、不采用）。"""
        result = _pa1_result(
            tmp_path,
            [
                make_trade(trade_id="1" * 32),
                make_trade(trade_id="2" * 32, code="000858", name="五粮液"),
            ],
        )
        outcome = project_outcome(
            make_decision(), [_attribution()], [result], **_window(),
        )
        assert outcome.performance_evidence_state == "MEASURED"
        assert outcome.performance_evidences[0]["security_code"] == SECURITY

    def test_invalid_attribution_set_fails_closed(self, tmp_path):
        a = _attribution()
        conflict = a.to_dict()
        conflict["trade_operation"] = "sell"
        from formal_trade_attribution import compute_attribution_hash
        conflict["attribution_hash"] = compute_attribution_hash(conflict)
        with pytest.raises(AttributionConflictError):
            project_outcome(
                make_decision(), [a, conflict],
                [_pa1_result(tmp_path, [make_trade()])], **_window(),
            )

    def test_forged_decision_rejected(self, tmp_path):
        bad_decision = make_decision(snapshot_hash="0" * 64)
        with pytest.raises(AttributionValidationError):
            project_outcome(
                bad_decision, [_attribution()],
                [_pa1_result(tmp_path, [make_trade()])], **_window(),
            )


# ---------------------------------------------------------------------------
# 证据类型分离：feedback 独立维度
# ---------------------------------------------------------------------------

class TestEvidenceTypeSeparation:
    def test_e_feedback_only_keeps_performance_not_measured(self, tmp_path):
        outcome = project_outcome(
            make_decision(), [_attribution()], [], [_feedback()], **_window(),
        )
        assert outcome.performance_evidence_state == "NOT_MEASURED"
        assert outcome.feedback_evidence_state == "MEASURED"
        assert len(outcome.feedback_evidences) == 1
        assert REASON_NO_PERFORMANCE_EVIDENCE in outcome.reason_codes

    def test_f_both_dimensions_preserved_separately(self, tmp_path):
        result = _pa1_result(tmp_path, [make_trade()])
        outcome = project_outcome(
            make_decision(),
            [_attribution()],
            [result],
            [_feedback()],
            **_window(),
        )
        assert outcome.performance_evidence_state == "MEASURED"
        assert outcome.feedback_evidence_state == "MEASURED"
        assert len(outcome.performance_evidences) == 1
        assert len(outcome.feedback_evidences) == 1
        d = outcome.to_dict()
        assert d["performance_evidences"][0]["authority_version"] == PA1_AUTHORITY_VERSION
        assert d["feedback_evidences"][0]["metrics"]["outcome_status"] == "better_than_expected"
        # 两维度各自独立存在，未合并进同一证据桶
        assert set(d) >= {"performance_evidences", "feedback_evidences"}

    def test_feedback_validation(self):
        with pytest.raises(OutcomeValidationError):
            validate_feedback_evidence({"evidence_id": "x", "security_code": SECURITY})
        with pytest.raises(OutcomeValidationError):
            _feedback(metrics={"x": float("nan")})
        assert _feedback().security_code == SECURITY

    def test_feedback_conflict_rejected(self, tmp_path):
        result = _pa1_result(tmp_path, [make_trade()])
        a = _feedback()
        b = _feedback(metrics={"outcome_status": "worse_than_expected"})
        with pytest.raises(OutcomeEvidenceConflictError):
            project_outcome(
                make_decision(), [_attribution()], [result], [a, b], **_window(),
            )


# ---------------------------------------------------------------------------
# 归属 ≠ 合规 / 时间纪律 / 确定性 / 纯核心（原 O1 契约保留）
# ---------------------------------------------------------------------------

class TestPreservedContracts:
    def test_wait_to_buy_preserved(self, tmp_path):
        decision = make_decision(next_best_action="WAIT")
        outcome = project_outcome(decision, [_attribution(decision=decision)], [], **_window())
        assert outcome.decision_next_best_action == "WAIT"
        assert outcome.behavior_deviations[0]["trade_operation"] == "buy"
        assert outcome.execution_summary["state"] == "EXECUTED_TRADE"

    def test_exit_to_add_preserved(self, tmp_path):
        decision = make_decision(next_best_action="EXIT")
        trade = make_trade(operation="add", execution_status="partial", actual_quantity=50)
        outcome = project_outcome(decision, [_attribution(decision=decision, trade=trade)], [], **_window())
        assert outcome.decision_next_best_action == "EXIT"
        assert outcome.behavior_deviations[0]["trade_operation"] == "add"

    def test_no_fake_validity_status(self, tmp_path):
        outcome = project_outcome(
            make_decision(), [_attribution()],
            [_pa1_result(tmp_path, [make_trade()])], **_window(),
        )
        d = outcome.to_dict()
        for key in d:
            assert "validity" not in key and "EXPIRED" not in str(d[key])
        assert "decision_review_by" in d

    def test_review_by_past_not_a_deadline(self, tmp_path):
        decision = make_decision(review_by="2026-08-09T00:00:00.000000Z")
        outcome = project_outcome(decision, [_attribution(decision=decision)], [], **_window())
        assert outcome.decision_review_by == "2026-08-09T00:00:00.000000Z"

    def test_measurement_before_commit_rejected(self, tmp_path):
        with pytest.raises(AttributionValidationError):
            project_outcome(
                make_decision(), [_attribution()], [],
                measurement_start="2026-08-10T05:00:00.000000Z",
                measurement_end="2026-08-10T06:00:00.000000Z",
                as_of="2026-08-10T06:00:00.000000Z",
            )

    def test_reversed_window_rejected(self, tmp_path):
        with pytest.raises(AttributionValidationError):
            project_outcome(
                make_decision(), [_attribution()], [],
                measurement_start=MEASUREMENT_END,
                measurement_end=MEASUREMENT_START,
                as_of=AS_OF,
            )

    def test_same_inputs_same_projection(self, tmp_path):
        result = _pa1_result(tmp_path, [make_trade()])
        kwargs = dict(_window())
        out1 = project_outcome(make_decision(), [_attribution()], [result], **kwargs)
        out2 = project_outcome(make_decision(), [_attribution()], [result], **kwargs)
        assert out1 == out2
        assert out1.to_dict() == out2.to_dict()

    def test_module_has_no_io_imports(self):
        source = inspect.getsource(fdo)
        for forbidden in ("import sqlite3", "import os", "import socket", "requests", "urllib"):
            assert forbidden not in source
        assert "datetime.now" not in source
        assert "uuid" not in source


# ---------------------------------------------------------------------------
# 现有权威 parity（消费真实 PA1 输出，不重算）
# ---------------------------------------------------------------------------

class TestExistingAuthorityParity:
    def test_real_pa1_output_binds_metrics(self, tmp_path):
        """真实 PA1 输出（含 PnL）作为证据被绑定引用，不重算。"""
        result = _pa1_result(
            tmp_path,
            [
                make_trade(trade_id="1" * 32, operation="buy", executed_at="2026-08-10T06:45:00+00:00"),
                make_trade(
                    trade_id="2" * 32, operation="sell", executed_at="2026-08-10T08:30:00+00:00",
                ),
            ],
        )
        attributions = [
            _attribution(trade=make_trade(trade_id="1" * 32, operation="buy")),
            _attribution(
                trade=make_trade(trade_id="2" * 32, operation="sell"),
                attribution_id="trade_attribution_" + "2" * 32,
            ),
        ]
        outcome = project_outcome(
            make_decision(), attributions, [result], **_window(),
        )
        perf = outcome.performance_evidences[0]
        assert perf["computation_fingerprint"] == result["computation_fingerprint"]
        assert perf["input_trade_ids"] == ["1" * 32, "2" * 32]
        assert perf["metrics"]["realized_pnl"] == _pa1_position(result, SECURITY)["realized_pnl"]
        assert perf["metrics"]["remaining_quantity"] == 0

    def test_no_pnl_reimplementation_in_module(self):
        source = inspect.getsource(fdo)
        for forbidden in ("realized_pnl =", "return =", "benchmark", "avg_cost"):
            assert forbidden not in source
