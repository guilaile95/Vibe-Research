import test from "node:test";
import assert from "node:assert/strict";
import {
  formatCapitalFlowAmount,
  summarizeSectorCapitalFlow,
} from "../src/lib/sectorCapitalFlow.ts";

test("summarizeSectorCapitalFlow sorts rows and calculates rolling totals", () => {
  const rows = [
    { date: "2026-07-28", main_net: -20 },
    { date: "2026-07-30", main_net: 100 },
    { date: "2026-07-29", main_net: 50 },
    { date: "", main_net: 999 },
    { date: "2026-07-27", main_net: Number.NaN },
  ];

  assert.deepEqual(summarizeSectorCapitalFlow(rows), {
    latestDate: "2026-07-30",
    latestMainNet: 100,
    net5d: 130,
    net20d: 130,
    positiveDays20: 2,
    sampleSize5: 3,
    sampleSize20: 3,
  });
});

test("summarizeSectorCapitalFlow limits windows to 5 and 20 valid sessions", () => {
  const rows = Array.from({ length: 25 }, (_, index) => ({
    date: `2026-07-${String(30 - index).padStart(2, "0")}`,
    main_net: index + 1,
  }));

  const summary = summarizeSectorCapitalFlow(rows);
  assert.ok(summary);
  assert.equal(summary.sampleSize5, 5);
  assert.equal(summary.sampleSize20, 20);
  assert.equal(summary.net5d, 15);
  assert.equal(summary.net20d, 210);
  assert.equal(summary.positiveDays20, 20);
});

test("summarizeSectorCapitalFlow returns null without valid rows", () => {
  assert.equal(summarizeSectorCapitalFlow([]), null);
  assert.equal(
    summarizeSectorCapitalFlow([
      { date: null, main_net: 1 },
      { date: "2026-07-30", main_net: null },
    ]),
    null,
  );
});

test("formatCapitalFlowAmount uses compact signed Chinese units", () => {
  assert.equal(formatCapitalFlowAmount(125_000_000), "+1.25亿");
  assert.equal(formatCapitalFlowAmount(-20_000_000), "-2000.0万");
  assert.equal(formatCapitalFlowAmount(25_000), "+2.50万");
  assert.equal(formatCapitalFlowAmount(0), "0");
  assert.equal(formatCapitalFlowAmount(Number.NaN), "—");
});
