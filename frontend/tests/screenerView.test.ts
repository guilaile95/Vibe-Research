import assert from "node:assert/strict";
import test from "node:test";

import {
  ScreenerRequestGate,
  bucketsAreDisjoint,
  buildEvaluatePayload,
  groupResults,
  loadSourceCodes,
  normalizeCodes,
  parseCodeDraft,
  validateConditionDraft,
  validateScreenerDraft,
  defaultCondition,
  MAX_CODES,
} from "../src/lib/screenerView.ts";
import type { ScreenerEvaluateResult } from "../src/lib/api/types.ts";

test("parse and normalize codes: dedupe + sort WITHOUT truncate", () => {
  const parsed = parseCodeDraft("600519, 000001 600519 abc 12");
  assert.deepEqual(parsed, ["600519", "000001", "600519"]);
  assert.deepEqual(normalizeCodes(parsed), ["000001", "600519"]);

  // 31 unique codes must all be retained (no silent slice)
  const thirtyOne = Array.from({ length: 31 }, (_, i) => String(i + 1).padStart(6, "0"));
  const norm = normalizeCodes(thirtyOne);
  assert.equal(norm.length, 31);
  assert.equal(norm[0], "000001");
  assert.equal(norm[30], "000031");
});

test("validateScreenerDraft: 31 unique → overflow error; 30 unique ok", () => {
  const thirtyOne = Array.from({ length: 31 }, (_, i) => String(i + 1).padStart(6, "0"));
  const err = validateScreenerDraft(thirtyOne, [defaultCondition("price_gt_sma20")]);
  assert.ok(err);
  assert.ok(err!.includes("最多 30 个代码"));

  const thirty = thirtyOne.slice(0, 30);
  assert.equal(validateScreenerDraft(thirty, [defaultCondition("price_gt_sma20")]), null);
});

test("31 raw / 30 unique after dedupe → valid", () => {
  const raw = [
    ...Array.from({ length: 30 }, (_, i) => String(i + 1).padStart(6, "0")),
    "000001", // duplicate
  ];
  assert.equal(raw.length, 31);
  const norm = normalizeCodes(raw);
  assert.equal(norm.length, 30);
  assert.equal(validateScreenerDraft(norm, [defaultCondition("price_gt_sma20")]), null);
  const payload = buildEvaluatePayload(norm, [defaultCondition("price_gt_sma20")]);
  assert.equal(payload.codes.length, 30);
});

test("buildEvaluatePayload refuses overflow (no silent truncate)", () => {
  const thirtyOne = Array.from({ length: 31 }, (_, i) => String(i + 1).padStart(6, "0"));
  assert.throws(
    () => buildEvaluatePayload(thirtyOne, [defaultCondition("price_gt_sma20")]),
    /最多 30 个代码/,
  );
});

test("loadSourceCodes: source path may truncate with explicit hint", () => {
  const many = Array.from({ length: 103 }, (_, i) => String(i + 1).padStart(6, "0"));
  const loaded = loadSourceCodes(many, MAX_CODES);
  assert.equal(loaded.truncated, true);
  assert.equal(loaded.sourceTotal, 103);
  assert.equal(loaded.codes.length, 30);
  assert.ok(loaded.hint.includes("来源共有 103 个代码"));
  assert.ok(loaded.hint.includes("本次载入前 30 个"));
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
});

test("ScreenerRequestGate: single-flight while loading", () => {
  const gate = new ScreenerRequestGate();
  const t1 = gate.beginIfIdle("idle");
  assert.ok(t1);
  const t2 = gate.beginIfIdle("idle");
  assert.equal(t2, null);
  gate.end(t1!.generation);
  const t3 = gate.beginIfIdle("idle");
  assert.ok(t3);
});

test("ScreenerRequestGate: stale generation discarded", () => {
  const gate = new ScreenerRequestGate();
  const t1 = gate.begin();
  const t2 = gate.begin();
  assert.equal(gate.isCurrent(t1.generation), false);
  assert.equal(gate.isCurrent(t2.generation), true);
  gate.end(t2.generation);
});

test("error path preserves draft conceptually via pure validation still working", () => {
  const codes = ["000001"];
  const conditions = [defaultCondition("price_gt_sma20")];
  assert.equal(validateScreenerDraft(codes, conditions), null);
  const payload = buildEvaluatePayload(codes, conditions);
  assert.equal(payload.codes[0], "000001");
});

test("sector representatives not embedded in frontend screenerView", async () => {
  const sv = await import("../src/lib/screenerView.ts");
  assert.equal("SECTOR_REPRESENTATIVE_CODES" in sv, false);
  // Research index must not re-export text-parsing helpers
  const idx = await import("../src/data/sectorResearch/index.ts");
  assert.equal("getSectorRepresentativeCodes" in idx, false);
  assert.equal("extractCodesFromSourceRef" in idx, false);
});
