"""P0-TB1 正式决策 ↔ 手动交易归属核心测试：纯领域逻辑，无 I/O。"""
from __future__ import annotations

import pytest

import formal_trade_attribution as fta
import frozen_decision_store as fd_store
from frozen_decision_service import freeze_decision
from formal_trade_attribution import (
    AttributionConflictError,
    AttributionSchemaVersionError,
    AttributionValidationError,
    FormalTradeAttribution,
    SCHEMA_VERSION,
    attribution_for_trade,
    attributions_for_decision,
    compute_attribution_hash,
    create_attribution,
    from_dict,
    validate_attribution_set,
)

COMMITTED_AT = "2026-08-10T06:00:00.000000Z"
TRADE_CREATED_AT = "2026-08-10T06:30:00.000000+00:00"  # Trade Ledger 权威格式（+00:00）
TRADE_EXECUTED_AT = "2026-08-10T06:45:00.000000+00:00"
REVIEW_BY = "2026-08-25T00:00:00.000000Z"
CREATED_AT = "2026-08-10T07:00:00.000000Z"

DECISION_ID = "decision_" + "a" * 32
TRADE_ID = "b" * 32
ATTRIBUTION_ID = "trade_attribution_" + "c" * 32
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
    """构造与 P0-FD1 服务产物同形的合法 Frozen Decision 见证。"""
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
        "trade_id": TRADE_ID,
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


# ---------------------------------------------------------------------------
# 正常归属
# ---------------------------------------------------------------------------

class TestCreateHappyPath:
    def test_full_buy_attribution(self):
        record = create_attribution(
            make_decision(), make_trade(),
            attribution_id=ATTRIBUTION_ID, created_at=CREATED_AT,
        )
        assert record.attribution_id == ATTRIBUTION_ID
        assert record.trade_id == TRADE_ID
        assert record.decision_id == DECISION_ID
        assert record.decision_snapshot_hash == make_decision()["snapshot_hash"]
        assert record.security_code == SECURITY
        assert record.strategy == "SWING"
        assert record.campaign_id == CAMPAIGN_ID
        assert record.thesis_id == THESIS_ID
        assert record.thesis_revision == 2
        assert record.decision_committed_at == COMMITTED_AT
        assert record.decision_review_by == REVIEW_BY
        assert record.decision_next_best_action == "BUY SMALL"
        assert record.trade_operation == "buy"
        assert record.trade_execution_status == "full"
        assert record.trade_executed_at == "2026-08-10T06:45:00.000000Z"  # 跨格式规范化
        assert record.trade_created_at == "2026-08-10T06:30:00.000000Z"
        assert record.created_at == CREATED_AT
        assert record.schema_version == SCHEMA_VERSION
        assert len(record.attribution_hash) == 64

    def test_attribution_id_auto_generated_when_omitted(self):
        record = create_attribution(make_decision(), make_trade(), created_at=CREATED_AT)
        assert record.attribution_id.startswith("trade_attribution_")
        assert len(record.attribution_id) == len("trade_attribution_") + 32

    def test_created_at_auto_generated_when_omitted(self):
        record = create_attribution(make_decision(), make_trade())
        assert record.created_at.endswith("Z")
        assert "." in record.created_at

    def test_partial_status_requires_executed_at(self):
        record = create_attribution(
            make_decision(),
            make_trade(execution_status="partial", executed_at=TRADE_EXECUTED_AT),
            attribution_id=ATTRIBUTION_ID, created_at=CREATED_AT,
        )
        assert record.trade_execution_status == "partial"
        assert record.trade_executed_at == "2026-08-10T06:45:00.000000Z"

    def test_not_executed_preserved(self):
        record = create_attribution(
            make_decision(),
            make_trade(
                execution_status="not_executed", executed_at=None,
                actual_price=None, actual_quantity=0, unexecuted_reason="涨停封板",
            ),
            attribution_id=ATTRIBUTION_ID, created_at=CREATED_AT,
        )
        assert record.trade_execution_status == "not_executed"
        assert record.trade_executed_at is None


