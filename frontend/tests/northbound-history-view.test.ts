import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type {
  NorthboundHistoryEnvelope,
  NorthboundHistoryPoint,
} from "../src/lib/api/types.ts";
import {
  buildNorthboundTurnoverGeometry,
  normalizeNorthboundHistorySeries,
} from "../src/lib/northboundHistoryView.ts";
import { formatCount, formatTurnoverMn } from "../src/lib/northboundView.ts";

function point(
  trade_date: string,
  total_turnover_mn: number,
  trade_count: number | null = 1000,
  etf_turnover_mn: number | null = 10,
): NorthboundHistoryPoint {
  return { trade_date, total_turnover_mn, trade_count, etf_turnover_mn };
}

function env(series: NorthboundHistoryPoint[]): NorthboundHistoryEnvelope {
  return {
    schema_version: "northbound-history-v0.1",
    source: "HKEX Stock Connect Daily Statistics",
    source_tier: "authoritative",
    status: "normal",
    fetched_at: "2026-08-01T00:00:00+00:00",
    requested_days: 20,
    returned_points: series.length,
    limitations: [],
    series,
  };
}

function twentyDays(): NorthboundHistoryPoint[] {
  // 20 ascending weekdays starting 2026-07-01-ish
  const dates = [
    "2026-07-01", "2026-07-02", "2026-07-03", "2026-07-06", "2026-07-07",
    "2026-07-08", "2026-07-09", "2026-07-10", "2026-07-13", "2026-07-14",
    "2026-07-15", "2026-07-16", "2026-07-17", "2026-07-20", "2026-07-21",
    "2026-07-22", "2026-07-23", "2026-07-24", "2026-07-27", "2026-07-28",
  ];
  return dates.map((d, i) => point(d, 100 + i, 1000 + i, 1 + i));
}

describe("normalizeNorthboundHistorySeries", () => {
  it("keeps normal 20 points ascending", () => {
    const series = twentyDays();
    const out = normalizeNorthboundHistorySeries(env(series), 20);
    assert.equal(out.length, 20);
    assert.deepEqual(
      out.map((p) => p.trade_date),
      series.map((p) => p.trade_date),
    );
  });

  it("sorts disordered input ascending", () => {
    const series = [
      point("2026-07-10", 3),
      point("2026-07-01", 1),
      point("2026-07-05", 2),
    ];
    const out = normalizeNorthboundHistorySeries(env(series), 20);
    assert.deepEqual(
      out.map((p) => p.trade_date),
      ["2026-07-01", "2026-07-05", "2026-07-10"],
    );
  });

  it("keeps latest 20 when more than maxPoints", () => {
    const series = twentyDays().concat([
      point("2026-07-29", 200),
      point("2026-07-30", 210),
    ]);
    const out = normalizeNorthboundHistorySeries(env(series), 20);
    assert.equal(out.length, 20);
    // Drop oldest 2 of original 20, keep latest through 2026-07-30.
    assert.equal(out[0].trade_date, "2026-07-03");
    assert.equal(out[out.length - 1].trade_date, "2026-07-30");
  });

  it("dedupes same trade_date first-wins", () => {
    const series = [
      point("2026-07-01", 11, 1, 1),
      point("2026-07-01", 99, 9, 9),
      point("2026-07-02", 22, 2, 2),
    ];
    const out = normalizeNorthboundHistorySeries(env(series), 20);
    assert.equal(out.length, 2);
    assert.equal(out[0].total_turnover_mn, 11);
  });

  it("filters illegal dates and 2026-02-31", () => {
    const series = [
      point("2026-02-31", 10),
      point("bad-date", 10),
      point("2026-07-01", 10),
    ];
    const out = normalizeNorthboundHistorySeries(env(series), 20);
    assert.deepEqual(out.map((p) => p.trade_date), ["2026-07-01"]);
  });

  it("filters negative / NaN / Infinity totals; keeps total=0", () => {
    const series = [
      point("2026-07-01", -1),
      point("2026-07-02", Number.NaN),
      point("2026-07-03", Number.POSITIVE_INFINITY),
      point("2026-07-04", 0),
      point("2026-07-05", 5),
    ];
    const out = normalizeNorthboundHistorySeries(env(series), 20);
    assert.deepEqual(
      out.map((p) => p.trade_date),
      ["2026-07-04", "2026-07-05"],
    );
    assert.equal(out[0].total_turnover_mn, 0);
  });

  it("normalizes illegal trade_count and ETF to null", () => {
    const series: NorthboundHistoryPoint[] = [
      {
        trade_date: "2026-07-01",
        total_turnover_mn: 10,
        trade_count: Number.NaN as unknown as number,
        etf_turnover_mn: -3,
      },
      {
        trade_date: "2026-07-02",
        total_turnover_mn: 11,
        trade_count: Number.POSITIVE_INFINITY as unknown as number,
        etf_turnover_mn: Number.NaN as unknown as number,
      },
    ];
    const out = normalizeNorthboundHistorySeries(env(series), 20);
    assert.equal(out.length, 2);
    assert.equal(out[0].trade_count, null);
    assert.equal(out[0].etf_turnover_mn, null);
    assert.equal(out[1].trade_count, null);
    assert.equal(out[1].etf_turnover_mn, null);
  });

  it("does not mutate input envelope/series", () => {
    const series = twentyDays();
    const e = env(series);
    const before = JSON.stringify(e);
    normalizeNorthboundHistorySeries(e, 20);
    assert.equal(JSON.stringify(e), before);
  });

  it("returns empty for empty/null inputs and maxPoints<=0", () => {
    assert.deepEqual(normalizeNorthboundHistorySeries(null), []);
    assert.deepEqual(normalizeNorthboundHistorySeries(undefined), []);
    assert.deepEqual(normalizeNorthboundHistorySeries(env([]), 20), []);
    assert.deepEqual(normalizeNorthboundHistorySeries(env(twentyDays()), 0), []);
    assert.deepEqual(normalizeNorthboundHistorySeries(env(twentyDays()), -1), []);
  });
});

