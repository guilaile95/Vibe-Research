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