# ---------------------------------------------------------------------------
# 决策见证验证（输入 A）
# ---------------------------------------------------------------------------

class TestWitnessVerification:
    def test_wrong_hash_rejected(self):
        decision = make_decision(snapshot_hash="0" * 64)
        with pytest.raises(AttributionValidationError):
            create_attribution(decision, make_trade())

    def test_missing_hash_rejected(self):
        decision = make_decision()
        del decision["snapshot_hash"]
        with pytest.raises(AttributionValidationError):
            create_attribution(decision, make_trade())

    def test_recomputed_hash_with_unsynced_fields_rejected(self):
        # 字段被改但 snapshot_json / snapshot_hash 未同步 → 文本比对失败
        decision = make_decision()
        decision["next_best_action"] = "HOLD"  # 字段变了
        with pytest.raises(AttributionValidationError):
            create_attribution(decision, make_trade())

    def test_user_confirmed_not_strict_true_rejected(self):
        for value in (False, None, 1, "true", "yes"):
            decision = make_decision(user_confirmed=value)
            with pytest.raises(AttributionValidationError):
                create_attribution(decision, make_trade())

    def test_user_confirmed_missing_rejected(self):
        decision = make_decision()
        del decision["user_confirmed"]
        with pytest.raises(AttributionValidationError):
            create_attribution(decision, make_trade())

    def test_wrong_snapshot_schema_version_rejected(self):
        decision = make_decision(snapshot_schema_version="frozen-decision-ledger.v9.9")
        with pytest.raises(AttributionValidationError):
            create_attribution(decision, make_trade())

    def test_bad_decision_id_rejected(self):
        decision = make_decision(decision_id="campaign_" + "a" * 32)
        with pytest.raises(AttributionValidationError):
            create_attribution(decision, make_trade())

    def test_bad_security_code_rejected(self):
        decision = make_decision(security_code="60051")
        with pytest.raises(AttributionValidationError):
            create_attribution(decision, make_trade())

    def test_unknown_strategy_rejected(self):
        decision = make_decision(strategy="DAYTRADE")
        with pytest.raises(AttributionValidationError):
            create_attribution(decision, make_trade())

    def test_bad_campaign_id_rejected(self):
        decision = make_decision(campaign_id="campaign_xyz")
        with pytest.raises(AttributionValidationError):
            create_attribution(decision, make_trade())

    def test_bad_thesis_id_or_revision_rejected(self):
        for bad in (0, -1, 1.5, "2", True):
            decision = make_decision(thesis_revision=bad)
            with pytest.raises(AttributionValidationError):
                create_attribution(decision, make_trade())

    def test_bad_committed_at_rejected(self):
        decision = make_decision(committed_at="2026-08-10T06:00:00+00:00")
        with pytest.raises(AttributionValidationError):
            create_attribution(decision, make_trade())

    def test_bad_review_by_rejected(self):
        decision = make_decision(review_by="明天")
        with pytest.raises(AttributionValidationError):
            create_attribution(decision, make_trade())

    def test_unknown_nba_rejected(self):
        decision = make_decision(next_best_action="MAYBE BUY")
        with pytest.raises(AttributionValidationError):
            create_attribution(decision, make_trade())

    def test_nan_in_view_rejected(self):
        # 手工构造含 NaN 的见证：canonical 化必须拒绝（不产生自洽文本）
        snapshot = _snapshot(asset_view={"x": float("nan")})
        decision = {
            **snapshot,
            "snapshot_json": "{}",
            "snapshot_hash": "0" * 64,
            "user_confirmed": True,
            "created_at": "2026-08-10T05:00:00.000000Z",
        }
        with pytest.raises(AttributionValidationError):
            create_attribution(decision, make_trade())

    def test_not_mapping_rejected(self):
        with pytest.raises(AttributionValidationError):
            create_attribution(["not", "a", "mapping"], make_trade())


# ---------------------------------------------------------------------------
# 交易记录验证（输入 B）
# ---------------------------------------------------------------------------

