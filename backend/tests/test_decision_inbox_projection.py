"""P0-DI1 Decision Inbox 纯域投影核心测试：26 项测试矩阵，零 I/O。"""
from __future__ import annotations

import inspect
from datetime import datetime, timedelta

import pytest

import decision_inbox_projection as di
from decision_inbox_projection import (
    CampaignFacts,
    DecisionInboxValidationError,
    InboxItem,
    project_campaign,
    project_campaigns,
)

SECURITY = "600519"
STRATEGY = "SWING"
CAMPAIGN_ID = "campaign_" + "a" * 32
AS_OF = "2026-08-12T08:00:00.000000Z"
REVIEW_BY_FUTURE = "2026-08-25T00:00:00.000000Z"
REVIEW_BY_PAST = "2026-08-01T00:00:00.000000Z"
COMMITTED_AT = "2026-08-10T06:00:00.000000Z"
DECISION_ID = "decision_" + "b" * 32


def _decision(review_by: str = REVIEW_BY_FUTURE, nba: str = "HOLD") -> dict:
    return {
        "decision_id": DECISION_ID,
        "committed_at": COMMITTED_AT,
        "review_by": review_by,
        "previous_next_best_action": nba,
    }


def facts(**overrides) -> CampaignFacts:
    """构造一个"全部干净"的归一化输入（各用例按需覆盖）。"""
    base = {
        "security_code": SECURITY,
        "strategy": STRATEGY,
        "campaign_id": CAMPAIGN_ID,
        "campaign_status": "ACTIVE",
        "thesis_state": "READY",
        "current_thesis": "STABLE",
        "latest_frozen_decision": _decision(),
        "hard_risk_state": "CLEAR",
        "material_change_state": "NONE",
        "critical_data_state": "USABLE",
        "decision_confidence": "HIGH",
        "coverage_complete": True,
        "as_of": AS_OF,
        "authority_refs": ["thesis:xxx"],
    }
    base.update(overrides)
    return CampaignFacts(**base)


# ---------------------------------------------------------------------------
# 1-8：Thesis / Formal Decision 语义
# ---------------------------------------------------------------------------

class TestThesisSemantics:
    def test_1_stable_clean_coverage_no_action(self):
        item = project_campaign(facts())
        assert item.visible_state == "NO_ACTION_REQUIRED"
        assert item.reason_codes == ("CLEAN",)
        assert item.ai_review_recommended is False

    def test_2_weakened_review(self):
        item = project_campaign(facts(current_thesis="WEAKENED"))
        assert item.visible_state == "REVIEW_REQUIRED"
        assert di.REASON_THESIS_WEAKENED in item.reason_codes

    def test_3_disproven_review(self):
        item = project_campaign(facts(current_thesis="DISPROVEN"))
        assert item.visible_state == "REVIEW_REQUIRED"
        assert di.REASON_THESIS_DISPROVEN in item.reason_codes

    def test_4_invalidated_review(self):
        item = project_campaign(facts(current_thesis="INVALIDATED"))
        assert item.visible_state == "REVIEW_REQUIRED"
        assert di.REASON_THESIS_INVALIDATED in item.reason_codes

    def test_5_unknown_thesis_review(self):
        item = project_campaign(facts(current_thesis="UNKNOWN"))
        assert item.visible_state == "REVIEW_REQUIRED"
        assert di.REASON_THESIS_UNKNOWN in item.reason_codes

    def test_6_missing_thesis_setup(self):
        item = project_campaign(facts(thesis_state="MISSING"))
        assert item.visible_state == "SETUP_REQUIRED"
        assert di.REASON_THESIS_MISSING in item.reason_codes

    def test_7_not_frozen_setup(self):
        item = project_campaign(facts(thesis_state="NOT_FROZEN"))
        assert item.visible_state == "SETUP_REQUIRED"
        assert di.REASON_THESIS_NOT_FROZEN in item.reason_codes

    def test_7b_not_ready_setup(self):
        item = project_campaign(facts(thesis_state="NOT_READY"))
        assert item.visible_state == "SETUP_REQUIRED"
        assert di.REASON_THESIS_NOT_READY in item.reason_codes

    def test_8_missing_formal_decision_setup(self):
        item = project_campaign(facts(latest_frozen_decision=None))
        assert item.visible_state == "SETUP_REQUIRED"
        assert di.REASON_FORMAL_DECISION_MISSING in item.reason_codes


# ---------------------------------------------------------------------------
# 9-10：review_by
# ---------------------------------------------------------------------------

