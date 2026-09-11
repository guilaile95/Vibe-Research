import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  formatSampleCoverage,
  formatStockRelativePercent,
  formatStockRelativePoints,
} from "../src/lib/stockRelativeContextView.ts";

test("relative percentage formatting preserves positive, negative, zero, and null", () => {
  assert.equal(formatStockRelativePercent(7.3), "+7.30%");
  assert.equal(formatStockRelativePercent(-2.5), "-2.50%");
  assert.equal(formatStockRelativePercent(0), "0.00%");
  assert.equal(formatStockRelativePercent(null), "—");
  assert.equal(formatStockRelativePercent(Number.NaN), "—");
});

test("relative differences are rendered as percentage points", () => {
  assert.equal(formatStockRelativePoints(7.3), "+7.30 个百分点");
  assert.equal(formatStockRelativePoints(-2.5), "-2.50 个百分点");
  assert.equal(formatStockRelativePoints(null), "—");
});

test("sample coverage exposes counts without fabricating unavailable coverage", () => {
  assert.equal(formatSampleCoverage(4, 5, 0.8), "4 / 5（80.0%）");
  assert.equal(formatSampleCoverage(0, 0, null), "0 / 0");
  assert.equal(formatSampleCoverage(2, 5, Number.NaN), "2 / 5");
});

test("StockData relative card keeps the accepted disclosure and null-safe paths", () => {
  const source = readFileSync(
    new URL("../src/components/stock/StockRelativeContextCard.tsx", import.meta.url),
    "utf8",
  );
  assert.match(source, /UNADJUSTED/);
  assert.match(source, /百分点/);
  assert.match(source, /industry_membership_semantics/);
  assert.match(source, /UNKNOWN/);
  assert.match(source, /行业有效样本/);
  assert.match(source, /市场有效样本/);
  assert.match(source, /data\.periods\[horizon\]/);
  for (const forbidden of ["BUY", "SELL", "建议买入", "建议卖出", "综合评分"]) {
    assert.equal(source.includes(forbidden), false, `relative card must not contain ${forbidden}`);
  }
});
