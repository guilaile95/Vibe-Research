import assert from "node:assert/strict";
import test from "node:test";

import { decisionActionLabel } from "../src/lib/decisionActionView.ts";
import { CAMPAIGN_STRATEGY_LABELS } from "../src/lib/decisionInbox.ts";
import {
  actualCapitalStateLabel,
  actualCapitalSummary,
  allocationStateLabel,
  campaignStrategyLabel,
  dueStateLabel,
  formalOutcomeIdentityTitle,
  frozenDecisionNbaLabel,
  mergeOutcomeItem,
  outcomeStatusLabel,
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
