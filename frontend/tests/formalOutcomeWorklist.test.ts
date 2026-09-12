import assert from "node:assert/strict";
import test from "node:test";

import { decisionActionLabel } from "../src/lib/decisionActionView.ts";
import { CAMPAIGN_STRATEGY_LABELS } from "../src/lib/decisionInbox.ts";
import {
  COUNTERFACTUAL_COLUMN_HEADER,
  COUNTERFACTUAL_DECISION_REFERENCE_LABEL,
  COUNTERFACTUAL_EVALUATION_LABEL,
  COUNTERFACTUAL_PATH_HEADING,
  COUNTERFACTUAL_RETURN_LABEL,
  COUNTERFACTUAL_SCOPE_COPY,
  COUNTERFACTUAL_SEPARATION_COPY,
  PROCESS_REVIEW_BOUND_HEADING,
  PROCESS_REVIEW_COVERAGE_COPY,
  PROCESS_REVIEW_DIMENSIONS,
  PROCESS_REVIEW_ERROR_COPY,
  PROCESS_REVIEW_NONE_COPY,
  actualCapitalStateLabel,
  actualCapitalSummary,
  allocationStateLabel,
  campaignStrategyLabel,
  counterfactualStateLabel,
  counterfactualSummary,
  dueStateLabel,
  formalOutcomeIdentityTitle,
  frozenDecisionNbaLabel,
  mergeOutcomeItem,
  outcomeStatusLabel,
  processReviewDimensionLabel,
  processReviewDimensionStatusLabel,
  processReviewPacketSummary,
  processReviewQualityLabel,
  processReviewTwoPassSummary,
  scanStateLabel,
  worklistItems,
  worklistLabel,
} from "../src/lib/formalOutcomeWorklist.ts";
import type { FormalDecisionReviewWorklist } from "../src/lib/api/types.ts";

const item = {
  decision_id: "decision_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  decision_review_by: "2026-09-01T00:00:00.000000Z",
  due_state: "NOT_DUE" as const,
  group: "upcoming" as const,
};

const worklist: FormalDecisionReviewWorklist = {
  schema_version: "formal_decision_review_worklist.v0.1",
  evaluation_as_of: "2026-08-01T00:00:00.000000Z",
  due: [],
  upcoming: [item],
  unavailable: [],
  counts: { due: 0, upcoming: 1, unavailable: 0, total: 1 },
};

test("NOT_DUE remains canonical while worklist uses Upcoming UI group", () => {
  assert.equal(worklistItems(worklist, "upcoming")[0]?.due_state, "NOT_DUE");
  assert.equal(worklistItems(worklist, "upcoming")[0]?.group, "upcoming");
  assert.equal(worklistLabel("upcoming"), "尚未到期");
  assert.equal(dueStateLabel("NOT_DUE"), "尚未到期");
  assert.equal(dueStateLabel("DUE"), "已到复核时点");
});

test("worklist groups are read-only projections", () => {
  const before = JSON.stringify(worklist);
  assert.equal(worklistItems(worklist, "due").length, 0);
  assert.equal(worklistItems(worklist, "unavailable").length, 0);
  assert.equal(JSON.stringify(worklist), before);
});

test("Frozen NBA labels reuse Decision Inbox action labels without evaluation", () => {
  assert.equal(frozenDecisionNbaLabel("WAIT"), decisionActionLabel("WAIT"));
  assert.equal(frozenDecisionNbaLabel("HOLD"), decisionActionLabel("HOLD"));
  assert.equal(frozenDecisionNbaLabel("EXIT"), decisionActionLabel("EXIT"));
  assert.equal(frozenDecisionNbaLabel("WAIT"), "等待");
  assert.equal(frozenDecisionNbaLabel("HOLD"), "继续持有");
  assert.equal(frozenDecisionNbaLabel("EXIT"), "退出");
});

