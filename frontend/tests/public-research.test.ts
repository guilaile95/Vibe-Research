import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { parsePublicResearch, type PublicSource } from "../src/lib/publicResearch.ts";
const golden = JSON.parse(readFileSync(new URL("./fixtures/public-research.golden.json", import.meta.url), "utf8"));
const oldNow = Date.now;
Date.now = () => Date.parse("2026-10-12T23:00:00Z");
test.after(() => { Date.now = oldNow; });
test("every fixed provider golden validates without changing market identity", () => {
  for (const source of Object.keys(golden) as PublicSource[]) assert.deepEqual(parsePublicResearch(golden[source], source), golden[source]);
});
for (const mutation of [
  (x: any) => { x.source_id = "public_kalshi"; },
  (x: any) => { x.blocks[0].subject = "ashby:private"; },
  (x: any) => { x.blocks[0].rows[0].listings = [null]; },
  (x: any) => { x.blocks[0].rows[0].listings[0].source_time = "2026-02-30T00:00:00Z"; },
  (x: any) => { x.blocks[0].rows[0].listing_count = 4; },
  (x: any) => { x.blocks[0].rows[0].ats = {}; },
  (x: any) => { x.blocks[0].evidence.locally_received_at = "2026-10-01T00:00:00+08:60"; },
  (x: any) => { x.blocks[0].captured_at = "2026-10-12T12:00:00.000001Z"; },
  (x: any) => { x.blocks[0].source_url = "file:///private"; },
  (x: any) => { x.selection_mode = "LIVE"; },
  (x: any) => { x.ingestion_enabled = true; },
]) test("malformed receipt fails closed " + mutation.toString(), () => {
  const value = structuredClone(golden.hiring_anchor_signal); mutation(value);
  assert.throws(() => parsePublicResearch(value, "hiring_anchor_signal"));
});
for (const [source, key, bad] of [
  ["tw_monthly_revenue", "yoy_pct", 20], ["tw_monthly_revenue", "currency", "USD"], ["tw_monthly_revenue", "issuer", "9999"],
  ["dram_spot_thermo", "is_hbm_price", true], ["dram_spot_thermo", "unit", "USD per HBM stack"],
  ["cn_commodity_futures", "change_pct", 5], ["cn_commodity_futures", "delivery_month", "2026-12"],
  ["cn_commodity_futures", "exchange", "LME"], ["cn_commodity_futures", "roll_adjustment", "verified"],
  ["hiring_anchor_signal", "fulfilled_hires", 100], ["hiring_anchor_signal", "board", "other"],
  ["public_kalshi", "bid", .99], ["public_kalshi", "value", 42], ["public_polymarket", "value", -.5],
  ["public_polymarket", "source_date", "0000-01-01"],
] as const) test(`qualification cannot become certified data: ${source} ${key}`, () => {
  const value = structuredClone(golden[source]); value.blocks[0].rows[0][key] = bad;
  assert.throws(() => parsePublicResearch(value, source));
});

test("aggregate response traversal budget fails before exponential nested arrays", () => {
  const value = structuredClone(golden.public_kalshi);
  value.extra = Array.from({ length: 100 }, () => Array.from({ length: 3000 }, () => 0));
  assert.throws(() => parsePublicResearch(value, "public_kalshi"));
});
test("open zero book stays unknown, positive one-sided and closed quotes retain convention", () => {
  const value = structuredClone(golden.public_kalshi), row = value.blocks[0].rows[0];
  Object.assign(row, { bid: 0, ask: 0, value: null, price_convention: "unquoted", missing: ["AMBIGUOUS_OR_MISSING_BOOK"] });
  assert.doesNotThrow(() => parsePublicResearch(value, "public_kalshi"));
  Object.assign(row, { value: 0, price_convention: "yes_bid_ask_midpoint_dollars" });
  assert.throws(() => parsePublicResearch(value, "public_kalshi"));
  Object.assign(row, { market_status: "closed", status: "closed" });
  assert.doesNotThrow(() => parsePublicResearch(value, "public_kalshi"));
  Object.assign(row, { market_status: "open", ask: .4, value: .2 });
  assert.doesNotThrow(() => parsePublicResearch(value, "public_kalshi"));
  Object.assign(row, { bid: null, value: .3, price_convention: "yes_last_trade_dollars" });
  assert.doesNotThrow(() => parsePublicResearch(value, "public_kalshi"));
});