class TestTradeVerification:
    def test_bad_trade_id_rejected(self):
        for bad in ("prefixed_" + "a" * 32, "a" * 31, "A" * 32, "", None):
            with pytest.raises(AttributionValidationError):
                create_attribution(make_decision(), make_trade(trade_id=bad))

    def test_unknown_operation_rejected(self):
        for bad in ("BUY", "Buy", "sell_now", "hold", None):
            with pytest.raises(AttributionValidationError):
                create_attribution(make_decision(), make_trade(operation=bad))

    def test_unknown_execution_status_rejected(self):
        for bad in ("FULL", "done", "pending", None):
            with pytest.raises(AttributionValidationError):
                create_attribution(make_decision(), make_trade(execution_status=bad))

    def test_full_without_executed_at_rejected(self):
        with pytest.raises(AttributionValidationError):
            create_attribution(make_decision(), make_trade(executed_at=None))

    def test_not_executed_with_executed_at_rejected(self):
        with pytest.raises(AttributionValidationError):
            create_attribution(
                make_decision(),
                make_trade(execution_status="not_executed", unexecuted_reason="x"),
            )

    def test_missing_created_at_rejected(self):
        trade = make_trade()
        del trade["created_at"]
        with pytest.raises(AttributionValidationError):
            create_attribution(make_decision(), trade)

    def test_voided_trade_new_attribution_rejected(self):
        with pytest.raises(AttributionValidationError):
            create_attribution(
                make_decision(),
                make_trade(voided_at="2026-08-11T00:00:00.000000+00:00"),
            )

    def test_naive_timestamp_rejected(self):
        with pytest.raises(AttributionValidationError):
            create_attribution(
                make_decision(), make_trade(created_at="2026-08-10T06:30:00")
            )

    def test_non_zero_offset_timestamp_rejected(self):
        with pytest.raises(AttributionValidationError):
            create_attribution(
                make_decision(), make_trade(created_at="2026-08-10T14:30:00+08:00")
            )


# ---------------------------------------------------------------------------
# 证券身份 / thesis 绑定
# ---------------------------------------------------------------------------

class TestIdentityBinding:
    def test_security_mismatch_fails_closed(self):
        with pytest.raises(AttributionValidationError):
            create_attribution(make_decision(), make_trade(code="000858"))

    def test_thesis_matching_passes(self):
        record = create_attribution(
            make_decision(), make_trade(thesis_id=THESIS_ID, thesis_revision=2),
            attribution_id=ATTRIBUTION_ID, created_at=CREATED_AT,
        )
        assert record.thesis_id == THESIS_ID

    def test_thesis_both_null_passes(self):
        record = create_attribution(
            make_decision(), make_trade(thesis_id=None, thesis_revision=None),
            attribution_id=ATTRIBUTION_ID, created_at=CREATED_AT,
        )
        assert record.thesis_id == THESIS_ID  # 决策成为归属锚

    def test_thesis_id_only_fails_closed(self):
        with pytest.raises(AttributionValidationError):
            create_attribution(make_decision(), make_trade(thesis_id=THESIS_ID, thesis_revision=None))

    def test_thesis_revision_only_fails_closed(self):
        with pytest.raises(AttributionValidationError):
            create_attribution(make_decision(), make_trade(thesis_id=None, thesis_revision=2))

    def test_thesis_id_conflict_fails_closed(self):
        with pytest.raises(AttributionValidationError):
            create_attribution(
                make_decision(), make_trade(thesis_id="f" * 32, thesis_revision=2)
            )

    def test_thesis_revision_conflict_fails_closed(self):
        with pytest.raises(AttributionValidationError):
            create_attribution(
                make_decision(), make_trade(thesis_id=THESIS_ID, thesis_revision=3)
            )


# ---------------------------------------------------------------------------
# 时域来源
# ---------------------------------------------------------------------------

