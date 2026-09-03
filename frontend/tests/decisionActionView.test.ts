import assert from "node:assert/strict";
import test from "node:test";

import {
  decisionEvaluationLabel,
  presentFrozenDecision,
  presentSellEngine,
} from "../src/lib/decisionActionView.ts";
import type { DecisionInboxCampaignItem } from "../src/lib/api/types.ts";

const CAMPAIGN_ID = "campaign_" + "a".repeat(32);
const DECISION_ID = "decision_" + "b".repeat(32);

test("unsupported runtime evaluations fail closed instead of looking not evaluated", () => {
  assert.equal(decisionEvaluationLabel("NOT_EVALUATED"), "尚未评估");
  assert.equal(decisionEvaluationLabel("FUTURE_RUNTIME_ENUM"), "无法识别的状态");
  assert.notEqual(decisionEvaluationLabel("FUTURE_RUNTIME_ENUM"), "尚未评估");
});

function item(
  overrides: Partial<DecisionInboxCampaignItem> = {},
): DecisionInboxCampaignItem {
  return {
    schema_version: "decision_inbox_projection.v0.1",
    visible_state: "NO_ACTION_REQUIRED",
    reason_codes: ["CLEAN"],
    security_code: "600519",
    strategy: "SWING",
    campaign_id: CAMPAIGN_ID,
    campaign_status: "ACTIVE",
    as_of: "2026-08-24T00:00:00.000000Z",
    formal_decision_evaluation: "EVALUATED",
    last_frozen_decision: {
      decision_id: DECISION_ID,
      committed_at: "2026-08-20T00:00:00.000000Z",
      review_by: "2026-08-30T00:00:00.000000Z",
      previous_next_best_action: "BUY SMALL",
    },
    ...overrides,
  };
}

test("applicable executable Frozen Decision exposes an explicit Trade continuation", () => {
  const view = presentFrozenDecision(item());
  assert.equal(view.state, "APPLICABLE");
  assert.equal(view.action, "BUY SMALL");
  assert.equal(view.actionLabel, "小仓位买入");
  assert.equal(view.reviewState, "UPCOMING");
  assert.equal(
    view.tradeHref,
    `/trades?create=1&code=600519&campaign_id=${CAMPAIGN_ID}&decision_id=${DECISION_ID}&next_best_action=BUY+SMALL`,
  );
});

test("historical or non-execution Frozen Decisions never open the Trade continuation", () => {
  const historical = presentFrozenDecision(item({ formal_decision_evaluation: "NOT_EVALUATED" }));
  assert.equal(historical.state, "HISTORICAL");
  assert.equal(historical.tradeHref, null);

  const hold = presentFrozenDecision(item({
    last_frozen_decision: {
      ...item().last_frozen_decision!,
      previous_next_best_action: "HOLD",
    },
  }));
  assert.equal(hold.state, "APPLICABLE");
  assert.equal(hold.actionLabel, "继续持有");
  assert.equal(hold.tradeHref, null);
});

test("review due is derived from the snapshot as_of, never the browser wall clock", () => {
  const view = presentFrozenDecision(item({
    as_of: "2026-09-01T00:00:00.000000Z",
  }));
  assert.equal(view.reviewState, "DUE");
});

test("malformed historical data fails closed without a decision id or Trade link", () => {
  const view = presentFrozenDecision(item({
    last_frozen_decision: {
      ...item().last_frozen_decision!,
      decision_id: "decision_bad",
    },
  }));
  assert.equal(view.state, "INVALID");
  assert.equal(view.decisionId, null);
  assert.equal(view.tradeHref, null);
});

function sell(overrides: Record<string, unknown> = {}) {
  return {
    schema_version: "sell_engine.projection.vnext.v0.1",
    authority_ref: "sell_engine:projection:vnext.v0.1",
    security_code: "600519",
    strategy: "SWING",
    campaign_id: CAMPAIGN_ID,
    as_of: "2026-08-24T00:00:00.000000Z",
    sell_state: "WATCH_TO_REDUCE",
    sell_evaluation: "NOT_EVALUATED",
    primary_reason: "RISK_EXIT",
    reason_codes: ["HARD_RISK_CONFIRMED"],
    supporting_reasons: ["RISK_EXIT"],
    opposing_reasons: [],
    uncertainties: ["RISK_REWARD_NOT_EVALUATED"],
    hold_positive_proof: false,
    review_pressure: true,
    thesis_id: null,
    thesis_revision: null,
    authority_refs: ["sell_engine:projection:vnext.v0.1"],
    dimensions: {},
    ...overrides,
  };
}

test("incomplete Sell Engine can expose review pressure without claiming a complete conclusion", () => {
  const view = presentSellEngine(item({
    sell_engine: sell() as DecisionInboxCampaignItem["sell_engine"],
  }));
  assert.equal(view.state, "INCOMPLETE");
  assert.equal(view.evaluation, "NOT_EVALUATED");
  assert.equal(view.sellLabel, "观察并准备减仓");
  assert.equal(view.reviewPressure, true);
  assert.deepEqual(view.uncertainties, ["RISK_REWARD_NOT_EVALUATED"]);
});

test("HOLD without positive proof is rejected at the presentation boundary", () => {
  const view = presentSellEngine(item({
    sell_engine: sell({
      sell_state: "HOLD",
      sell_evaluation: "EVALUATED",
      hold_positive_proof: false,
    }) as DecisionInboxCampaignItem["sell_engine"],
  }));
  assert.equal(view.state, "ERROR");
  assert.equal(view.sellState, null);
  assert.match(view.sellLabel, /缺少正面证明/);
});

test("missing or malformed Sell Engine stays unavailable", () => {
  assert.equal(presentSellEngine(item({ sell_engine: undefined })).state, "UNAVAILABLE");
  assert.equal(
    presentSellEngine(item({ sell_engine: { sell_evaluation: "HEALTHY" } as never })).state,
    "UNAVAILABLE",
  );
});

test("Sell Engine rejects stale schemas and cross-campaign or cross-snapshot identity", () => {
  for (const invalid of [
    sell({ schema_version: "sell_engine.projection.v0.1" }),
    sell({ authority_ref: "sell_engine_projection" }),
    sell({ campaign_id: "campaign_" + "f".repeat(32) }),
    sell({ security_code: "000001" }),
    sell({ strategy: "MEDIUM" }),
    sell({ as_of: "2026-08-23T00:00:00.000000Z" }),
  ]) {
    assert.equal(presentSellEngine(item({
      sell_engine: invalid as DecisionInboxCampaignItem["sell_engine"],
    })).state, "UNAVAILABLE");
  }
});
