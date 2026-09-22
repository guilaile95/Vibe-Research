import assert from "node:assert/strict";
import test from "node:test";

import { formatDiscoveryObservationValue as format } from "../src/lib/discoveryObservation.ts";

test("Discovery historical returns use fractional ratios, including zero and losses", () => {
  for (const code of ["return_5d", "RETURN_20D", "return_60d", "POSITIVE_RETURN_20D", "POSITIVE_RETURN_60D"]) {
    assert.equal(format(code, 0.12), "+12.00%", code);
    assert.equal(format(code, -0.0345), "-3.45%", code);
    assert.equal(format(code, 0), "0.00%", code);
  }
  assert.equal(format("close_vs_ma20", 0.015), "+1.50%");
});

test("Discovery session, sector and turnover values already contain percent units", () => {
  for (const code of [
    "POSITIVE_SESSION_MOMENTUM", "TURNOVER_IN_ACTIVE_MARKET_QUARTILE",
    "SECTOR_CONTEXT_SUPPORTIVE", "SECTOR_SUPPORTIVE", "SECTOR_WEAK", "SECTOR_UNKNOWN",
    "change_pct", "turnover_pct", "average_change_pct",
  ]) {
    assert.equal(format(code, 1.25), "+1.25%", code);
    assert.equal(format(code, -2.5), "-2.50%", code);
    assert.equal(format(code, 0), "0.00%", code);
  }
});

test("Discovery money, prices and volume ratios retain their actual dimensions", () => {
  assert.equal(format("LIQUIDITY_AT_OR_ABOVE_MARKET_MEDIAN", 1_250_000_000), "12.50 亿元");
  assert.equal(format("amount", 0), "0.00 亿元");
  assert.equal(format("float_market_cap", 12_500_000_000), "125.00 亿元");
  assert.equal(format("price", 12.345), "12.35 元");
  assert.equal(format("latest_close", 0), "0.00 元");
  assert.equal(format("volume_ratio", 1.25), "1.25x");
  assert.equal(format("volume_ratio_20d", 0.8), "0.80x");
});

test("Discovery formats backend valuation and financial objects by their parent code", () => {
  assert.deepEqual(format("BASIC_VALUATION_AVAILABLE", { pe_ttm: 18.5, pb: 0 }), {
    pe_ttm: "18.50 倍", pb: "0.00 倍",
  });
  const financials = {
    period: "2026-06-30", revenue_yoy: 12.5, net_profit_yoy: -3.4,
    operating_cash_flow: -250_000_000, roe: 8.75, future_metric: 0.123456,
  };
  assert.deepEqual(format("FUNDAMENTAL_FACT_AVAILABLE", financials), {
    ...financials, revenue_yoy: "+12.50%", net_profit_yoy: "-3.40%",
    operating_cash_flow: "-2.50 亿元", roe: "+8.75%",
  });
  assert.equal(financials.revenue_yoy, 12.5, "formatting must not mutate the API value");
  assert.deepEqual(format("FUNDAMENTAL_FACT_AVAILABLE", { revenue_yoy: "12.5%", roe: "8.75%" }), {
    revenue_yoy: "12.5%", roe: "8.75%",
  });
});

test("Discovery missing and nonfinite observations stay unknown, including nested facts", () => {
  for (const code of ["POSITIVE_RETURN_20D", "POSITIVE_SESSION_MOMENTUM", "amount", "price", "volume_ratio_20d", "UNRECOGNIZED"]) {
    for (const value of [null, undefined, NaN, Infinity, -Infinity]) {
      assert.equal(format(code, value), "未知", `${code}: ${value}`);
    }
  }
  assert.deepEqual(format("BASIC_VALUATION_AVAILABLE", { pe_ttm: null, pb: Infinity }), {
    pe_ttm: "未知", pb: "未知",
  });
  assert.deepEqual(format("FUNDAMENTAL_FACT_AVAILABLE", { roe: NaN, operating_cash_flow: null }), {
    roe: "未知", operating_cash_flow: "未知",
  });
});

test("Discovery unknown codes and nested fields retain raw values without guessing units", () => {
  const value = { return_20d: 0.123456, amount: 125_000_000, price: 12.3456, pe_ttm: 18.5 };
  assert.deepEqual(format("FUTURE_OBSERVATION", value), value);
  for (const code of ["UNKNOWN_RETURN_20D", "SOME_CHANGE_PCT", "NEW_AMOUNT", "FUTURE_RATIO"]) {
    assert.equal(format(code, 0.123456), 0.123456, code);
  }
  assert.deepEqual(format("BASIC_VALUATION_AVAILABLE", { future: { pb: 1.23456 } }), {
    future: { pb: 1.23456 },
  });
  assert.deepEqual(format("FUTURE_OBSERVATION", [0.123456, null, Infinity]), [0.123456, "未知", "未知"]);
  assert.equal(format("RETURN_20D", "0.12"), "0.12", "do not coerce unknown string encodings");
});

test("Discovery catalyst counts and existing status values keep their semantics", () => {
  assert.deepEqual(format("CATALYST_CLUE_AVAILABLE", {
    announcement_count: 2, intel_mentions: null, intel_sources: 0, intel_mapping_status: "MAPPED",
  }), {
    announcement_count: 2, intel_mentions: "未知", intel_sources: 0, intel_mapping_status: "MAPPED",
  });
  assert.equal(format("LIQUIDITY", "AVAILABLE"), "AVAILABLE");
});
