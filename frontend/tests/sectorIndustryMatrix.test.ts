import assert from "node:assert/strict";
import test from "node:test";

import {
  formatMatrixPercent,
  sectorIndustryMatrixState,
  sortSectorIndustryRows,
} from "../src/lib/sectorIndustryMatrix.ts";

function row(name: string, five: number | null, up: number | null, status: "normal" | "partial" | "unavailable" = "normal") {
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
    valuation: { status: "UNAVAILABLE_IN_V0_1", message: "当前数据源未提供可信行业级估值。" },
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

test("industry matrix state distinguishes normal, partial, unavailable, empty, and read failure", () => {
  const normal = { status: "normal", universe_status: "normal", items: [row("电子", 1, 0.5)] } as never;
  const partial = { status: "partial", universe_status: "normal", items: [row("电子", 1, 0.5, "partial")] } as never;
  const unavailable = { status: "unavailable", universe_status: "normal", items: [] } as never;
  const empty = { status: "normal", universe_status: "empty", items: [] } as never;
  assert.equal(sectorIndustryMatrixState(normal, false, false), "normal");
  assert.equal(sectorIndustryMatrixState(partial, false, false), "partial");
  assert.equal(sectorIndustryMatrixState(unavailable, false, false), "unavailable");
  assert.equal(sectorIndustryMatrixState(empty, false, false), "empty");
  assert.equal(sectorIndustryMatrixState(null, false, true), "error");
  assert.equal(sectorIndustryMatrixState(null, true, false), "loading");
});