class TestTemporalProvenance:
    def test_trade_created_before_decision_committed_rejected(self):
        # 事后伪造归属：交易先于决策
        with pytest.raises(AttributionValidationError):
            create_attribution(
                make_decision(),
                make_trade(created_at="2026-08-10T05:00:00.000000+00:00"),
            )

    def test_execution_before_decision_committed_rejected(self):
        with pytest.raises(AttributionValidationError):
            create_attribution(
                make_decision(),
                make_trade(
                    created_at="2026-08-10T06:30:00.000000+00:00",
                    executed_at="2026-08-10T05:59:00.000000+00:00",
                ),
            )

    def test_equal_instants_accepted(self):
        # 决策提交与交易创建同一时刻 → 允许（不晚于）
        record = create_attribution(
            make_decision(),
            make_trade(created_at="2026-08-10T06:00:00.000000+00:00"),
            attribution_id=ATTRIBUTION_ID, created_at=CREATED_AT,
        )
        assert record.trade_created_at == COMMITTED_AT

    def test_z_and_plus_offset_formats_compared_correctly(self):
        # 决策 Z 格式 vs 交易 +00:00 格式的跨格式比较
        record = create_attribution(
            make_decision(),
            make_trade(
                created_at="2026-08-10T06:30:00.000000Z",
                executed_at="2026-08-10T06:45:00.000000Z",
            ),
            attribution_id=ATTRIBUTION_ID, created_at=CREATED_AT,
        )
        assert record.trade_created_at == "2026-08-10T06:30:00.000000Z"


# ---------------------------------------------------------------------------
# 归属 ≠ 合规
# ---------------------------------------------------------------------------

class TestAttributionNotCompliance:
    def test_wait_to_buy_deviation_preserved(self):
        decision = make_decision(next_best_action="WAIT")
        record = create_attribution(
            decision, make_trade(operation="buy"),
            attribution_id=ATTRIBUTION_ID, created_at=CREATED_AT,
        )
        assert record.decision_next_best_action == "WAIT"
        assert record.trade_operation == "buy"
        assert record.decision_next_best_action != record.trade_operation

    def test_exit_to_add_deviation_preserved(self):
        decision = make_decision(next_best_action="EXIT")
        record = create_attribution(
            decision, make_trade(operation="add"),
            attribution_id=ATTRIBUTION_ID, created_at=CREATED_AT,
        )
        assert record.decision_next_best_action == "EXIT"
        assert record.trade_operation == "add"

    def test_review_by_past_does_not_reject(self):
        # review_by 早于交易：不是有效性引擎，仅保留证据
        decision = make_decision(review_by="2026-08-09T00:00:00.000000Z")
        record = create_attribution(
            decision, make_trade(),
            attribution_id=ATTRIBUTION_ID, created_at=CREATED_AT,
        )
        assert record.decision_review_by == "2026-08-09T00:00:00.000000Z"

    def test_no_fake_validity_status_in_record(self):
        record = create_attribution(
            make_decision(), make_trade(),
            attribution_id=ATTRIBUTION_ID, created_at=CREATED_AT,
        )
        # 归属记录不包含任何有效性/失效状态字段
        assert "validity_status" not in record.to_dict()
        assert "EXPIRED" not in record.to_dict().values()
        assert "STALE" not in record.to_dict().values()


# ---------------------------------------------------------------------------
# 哈希与严格序列化
# ---------------------------------------------------------------------------

