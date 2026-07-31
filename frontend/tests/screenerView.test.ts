import assert from "node:assert/strict";
import test from "node:test";

import {
  ScreenerRequestGate,
  bucketsAreDisjoint,
  buildEvaluatePayload,
  groupResults,
  mergeCodes,
  normalizeCodes,
  parseCodeDraft,
  validateConditionDraft,
  validateScreenerDraft,
  defaultCondition,
} from "../src/lib/screenerView.ts";
import type { ScreenerEvaluateResult } from "../src/lib/api/types.ts";

test("parse and normalize codes: dedupe + sort + cap", () => {
  const parsed = parseCodeDraft("600519, 000001 600519 abc 12");
  assert.deepEqual(parsed, ["600519", "000001", "600519"]);
  assert.deepEqual(normalizeCodes(parsed), ["000001", "600519"]);
});

test("mergeCodes from multiple sources", () => {
  assert.deepEqual(mergeCodes(["600519"], ["000001", "600519"]), ["000001", "600519"]);
});

test("buildEvaluatePayload condition construction", () => {
  const payload = buildEvaluatePayload(
    ["600519", "000001"],
    [
      defaultCondition("price_gt_sma20"),
      defaultCondition("rsi_between"),
      defaultCondition("volume_ratio_gte"),
    ],
  );
  assert.deepEqual(payload.codes, ["000001", "600519"]);
  assert.deepEqual(payload.conditions, [
    { id: "price_gt_sma20" },
    { id: "rsi_between", params: { min: 30, max: 70 } },
    { id: "volume_ratio_gte", params: { threshold: 1.5 } },
  ]);
});

test("groupResults splits three buckets", () => {
  const result: ScreenerEvaluateResult = {
    status: "partial",
    evaluated_at: "t",
    logic: "AND",
    matched: [{ code: "000001", bucket: "matched", matched: true, technical_status: "normal", trade_date: null, condition_results: [], limitations: [] }],
    rejected: [{ code: "000002", bucket: "rejected", matched: false, technical_status: "normal", trade_date: null, condition_results: [], limitations: [] }],
    unavailable: [{ code: "000003", bucket: "unavailable", matched: null, technical_status: "unavailable", trade_date: null, condition_results: [], limitations: [] }],
    limitations: [],
    schema_version: "screener-v0.1",
  };
  const g = groupResults(result);
  assert.equal(g.matched.length, 1);
  assert.equal(g.rejected.length, 1);
  assert.equal(g.unavailable.length, 1);
  assert.equal(bucketsAreDisjoint(result), true);
});

test("rejected and unavailable are mutually exclusive check", () => {
  const bad: ScreenerEvaluateResult = {
    status: "partial",
    evaluated_at: "t",
    logic: "AND",
    matched: [],
    rejected: [{ code: "000001", bucket: "rejected", matched: false, technical_status: "normal", trade_date: null, condition_results: [], limitations: [] }],
    unavailable: [{ code: "000001", bucket: "unavailable", matched: null, technical_status: "unavailable", trade_date: null, condition_results: [], limitations: [] }],
    limitations: [],
    schema_version: "screener-v0.1",
  };
  assert.equal(bucketsAreDisjoint(bad), false);
});

test("illegal param precheck", () => {
  assert.ok(validateConditionDraft({ id: "rsi_between", params: { min: 80, max: 20 } }));
  assert.ok(validateConditionDraft({ id: "volume_ratio_gte", params: { threshold: 0 } }));
  assert.equal(validateConditionDraft({ id: "price_gt_sma20" }), null);
  assert.ok(validateScreenerDraft([], [defaultCondition("price_gt_sma20")]));
  assert.ok(validateScreenerDraft(["000001"], []));
  assert.ok(
    validateScreenerDraft(
      ["000001"],
      [defaultCondition("price_gt_sma20"), defaultCondition("price_gt_sma20")],
    ),
  );
});

test("ScreenerRequestGate: single-flight while loading", () => {
  const gate = new ScreenerRequestGate();
  const t1 = gate.beginIfIdle("idle");
  assert.ok(t1);
  // Second click before end() must be ignored (sync, no React phase needed)
  const t2 = gate.beginIfIdle("idle");
  assert.equal(t2, null);
  gate.end(t1!.generation);
  const t3 = gate.beginIfIdle("idle");
  assert.ok(t3);
});

test("ScreenerRequestGate: stale generation discarded", () => {
  const gate = new ScreenerRequestGate();
  const t1 = gate.begin();
  const t2 = gate.begin(); // force supersede
  assert.equal(gate.isCurrent(t1.generation), false);
  assert.equal(gate.isCurrent(t2.generation), true);
  gate.end(t2.generation);
});

test("error path preserves draft conceptually via pure validation still working", () => {
  // Draft codes/conditions remain valid independently of phase
  const codes = ["000001"];
  const conditions = [defaultCondition("price_gt_sma20")];
  assert.equal(validateScreenerDraft(codes, conditions), null);
  // After "error", same draft still builds payload
  const payload = buildEvaluatePayload(codes, conditions);
  assert.equal(payload.codes[0], "000001");
});
