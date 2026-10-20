import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { financialAmount, financialEps } from "../src/lib/globalFinancials.ts";
import type { GlobalMetrics } from "../src/lib/api/types.ts";
const metrics: GlobalMetrics = { report_date: "2026-06-30", revenue: 100, revenue_yoy: null, net_profit: 0, eps: 2, roe: null, gross_margin: null, net_margin: null, debt_ratio: null, reporting_currency: "CNY", amount_unit: "PROVIDER_RAW_SCALE_UNVERIFIED", amount_scale_to_currency_units: null };
test("HK-listed CNY reporting currency never becomes HKD and unknown scale never becomes 亿", () => {
  const amount = financialAmount(100000000, metrics);
  assert.match(amount, /人民币/);
  assert.match(amount, /原始值.*未验证/);
  assert.doesNotMatch(amount, /亿|港元|美元/);
  assert.match(financialEps(2, metrics), /人民币\/股/);
  assert.match(financialAmount(0, metrics), /^0（/);
});
test("missing or unsupported currency and scale remain explicit", () => {
  assert.match(financialAmount(100, { ...metrics, reporting_currency: null }), /报告币种未知/);
  assert.match(financialAmount(100, { ...metrics, amount_unit: undefined }), /未验证/);
  assert.equal(financialAmount(null, metrics), "—");
  assert.equal(financialAmount(NaN, metrics), "—");
});
test("only explicit verified unit and scale support 亿", () => {
  assert.match(financialAmount(1e8, { ...metrics, amount_unit: "CURRENCY_UNITS", amount_scale_to_currency_units: 1 }), /1.00 亿人民币/);
  assert.match(financialAmount(1e8, { ...metrics, amount_unit: "CURRENCY_UNITS", amount_scale_to_currency_units: null }), /未验证/);
});
test("financial card and AI context share formatters; quote formatting is unchanged", () => {
  const source = readFileSync(new URL("../src/pages/StockData.tsx", import.meta.url), "utf8");
  assert.equal(source.match(/financialAmount\(gstock.metrics.revenue, gstock.metrics\)/g)?.length, 2);
  assert.equal(source.match(/financialAmount\(gstock.metrics.net_profit, gstock.metrics\)/g)?.length, 2);
  assert.equal(source.match(/financialEps\(gstock.metrics.eps, gstock.metrics\)/g)?.length, 2);
  assert.doesNotMatch(source, /bigMoney\(gstock.metrics/);
  assert.match(source, /bigMoney\(gstock.quote.mcap, gstock.market\)/);
});
