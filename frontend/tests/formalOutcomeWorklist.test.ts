import assert from "node:assert/strict";
import test from "node:test";

import {
  frozenDecisionNbaLabel,
  mergeOutcomeItem,
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
  assert.equal(worklistLabel("upcoming"), "Upcoming");
});

test("worklist groups are read-only projections", () => {
  const before = JSON.stringify(worklist);
  assert.equal(worklistItems(worklist, "due").length, 0);
  assert.equal(worklistItems(worklist, "unavailable").length, 0);
  assert.equal(JSON.stringify(worklist), before);
});

test("Frozen NBA labels preserve historical actions without evaluation", () => {
  assert.equal(frozenDecisionNbaLabel("WAIT"), "WAIT");
  assert.equal(frozenDecisionNbaLabel("HOLD"), "HOLD");
  assert.equal(frozenDecisionNbaLabel("EXIT"), "EXIT");
});

test("missing Frozen NBA remains UNKNOWN instead of being inferred", () => {
  for (const value of ["", "  ", null, undefined, 42, { action: "WAIT" }]) {
    assert.equal(frozenDecisionNbaLabel(value), "UNKNOWN");
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
