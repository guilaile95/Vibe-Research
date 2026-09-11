import assert from "node:assert/strict";
import test from "node:test";

import {
  formatMatrixPercent,
  formatMatrixNumber,
  sectorIndustryMatrixState,
  sortSectorIndustryRows,
} from "../src/lib/sectorIndustryMatrix.ts";

function valuationMetric(positive_median: number | null) {
  return {
    status: positive_median == null ? "UNAVAILABLE" : "NORMAL",
    observed_count: positive_median == null ? 0 : 2,
    missing_count: positive_median == null ? 2 : 0,
    positive_count: positive_median == null ? 0 : 2,
    zero_count: 0,
    negative_count: 0,
    positive_median,
    median_status: positive_median == null ? "NO_POSITIVE_VALUES" : "NORMAL",
    observed_coverage_ratio: positive_median == null ? 0 : 1,
    positive_coverage_ratio: positive_median == null ? 0 : 1,
    positive_coverage_denominator: "CURRENT_MEMBER_COUNT",
    positive_market_cap_coverage_ratio: positive_median == null ? 0 : 1,
    market_cap_coverage_denominator: "ALL_CURRENT_MEMBERS_WITH_VALID_POSITIVE_MARKET_CAP",
  };
}

function row(name: string, five: number | null, up: number | null, status: "normal" | "partial" | "unavailable" = "normal", peMedian: number | null = 10, pbMedian: number | null = 1) {
  return {
    industry_key: name,
    industry_name: name,
    classification_status: "KNOWN",
    status,
    expected_member_count: 2,
    current_member_count: 2,
    rdp_usable_member_count: status === "partial" ? 1 : 2,
    unavailable_member_count: status === "partial" ? 1 : 0,
    coverage_ratio: status === "partial" ? 0.5 : 1,
    snapshot_as_of: "2026-09-08T00:00:00Z",
    rdp_as_of: "2026-09-08",
    provenance: { classification_provider: "EASTMONEY", membership_source: "fixture", membership_semantics: "CURRENT_MEMBERSHIP_SNAPSHOT", rdp: null },
    metrics: {
      member_aggregate_return_5d_pct: five,
      member_aggregate_return_20d_pct: null,
      return_5d_usable_count: five == null ? 0 : 2,
      return_20d_usable_count: 0,
      member_aggregate_acceleration_5d_pct: null,
      acceleration_5d_status: "UNAVAILABLE_WITH_CURRENT_RDP_FEATURES",
    },
    breadth: {
      up_member_count: 0,
      down_member_count: 0,
      flat_member_count: 0,
      change_usable_count: 2,
      change_unavailable_count: 0,
      up_ratio: up,
      down_ratio: 0,
      flat_ratio: 0,
      basis: "CURRENT_MEMBERS_WITH_CHANGE_PCT",
      above_ma20_count: 0,
      ma20_usable_count: 0,
      ma20_unavailable_count: 2,
      above_ma20_ratio: null,
      ma20_basis: "RDP_MEMBERS_WITH_20_OBSERVATIONS",
    },
    participation: {
      turnover_pct_avg: 0,
      turnover_usable_count: 2,
      amount_total: 0,
      amount_usable_count: 2,
      volume_ratio_20d_avg: 0,
      volume_ratio_20d_usable_count: 2,
      semantics: "TRANSPARENT_PARTICIPATION_PROXY_ONLY",
    },
    crowding: { status: "PROXY_ONLY", semantics: "TRANSPARENT_PARTICIPATION_PROXY_ONLY" },
    valuation: {
      status: "NORMAL",
      semantics: "CURRENT_MEMBER_VALUATION_DISTRIBUTION_ONLY",
      message: "这里只统计当前 Eastmoney 行业成员的 PE/PB 分布，不是行业指数估值，也不是历史估值分位。",
      pe_ttm: valuationMetric(peMedian),
      pb: valuationMetric(pbMedian),
      market_cap_observed_count: 2,
      market_cap_missing_or_invalid_count: 0,
      market_cap: { status: "NORMAL", observed_count: 2, missing_count: 0, positive_total: 100, basis: "VALID_POSITIVE_MARKET_CAP_ONLY" },
      historical_percentile: { status: "NOT_AVAILABLE" },
      sector_index_valuation_authority: { status: "NOT_AVAILABLE" },
      limitations: [],
    },
    warnings: [],
    limitations: [],
  } as never;
}

test("industry matrix sorting keeps nulls last and preserves zero", () => {
  const rows = sortSectorIndustryRows([row("乙", 0, 0), row("甲", null, 0.5), row("丙", 2, null)], "member_aggregate_return_5d_pct");
  assert.deepEqual(rows.map((item) => item.industry_name), ["丙", "乙", "甲"]);
  assert.equal(formatMatrixPercent(0), "0.00%");
  assert.equal(formatMatrixPercent(null), "—");
  assert.equal(formatMatrixPercent(0, true), "0.00%");
});

test("valuation median sorting keeps nulls last and formatting does not fabricate zero", () => {
  const rows = [row("乙", 0, 0, "normal", null), row("甲", 0, 0, "normal", 12), row("丙", 0, 0, "normal", 0)];
  assert.deepEqual(sortSectorIndustryRows(rows, "pe_ttm_positive_median").map((item) => item.industry_name), ["甲", "丙", "乙"]);
  assert.equal(formatMatrixNumber(0), "0.00");
  assert.equal(formatMatrixNumber(null), "—");
});

test("industry matrix state distinguishes normal, partial, unavailable, empty, and read failure", () => {
  const normal = { status: "normal", universe_status: "normal", items: [row("电子", 1, 0.5)] } as never;
  const partial = { status: "partial", universe_status: "normal", items: [row("电子", 1, 0.5, "partial")] } as never;
  const unavailable = { status: "unavailable", universe_status: "normal", items: [] } as never;
  const rdpUnavailableWithValuation = { status: "unavailable", universe_status: "normal", items: [row("电子", null, null, "unavailable")] } as never;
  const empty = { status: "normal", universe_status: "empty", items: [] } as never;
  assert.equal(sectorIndustryMatrixState(normal, false, false), "normal");
  assert.equal(sectorIndustryMatrixState(partial, false, false), "partial");
  assert.equal(sectorIndustryMatrixState(unavailable, false, false), "unavailable");
  assert.equal(sectorIndustryMatrixState(rdpUnavailableWithValuation, false, false), "partial");
  assert.equal(sectorIndustryMatrixState(empty, false, false), "empty");
  assert.equal(sectorIndustryMatrixState(null, false, true), "error");
  assert.equal(sectorIndustryMatrixState(null, true, false), "loading");
});
