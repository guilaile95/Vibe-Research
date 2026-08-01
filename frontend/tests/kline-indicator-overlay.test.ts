import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { KlineBar, TechnicalIndicatorSeriesPoint } from "../src/lib/api/types.ts";
import {
  buildKlineIndicatorGeometry,
  normalizeKlineIndicatorOverlay,
} from "../src/lib/klineIndicatorOverlay.ts";

function bar(
  date: string,
  open: number | string,
  high: number | string,
  low: number | string,
  close: number | string,
  extra: Partial<KlineBar> = {},
): KlineBar {
  return { date, open: open as number, high: high as number, low: low as number, close: close as number, ...extra };
}

function ind(
  date: string,
  sma20: number | null,
  sma60: number | null,
  upper: number | null,
  lower: number | null,
): TechnicalIndicatorSeriesPoint {
  return {
    date,
    sma20,
    sma60,
    bollinger_upper: upper,
    bollinger_middle: null,
    bollinger_lower: lower,
    macd_dif: null,
    macd_dea: null,
    macd_histogram: null,
    rsi14: null,
    volume_ratio_5_20: null,
  };
}

describe("normalizeKlineIndicatorOverlay — kline cleaning", () => {
  it("keeps valid OHLC and numeric strings", () => {
    const bars = [
      bar("2026-07-31", "10", "12", "9", "11"),
      bar("2026-07-30", 10, 11, 9.5, 10.5),
    ];
    const out = normalizeKlineIndicatorOverlay(bars, [], 60);
    assert.equal(out.length, 2);
    assert.equal(out[0].date, "2026-07-30");
    assert.equal(out[1].open, 10);
    assert.equal(out[1].high, 12);
  });

  it("accepts datetime prefixes", () => {
    const bars = [
      { datetime: "2026-07-31 15:00:00", open: 10, high: 11, low: 9, close: 10.5 },
      { date: "2026-07-30T15:00:00", open: 10, high: 11, low: 9, close: 10.2 },
    ] as KlineBar[];
    const out = normalizeKlineIndicatorOverlay(bars, [], 60);
    assert.deepEqual(out.map((p) => p.date), ["2026-07-30", "2026-07-31"]);
  });

  it("filters illegal dates and calendar dates", () => {
    const bars = [
      bar("2026-02-31", 10, 11, 9, 10),
      bar("2026-13-01", 10, 11, 9, 10),
      bar("2026-00-01", 10, 11, 9, 10),
      bar("2026-7-1", 10, 11, 9, 10),
      bar("", 10, 11, 9, 10),
      bar("2026-07-01", 10, 11, 9, 10),
    ];
    const out = normalizeKlineIndicatorOverlay(bars, [], 60);
    assert.deepEqual(out.map((p) => p.date), ["2026-07-01"]);
  });

  it("filters NaN/Infinity/negative/zero/bool and invalid OHLC relations", () => {
    const bars = [
      bar("2026-07-01", Number.NaN, 11, 9, 10),
      bar("2026-07-02", Number.POSITIVE_INFINITY, 11, 9, 10),
      bar("2026-07-03", -1, 11, 9, 10),
      bar("2026-07-04", 0, 11, 9, 10),
      { date: "2026-07-05", open: true as unknown as number, high: 11, low: 9, close: 10 },
      bar("2026-07-06", 10, 9, 11, 10), // high < low
      bar("2026-07-07", 12, 11, 9, 10), // high < open
      bar("2026-07-08", 10, 11, 10.5, 9), // low > close
      bar("2026-07-09", 10, 12, 9, 11),
    ];
    const out = normalizeKlineIndicatorOverlay(bars, [], 60);
    assert.deepEqual(out.map((p) => p.date), ["2026-07-09"]);
  });

  it("duplicate dates keep first valid; first invalid second valid keeps second", () => {
    const bars = [
      bar("2026-07-01", 10, 12, 9, 11),
      bar("2026-07-01", 20, 22, 19, 21),
      bar("2026-07-02", Number.NaN, 11, 9, 10),
      bar("2026-07-02", 10, 11, 9, 10.5),
    ];
    const out = normalizeKlineIndicatorOverlay(bars, [], 60);
    assert.equal(out.length, 2);
    assert.equal(out[0].close, 11);
    assert.equal(out[1].close, 10.5);
  });
});

