import assert from "node:assert/strict";
import test from "node:test";
import { financialEvidenceContext } from "../src/lib/stockDataEvidence.ts";
const fixture = (extra = {}) => ({ period_end: "2026-09-30", revenue: 0, net_profit: -3,
 data_quality: { source: "tonghuashun_via_akshare", fetch_mode: "snapshot", report_basis: "cumulative_report_period", point_in_time_supported: false, publication_date_known: false, status: "partial" }, ...extra });
test("financial context preserves zero, negative and qualified units", () => {
 const text = financialEvidenceContext(fixture({ roe: "0%", free_cash_flow: "-2亿元" }));
 for (const value of ["营收 0", "净利润 -3", "ROE 0%", "自由现金流 -2亿元", "非PIT", "未核验"]) assert.ok(text.includes(value));
});
test("unknown revenue does not erase other qualified observations", () => {
 const text = financialEvidenceContext(fixture({ revenue: null }));
 assert.ok(text.includes("营收 未知")); assert.ok(text.includes("净利润 -3"));
});
test("invalid provenance blocks all observations", () => {
 for (const q of [null, [], { ...fixture().data_quality, status: ["partial"] }, { ...fixture().data_quality, source: "other" }])
  assert.ok(!financialEvidenceContext(fixture({ data_quality: q })).includes("净利润 -3"));
});
test("nonfinite, arbitrary and oversized scalars stay unknown and bounded", () => {
 for (const v of [NaN, Infinity, true, {}, "0".repeat(1000000), "one billion"]) {
  const text = financialEvidenceContext(fixture({ revenue: v }));
  assert.ok(text.includes("营收 未知")); assert.ok(text.length < 1500);
 }
});
test("invalid dates including year zero stay unknown", () => {
 for (const period_end of ["0000-01-01", "2026-02-30", "yesterday", null])
  assert.ok(financialEvidenceContext(fixture({ period_end })).includes("报告期末 未知"));
});