class TestHashAndSerialization:
    def test_hash_deterministic_and_covers_all_fields(self):
        record = create_attribution(
            make_decision(), make_trade(),
            attribution_id=ATTRIBUTION_ID, created_at=CREATED_AT,
        )
        d = record.to_dict()
        assert compute_attribution_hash(d) == record.attribution_hash
        # 每个字段（含 attribution_id / created_at）都受哈希保护
        for field in d:
            if field == "attribution_hash":
                continue
            tampered = dict(d)
            if isinstance(tampered[field], str):
                tampered[field] = tampered[field] + "x"
            else:
                tampered[field] = tampered[field] + 1
            assert compute_attribution_hash(tampered) != record.attribution_hash

    def test_to_from_dict_roundtrip(self):
        record = create_attribution(
            make_decision(), make_trade(),
            attribution_id=ATTRIBUTION_ID, created_at=CREATED_AT,
        )
        assert from_dict(record.to_dict()) == record

    def test_from_dict_missing_field_rejected(self):
        record = create_attribution(
            make_decision(), make_trade(),
            attribution_id=ATTRIBUTION_ID, created_at=CREATED_AT,
        )
        d = record.to_dict()
        del d["campaign_id"]
        with pytest.raises(AttributionValidationError):
            from_dict(d)

    def test_from_dict_extra_field_rejected(self):
        record = create_attribution(
            make_decision(), make_trade(),
            attribution_id=ATTRIBUTION_ID, created_at=CREATED_AT,
        )
        d = record.to_dict()
        d["extra"] = 1
        with pytest.raises(AttributionValidationError):
            from_dict(d)

    def test_from_dict_wrong_type_rejected(self):
        record = create_attribution(
            make_decision(), make_trade(),
            attribution_id=ATTRIBUTION_ID, created_at=CREATED_AT,
        )
        d = record.to_dict()
        d["thesis_revision"] = "2"
        with pytest.raises(AttributionValidationError):
            from_dict(d)

    def test_from_dict_tampered_hash_rejected(self):
        record = create_attribution(
            make_decision(), make_trade(),
            attribution_id=ATTRIBUTION_ID, created_at=CREATED_AT,
        )
        d = record.to_dict()
        d["attribution_hash"] = "0" * 64
        with pytest.raises(AttributionValidationError):
            from_dict(d)

    def test_from_dict_tampered_content_rejected(self):
        record = create_attribution(
            make_decision(), make_trade(),
            attribution_id=ATTRIBUTION_ID, created_at=CREATED_AT,
        )
        d = record.to_dict()
        d["trade_operation"] = "sell"
        with pytest.raises(AttributionValidationError):
            from_dict(d)

    def test_from_dict_non_canonical_timestamp_rejected(self):
        record = create_attribution(
            make_decision(), make_trade(),
            attribution_id=ATTRIBUTION_ID, created_at=CREATED_AT,
        )
        d = record.to_dict()
        d["created_at"] = "2026-08-10T07:00:00+00:00"
        with pytest.raises(AttributionValidationError):
            from_dict(d)

    def test_from_dict_unknown_schema_rejected(self):
        record = create_attribution(
            make_decision(), make_trade(),
            attribution_id=ATTRIBUTION_ID, created_at=CREATED_AT,
        )
        d = record.to_dict()
        d["schema_version"] = "formal_trade_attribution.v9.9"
        with pytest.raises(AttributionSchemaVersionError):
            from_dict(d)

    def test_from_dict_status_executed_at_consistency(self):
        record = create_attribution(
            make_decision(), make_trade(),
            attribution_id=ATTRIBUTION_ID, created_at=CREATED_AT,
        )
        d = record.to_dict()
        d["trade_execution_status"] = "not_executed"
        with pytest.raises(AttributionValidationError):
            from_dict(d)

    def test_from_dict_not_executed_with_none_executed_at_ok(self):
        record = create_attribution(
            make_decision(),
            make_trade(execution_status="not_executed", executed_at=None, unexecuted_reason="x"),
            attribution_id=ATTRIBUTION_ID, created_at=CREATED_AT,
        )
        assert from_dict(record.to_dict()) == record


# ---------------------------------------------------------------------------
# 集合验证
# ---------------------------------------------------------------------------

