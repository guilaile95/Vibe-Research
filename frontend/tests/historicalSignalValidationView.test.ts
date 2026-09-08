import assert from "node:assert/strict";
import test from "node:test";
import { benchmarkNegativeSummary, metricText, validationStatusLabel } from "../src/lib/historicalSignalValidationView.ts";

test("historical validation keeps benchmark absence explicit", () => {
  const noBenchmark = {
    excess_return: null,
    failures: null,
  } as any;
  assert.equal(benchmarkNegativeSummary(noBenchmark), null);
  assert.equal(metricText(null), "—");
});

test("historical validation labels statuses and valid benchmark negatives", () => {
  const window = {
    excess_return: { count: 4 },
    failures: 1,
  } as any;
  assert.deepEqual(benchmarkNegativeSummary(window), { count: 1, ratio: 25 });
  assert.equal(validationStatusLabel("IMMATURE"), "窗口未成熟");
});
