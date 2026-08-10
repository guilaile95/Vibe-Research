"""Frozen Decision Ledger 服务层测试：确认门、严格验证、确定性哈希、幂等重放。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import frozen_decision_service as svc
import frozen_decision_store as store


def valid_payload(**overrides) -> dict:
    payload = {
        "security_code": "600519",
        "strategy": "SWING",
        "campaign_id": "campaign_" + "b" * 32,
        "thesis_id": "c" * 32,
        "thesis_revision": 2,
        "asset_view": {"label": "贵州茅台", "pe": 30.5},
        "trade_view": {"entry_zone": [1400, 1450], "size_pct": 0.1},
        "portfolio_view": {"target_weight": 0.15},
        "next_best_action": "BUY SMALL",
        "action_envelope": {"max_size": 0.1, "min_size": 0.05},
        "maintain_conditions": ["营收增速保持", "PE 不高于 35"],
        "upgrade_conditions": ["站稳年线"],
        "downgrade_conditions": ["跌破 60 日线"],
        "invalidation_conditions": ["业绩暴雷"],
        "strategy_horizon": "2 至 4 周",
        "review_by": "2026-08-25T00:00:00Z",
        "key_assumptions": ["宏观流动性宽松"],
        "event_invalidation_conditions": ["减持公告"],
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
        "user_confirmed": True,
    }
    payload.update(overrides)
    return payload


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "frozen_decisions.sqlite3"


def _rebuild_snapshot(frozen: dict) -> dict:
    return {key: frozen[key] for key in store.SNAPSHOT_KEYS}


def _recompute(frozen: dict, **changes) -> dict:
    """基于既有冻结对象生成内部自洽的变体：snapshot_json/hash 同步重建。"""
    snapshot = _rebuild_snapshot(frozen)
    snapshot.update(changes)
    out = dict(frozen)
    out.update(snapshot)
    out["snapshot_json"] = store.canonical_json(snapshot)
    out["snapshot_hash"] = store.snapshot_hash(snapshot)
    return out


# ---------------------------------------------------------------------------
# 正常冻结
# ---------------------------------------------------------------------------

class TestFreezeHappyPath:
    def test_freeze_creates_frozen_decision(self, db_path):
        frozen = svc.freeze_decision(valid_payload(), db_path)
        assert frozen["decision_id"].startswith("decision_")
        assert len(frozen["decision_id"]) == len("decision_") + 32
        assert len(frozen["snapshot_hash"]) == 64
        assert frozen["user_confirmed"] is True
        assert frozen["validity_status_at_commit"] == "CURRENT"
        assert frozen["snapshot_schema_version"] == store.SCHEMA_VERSION
        assert frozen["committed_at"].endswith("Z")
        assert frozen["review_by"] == "2026-08-25T00:00:00.000000Z"
        assert frozen["asset_view"] == {"label": "贵州茅台", "pe": 30.5}
        assert frozen["trade_view"] == {"entry_zone": [1400, 1450], "size_pct": 0.1}
        assert frozen["portfolio_view"] == {"target_weight": 0.15}
        assert frozen["evidence_refs"] == ["ev_123"]
        assert frozen["risk_refs"] == []
        assert frozen["source_refs"] == ["src_1"]

    def test_frozen_readable_and_listable(self, db_path):
        frozen = svc.freeze_decision(valid_payload(), db_path)
        got = svc.get_decision(frozen["decision_id"], db_path)
        assert got == frozen
        listed = svc.list_decisions(db_path)
        assert listed == [frozen]

    def test_three_views_persisted_independently(self, db_path):
        frozen = svc.freeze_decision(valid_payload(), db_path)
        got = svc.get_decision(frozen["decision_id"], db_path)
        # 三个视图各自原样独立存在，未被压缩为单一 BUY/SELL 字段
        assert got["asset_view"] == {"label": "贵州茅台", "pe": 30.5}
        assert got["trade_view"] == {"entry_zone": [1400, 1450], "size_pct": 0.1}
        assert got["portfolio_view"] == {"target_weight": 0.15}
        assert set(got) & {"asset_view", "trade_view", "portfolio_view"}

    def test_review_by_normalized_to_canonical_utc(self, db_path):
        frozen = svc.freeze_decision(
            valid_payload(review_by="2026-08-25T08:00:00+00:00"), db_path
        )
        assert frozen["review_by"] == "2026-08-25T08:00:00.000000Z"

    def test_missing_db_read_returns_empty_without_side_effects(self, tmp_path):
        missing = tmp_path / "no" / "dir" / "frozen_decisions.sqlite3"
        assert svc.get_decision("decision_" + "a" * 32, missing) is None
        assert svc.list_decisions(missing) == []
        assert not (tmp_path / "no").exists()


# ---------------------------------------------------------------------------
# 确定性哈希与身份
# ---------------------------------------------------------------------------

class TestHashAndIdentity:
    def test_same_payload_two_commits_two_decisions(self, db_path):
        first = svc.freeze_decision(valid_payload(), db_path)
        second = svc.freeze_decision(valid_payload(), db_path)
        assert first["decision_id"] != second["decision_id"]
        # 业务内容一致，但身份不按业务键去重
        assert len(svc.list_decisions(db_path)) == 2
        assert first["security_code"] == second["security_code"]

    def test_snapshot_hash_covers_all_protected_fields(self, db_path):
        frozen = svc.freeze_decision(valid_payload(), db_path)
        base_hash = store.snapshot_hash(_rebuild_snapshot(frozen))
        assert base_hash == frozen["snapshot_hash"]
        # 逐个修改保护字段，哈希必须变化
        mutations = {
            "security_code": "000858",
            "strategy": "MEDIUM",
            "campaign_id": "campaign_" + "e" * 32,
            "thesis_id": "f" * 32,
            "thesis_revision": 3,
            "asset_view": {"pe": 99},
            "trade_view": {"size_pct": 0.5},
            "portfolio_view": {"target_weight": 0.9},
            "next_best_action": "HOLD",
            "action_envelope": {"max_size": 0.9},
            "maintain_conditions": ["改"],
            "upgrade_conditions": ["改"],
            "downgrade_conditions": ["改"],
            "invalidation_conditions": ["改"],
            "strategy_horizon": "改",
            "review_by": "2026-12-01T00:00:00Z",
            "key_assumptions": ["改"],
            "event_invalidation_conditions": ["改"],
            "risk_policy_version": "改",
            "opportunity_policy_version": "改",
            "decision_policy_version": "改",
            "behavior_model_version": "改",
            "evidence_refs": ["改"],
            "risk_refs": ["改"],
            "source_refs": ["改"],
        }
        for field, value in mutations.items():
            altered = dict(frozen)
            altered[field] = value
            assert store.snapshot_hash(_rebuild_snapshot(altered)) != base_hash, (
                f"hash 未覆盖 {field}"
            )

    def test_snapshot_hash_deterministic(self, db_path):
        frozen = svc.freeze_decision(valid_payload(), db_path)
        rebuilt = _rebuild_snapshot(frozen)
        assert store.canonical_json(rebuilt) == store.canonical_json(dict(rebuilt))
        assert store.snapshot_hash(rebuilt) == frozen["snapshot_hash"]


# ---------------------------------------------------------------------------
# 用户确认门
# ---------------------------------------------------------------------------

class TestUserCommitGate:
    @pytest.mark.parametrize(
        "value",
        [False, None, 1, 0, "true", "True", "yes", [], {}],
    )
    def test_non_strict_true_rejected(self, db_path, value):
        with pytest.raises(svc.FrozenDecisionValidationError):
            svc.freeze_decision(valid_payload(user_confirmed=value), db_path)
        assert svc.list_decisions(db_path) == []

    def test_missing_user_confirmed_rejected(self, db_path):
        payload = valid_payload()
        del payload["user_confirmed"]
        with pytest.raises(svc.FrozenDecisionValidationError):
            svc.freeze_decision(payload, db_path)


# ---------------------------------------------------------------------------
# 严格验证矩阵
# ---------------------------------------------------------------------------

class TestValidation:
    @pytest.mark.parametrize("code", ["60051", "6005190", "60051a", "abc", "", 600519])
    def test_security_code_rejected(self, db_path, code):
        with pytest.raises(svc.FrozenDecisionValidationError):
            svc.freeze_decision(valid_payload(security_code=code), db_path)

    @pytest.mark.parametrize("strategy", ["swing", "SWING ", " Swing", "", None, 1])
    def test_strategy_strict_enum(self, db_path, strategy):
        with pytest.raises(svc.FrozenDecisionValidationError):
            svc.freeze_decision(valid_payload(strategy=strategy), db_path)

    @pytest.mark.parametrize("strategy", ["SHORT", "SWING", "MEDIUM"])
    def test_strategy_valid_values(self, db_path, strategy):
        frozen = svc.freeze_decision(valid_payload(strategy=strategy), db_path)
        assert frozen["strategy"] == strategy

    @pytest.mark.parametrize(
        "campaign_id",
        ["campaign_abc", "campaign_" + "A" * 32, "C" + "a" * 39, "", None],
    )
    def test_campaign_id_rejected(self, db_path, campaign_id):
        with pytest.raises(svc.FrozenDecisionValidationError):
            svc.freeze_decision(valid_payload(campaign_id=campaign_id), db_path)

    @pytest.mark.parametrize(
        "thesis_id", ["abc", "C" * 32, "c" * 31, "thesis_" + "c" * 32, ""]
    )
    def test_thesis_id_rejected(self, db_path, thesis_id):
        with pytest.raises(svc.FrozenDecisionValidationError):
            svc.freeze_decision(valid_payload(thesis_id=thesis_id), db_path)

    @pytest.mark.parametrize("revision", [0, -1, 1.5, "2", True, None])
    def test_thesis_revision_rejected(self, db_path, revision):
        with pytest.raises(svc.FrozenDecisionValidationError):
            svc.freeze_decision(valid_payload(thesis_revision=revision), db_path)

    @pytest.mark.parametrize(
        "review_by",
        [None, "", "2026-08-25", "2026-08-25T00:00:00", "2026-08-25T08:00:00+08:00", "明天"],
    )
    def test_review_by_missing_or_invalid_rejected_without_inference(self, db_path, review_by):
        with pytest.raises(svc.FrozenDecisionValidationError):
            svc.freeze_decision(valid_payload(review_by=review_by), db_path)

    def test_review_by_required(self, db_path):
        payload = valid_payload()
        del payload["review_by"]
        with pytest.raises(svc.FrozenDecisionValidationError):
            svc.freeze_decision(payload, db_path)

    @pytest.mark.parametrize(
        "field",
        ["asset_view", "trade_view", "portfolio_view", "action_envelope"],
    )
    def test_view_must_be_object(self, db_path, field):
        for bad in ([], "str", 1, None, True):
            with pytest.raises(svc.FrozenDecisionValidationError):
                svc.freeze_decision(valid_payload(**{field: bad}), db_path)

    @pytest.mark.parametrize(
        "field", ["asset_view", "trade_view", "portfolio_view", "action_envelope"]
    )
    def test_view_rejects_nan_infinity(self, db_path, field):
        with pytest.raises(svc.FrozenDecisionValidationError):
            svc.freeze_decision(
                valid_payload(**{field: {"x": float("nan")}}), db_path
            )
        with pytest.raises(svc.FrozenDecisionValidationError):
            svc.freeze_decision(
                valid_payload(**{field: {"x": float("inf")}}), db_path
            )

    def test_view_nested_unknown_values_preserved(self, db_path):
        payload = valid_payload(asset_view={"a": 1, "b": {"c": [1, 2, {"d": "x"}]}})
        frozen = svc.freeze_decision(payload, db_path)
        assert frozen["asset_view"] == {"a": 1, "b": {"c": [1, 2, {"d": "x"}]}}

    @pytest.mark.parametrize(
        "nba", ["BUY", "buy now", "SELL", "", "WAIT ", None, 1]
    )
    def test_next_best_action_strict_enum(self, db_path, nba):
        with pytest.raises(svc.FrozenDecisionValidationError):
            svc.freeze_decision(valid_payload(next_best_action=nba), db_path)

    @pytest.mark.parametrize(
        "field",
        [
            "maintain_conditions",
            "upgrade_conditions",
            "downgrade_conditions",
            "invalidation_conditions",
            "key_assumptions",
            "event_invalidation_conditions",
        ],
    )
    def test_conditions_must_be_list(self, db_path, field):
        for bad in ("str", {"a": 1}, None, 1):
            with pytest.raises(svc.FrozenDecisionValidationError):
                svc.freeze_decision(valid_payload(**{field: bad}), db_path)

    def test_conditions_containing_nan_rejected(self, db_path):
        with pytest.raises(svc.FrozenDecisionValidationError):
            svc.freeze_decision(
                valid_payload(maintain_conditions=["ok", float("nan")]), db_path
            )

    @pytest.mark.parametrize("horizon", ["", "   ", None, 1, [], True])
    def test_strategy_horizon_rejected(self, db_path, horizon):
        with pytest.raises(svc.FrozenDecisionValidationError):
            svc.freeze_decision(valid_payload(strategy_horizon=horizon), db_path)

    def test_strategy_horizon_object_allowed(self, db_path):
        frozen = svc.freeze_decision(
            valid_payload(strategy_horizon={"window": "2-4w", "note": "不设 TTL 推断"}), db_path
        )
        assert frozen["strategy_horizon"] == {"window": "2-4w", "note": "不设 TTL 推断"}

    def test_strategy_horizon_nan_validation_error(self, db_path):
        # P2-1：NaN 必须报 FrozenDecisionValidationError，而不是裸 TypeError
        with pytest.raises(svc.FrozenDecisionValidationError):
            svc.freeze_decision(
                valid_payload(strategy_horizon={"x": float("nan")}), db_path
            )
        with pytest.raises(svc.FrozenDecisionValidationError):
            svc.freeze_decision(
                valid_payload(strategy_horizon={"x": float("inf")}), db_path
            )

    @pytest.mark.parametrize(
        "field",
        [
            "risk_policy_version",
            "opportunity_policy_version",
            "decision_policy_version",
            "behavior_model_version",
        ],
    )
    def test_policy_version_must_be_nonempty_str(self, db_path, field):
        for bad in ("", "  ", None, 1):
            with pytest.raises(svc.FrozenDecisionValidationError):
                svc.freeze_decision(valid_payload(**{field: bad}), db_path)

    def test_explicit_unknown_policy_version_allowed(self, db_path):
        # UNKNOWN 只允许显式由调用方提供，服务不注入
        frozen = svc.freeze_decision(
            valid_payload(risk_policy_version="UNKNOWN"), db_path
        )
        assert frozen["risk_policy_version"] == "UNKNOWN"

    def test_confidence_stack_preserved_not_averaged(self, db_path):
        frozen = svc.freeze_decision(valid_payload(), db_path)
        assert frozen["data_quality"] == {"grade": "high"}
        assert frozen["evidence_confidence"] == 0.8
        assert frozen["inference_confidence"] == "medium"
        assert frozen["decision_confidence"] is None

    def test_confidence_stack_optional(self, db_path):
        payload = valid_payload()
        for key in (
            "data_quality",
            "evidence_confidence",
            "inference_confidence",
            "decision_confidence",
        ):
            del payload[key]
        frozen = svc.freeze_decision(payload, db_path)
        assert frozen["data_quality"] is None

    def test_confidence_rejects_nan(self, db_path):
        with pytest.raises(svc.FrozenDecisionValidationError):
            svc.freeze_decision(valid_payload(evidence_confidence=float("nan")), db_path)

    def test_refs_must_be_string_lists(self, db_path):
        for bad in ("ev_1", {"a": 1}, [1, 2], [None]):
            with pytest.raises(svc.FrozenDecisionValidationError):
                svc.freeze_decision(valid_payload(evidence_refs=bad), db_path)

    def test_refs_optional_default_empty(self, db_path):
        payload = valid_payload()
        for key in ("evidence_refs", "risk_refs", "source_refs"):
            del payload[key]
        frozen = svc.freeze_decision(payload, db_path)
        assert frozen["evidence_refs"] == []
        assert frozen["risk_refs"] == []
        assert frozen["source_refs"] == []

    def test_unknown_top_level_field_rejected(self, db_path):
        payload = valid_payload()
        payload["stratagy"] = "SWING"
        with pytest.raises(svc.FrozenDecisionValidationError):
            svc.freeze_decision(payload, db_path)

    def test_missing_required_field_rejected(self, db_path):
        for key in (
            "security_code",
            "strategy",
            "campaign_id",
            "thesis_id",
            "thesis_revision",
            "asset_view",
            "trade_view",
            "portfolio_view",
            "next_best_action",
            "action_envelope",
            "maintain_conditions",
            "upgrade_conditions",
            "downgrade_conditions",
            "invalidation_conditions",
            "strategy_horizon",
            "review_by",
            "key_assumptions",
            "event_invalidation_conditions",
            "risk_policy_version",
            "opportunity_policy_version",
            "decision_policy_version",
            "behavior_model_version",
            "user_confirmed",
        ):
            payload = valid_payload()
            del payload[key]
            with pytest.raises(svc.FrozenDecisionValidationError):
                svc.freeze_decision(payload, db_path)

    @pytest.mark.parametrize(
        "field", ["committed_at", "snapshot_hash", "snapshot_schema_version", "created_at"]
    )
    def test_service_generated_fields_rejected_in_new_freeze(self, db_path, field):
        payload = valid_payload()
        payload[field] = "whatever"
        with pytest.raises(svc.FrozenDecisionValidationError):
            svc.freeze_decision(payload, db_path)

    def test_payload_must_be_mapping(self, db_path):
        for bad in (None, [], "str", 1):
            with pytest.raises(svc.FrozenDecisionValidationError):
                svc.freeze_decision(bad, db_path)


# ---------------------------------------------------------------------------
# 精确重放
# ---------------------------------------------------------------------------

class TestReplay:
    def test_exact_replay_idempotent(self, db_path):
        frozen = svc.freeze_decision(valid_payload(), db_path)
        replay = svc.freeze_decision(frozen, db_path)
        assert replay == frozen
        assert len(svc.list_decisions(db_path)) == 1

    def test_replay_with_modified_content_rejected(self, db_path):
        frozen = svc.freeze_decision(valid_payload(), db_path)
        tampered = dict(frozen)
        tampered["asset_view"] = {"label": "篡改"}
        with pytest.raises(svc.FrozenDecisionValidationError):
            svc.freeze_decision(tampered, db_path)

    def test_replay_with_modified_hash_rejected(self, db_path):
        frozen = svc.freeze_decision(valid_payload(), db_path)
        tampered = dict(frozen)
        tampered["snapshot_hash"] = "0" * 64
        with pytest.raises(svc.FrozenDecisionValidationError):
            svc.freeze_decision(tampered, db_path)

    def test_replay_with_modified_snapshot_json_rejected(self, db_path):
        frozen = svc.freeze_decision(valid_payload(), db_path)
        tampered = dict(frozen)
        # canonical 文本紧凑无空格；直接改文本但不改字段 → 文本与快照不一致
        tampered["snapshot_json"] = tampered["snapshot_json"].replace(
            '"pe":30.5', '"pe":99'
        )
        assert tampered["snapshot_json"] != frozen["snapshot_json"]
        with pytest.raises(svc.FrozenDecisionValidationError):
            svc.freeze_decision(tampered, db_path)

    def test_replay_with_invalid_decision_id_rejected(self, db_path):
        frozen = svc.freeze_decision(valid_payload(), db_path)
        tampered = dict(frozen)
        tampered["decision_id"] = "campaign_" + "a" * 32
        with pytest.raises(svc.FrozenDecisionValidationError):
            svc.freeze_decision(tampered, db_path)

    def test_replay_missing_fields_rejected(self, db_path):
        frozen = svc.freeze_decision(valid_payload(), db_path)
        for key in ("snapshot_hash", "committed_at", "decision_id"):
            tampered = dict(frozen)
            del tampered[key]
            with pytest.raises(svc.FrozenDecisionValidationError):
                svc.freeze_decision(tampered, db_path)

    def test_replay_unknown_field_rejected(self, db_path):
        frozen = svc.freeze_decision(valid_payload(), db_path)
        tampered = dict(frozen)
        tampered["extra"] = 1
        with pytest.raises(svc.FrozenDecisionValidationError):
            svc.freeze_decision(tampered, db_path)

    def test_replay_user_confirmed_still_required(self, db_path):
        frozen = svc.freeze_decision(valid_payload(), db_path)
        tampered = dict(frozen)
        tampered["user_confirmed"] = "yes"
        with pytest.raises(svc.FrozenDecisionValidationError):
            svc.freeze_decision(tampered, db_path)

    def test_replay_different_snapshot_schema_rejected(self, db_path):
        frozen = svc.freeze_decision(valid_payload(), db_path)
        tampered = dict(frozen)
        tampered["snapshot_schema_version"] = "frozen-decision-ledger.v0.2"
        with pytest.raises(svc.FrozenDecisionValidationError):
            svc.freeze_decision(tampered, db_path)


class TestReplayP1AbsentTarget:
    """P1-A：重放仅允许已提交 decision_id；禁止重放创建新记录。"""

    def test_a_absent_target_empty_db_rejected_db_remains_empty(self, db_path, tmp_path):
        # 在另一个库生成完整、内部自洽的冻结对象（含调用方持有的
        # decision_id / committed_at / created_at / snapshot_json / snapshot_hash）
        other_db = tmp_path / "other.sqlite3"
        frozen = svc.freeze_decision(valid_payload(), other_db)
        # 目标库为空：重放必须被拒绝，库保持为空
        with pytest.raises(svc.FrozenDecisionReplayNotFoundError):
            svc.freeze_decision(frozen, db_path)
        assert svc.list_decisions(db_path) == []

    def test_b_missing_db_replay_rejected_nothing_created(self, tmp_path):
        missing = tmp_path / "no" / "such" / "frozen_decisions.sqlite3"
        other_db = tmp_path / "other.sqlite3"
        frozen = svc.freeze_decision(valid_payload(), other_db)
        with pytest.raises(svc.FrozenDecisionReplayNotFoundError):
            svc.freeze_decision(frozen, missing)
        assert not (tmp_path / "no").exists()

    def test_c_existing_exact_replay_idempotent(self, db_path):
        frozen = svc.freeze_decision(valid_payload(), db_path)
        replay = svc.freeze_decision(frozen, db_path)
        assert replay == frozen
        assert len(svc.list_decisions(db_path)) == 1

    def test_d_existing_conflicting_replay_conflict_original_unchanged(self, db_path):
        frozen = svc.freeze_decision(valid_payload(), db_path)
        conflicting = _recompute(frozen, next_best_action="HOLD")
        with pytest.raises(store.FrozenDecisionConflictError):
            svc.freeze_decision(conflicting, db_path)
        assert svc.get_decision(frozen["decision_id"], db_path) == frozen

    def test_e_replay_cannot_backdate_committed_at(self, db_path):
        frozen = svc.freeze_decision(valid_payload(), db_path)
        backdated = _recompute(frozen, committed_at="2020-01-01T00:00:00.000000Z")
        with pytest.raises(store.FrozenDecisionConflictError):
            svc.freeze_decision(backdated, db_path)
        # 原始提交时刻保持不变，未被回填/回改
        got = svc.get_decision(frozen["decision_id"], db_path)
        assert got["committed_at"] == frozen["committed_at"]
        assert got["committed_at"] != "2020-01-01T00:00:00.000000Z"

    def test_replay_with_non_canonical_created_at_rejected(self, db_path):
        frozen = svc.freeze_decision(valid_payload(), db_path)
        for bad in ("garbage", "2026-08-10T06:00:01+00:00", ""):
            tampered = dict(frozen)
            tampered["created_at"] = bad
            with pytest.raises(svc.FrozenDecisionValidationError):
                svc.freeze_decision(tampered, db_path)

    def test_replay_absent_target_with_synthetic_payload_rejected(self, db_path):
        # 纯手工构造的自洽 payload（未经服务提交）同样被拒绝
        real = svc.freeze_decision(valid_payload(), db_path)
        synthetic = _recompute(
            real,
            decision_id="decision_" + "9" * 32,
            committed_at="2021-05-05T00:00:00.000000Z",
        )
        synthetic["created_at"] = "2021-05-05T00:00:01.000000Z"
        with pytest.raises(svc.FrozenDecisionReplayNotFoundError):
            svc.freeze_decision(synthetic, db_path)
        assert svc.get_decision(synthetic["decision_id"], db_path) is None


# ---------------------------------------------------------------------------
# 读取契约
# ---------------------------------------------------------------------------

class TestReadContract:
    def test_get_missing_returns_none(self, db_path):
        assert svc.get_decision("decision_" + "a" * 32, db_path) is None

    def test_list_order_and_filters(self, db_path):
        svc.freeze_decision(
            valid_payload(security_code="600519", strategy="SWING", campaign_id="campaign_" + "1" * 32), db_path
        )
        svc.freeze_decision(
            valid_payload(security_code="000858", strategy="SHORT", campaign_id="campaign_" + "2" * 32), db_path
        )
        svc.freeze_decision(
            valid_payload(security_code="600519", strategy="MEDIUM", campaign_id="campaign_" + "1" * 32), db_path
        )
        by_code = svc.list_decisions(db_path, security_code="600519")
        assert len(by_code) == 2
        by_campaign = svc.list_decisions(db_path, campaign_id="campaign_" + "1" * 32)
        assert len(by_campaign) == 2
        by_strategy = svc.list_decisions(db_path, strategy="SHORT")
        assert len(by_strategy) == 1
        # 确定性排序：committed_at ASC，decision_id ASC
        all_decisions = svc.list_decisions(db_path)
        assert all_decisions == sorted(
            all_decisions, key=lambda d: (d["committed_at"], d["decision_id"])
        )

    def test_frozen_decision_never_mutates_across_reads(self, db_path):
        frozen = svc.freeze_decision(valid_payload(), db_path)
        first = svc.get_decision(frozen["decision_id"], db_path)
        second = svc.get_decision(frozen["decision_id"], db_path)
        assert first == second == frozen