class TestSetValidation:
    def _attribution(self, trade=None, decision=None, attribution_id=ATTRIBUTION_ID, created_at=CREATED_AT):
        return create_attribution(
            decision or make_decision(),
            trade or make_trade(),
            attribution_id=attribution_id, created_at=created_at,
        )

    def test_one_trade_two_decisions_rejected(self):
        other_decision = make_decision(decision_id="decision_" + "f" * 32)
        records = [
            self._attribution(),
            create_attribution(
                other_decision, make_trade(),  # 同 trade_id 不同决策
                attribution_id="trade_attribution_" + "9" * 32,
                created_at=CREATED_AT,
            ),
        ]
        with pytest.raises(AttributionConflictError):
            validate_attribution_set(records)

    def test_one_decision_many_trades_allowed(self):
        records = [
            self._attribution(
                trade=make_trade(trade_id="1" * 32),
                attribution_id="trade_attribution_" + "1" * 32,
            ),
            self._attribution(
                trade=make_trade(trade_id="2" * 32, operation="add", execution_status="partial"),
                attribution_id="trade_attribution_" + "2" * 32,
            ),
            self._attribution(
                trade=make_trade(trade_id="3" * 32, operation="reduce"),
                attribution_id="trade_attribution_" + "3" * 32,
            ),
        ]
        validated = validate_attribution_set(records)
        assert len(validated) == 3

    def test_exact_duplicate_idempotent(self):
        records = [self._attribution(), self._attribution()]
        validated = validate_attribution_set(records)
        assert len(validated) == 2

    def test_same_id_conflicting_content_rejected(self):
        other = self._attribution().to_dict()
        other["trade_operation"] = "sell"
        other["attribution_hash"] = compute_attribution_hash(other)
        with pytest.raises(AttributionConflictError):
            validate_attribution_set([self._attribution(), other])

    def test_invalid_record_rejected(self):
        bad = self._attribution().to_dict()
        bad["strategy"] = "DAYTRADE"
        with pytest.raises(AttributionValidationError):
            validate_attribution_set([bad])

    def test_same_decision_identity_drift_rejected(self):
        drift = self._attribution(
            trade=make_trade(trade_id="7" * 32),
            attribution_id="trade_attribution_" + "7" * 32,
        ).to_dict()
        drift["campaign_id"] = "campaign_" + "9" * 32
        drift["attribution_hash"] = compute_attribution_hash(drift)
        with pytest.raises(AttributionConflictError):
            validate_attribution_set([self._attribution(), drift])

    def test_order_independent(self):
        a = self._attribution(
            trade=make_trade(trade_id="1" * 32),
            attribution_id="trade_attribution_" + "1" * 32,
        )
        b = self._attribution(
            trade=make_trade(trade_id="2" * 32, operation="sell"),
            attribution_id="trade_attribution_" + "2" * 32,
        )
        key = lambda d: d["attribution_id"]  # noqa: E731
        assert sorted(validate_attribution_set([a, b]), key=key) == sorted(
            validate_attribution_set([b, a]), key=key
        )

    def test_mixed_object_and_mapping_inputs(self):
        a = self._attribution()
        b = self._attribution(
            trade=make_trade(trade_id="2" * 32),
            attribution_id="trade_attribution_" + "2" * 32,
        )
        validated = validate_attribution_set([a, b.to_dict()])
        assert len(validated) == 2


# ---------------------------------------------------------------------------
# 投影
# ---------------------------------------------------------------------------

class TestProjections:
    def _three_attributions(self):
        records = [
            create_attribution(
                make_decision(),
                make_trade(trade_id="1" * 32),
                attribution_id="trade_attribution_" + "1" * 32,
                created_at="2026-08-10T07:00:00.000000Z",
            ),
            create_attribution(
                make_decision(decision_id="decision_" + "f" * 32),
                make_trade(trade_id="2" * 32),
                attribution_id="trade_attribution_" + "2" * 32,
                created_at="2026-08-10T07:01:00.000000Z",
            ),
            create_attribution(
                make_decision(),
                make_trade(trade_id="3" * 32, operation="add"),
                attribution_id="trade_attribution_" + "3" * 32,
                created_at="2026-08-10T07:02:00.000000Z",
            ),
        ]
        return records

    def test_attributions_for_decision_filters_and_sorts(self):
        records = self._three_attributions()
        result = attributions_for_decision(DECISION_ID, records)
        assert [r["trade_id"] for r in result] == ["1" * 32, "3" * 32]
        # 确定性排序：created_at ASC, attribution_id ASC
        assert result == sorted(result, key=lambda r: (r["created_at"], r["attribution_id"]))

    def test_attribution_for_trade(self):
        records = self._three_attributions()
        result = attribution_for_trade("2" * 32, records)
        assert len(result) == 1
        assert result[0]["decision_id"] == "decision_" + "f" * 32

    def test_projection_rejects_invalid_collection(self):
        valid = self._three_attributions()
        conflict = create_attribution(
            make_decision(decision_id="decision_" + "f" * 32),
            make_trade(trade_id="1" * 32),  # 与第一条同 trade_id 不同决策
            attribution_id="trade_attribution_" + "8" * 32,
            created_at=CREATED_AT,
        )
        records = valid + [conflict]
        with pytest.raises(AttributionConflictError):
            attributions_for_decision(DECISION_ID, records)
        with pytest.raises(AttributionConflictError):
            attribution_for_trade("1" * 32, records)


