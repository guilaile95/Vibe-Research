import assert from "node:assert/strict";
import test from "node:test";
import { applyNdjsonLine, createNdjsonProtocolState } from "../src/lib/api.ts";
import { parseLeadAnalysisContext, type LeadAnalysisContext } from "../src/lib/leadAnalysisContext.ts";

const context: LeadAnalysisContext = {
  schema_version: "daily-review-lead-context.v1", kind: "activity",
  subject: { code: "600519", name: "贵州茅台" }, source_path: "capital_activity.amount_top[0]",
  source: { status: "normal", source: "fixture", trade_date: null, data_time: null, fetched_at: "2026-09-25 16:00:00", is_stale: null },
  review_generated_at: "2026-09-25 16:01:00", cache_stale: true,
  facts: { amount: 0, change_pct: null }, unknowns: ["源时间未知"],
};

test("lead provenance passes through the stream without replacing missing source time or zero values", () => {
  const state = createNdjsonProtocolState(); let received: LeadAnalysisContext | undefined;
  applyNdjsonLine(state, JSON.stringify({ type: "lead_context", context }), { onLeadContext: (value) => { received = value; } });
  applyNdjsonLine(state, JSON.stringify({ type: "delta", text: "线索草稿" }));
  applyNdjsonLine(state, JSON.stringify({ type: "done" }));
  assert.deepEqual(received, context);
  assert.equal(received?.source.data_time, null);
  assert.equal(received?.facts.amount, 0);
  assert.equal(state.sawDone, true);
  assert.equal(state.sawError, false);
});

test("malformed and late provenance cannot complete as a successful valid source", () => {
  for (const value of [null, {}, { ...context, source: {} }, { ...context, unknowns: [4] }, { ...context, facts: { amount: {} } }]) {
    const state = createNdjsonProtocolState(); let called = false;
    applyNdjsonLine(state, JSON.stringify({ type: "lead_context", context: value }), { onLeadContext: () => { called = true; } });
    assert.equal(state.sawError, true);
    assert.equal(called, false);
  }
  assert.equal(parseLeadAnalysisContext({ ...context, facts: { amount: Infinity } }), undefined);
  const state = createNdjsonProtocolState();
  applyNdjsonLine(state, JSON.stringify({ type: "done" }));
  applyNdjsonLine(state, JSON.stringify({ type: "lead_context", context }));
  assert.equal(state.sawError, true);
});
