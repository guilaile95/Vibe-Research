import assert from "node:assert/strict";
import test from "node:test";

import {
  MAX_CODES,
  buildEvaluatePayload,
  buildFullMarketQuery,
  defaultCondition,
  groupResults,
  loadSourceCodes,
  normalizeCodes,
  parseCodeDraft,
  validateScreenerDraft,
} from "../src/lib/recoveredScreener.ts";
import { recoveredMarketApi } from "../src/lib/recoveredMarketApi.ts";
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

test("Full Market filters support AND arrays, legacy input, and reject invalid values", async () => {
  const filters = [
    { metric: "return_20d" as const, operator: "gte" as const, value: 0.05 },
    { metric: "return_20d" as const, operator: "lte" as const, value: 0.2 },
  ];
  assert.deepEqual(buildFullMarketQuery({ filters }).filters, filters);
  assert.deepEqual(buildFullMarketQuery({ filters: [] }).filters, []);
  assert.equal(buildFullMarketQuery({ filter_metric: "return_20d", filter_operator: "gte", filter_value: 0 }).filter_value, 0);
  assert.throws(() => buildFullMarketQuery({ filters: [{ ...filters[0], value: Number.NaN }] }), /全市场筛选参数无效/);
  assert.throws(() => buildFullMarketQuery({ filters: Array.from({ length: 21 }, () => filters[0]) }), /全市场筛选参数无效/);

  const originalFetch = globalThis.fetch;
  let requestedUrl = "";
  globalThis.fetch = (async (input: RequestInfo | URL) => {
    requestedUrl = typeof input === "string" ? input : input.toString();
    return new Response("{}", { status: 200, headers: { "content-type": "application/json" } });
  }) as typeof fetch;
  try {
    await recoveredMarketApi.getFullMarket({ filters });
  } finally {
    globalThis.fetch = originalFetch;
  }
  assert.deepEqual(JSON.parse(new URL(requestedUrl, "http://localhost").searchParams.get("filters") || "null"), filters);
});

test("result grouping preserves matched/rejected/unavailable buckets", () => {
  const result: ScreenerEvaluateResult = {
    status: "partial",
    evaluated_at: "t",
    logic: "AND",
    matched: [{ code: "000001", bucket: "matched", matched: true, technical_status: "normal", trade_date: null, condition_results: [], limitations: [] }],
    rejected: [{ code: "000002", bucket: "rejected", matched: false, technical_status: "normal", trade_date: null, condition_results: [], limitations: [] }],
    unavailable: [{ code: "000003", bucket: "unavailable", matched: null, technical_status: "unavailable", trade_date: null, condition_results: [], limitations: [] }],
    research_data: {
      schema_version: "research-data-plane.v0.1",
      dataset_id: "ashare_daily_unadjusted",
      provider_id: "local_bulk_dump",
      adjustment: "UNADJUSTED",
      status: "normal",
      fetched_at: "2026-07-31T00:00:00Z",
      as_of: "2026-07-30",
      coverage: { start: "2026-01-01", end: "2026-07-30", row_count: 120, code_count: 3 },
      provenance: { source_kind: "LOCAL_BULK_DUMP", artifact_sha256: "abc" },
      limitations: ["Research Runtime 数据不是 Canonical Fact Authority。"],
    },
    limitations: [],
    schema_version: "screener-v0.1",
  };
  const groups = groupResults(result);
  assert.equal(groups.matched.length, 1);
  assert.equal(groups.rejected.length, 1);
  assert.equal(groups.unavailable.length, 1);
});