# ---------------------------------------------------------------------------
# 与既有权威的 parity
# ---------------------------------------------------------------------------

class TestParity:
    def test_real_frozen_decision_service_output_accepted(self, tmp_path):
        """FD1 服务真实产出可直接作为见证（FROZEN_DECISION_PARITY）。"""
        frozen = freeze_decision(
            {
                "security_code": "600519",
                "strategy": "SWING",
                "campaign_id": "campaign_" + "d" * 32,
                "thesis_id": THESIS_ID,
                "thesis_revision": 2,
                "asset_view": {"label": "茅台"},
                "trade_view": {"size_pct": 0.1},
                "portfolio_view": {"target_weight": 0.15},
                "next_best_action": "WAIT",
                "action_envelope": {"max_size": 0.1},
                "maintain_conditions": ["a"],
                "upgrade_conditions": [],
                "downgrade_conditions": [],
                "invalidation_conditions": [],
                "strategy_horizon": "2 周",
                "review_by": "2026-08-25T00:00:00Z",
                "key_assumptions": [],
                "event_invalidation_conditions": [],
                "risk_policy_version": "v1",
                "opportunity_policy_version": "v1",
                "decision_policy_version": "v1",
                "behavior_model_version": "v1",
                "user_confirmed": True,
            },
            tmp_path / "fd.sqlite3",
        )
        # 交易创建时刻必须不晚于服务生成的 committed_at（用明确的未来时间）
        trade = make_trade(
            created_at="2026-08-12T08:00:00.000000+00:00",
            executed_at="2026-08-12T08:05:00.000000+00:00",
        )
        record = create_attribution(frozen, trade)
        assert record.decision_id == frozen["decision_id"]
        assert record.decision_snapshot_hash == frozen["snapshot_hash"]
        assert record.decision_next_best_action == "WAIT"
        assert record.trade_operation == "buy"

    def test_trade_ledger_real_shape_accepted(self):
        """Trade Ledger 存储记录全字段形状（含价格/数量等无关字段）可接受。"""
        trade = make_trade(
            planned_price=1500.0, planned_quantity=100,
            actual_price=1500.0, actual_quantity=100,
            fee=5.0, other_cost=0.0,
            unexecuted_reason=None, note="手动交易",
            advice_trade_date=None, advice_generated_at=None, advice_snapshot=None,
        )
        record = create_attribution(
            make_decision(), trade,
            attribution_id=ATTRIBUTION_ID, created_at=CREATED_AT,
        )
        assert record.trade_operation == "buy"
        assert record.trade_execution_status == "full"

    def test_trade_operation_enum_parity(self):
        assert set(fta.TRADE_OPERATIONS) == {"buy", "add", "reduce", "sell"}
        assert set(fta.TRADE_EXECUTION_STATUSES) == {"full", "partial", "not_executed"}

    def test_frozen_decision_parity_constants(self):
        assert fta.FROZEN_DECISION_SCHEMA_VERSION == fd_store.SCHEMA_VERSION
        assert fta.STRATEGIES == fd_store.STRATEGIES
        assert fta.NEXT_BEST_ACTIONS == fd_store.NEXT_BEST_ACTIONS
