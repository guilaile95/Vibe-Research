import assert from "node:assert/strict";
import test from "node:test";

import {
  MAX_CODES,
  buildEvaluatePayload,
  defaultCondition,
  groupResults,
  loadSourceCodes,
  normalizeCodes,
  parseCodeDraft,
  validateScreenerDraft,
} from "../src/lib/recoveredScreener.ts";
import type { ScreenerEvaluateResult } from "../src/lib/recoveredMarketTypes.ts";

test("screener code normalization dedupes, sorts and does not silently truncate", () => {
  assert.deepEqual(normalizeCodes(parseCodeDraft("600519 000001 600519 bad")), ["000001", "600519"]);
  const many = Array.from({ length: 31 }, (_, i) => String(i + 1).padStart(6, "0"));
  assert.equal(normalizeCodes(many).length, 31);
  assert.match(validateScreenerDraft(many, [defaultCondition("price_gt_sma20")]) || "", /最多 30 个代码/);
});

test("source loads may truncate with an explicit hint", () => {
  const many = Array.from({ length: 103 }, (_, i) => String(i + 1).padStart(6, "0"));
  const loaded = loadSourceCodes(many);
  assert.equal(loaded.codes.length, MAX_CODES);
  assert.equal(loaded.truncated, true);
  assert.match(loaded.hint, /来源共有 103 个代码/);
});

test("evaluate payload keeps validated AND conditions", () => {
  const payload = buildEvaluatePayload(["600519", "000001"], [defaultCondition("price_gt_sma20")]);
  assert.deepEqual(payload.codes, ["000001", "600519"]);
  assert.equal(payload.conditions[0].id, "price_gt_sma20");
});

test("result grouping preserves matched/rejected/unavailable buckets", () => {
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
  const groups = groupResults(result);
  assert.equal(groups.matched.length, 1);
  assert.equal(groups.rejected.length, 1);
  assert.equal(groups.unavailable.length, 1);
});
