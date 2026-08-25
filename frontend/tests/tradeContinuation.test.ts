import assert from "node:assert/strict";
import test from "node:test";

import {
  buildTradeContinuationHref,
  buildEvaluatedTradeContinuationHref,
  continuationTradeDraft,
  isPreferredAttributionCandidate,
  parseTradeContinuation,
} from "../src/lib/tradeContinuation.ts";
import type { TradeAttributionCandidate } from "../src/lib/api/types.ts";

const CAMPAIGN_ID = "campaign_" + "a".repeat(32);
const DECISION_ID = "decision_" + "b".repeat(32);
const SNAPSHOT_HASH = "c".repeat(64);
const REF = { decision_id: DECISION_ID, snapshot_hash: SNAPSHOT_HASH };

test("continuation URL carries only server-issued decision identity and witness", () => {
  assert.equal(
    buildTradeContinuationHref({ securityCode: "600519", continuationRef: REF }),
    `/trades?create=1&code=600519&decision_id=${DECISION_ID}&snapshot_hash=${SNAPSHOT_HASH}`,
  );
  assert.equal(buildTradeContinuationHref({ securityCode: "600519", continuationRef: {
    decision_id: DECISION_ID,
    snapshot_hash: "bad",
  } }), null);
  assert.equal(buildTradeContinuationHref({ securityCode: "600519", continuationRef: null }), null);
});

test("Trade page consumes only a complete valid continuation contract", () => {
  const parsed = parseTradeContinuation(new URLSearchParams({
    create: "1",
    code: "600519",
    decision_id: DECISION_ID,
    snapshot_hash: SNAPSHOT_HASH,
  }));
  assert.deepEqual(parsed, { securityCode: "600519", continuationRef: REF });
  assert.equal(parseTradeContinuation(new URLSearchParams({ create: "1", code: "600519" })), null);
  assert.equal(parseTradeContinuation(new URLSearchParams({
    create: "1",
    code: "600519",
    campaign_id: CAMPAIGN_ID,
    decision_id: DECISION_ID,
    next_best_action: "BUY SMALL",
  })), null);
});

test("post-commit continuation requires an applicable EVALUATED durable read", () => {
  assert.ok(buildEvaluatedTradeContinuationHref({
    securityCode: "600519",
    continuationRef: REF,
    formalDecisionEvaluation: "EVALUATED",
  }));
  for (const formalDecisionEvaluation of ["NOT_EVALUATED", "UNKNOWN", "ERROR", "FUTURE_ENUM", null]) {
    assert.equal(buildEvaluatedTradeContinuationHref({
      securityCode: "600519",
      continuationRef: REF,
      formalDecisionEvaluation,
    }), null, String(formalDecisionEvaluation));
  }
});

test("continuation pre-fills only security code and server-issued ref", () => {
  const context = parseTradeContinuation(new URLSearchParams({
    create: "1",
    code: "600519",
    decision_id: DECISION_ID,
    snapshot_hash: SNAPSHOT_HASH,
  }));
  assert.ok(context);
  const draft = continuationTradeDraft(context);
  assert.equal(draft.code, "600519");
  assert.deepEqual(draft.continuation_ref, REF);
  assert.equal(draft.name, "");
  assert.equal(draft.operation, "");
  assert.equal(draft.execution_status, "");
  assert.equal(draft.executed_at, "");
  assert.equal(draft.actual_price, "");
  assert.equal(draft.actual_quantity, "");
  assert.equal(draft.fee, "");
  assert.equal(draft.other_cost, "");
  assert.equal(draft.advice_ref, null);
  assert.equal(draft.thesis_ref, null);
});

function candidate(overrides: Partial<TradeAttributionCandidate> = {}): TradeAttributionCandidate {
  return {
    decision_id: DECISION_ID,
    campaign_id: CAMPAIGN_ID,
    security_code: "600519",
    strategy: "SWING",
    thesis_id: "d".repeat(32),
    thesis_revision: 1,
    committed_at: "2026-08-20T00:00:00.000000Z",
    review_by: "2026-08-30T00:00:00.000000Z",
    next_best_action: "BUY SMALL",
    snapshot_hash: SNAPSHOT_HASH,
    ...overrides,
  };
}

test("candidate hint highlights an exact post-create match but never selects it", () => {
  const tradeId = "e".repeat(32);
  const hint = { tradeId, campaignId: CAMPAIGN_ID, decisionId: DECISION_ID };
  assert.equal(isPreferredAttributionCandidate(hint, tradeId, candidate()), true);
  assert.equal(isPreferredAttributionCandidate(hint, "f".repeat(32), candidate()), false);
  assert.equal(isPreferredAttributionCandidate(hint, tradeId, candidate({
    decision_id: "decision_" + "9".repeat(32),
  })), false);
  assert.equal(isPreferredAttributionCandidate(null, tradeId, candidate()), false);
});
