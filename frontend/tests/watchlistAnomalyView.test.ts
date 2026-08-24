import assert from "node:assert/strict";
import test from "node:test";

import { filterAndSortWatchlistCodes } from "../src/lib/watchlist.ts";

const codes = ["600519", "000001", "300750"];
const quotes = {
  "600519": { change_pct: 1.2, amount_wan: 20_000 },
  "000001": { change_pct: -4.5, amount_wan: 8_000 },
  "300750": { change_pct: 2.0 },
} as never;
const anomalies = [{ code: "300750" }, { code: "600519" }] as never;

test("filters only actual provider records without mutating authority order", () => {
  assert.deepEqual(
    filterAndSortWatchlistCodes(codes, quotes, anomalies, "watchlist", true),
    ["600519", "300750"],
  );
  assert.deepEqual(codes, ["600519", "000001", "300750"]);
});

test("sorts anomaly, absolute change, and turnover with missing values last", () => {
  assert.deepEqual(
    filterAndSortWatchlistCodes(codes, quotes, anomalies, "anomaly", false),
    ["600519", "300750", "000001"],
  );
  assert.deepEqual(
    filterAndSortWatchlistCodes(codes, quotes, anomalies, "change", false),
    ["000001", "300750", "600519"],
  );
  assert.deepEqual(
    filterAndSortWatchlistCodes(codes, quotes, anomalies, "amount", false),
    ["600519", "000001", "300750"],
  );
});