class TestReviewBy:
    def test_9_review_by_reached_review(self):
        item = project_campaign(facts(latest_frozen_decision=_decision(review_by=REVIEW_BY_PAST)))
        assert item.visible_state == "REVIEW_REQUIRED"
        assert di.REASON_REVIEW_BY_REACHED in item.reason_codes

    def test_10_future_review_by_no_fake_validity(self):
        # 未来 review_by：干净 → NO_ACTION_REQUIRED，绝不生成 AGING/STALE/EXPIRED
        item = project_campaign(facts())
        assert item.visible_state == "NO_ACTION_REQUIRED"
        for fake in ("AGING", "STALE", "EXPIRED", "INVALIDATED", "CURRENT"):
            assert fake not in item.reason_codes
            assert fake not in str(item.to_dict())


# ---------------------------------------------------------------------------
# 11-13：Hard Risk / Data Block 优先级
# ---------------------------------------------------------------------------

class TestHardRiskAndData:
    def test_11_confirmed_hard_risk_review(self):
        item = project_campaign(facts(hard_risk_state="CONFIRMED"))
        assert item.visible_state == "REVIEW_REQUIRED"
        assert di.REASON_HARD_RISK_CONFIRMED in item.reason_codes

    def test_12_data_blocked(self):
        item = project_campaign(facts(critical_data_state="BLOCKED"))
        assert item.visible_state == "BLOCKED_BY_DATA"
        assert di.REASON_CRITICAL_DATA_BLOCKED in item.reason_codes

    def test_12b_data_unknown_and_stale(self):
        for state, reason in (
            ("UNKNOWN", di.REASON_CRITICAL_DATA_UNKNOWN),
            ("STALE", di.REASON_CRITICAL_DATA_STALE),
        ):
            item = project_campaign(facts(critical_data_state=state))
            assert item.visible_state == "BLOCKED_BY_DATA"
            assert reason in item.reason_codes

    def test_13_terminal_not_hidden_by_data_block(self):
        item = project_campaign(
            facts(current_thesis="DISPROVEN", critical_data_state="BLOCKED")
        )
        assert item.visible_state == "REVIEW_REQUIRED"
        assert di.REASON_THESIS_DISPROVEN in item.reason_codes

    def test_13b_hard_risk_not_hidden_by_data_block(self):
        item = project_campaign(
            facts(hard_risk_state="CONFIRMED", critical_data_state="BLOCKED")
        )
        assert item.visible_state == "REVIEW_REQUIRED"
        assert di.REASON_HARD_RISK_CONFIRMED in item.reason_codes


# ---------------------------------------------------------------------------
# 14-16：Material Change / Confidence / Coverage
# ---------------------------------------------------------------------------

class TestMaterialConfidenceCoverage:
    def test_14_material_change_review(self):
        for state, reason in (
            ("MATERIAL", di.REASON_MATERIAL_CHANGE_MATERIAL),
            ("CRITICAL", di.REASON_MATERIAL_CHANGE_CRITICAL),
        ):
            item = project_campaign(facts(material_change_state=state))
            assert item.visible_state == "REVIEW_REQUIRED"
            assert reason in item.reason_codes

    def test_15_low_confidence_ai_review_recommended(self):
        item = project_campaign(facts(decision_confidence="LOW"))
        assert item.visible_state == "NO_ACTION_REQUIRED"  # 不改可见状态
        assert item.ai_review_recommended is True
        assert di.REASON_LOW_CONFIDENCE in item.reason_codes

    def test_16_incomplete_coverage_not_no_action(self):
        item = project_campaign(facts(coverage_complete=False))
        assert item.visible_state == "BLOCKED_BY_DATA"
        assert di.REASON_COVERAGE_INCOMPLETE in item.reason_codes

    def test_16b_unknown_hard_risk_not_clean(self):
        # UNKNOWN != healthy：hard risk 未知不得默认 CLEAR
        item = project_campaign(facts(hard_risk_state="UNKNOWN"))
        assert item.visible_state != "NO_ACTION_REQUIRED"
        assert di.REASON_HARD_RISK_UNKNOWN in item.reason_codes

    def test_16c_unknown_material_change_not_clean(self):
        item = project_campaign(facts(material_change_state="UNKNOWN"))
        assert item.visible_state != "NO_ACTION_REQUIRED"
        assert di.REASON_MATERIAL_CHANGE_UNKNOWN in item.reason_codes


# ---------------------------------------------------------------------------
# 17-20：多 Campaign 独立 / 确定性 / 零突变 / 无别名泄漏
# ---------------------------------------------------------------------------