describe("buildNorthboundTurnoverGeometry", () => {
  it("single point sits in horizontal middle; Y from 0; finite coords", () => {
    const g = buildNorthboundTurnoverGeometry([point("2026-07-01", 100)], 640, 220);
    assert.equal(g.points.length, 1);
    assert.ok(Number.isFinite(g.points[0].x));
    assert.ok(Number.isFinite(g.points[0].y));
    assert.equal(g.points[0].x, g.padL + g.plotW / 2);
    assert.equal(g.zeroY, g.padT + g.plotH);
    assert.ok(g.points[0].y <= g.zeroY);
  });

  it("all-zero geometry still finite and Y-axis starts at 0", () => {
    const pts = [point("2026-07-01", 0), point("2026-07-02", 0), point("2026-07-03", 0)];
    const g = buildNorthboundTurnoverGeometry(pts, 640, 220);
    assert.equal(g.maxValue, 0);
    assert.equal(g.midValue, 0);
    for (const p of g.points) {
      assert.ok(Number.isFinite(p.x));
      assert.ok(Number.isFinite(p.y));
      assert.equal(p.y, g.zeroY);
    }
  });

  it("identical values produce equal y; multi-point spreads x", () => {
    const pts = [
      point("2026-07-01", 50),
      point("2026-07-02", 50),
      point("2026-07-03", 50),
    ];
    const g = buildNorthboundTurnoverGeometry(pts, 640, 220);
    assert.equal(g.points[0].y, g.points[1].y);
    assert.equal(g.points[1].y, g.points[2].y);
    assert.ok(g.points[0].x < g.points[1].x);
    assert.ok(g.points[1].x < g.points[2].x);
  });

  it("ordinary multi-point geometry has finite coords and ascending x", () => {
    const g = buildNorthboundTurnoverGeometry(twentyDays(), 640, 220);
    assert.equal(g.points.length, 20);
    for (let i = 0; i < g.points.length; i++) {
      assert.ok(Number.isFinite(g.points[i].x));
      assert.ok(Number.isFinite(g.points[i].y));
      assert.ok(g.points[i].y <= g.zeroY);
      if (i > 0) assert.ok(g.points[i].x > g.points[i - 1].x);
    }
    assert.ok(g.maxValue > 0);
    assert.ok(g.midValue > 0);
  });
});

describe("tooltip formatters reuse existing helpers", () => {
  it("formatTurnoverMn and formatCount match chart tooltip building blocks", () => {
    assert.equal(formatTurnoverMn(354101.65), "3541.02 亿");
    assert.equal(formatTurnoverMn(null), "—");
    assert.equal(formatCount(16471152), "16,471,152");
    assert.equal(formatCount(null), "—");
  });
});
