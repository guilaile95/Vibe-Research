import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const api = readFileSync(new URL("../src/lib/api.ts", import.meta.url), "utf8");
const types = readFileSync(new URL("../src/lib/api/types.ts", import.meta.url), "utf8");
const dailyReview = readFileSync(new URL("../src/pages/DailyReview.tsx", import.meta.url), "utf8");
const chart = readFileSync(new URL("../src/components/dailyReview/GlobalMarketTrendChart.tsx", import.meta.url), "utf8");

test("global market trend API requests the dedicated endpoint and exposes the complete transport type", () => {
  assert.match(api, /globalIndexTrends:\s*\(signal\?: AbortSignal\)\s*=>\s*\n\s*get<GlobalIndexTrends>\("\/global\/index-trends", signal \? \{ signal \} : undefined\)/);
  assert.match(types, /export interface GlobalIndexTrendPoint\s*\{[\s\S]*?time: string;[\s\S]*?price: number;[\s\S]*?change_pct: number;/);
  assert.match(types, /export interface GlobalIndexTrendSeries\s*\{[\s\S]*?previous_close: number;[\s\S]*?points: GlobalIndexTrendPoint\[\];/);
  assert.match(types, /export interface GlobalIndexTrendSeries\s*\{[\s\S]*?source: "tencent" \| "yahoo";[\s\S]*?trade_date: string;[\s\S]*?source_timezone: string;/);
  assert.match(types, /export interface GlobalIndexTrends\s*\{[\s\S]*?series: GlobalIndexTrendSeries\[\];[\s\S]*?missing_keys: string\[\];[\s\S]*?budget_seconds: number;/);
});

test("Daily Review loads real global trend transport and keeps its rows in sync with trend keys", () => {
  assert.match(dailyReview, /api\.globalIndexTrends\(controller\.signal\)/);
  assert.match(dailyReview, /}, 40_000\)/);
  assert.match(dailyReview, /loadGlobalTrends\(\)/);
  assert.match(dailyReview, /const trendKeys = new Set\(globalTrends\?\.series\.map\(\(item\) => item\.key\) \?\? \[\]\)/);
  assert.match(dailyReview, /\.\.\.globalIdx\.filter\(\(item\) => !trendKeys\.has\(item\.key\)\)/);
  assert.match(dailyReview, /<GlobalMarketTrendChart trends=\{globalTrends\} \/>/);
});

test("the chart uses backend points as-is rather than constructing synthetic lines", () => {
  assert.match(chart, /trends\.series\.map\(\(series, seriesIndex\) => \(\{/);
  assert.match(chart, /series\.points\s*\.map\(\(point\) => \(\{ timestamp: toTimestamp\(point\.time\), value: point\.change_pct \}\)\)/);
  assert.match(chart, /path: series\.points\.map/);
  assert.match(chart, /data-testid="global-market-trend-chart"/);
  assert.match(chart, /dateTimeFormatter/);
  assert.match(chart, /allPoints\.length < 2/);
  assert.doesNotMatch(chart, /Math\.(?:sin|cos|random)|sparkline|mock/i);
});

test("trend chart remains accessible and derives its series names from the returned payload", () => {
  assert.match(chart, /role="img"/);
  assert.match(chart, /aria-labelledby="global-market-trend-title global-market-trend-description"/);
  assert.match(chart, /chart\.series\.map\(\(item\) => item\.name\)\.join\("、"\)/);
});
