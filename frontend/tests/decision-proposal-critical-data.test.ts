import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const reviewSource = readFileSync(
  new URL("../src/pages/DecisionProposalReview.tsx", import.meta.url),
  "utf8",
);

test("Formal Decision Review renders CCD state/evaluation verbatim", () => {
  assert.match(reviewSource, /data-critical-data-state/);
  assert.match(reviewSource, /data-critical-data-evaluation/);
  assert.match(reviewSource, /record\?\.critical_data_state/);
  assert.match(reviewSource, /record\.critical_data_evaluation/);
  assert.doesNotMatch(reviewSource, /critical_data_state[^\n]*USABLE[^\n]*healthy/i);
});

test("Formal Decision Review only renders committed success after validated durable readback", () => {
  assert.match(reviewSource, /CommittedDecisionReadError/);
  assert.match(reviewSource, /正式决策已保存，但/);
  assert.match(reviewSource, /api\.getCommittedDecisionRuntime\(campaignId, decisionId\)/);
  assert.match(reviewSource, /setCommitted\(reread\)/);
  assert.match(reviewSource, /setCommitted\(null\);/);
  assert.match(reviewSource, /正式决策已保存并重新读取确认/);
});

test("Formal Decision Review exposes truthful optional Decision Challenge read states", () => {
  assert.match(reviewSource, /data-challenge-state/);
  for (const state of ["PENDING", "FOUND", "ABSENT", "ERROR"]) {
    assert.match(reviewSource, new RegExp(`\\"${state}\\"`));
  }
  assert.match(reviewSource, /决策挑战读取失败/);
  assert.match(reviewSource, /challengeReadState !== "FOUND"/);
  assert.match(reviewSource, /challengeReadState === "ABSENT"/);
  assert.match(reviewSource, /完成决策挑战/);
  assert.match(reviewSource, /data-decision-quality="NOT_EVALUATED"/);
  assert.match(reviewSource, /不会写入虚假引用/);
  assert.doesNotMatch(reviewSource, /quality_score/);
});