test("missing Frozen NBA remains unknown instead of being inferred as BUY/SELL", () => {
  for (const value of ["", "  ", null, undefined, 42, { action: "WAIT" }]) {
    assert.equal(frozenDecisionNbaLabel(value), "未知");
    assert.notEqual(frozenDecisionNbaLabel(value), "立即买入");
    assert.notEqual(frozenDecisionNbaLabel(value), "买入");
    assert.notEqual(frozenDecisionNbaLabel(value), "BUY");
    assert.notEqual(frozenDecisionNbaLabel(value), "SELL");
  }
});

test("identity title is security, strategy label, and NBA label", () => {
  assert.equal(
    formalOutcomeIdentityTitle({
      security_code: "600519",
      strategy: "SWING",
      next_best_action: "WAIT",
    }),
    "600519 · 波段 · 等待",
  );
  assert.equal(
    formalOutcomeIdentityTitle({
      security_code: "600519",
      strategy: "MEDIUM",
      next_best_action: "HOLD",
    }),
    "600519 · 中线 · 继续持有",
  );
  assert.equal(campaignStrategyLabel("SHORT"), CAMPAIGN_STRATEGY_LABELS.SHORT);
  assert.equal(campaignStrategyLabel("SWING"), CAMPAIGN_STRATEGY_LABELS.SWING);
  assert.equal(campaignStrategyLabel("MEDIUM"), CAMPAIGN_STRATEGY_LABELS.MEDIUM);
});

test("identity title does not fetch or invent a security name, BUY, or SELL for unknown NBA", () => {
  const title = formalOutcomeIdentityTitle({
    security_code: "600519",
    strategy: "SWING",
    next_best_action: null,
  });
  assert.equal(title, "600519 · 波段 · 未知");
  assert.equal(title.includes("茅台"), false);
  assert.equal(title.includes("BUY"), false);
  assert.equal(title.includes("SELL"), false);
  assert.equal(title.includes("买入"), false);
  assert.equal(title.includes("卖出"), false);
  assert.equal(title.includes("decision_"), false);
});

test("outcome, actual-capital, and attribution labels stay display-only", () => {
  assert.equal(outcomeStatusLabel("PENDING"), "待评估");
  assert.equal(outcomeStatusLabel("EVALUATED"), "已评估");
  assert.equal(actualCapitalStateLabel("NO_ACTUAL_TRADE"), "无实际交易");
  assert.equal(actualCapitalStateLabel("PENDING"), "待评估");
  assert.equal(allocationStateLabel("UNALLOCATED"), "未归属");
  assert.equal(allocationStateLabel("ALLOCATED"), "已归属");
  assert.equal(allocationStateLabel("UNPLANNED"), "非计划内");
  assert.equal(scanStateLabel("INVALID_WITNESS"), "见证校验失败");
  assert.equal(scanStateLabel("COMPLETE_EMPTY"), "扫描完成（无候选）");
  assert.deepEqual(
    actualCapitalSummary({ actual_capital_outcome: { state: "PENDING" } } as any),
    { label: "待评估 · 尚未到期", canonical: "PENDING / NOT_DUE" },
  );
  assert.deepEqual(
    actualCapitalSummary({ actual_capital_outcome: { state: "NO_ACTUAL_TRADE" } } as any),
    { label: "无实际交易 · 不适用", canonical: "NO_ACTUAL_TRADE / NOT_APPLICABLE" },
  );
});

test("process review dimension labels reuse Decision Proposal Challenge copy", () => {
  assert.deepEqual(PROCESS_REVIEW_DIMENSIONS, [
    "STRONGEST_SUPPORTING_EVIDENCE",
    "STRONGEST_OPPOSING_EVIDENCE",
    "PRE_MORTEM",
    "INVALIDATION_FACTS",
  ]);
  assert.equal(processReviewDimensionLabel("STRONGEST_SUPPORTING_EVIDENCE"), "最有力的支持证据");
  assert.equal(processReviewDimensionLabel("STRONGEST_OPPOSING_EVIDENCE"), "最有力的反对证据");
  assert.equal(processReviewDimensionLabel("PRE_MORTEM"), "如果判断失败，最可能的原因");
  assert.equal(processReviewDimensionLabel("INVALIDATION_FACTS"), "哪些事实会推翻判断");
  assert.equal(processReviewDimensionLabel("FUTURE_DIMENSION"), "FUTURE_DIMENSION");
  assert.equal(processReviewDimensionLabel(""), "—");
  assert.equal(processReviewDimensionLabel(null), "—");
});

