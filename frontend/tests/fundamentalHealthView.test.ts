import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  EARNINGS_SNAPSHOT_BALANCE_SHEET_QUALITY_HEADING,
  EARNINGS_SNAPSHOT_CASH_FLOW_QUALITY_HEADING,
  EARNINGS_SNAPSHOT_DATA_QUALITY_HEADING,
  EARNINGS_SNAPSHOT_GROWTH_HEADING,
  EARNINGS_SNAPSHOT_PROFITABILITY_HEADING,
  formatFinancialAmount,
  formatFinancialRatio,
  fundamentalHealthState,
} from "../src/lib/fundamentalHealthView.ts";

test("keeps missing and non-finite financial observations unknown", () => {
  assert.equal(formatFinancialRatio(null), "未知");
  assert.equal(formatFinancialRatio(Number.POSITIVE_INFINITY), "未知");
  assert.equal(formatFinancialAmount(undefined), "未知");
  assert.equal(formatFinancialAmount(Number.NaN), "未知");
});

test("formats exact deterministic ratios and CNY amounts", () => {
  assert.equal(formatFinancialRatio(1.5356), "153.6%");
  assert.equal(formatFinancialRatio(-0.05), "-5.0%");
  assert.equal(formatFinancialAmount(6_982_345_678), "69.82 亿元");
});

test("distinguishes normal, partial, empty, and error product states", () => {
  const normal = {
    revenue: "100亿",
    net_profit: "20亿",
    data_quality: { status: "normal" },
  } as never;
  const partial = {
    revenue: "100亿",
    net_profit: null,
    data_quality: { status: "partial" },
  } as never;

  assert.equal(fundamentalHealthState(normal, null), "normal");
  assert.equal(fundamentalHealthState(partial, null), "partial");
  assert.equal(fundamentalHealthState(null, null), "empty");
  assert.equal(fundamentalHealthState(normal, "failed"), "error");
});

test("earnings snapshot section headings stay Chinese-only display", () => {
  assert.equal(EARNINGS_SNAPSHOT_GROWTH_HEADING, "增长");
  assert.equal(EARNINGS_SNAPSHOT_PROFITABILITY_HEADING, "盈利能力");
  assert.equal(EARNINGS_SNAPSHOT_CASH_FLOW_QUALITY_HEADING, "现金流质量");
  assert.equal(EARNINGS_SNAPSHOT_BALANCE_SHEET_QUALITY_HEADING, "资产负债表质量");
  assert.equal(EARNINGS_SNAPSHOT_DATA_QUALITY_HEADING, "数据质量");
  for (const heading of [
    EARNINGS_SNAPSHOT_GROWTH_HEADING,
    EARNINGS_SNAPSHOT_PROFITABILITY_HEADING,
    EARNINGS_SNAPSHOT_CASH_FLOW_QUALITY_HEADING,
    EARNINGS_SNAPSHOT_BALANCE_SHEET_QUALITY_HEADING,
    EARNINGS_SNAPSHOT_DATA_QUALITY_HEADING,
  ]) {
    assert.doesNotMatch(heading, /Growth ·|Profitability ·|Cash Flow Quality|Balance Sheet Quality|Data Quality ·/);
    assert.doesNotMatch(heading, /\bBUY\b|\bSELL\b|财务评分/);
  }

  const source = readFileSync(
    new URL("../src/components/ui/EarningsSnapshot.tsx", import.meta.url),
    "utf8",
  );
  assert.match(source, /EARNINGS_SNAPSHOT_GROWTH_HEADING/);
  assert.match(source, /EARNINGS_SNAPSHOT_PROFITABILITY_HEADING/);
  assert.match(source, /EARNINGS_SNAPSHOT_CASH_FLOW_QUALITY_HEADING/);
  assert.match(source, /EARNINGS_SNAPSHOT_BALANCE_SHEET_QUALITY_HEADING/);
  assert.match(source, /EARNINGS_SNAPSHOT_DATA_QUALITY_HEADING/);
  assert.doesNotMatch(source, /Growth ·/);
  assert.doesNotMatch(source, /Profitability ·/);
  assert.doesNotMatch(source, /Cash Flow Quality/);
  assert.doesNotMatch(source, /Balance Sheet Quality/);
  assert.doesNotMatch(source, /Data Quality ·/);
});