class TestIsolationAndDeterminism:
    def test_17_same_security_two_campaigns_independent(self):
        camp_b = "campaign_" + "c" * 32
        item_a = project_campaign(facts(campaign_id=CAMPAIGN_ID))
        item_b = project_campaign(
            facts(campaign_id=camp_b, current_thesis="WEAKENED")
        )
        assert item_a.visible_state == "NO_ACTION_REQUIRED"
        assert item_b.visible_state == "REVIEW_REQUIRED"
        assert item_a.campaign_id == CAMPAIGN_ID
        assert item_b.campaign_id == camp_b
        # 不串线：A 的干净状态不受 B 影响
        assert di.REASON_CLEAN in item_a.reason_codes

    def test_18_mapping_order_variation_deterministic(self):
        record = facts().to_dict()
        reversed_record = {k: record[k] for k in reversed(list(record))}
        assert project_campaign(record).to_dict() == project_campaign(reversed_record).to_dict()
        # 输入顺序变化 → 多条目排序稳定
        f1 = facts(campaign_id=CAMPAIGN_ID)
        f2 = facts(campaign_id="campaign_" + "c" * 32)
        assert project_campaigns([f1, f2]) == project_campaigns([f2, f1])

    def test_19_input_object_zero_mutation(self):
        record = facts().to_dict()
        decision = record["latest_frozen_decision"]
        item = project_campaign(record)
        before = item.to_dict()
        # 篡改输入 dict（含嵌套）
        decision["review_by"] = "2099-01-01T00:00:00.000000Z"
        record["current_thesis"] = "WEAKENED"
        record["hard_risk_state"] = "CONFIRMED"
        assert item.to_dict() == before

    def test_20_deep_payload_no_alias_leakage(self):
        item = project_campaign(facts())
        # 内部字段深度冻结：不可变（赋值抛 TypeError）
        with pytest.raises(TypeError):
            item.last_frozen_decision["previous_next_best_action"] = "SELL"
        with pytest.raises(TypeError):
            item.explainability["what"] = "tampered"
        # to_dict 为 detached copy：修改返回值不影响 item
        d = item.to_dict()
        d["last_frozen_decision"]["review_by"] = "2099-01-01T00:00:00.000000Z"
        d["explainability"]["what"] = "tampered"
        d["reason_codes"].append("X")
        assert item.to_dict()["last_frozen_decision"]["review_by"] == REVIEW_BY_FUTURE
        assert item.to_dict()["explainability"]["what"] != "tampered"
        assert "X" not in item.to_dict()["reason_codes"]


# ---------------------------------------------------------------------------
# 21-26：纯性 / 边界契约
# ---------------------------------------------------------------------------

class TestPurityAndBoundaries:
    def test_21_no_wall_clock(self):
        source = inspect.getsource(di)
        assert "datetime.now" not in source
        assert "time.time" not in source

    def test_22_no_ai_network_db_fs(self):
        source = inspect.getsource(di)
        for forbidden in ("import sqlite3", "import os", "import socket",
                          "requests", "urllib", "import fastapi", "open("):
            assert forbidden not in source
        assert "import top_risk" not in source
        assert "import decision_cockpit" not in source
        assert "import portfolio_advice" not in source

    def test_23_no_buy_sell_generation(self):
        # 模块无任何 BUY/SELL 常量或动作枚举；输出不携带交易动作
        for name in dir(di):
            if name.isupper() and ("BUY" in name or "SELL" in name):
                raise AssertionError(f"禁止的交易动作常量：{name}")
        item = project_campaign(facts())
        d = item.to_dict()
        for key, value in d.items():
            assert "buy" not in str(key).lower()
            if isinstance(value, str):
                assert "BUY" not in value and "SELL" not in value

    def test_24_no_numeric_priority_score(self):
        item = project_campaign(facts())
        d = item.to_dict()
        assert "score" not in d and "priority" not in d
        assert "numeric" not in str(d)

    def test_25_last_frozen_decision_never_current_recommendation(self):
        item = project_campaign(facts())
        d = item.to_dict()
        assert "last_frozen_decision" in d
        assert d["last_frozen_decision"]["previous_next_best_action"] == "HOLD"
        assert "current_recommendation" not in d
        assert "CURRENT_RECOMMENDATION" not in str(d)

    def test_26_campaign_capital_relevance_unknown(self):
        item = project_campaign(facts())
        assert item.campaign_capital_relevance == "UNKNOWN"
        assert item.to_dict()["campaign_capital_relevance"] == "UNKNOWN"


# ---------------------------------------------------------------------------
# 边界：Campaign scope / UNASSIGNED / 严格校验
# ---------------------------------------------------------------------------

