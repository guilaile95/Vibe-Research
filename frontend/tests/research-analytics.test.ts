import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { analyticsModes, formatResearchNumber, parseAnalyticsInput, metricNames } from "../src/lib/researchAnalytics.ts";

test("undefined values never display as zero", () => {
  for (const value of [null, undefined, NaN, Infinity, "0", false]) assert.equal(formatResearchNumber(value), "未定义");
  assert.equal(formatResearchNumber(0, true), "0.00%");
  assert.equal(formatResearchNumber(.1, true), "10.00%");
});
test("input adapter accepts object only with bounded size", () => {
  assert.deepEqual(parseAnalyticsInput('{"fee_bps":null}'), { fee_bps: null });
  for (const text of ["null", "[]", "123", "invalid", "x".repeat(4_000_001)]) assert.throws(() => parseAnalyticsInput(text));
});
test("all modes and verified twenty core metrics", () => {
  assert.equal(analyticsModes.length, 5);
  assert.equal(Object.keys(metricNames).length, 20);
});
test("page declares privacy, missingness, stale-response guards and no automatic persistence", () => {
  const source = readFileSync(new URL("../src/pages/ResearchAnalytics.tsx", import.meta.url), "utf8");
  assert.match(source, /NOT_PROVEN/);
  assert.match(source, /合成示例/);
  assert.match(source, /generation.current === id/);
  assert.match(source, /aria-label="完整研究结果"/);
  assert.doesNotMatch(source, /localStorage|sessionStorage|eval\(|new Function|dangerouslySetInnerHTML/);
});

import { parseAnalyticsReport, parseAnalyticsExample } from "../src/lib/researchAnalytics.ts";
const fixture = JSON.parse(readFileSync(new URL("./e2e/research-analytics.fixture.json", import.meta.url), "utf8"));
test("nonempty backend fixtures pass runtime parser for every mode", () => {
  for (const mode of analyticsModes) {
    assert.equal(parseAnalyticsReport(fixture[mode.id].result, mode.id).status, fixture[mode.id].result.status);
    assert.deepEqual(parseAnalyticsExample({ synthetic: true, input: fixture[mode.id].input }, mode.id), fixture[mode.id].input);
  }
});
test("malformed analytics responses and wrong authority fail closed before JSX", () => {
  const original = fixture.simulation.result;
  for (const patch of [{ status: {} }, { limitations: null }, { curve: [null] }, { metrics: { x: null } }, { formal_writes: 1 }, { input_fingerprint: "fake" }, { scope: {} }, { historical_availability: "PROVEN" }, { unknown_private_payload: "canary" }]) {
    assert.throws(() => parseAnalyticsReport({ ...original, ...patch }, "simulation"));
  }
  assert.throws(() => parseAnalyticsReport(fixture.performance.result, "simulation"));
  for (const value of [{ synthetic: false, input: {} }, { synthetic: true, input: null }, { synthetic: true, input: [] }]) assert.throws(() => parseAnalyticsExample(value, "simulation"));
});

test("curve requires real ascending unique dates and mode-specific numeric values", () => {
  const report = fixture.simulation.result;
  for (const curve of [[{ date: "2026-02-30", nav: 100 }], [{ date: "2025-01-03", nav: 100 }, { date: "2025-01-02", nav: 100 }], [{ date: "2025-01-02", nav: 100 }, { date: "2025-01-02", nav: 101 }], [{ date: "2025-01-02", twr_index: 1 }, { date: "2025-01-03", twr_index: 2 }]]) {
    assert.throws(() => parseAnalyticsReport({ ...report, curve }, "simulation"));
  }
});

test("cost comparison parser rejects malformed groups, source authority and fake cross-currency total", () => {
  const value = fixture["cost-comparison"].result;
  for (const patch of [{ cross_currency_total: 100 }, { canonical_cost_method_unchanged: false }, { authority: "CANONICAL_FIFO" }, { groups: [null] }, { groups: [{ currency: "CNY", status: "COMPLETE", fifo: null, moving_average: {} }] }, { status: "MISSING_INPUTS", missing: ["bad"], groups: [{}] }]) {
    assert.throws(() => parseAnalyticsReport({ ...value, ...patch }, "cost-comparison"));
  }
  assert.equal(parseAnalyticsReport(value, "cost-comparison").groups?.length, 2);
});


test("cost-only result fields cannot enter other mode renderers", () => {
  for (const mode of analyticsModes.filter(m => m.id !== "cost-comparison")) {
    for (const patch of [{ groups: [null] }, { securities: [null] }, { groups: [] }, { securities: [] }, { whole_account_total: null }, { cross_currency_total: null }, { canonical_cost_method_unchanged: true }, { rounding_policy: "fake" }, { ordering: "fake" }]) {
      assert.throws(() => parseAnalyticsReport({ ...fixture[mode.id].result, ...patch }, mode.id));
    }
  }
});
