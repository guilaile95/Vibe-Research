import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  formatPositiveRank,
  formatValuationDelta,
  formatValuationNumber,
} from "../src/lib/stockValuationContextView.ts";

test("valuation number formatting keeps zero visible and null as an em dash", () => {
  assert.equal(formatValuationNumber(10), "10.00");
  assert.equal(formatValuationNumber(0), "0.00");
  assert.equal(formatValuationNumber(-5), "-5.00");
  assert.equal(formatValuationNumber(null), "—");
  assert.equal(formatValuationNumber(Number.NaN), "—");
});

test("valuation delta does not fabricate a zero from unavailable values", () => {
  assert.equal(formatValuationDelta(-5), "-5.00");
  assert.equal(formatValuationDelta(2.5), "+2.50");
  assert.equal(formatValuationDelta(null), "—");
  assert.notEqual(formatValuationDelta(null), "0.00");
});

test("positive rank stays unavailable when the sample is missing", () => {
  assert.equal(formatPositiveRank(1, 2), "1 / 2");
  assert.equal(formatPositiveRank(null, 2), "—");
  assert.equal(formatPositiveRank(1, 0), "—");
});

test("relative industry valuation card keeps disclosures and does not add trading language", () => {
  const source = readFileSync(
    new URL("../src/components/stock/StockValuationContextCard.tsx", import.meta.url),
    "utf8",
  );
  assert.match(source, /Eastmoney f115/);
  assert.match(source, /industry_membership_semantics/);
  assert.match(source, /当前行业为 UNKNOWN，行业正值中位数不计算；个股估值仍可独立显示。/);
  assert.match(source, /不是行业指数估值/);
  for (const forbidden of ["BUY", "SELL", "建议买入", "建议卖出", "综合评分"]) {
    assert.equal(source.includes(forbidden), false, `valuation card must not contain ${forbidden}`);
  }
});
