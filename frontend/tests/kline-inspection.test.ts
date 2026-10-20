import assert from "node:assert/strict";
import { test } from "node:test";
import { readFileSync } from "node:fs";
import { moveInspectionDate, formatInspectionVolume, inspectionContextKey } from "../src/lib/klineInspection.ts";
import { normalizeKlineIndicatorOverlay } from "../src/lib/klineIndicatorOverlay.ts";
const dates = ["2026-10-01", "2026-10-05", "2026-10-06"];
test("keyboard navigation clamps, starts predictably, and never invents a missing date", () => {
  assert.equal(moveInspectionDate(dates, null, "ArrowRight"), dates[0]);
  assert.equal(moveInspectionDate(dates, null, "ArrowLeft"), dates[2]);
  assert.equal(moveInspectionDate(dates, dates[1], "Home"), dates[0]);
  assert.equal(moveInspectionDate(dates, dates[1], "End"), dates[2]);
  let selected: string | null = dates[0];
  for (let i = 0; i < 100; i++) selected = moveInspectionDate(dates, selected, "ArrowRight");
  assert.equal(selected, dates[2]);
  for (let i = 0; i < 100; i++) selected = moveInspectionDate(dates, selected, "ArrowLeft");
  assert.equal(selected, dates[0]);
  assert.equal(moveInspectionDate(dates, "2026-10-03", "Tab"), "2026-10-03");
  assert.equal(moveInspectionDate([], null, "Home"), null);
});
test("identity separates subjects, periods, corrected data and volume", () => {
  const points = [{ date: dates[0], close: 10, volume: 1 }];
  const key = inspectionContextKey("000001", "day", points);
  assert.equal(key, inspectionContextKey("000001", "day", structuredClone(points)));
  assert.notEqual(key, inspectionContextKey("000002", "day", points));
  assert.notEqual(key, inspectionContextKey("000001", "week", points));
  assert.notEqual(key, inspectionContextKey("000001", "day", [{ ...points[0], volume: 2 }]));
  assert.notEqual(key, inspectionContextKey("000001", "day", [{ ...points[0], close: 11 }]));
});
test("volume uses exact raw values with no invented units, rejects negatives and nonfinite", () => {
  for (const value of [null, undefined, NaN, Infinity, -1, "100", true]) assert.equal(formatInspectionVolume(value), "未知 / 无效");
  assert.equal(formatInspectionVolume(0), "0");
  assert.equal(formatInspectionVolume(123456789012345), "123456789012345");
});
test("window is sixty valid bars and volume follows first valid OHLC source", () => {
  const bars = Array.from({ length: 75 }, (_, i) => ({date: new Date(Date.UTC(2026, 0, i + 1)).toISOString().slice(0, 10), open: 10, high: 12, low: 9, close: 11, volume: i}));
  const points = normalizeKlineIndicatorOverlay(bars, null, 60);
  assert.equal(points.length, 60);
  assert.equal(points[0].date, bars[15].date);
  assert.equal(points[0].volume, 15);
  assert.equal(normalizeKlineIndicatorOverlay([{...bars[0], open: -1}, {...bars[0], volume: -1}], null)[0].volume, null);
  assert.equal(normalizeKlineIndicatorOverlay([], null).length, 0);
});
test("component wiring preserves focus, exact-date linkage and late-request guards", () => {
  const chart = readFileSync(new URL("../src/components/ui/KlineChart.tsx", import.meta.url), "utf8");
  const research = readFileSync(new URL("../src/components/ui/ResearchKlineChart.tsx", import.meta.url), "utf8");
  assert.match(chart, /onKeyDown/);
  assert.match(chart, /event.preventDefault\(\)/);
  assert.match(chart, /overflow-x-auto/);
  assert.match(chart, /<caption/);
  assert.match(chart, /scope="row"/);
  assert.match(research, /inspectionContextKey\(code, barPeriod, points\)/);
  assert.match(research, /barPeriod !== "day"/);
  assert.match(research, /active = false; controller.abort\(\)/);
  assert.match(research, /onSelect\(event.date!\)/);
});