class TestCampaignScopeAndValidation:
    def test_pre_entry_not_in_held_inbox(self):
        item = project_campaign(facts(campaign_status="PRE-ENTRY"))
        assert item.visible_state == "SETUP_REQUIRED"
        assert di.REASON_CAMPAIGN_NOT_IN_SCOPE in item.reason_codes

    def test_unassigned_holding_setup_required(self):
        item = project_campaign(facts(campaign_id=None, campaign_status="ACTIVE"))
        assert item.visible_state == "SETUP_REQUIRED"
        assert di.REASON_UNASSIGNED_HOLDING in item.reason_codes
        assert item.campaign_id is None  # 不伪造 campaign_id

    def test_invalid_inputs_fail_closed(self):
        for bad in (
            {"security_code": "60051"},  # 格式错
            {"strategy": "DAYTRADE"},  # 枚举错
            {"campaign_id": "campaign_xyz"},  # 格式错
            {"campaign_status": "FROZEN"},  # 枚举错
            {"thesis_state": "FROZEN"},  # 枚举错
            {"current_thesis": "BULLISH"},  # 枚举错
            {"hard_risk_state": "RISKY"},  # 枚举错
            {"coverage_complete": "yes"},  # 非严格 bool
            {"as_of": "明天"},  # 时间戳错
            {"as_of": "2026-08-12T16:00:00+08:00"},  # 非零偏移
        ):
            with pytest.raises(DecisionInboxValidationError):
                facts(**bad)

    def test_decision_shape_strict(self):
        with pytest.raises(DecisionInboxValidationError):
            facts(latest_frozen_decision={"decision_id": DECISION_ID})
        with pytest.raises(DecisionInboxValidationError):
            facts(latest_frozen_decision={
                ** _decision(), "extra": 1,
            })
        with pytest.raises(DecisionInboxValidationError):
            facts(latest_frozen_decision={
                **_decision(), "decision_id": "campaign_" + "b" * 32,
            })

    def test_mapping_extra_or_missing_field_rejected(self):
        record = facts().to_dict()
        record["extra"] = 1
        with pytest.raises(DecisionInboxValidationError):
            project_campaign(record)
        record = facts().to_dict()
        del record["as_of"]
        with pytest.raises(DecisionInboxValidationError):
            project_campaign(record)


# ---------------------------------------------------------------------------
# 可解释性与工作流动作
# ---------------------------------------------------------------------------

class TestExplainability:
    def test_workflow_action_mapping(self):
        cases = [
            (facts(thesis_state="MISSING"), "REVIEW_THESIS"),
            (facts(latest_frozen_decision=None), "CREATE_FORMAL_DECISION"),
            (facts(critical_data_state="BLOCKED"), "REPAIR_DATA"),
            (facts(latest_frozen_decision=_decision(review_by=REVIEW_BY_PAST)), "REVIEW_FORMAL_DECISION"),
            (facts(hard_risk_state="CONFIRMED"), "REVIEW_FORMAL_DECISION"),
            (facts(current_thesis="WEAKENED"), "REVIEW_THESIS"),
            (facts(current_thesis="UNKNOWN"), "RESEARCH_EVIDENCE"),
            (facts(), "NONE"),
        ]
        for f, expected_action in cases:
            item = project_campaign(f)
            assert item.explainability["next_workflow_action"] == expected_action, f

    def test_explainability_fields_complete(self):
        item = project_campaign(facts(current_thesis="WEAKENED"))
        exp = item.to_dict()["explainability"]
        for key in ("what", "why_now", "what_changed", "which_campaign",
                    "authority_refs", "uncertainties", "clear_conditions",
                    "next_workflow_action"):
            assert key in exp
        assert exp["which_campaign"] == CAMPAIGN_ID
        assert exp["authority_refs"] == ["thesis:xxx"]
        assert exp["what_changed"] == "THESIS_WEAKENED"

    def test_authority_refs_never_fabricated(self):
        item = project_campaign(facts(authority_refs=[]))
        assert list(item.explainability["authority_refs"]) == []


# ---------------------------------------------------------------------------
# 输出契约
# ---------------------------------------------------------------------------

class TestOutputContract:
    def test_visible_state_single_and_reason_multi(self):
        # terminal + data blocked：state 唯一 REVIEW_REQUIRED，reason 可含 data
        item = project_campaign(
            facts(current_thesis="INVALIDATED", critical_data_state="BLOCKED")
        )
        assert item.visible_state == "REVIEW_REQUIRED"
        assert di.REASON_THESIS_INVALIDATED in item.reason_codes

    def test_to_dict_plain_json(self):
        item = project_campaign(facts())
        d = item.to_dict()
        assert type(d["explainability"]) is dict
        assert type(d["reason_codes"]) is list
        assert type(d["last_frozen_decision"]) is dict

    def test_deterministic_repeat(self):
        assert project_campaign(facts()) == project_campaign(facts())
        assert project_campaign(facts()).to_dict() == project_campaign(facts()).to_dict()
