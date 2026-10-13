import assert from "node:assert/strict";
import test from "node:test";

import {
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

test("preserves numeric zero facts through the product state", () => {
  for (const value of [0, "0", "0亿"]) {
    const fin = { revenue: value, net_profit: value, data_quality: { status: "normal" } } as never;
    assert.equal(fundamentalHealthState(fin, null), "normal");
    assert.equal(fundamentalHealthState({ ...fin, data_quality: { status: "partial" } } as never, null), "partial");
  }
  assert.equal(fundamentalHealthState({ revenue: 0, net_profit: null, data_quality: { status: "partial" } } as never, null), "partial");
});

test("absent or non-finite observations remain empty while finite negatives are present", () => {
  for (const value of [null, undefined, "", "  ", false, true, NaN, Infinity]) {
    assert.equal(fundamentalHealthState({ revenue: value, net_profit: value } as never, null), "empty");
  }
  assert.equal(fundamentalHealthState({ revenue: -1, net_profit: -2, data_quality: { status: "normal" } } as never, null), "normal");
});