describe("normalizeKlineIndicatorOverlay — indicator alignment", () => {
  it("matches fully, partially, and keeps kline without indicators", () => {
    const bars = [
      bar("2026-07-01", 10, 11, 9, 10.5),
      bar("2026-07-02", 10, 11, 9, 10.6),
      bar("2026-07-03", 10, 11, 9, 10.7),
    ];
    const series = [
      ind("2026-07-01", 10.1, 9.9, 11.5, 8.5),
      ind("2026-07-03", 10.2, 9.8, 11.6, 8.4),
      ind("2026-07-04", 10.3, 9.7, 11.7, 8.3), // no candle
    ];
    const out = normalizeKlineIndicatorOverlay(bars, series, 60);
    assert.equal(out.length, 3);
    assert.equal(out[0].sma20, 10.1);
    assert.equal(out[1].sma20, null);
    assert.equal(out[2].sma20, 10.2);
    assert.ok(!out.some((p) => p.date === "2026-07-04"));
  });

  it("no date match leaves all metrics null; invalid/0/negative metrics -> null; first-wins", () => {
    const bars = [bar("2026-07-01", 10, 11, 9, 10)];
    const series = [
      ind("2026-07-01", 0, -1, Number.NaN as unknown as number, Number.POSITIVE_INFINITY as unknown as number),
      ind("2026-07-01", 10.5, 10.2, 12, 8),
      ind("2026-07-10", 1, 1, 1, 1),
    ];
    const out = normalizeKlineIndicatorOverlay(bars, series, 60);
    assert.equal(out.length, 1);
    assert.equal(out[0].sma20, null);
    assert.equal(out[0].sma60, null);
    assert.equal(out[0].bollinger_upper, null);
    assert.equal(out[0].bollinger_lower, null);
  });
});

describe("normalizeKlineIndicatorOverlay — sort/truncate/immutability", () => {
  it("sorts ascending and keeps latest maxPoints", () => {
    const bars = Array.from({ length: 61 }, (_, i) => {
      const day = i + 1;
      const d = `2026-05-${String(day).padStart(2, "0")}`;
      // May only has 31 days; use sequential valid dates via July
      return null;
    }).filter(Boolean);
    // Build 61 valid July/June dates manually
    const dates: string[] = [];
    for (let i = 0; i < 61; i++) {
      const dt = new Date(Date.UTC(2026, 5, 1 + i)); // from 2026-06-01
      dates.push(dt.toISOString().slice(0, 10));
    }
    const many = dates.map((d) => bar(d, 10, 11, 9, 10));
    // shuffle
    const shuffled = [...many].reverse();
    const out = normalizeKlineIndicatorOverlay(shuffled, [], 60);
    assert.equal(out.length, 60);
    assert.equal(out[0].date, dates[1]);
    assert.equal(out[out.length - 1].date, dates[60]);
  });

  it("maxPoints edge cases and empty inputs", () => {
    const bars = [bar("2026-07-01", 10, 11, 9, 10), bar("2026-07-02", 10, 11, 9, 10)];
    assert.equal(normalizeKlineIndicatorOverlay(bars, [], 1).length, 1);
    assert.deepEqual(normalizeKlineIndicatorOverlay(bars, [], 0), []);
    assert.deepEqual(normalizeKlineIndicatorOverlay(bars, [], -3), []);
    assert.deepEqual(normalizeKlineIndicatorOverlay(null, null, 60), []);
    assert.deepEqual(normalizeKlineIndicatorOverlay([], [], 60), []);
  });

  it("does not mutate inputs", () => {
    const bars = [bar("2026-07-02", 10, 11, 9, 10), bar("2026-07-01", 10, 11, 9, 10)];
    const series = [ind("2026-07-01", 10.1, 9.9, 11, 9)];
    const barsBefore = JSON.stringify(bars);
    const seriesBefore = JSON.stringify(series);
    normalizeKlineIndicatorOverlay(bars, series, 60);
    assert.equal(JSON.stringify(bars), barsBefore);
    assert.equal(JSON.stringify(series), seriesBefore);
  });
});

