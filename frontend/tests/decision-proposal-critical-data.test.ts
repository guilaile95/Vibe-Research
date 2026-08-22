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

test("Formal Decision Review exposes truthful optional Decision Challenge read states", () => {
  assert.match(reviewSource, /data-challenge-state/);
  for (const state of ["PENDING", "FOUND", "ABSENT", "ERROR"]) {
    assert.match(reviewSource, new RegExp(`\\"${state}\\"`));
  }
  assert.match(reviewSource, /CHALLENGE_READ_ERROR/);
  assert.match(reviewSource, /challengeReadState !== "FOUND"/);
  assert.match(reviewSource, /challengeReadState === "ABSENT"/);
  assert.match(reviewSource, /Finalize Decision Challenge/);
  assert.match(reviewSource, /data-decision-quality="NOT_EVALUATED"/);
  assert.match(reviewSource, /不会写入假的 challenge 引用/);
  assert.doesNotMatch(reviewSource, /quality_score/);
});