test("process review NONE and ERROR copy stay descriptive without BUY/SELL", () => {
  assert.equal(PROCESS_REVIEW_NONE_COPY, "本次冻结决定没有绑定预冻结决策挑战。");
  assert.equal(PROCESS_REVIEW_ERROR_COPY, "过程复核不可用；绑定的决策挑战权威损坏或无法读取。");
  assert.equal(PROCESS_REVIEW_BOUND_HEADING, "已绑定决策挑战");
  assert.equal(PROCESS_REVIEW_COVERAGE_COPY, "挑战覆盖不等于判断正确。");
  for (const copy of [
    PROCESS_REVIEW_NONE_COPY,
    PROCESS_REVIEW_ERROR_COPY,
    PROCESS_REVIEW_BOUND_HEADING,
    PROCESS_REVIEW_COVERAGE_COPY,
  ]) {
    assert.equal(copy.includes("BUY"), false);
    assert.equal(copy.includes("SELL"), false);
    assert.equal(copy.includes("买入"), false);
    assert.equal(copy.includes("卖出"), false);
  }
});

test("process review status and packet labels stay display-only with unknown enum fallback", () => {
  assert.equal(processReviewDimensionStatusLabel("ANSWERED"), "已回答");
  assert.equal(processReviewDimensionStatusLabel("UNKNOWN"), "未知");
  assert.equal(processReviewDimensionStatusLabel("NOT_ANSWERED"), "未回答");
  assert.equal(processReviewDimensionStatusLabel("FUTURE_STATUS"), "FUTURE_STATUS");
  assert.deepEqual(
    processReviewPacketSummary({ packet_state: "COMPLETE", challenge_evaluation: "EVALUATED" }),
    { label: "数据包：完整 · 评估：已评估", canonical: "packet: COMPLETE · evaluation: EVALUATED" },
  );
  assert.deepEqual(
    processReviewPacketSummary({ packet_state: "FUTURE_PACKET", challenge_evaluation: "FUTURE_EVAL" }),
    { label: "数据包：FUTURE_PACKET · 评估：FUTURE_EVAL", canonical: "packet: FUTURE_PACKET · evaluation: FUTURE_EVAL" },
  );
  assert.deepEqual(
    processReviewTwoPassSummary({
      two_pass_state: "VALID",
      two_pass_semantic_independence_verified: "NO",
    }),
    {
      label: "两轮：有效 · 语义独立性已验证：否",
      canonical: "two-pass: VALID · semantic independence verified: NO",
    },
  );
  assert.deepEqual(
    processReviewTwoPassSummary({
      two_pass_state: "FUTURE_PASS",
      two_pass_semantic_independence_verified: "FUTURE_FLAG",
    }),
    {
      label: "两轮：FUTURE_PASS · 语义独立性已验证：FUTURE_FLAG",
      canonical: "two-pass: FUTURE_PASS · semantic independence verified: FUTURE_FLAG",
    },
  );
  assert.equal(processReviewQualityLabel("NOT_EVALUATED"), "过程质量：尚未评估");
  assert.equal(processReviewQualityLabel(undefined), "过程质量：尚未评估");
  assert.equal(processReviewQualityLabel("FUTURE_QUALITY"), "过程质量：FUTURE_QUALITY");
  assert.equal(processReviewQualityLabel("NOT_EVALUATED").includes("BUY"), false);
  assert.equal(processReviewQualityLabel("NOT_EVALUATED").includes("SELL"), false);
});