describe("buildKlineIndicatorGeometry", () => {
  it("ordinary multi-point geometry is finite", () => {
    const pts = normalizeKlineIndicatorOverlay(
      [
        bar("2026-07-01", 10, 11, 9, 10.5),
        bar("2026-07-02", 10.5, 12, 10, 11),
        bar("2026-07-03", 11, 12.5, 10.5, 12),
      ],
      [
        ind("2026-07-01", 10.2, 9.8, 11.2, 8.8),
        ind("2026-07-02", 10.4, 9.9, 11.5, 9.0),
        ind("2026-07-03", 10.6, 10.0, 12.0, 9.2),
      ],
      60,
    );
    const g = buildKlineIndicatorGeometry(pts, 720, 220);
    assert.equal(g.candles.length, 3);
    for (const c of g.candles) {
      for (const k of ["x", "yOpen", "yClose", "yHigh", "yLow", "bodyTop", "bodyH"] as const) {
        assert.ok(Number.isFinite(c[k]));
      }
    }
    for (const segs of Object.values(g.metricSegments)) {
      for (const seg of segs) {
        for (const p of seg.points) {
          assert.ok(Number.isFinite(p.x));
          assert.ok(Number.isFinite(p.y));
          assert.ok(Number.isFinite(p.value));
        }
      }
    }
  });

  it("single point and identical prices are safe", () => {
    const one = normalizeKlineIndicatorOverlay([bar("2026-07-01", 10, 10, 10, 10)], [ind("2026-07-01", 10, 10, 10, 10)], 60);
    const g1 = buildKlineIndicatorGeometry(one, 720, 220);
    assert.equal(g1.candles.length, 1);
    assert.ok(g1.priceHigh > g1.priceLow);
    assert.ok(Number.isFinite(g1.candles[0].x));

    const same = normalizeKlineIndicatorOverlay(
      [bar("2026-07-01", 5, 5, 5, 5), bar("2026-07-02", 5, 5, 5, 5)],
      [],
      60,
    );
    const g2 = buildKlineIndicatorGeometry(same, 0, Number.NaN);
    assert.equal(g2.width, 720);
    assert.equal(g2.height, 220);
    assert.ok(g2.priceHigh > g2.priceLow);
  });

  it("price range includes BOLL beyond candle high/low", () => {
    const pts = normalizeKlineIndicatorOverlay(
      [bar("2026-07-01", 10, 11, 9, 10.5)],
      [ind("2026-07-01", 10.2, 9.8, 15, 5)],
      60,
    );
    const g = buildKlineIndicatorGeometry(pts, 720, 220);
    assert.ok(g.priceHigh >= 15);
    assert.ok(g.priceLow <= 5);
  });

  it("null metrics create gaps; single metric point forms singleton segment", () => {
    const pts = normalizeKlineIndicatorOverlay(
      [
        bar("2026-07-01", 10, 11, 9, 10),
        bar("2026-07-02", 10, 11, 9, 10),
        bar("2026-07-03", 10, 11, 9, 10),
        bar("2026-07-04", 10, 11, 9, 10),
        bar("2026-07-05", 10, 11, 9, 10),
      ],
      [
        ind("2026-07-01", 10.1, null, null, null),
        ind("2026-07-02", 10.2, null, null, null),
        // 07-03 missing -> gap
        ind("2026-07-04", 10.3, null, null, null),
        ind("2026-07-05", 10.4, null, null, null),
      ],
      60,
    );
    // force a single-point metric for sma60
    pts[2].sma60 = 9.9;
    const g = buildKlineIndicatorGeometry(pts, 720, 220);
    assert.equal(g.metricSegments.sma20.length, 2);
    assert.equal(g.metricSegments.sma20[0].points.length, 2);
    assert.equal(g.metricSegments.sma20[1].points.length, 2);
    assert.equal(g.metricSegments.sma60.length, 1);
    assert.equal(g.metricSegments.sma60[0].points.length, 1);
  });
});
