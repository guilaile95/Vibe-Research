import assert from "node:assert/strict";
import test from "node:test";

import {
  buildNorthboundTurnoverGeometry,
  normalizeNorthboundHistorySeries,
} from "../src/lib/northboundHistoryView.ts";
import type { NorthboundHistoryEnvelope } from "../src/lib/recoveredMarketTypes.ts";

function env(): NorthboundHistoryEnvelope {
  return {
    schema_version: "northbound-history-v0.1",
    source: "HKEX Stock Connect Daily Statistics",
    source_tier: "authoritative",
    status: "normal",
    fetched_at: "2026-08-01T00:00:00Z",
    requested_days: 20,
    returned_points: 3,
    limitations: [],
    series: [
      { trade_date: "2026-07-03", total_turnover_mn: 120, trade_count: 3, etf_turnover_mn: 2 },
      { trade_date: "2026-07-01", total_turnover_mn: 100, trade_count: 1, etf_turnover_mn: 1 },
      { trade_date: "2026-07-02", total_turnover_mn: 110, trade_count: 2, etf_turnover_mn: 1.5 },
    ],
  };
}

test("northbound history normalizes ascending without mutation", () => {
  const source = env();
  const before = JSON.stringify(source);
  const points = normalizeNorthboundHistorySeries(source);
  assert.deepEqual(points.map((point) => point.trade_date), ["2026-07-01", "2026-07-02", "2026-07-03"]);
  assert.equal(JSON.stringify(source), before);
});

test("northbound geometry is finite and zero-based", () => {
  const geometry = buildNorthboundTurnoverGeometry(normalizeNorthboundHistorySeries(env()));
  assert.equal(geometry.points.length, 3);
  assert.ok(geometry.maxValue > 0);
  for (const point of geometry.points) {
    assert.ok(Number.isFinite(point.x));
    assert.ok(Number.isFinite(point.y));
    assert.ok(point.y <= geometry.zeroY);
  }
});