test("counterfactual path labels stay Chinese and display-only", () => {
  assert.equal(COUNTERFACTUAL_COLUMN_HEADER, "反事实路径");
  assert.equal(COUNTERFACTUAL_PATH_HEADING, "个股收盘到收盘路径");
  assert.equal(COUNTERFACTUAL_DECISION_REFERENCE_LABEL, "决定参考价");
  assert.equal(COUNTERFACTUAL_EVALUATION_LABEL, "评估时点价");
  assert.equal(COUNTERFACTUAL_RETURN_LABEL, "收益");
  assert.equal(COUNTERFACTUAL_SCOPE_COPY, "仅个股路径，不是组合盈亏，也不是判断质量");
  assert.equal(COUNTERFACTUAL_SEPARATION_COPY, "该路径与实际资金结果相互独立。");
  assert.equal(counterfactualStateLabel("EVALUATED"), "已评估");
  assert.equal(counterfactualStateLabel("NOT_EVALUATED"), "尚未评估");
  assert.equal(counterfactualStateLabel("UNKNOWN"), "信息不足");
  assert.equal(counterfactualStateLabel("ERROR"), "读取失败");
  assert.equal(counterfactualStateLabel("FUTURE_STATE"), "FUTURE_STATE");
  assert.equal(counterfactualStateLabel(""), "—");
  assert.equal(counterfactualStateLabel(null), "—");
  assert.deepEqual(
    counterfactualSummary({ counterfactual_outcome: { state: "EVALUATED" } } as any),
    { label: "已评估", canonical: "EVALUATED" },
  );
  assert.deepEqual(
    counterfactualSummary({ counterfactual_outcome: { state: "NOT_EVALUATED" } } as any),
    { label: "尚未评估", canonical: "NOT_EVALUATED" },
  );
  assert.deepEqual(
    counterfactualSummary({ counterfactual_outcome: { state: "UNKNOWN" } } as any),
    { label: "信息不足", canonical: "UNKNOWN" },
  );
  assert.deepEqual(
    counterfactualSummary({ counterfactual_outcome: { state: "ERROR" } } as any),
    { label: "读取失败", canonical: "ERROR" },
  );
  assert.deepEqual(
    counterfactualSummary({ counterfactual_outcome: { state: "FUTURE_STATE" } } as any),
    { label: "FUTURE_STATE", canonical: "FUTURE_STATE" },
  );
  assert.deepEqual(
    counterfactualSummary({} as any),
    { label: "—", canonical: "" },
  );
  for (const copy of [
    COUNTERFACTUAL_COLUMN_HEADER,
    COUNTERFACTUAL_PATH_HEADING,
    COUNTERFACTUAL_DECISION_REFERENCE_LABEL,
    COUNTERFACTUAL_EVALUATION_LABEL,
    COUNTERFACTUAL_RETURN_LABEL,
    COUNTERFACTUAL_SCOPE_COPY,
    COUNTERFACTUAL_SEPARATION_COPY,
    counterfactualStateLabel("EVALUATED"),
    counterfactualStateLabel("NOT_EVALUATED"),
    counterfactualSummary({ counterfactual_outcome: { state: "EVALUATED" } } as any).label,
  ]) {
    assert.equal(copy.includes("BUY"), false);
    assert.equal(copy.includes("SELL"), false);
    assert.equal(copy.includes("买入"), false);
    assert.equal(copy.includes("卖出"), false);
  }
});

test("missing historical row can be merged from exact outcome authority", () => {
  const existing = {
    decision_id: "decision_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
    outcome_status: "EVALUATED",
    schema_version: "formal_decision_outcome.v0.1",
  } as any;
  const fetched = {
    decision_id: "decision_cccccccccccccccccccccccccccccccc",
    outcome_status: "PENDING",
    schema_version: "formal_decision_outcome.v0.1",
  } as any;
  const merged = mergeOutcomeItem([existing], fetched);
  assert.deepEqual(merged.map((item) => item.decision_id), [existing.decision_id, fetched.decision_id]);
  assert.equal(mergeOutcomeItem(merged, { ...fetched, outcome_status: "EVALUATED" } as any)[1].outcome_status, "EVALUATED");
});
