import assert from "node:assert/strict";
import test from "node:test";

import { buildDecisionPriorities, isExplicitAction } from "../src/lib/decisionPriority.ts";
import type { TodayActions } from "../src/lib/decisionCockpit.ts";

const base: TodayActions = {
  trade_date: "2026-08-08",
  as_of: "2026-08-08T09:30:00+08:00",
  plan: null,
  plan_note: null,
  warnings: [],
  holdings: [],
  watchlist_movers: [],
};

test("passive actions do not become priorities", () => {
  for (const value of [null, "", "HOLD", "watch", "持有", "观察"]) {
    assert.equal(isExplicitAction(value), false);
  }
  assert.equal(isExplicitAction("REDUCE"), true);
  assert.equal(isExplicitAction("加仓"), true);
});

test("priority order is explicit holding action, holding flag, watchlist flag", () => {
  const data: TodayActions = {
    ...base,
    holdings: [
      { code: "000001", name: "A", shares: 1, price: 10, advice_action: "HOLD", advice_qty: null, plan_signals_summary: null, flags: ["风险标记"], change_pct: 1, pnl_pct: 2 },
      { code: "600519", name: "B", shares: 1, price: 10, advice_action: "REDUCE", advice_qty: 100, plan_signals_summary: "趋势弱", flags: [], change_pct: -2, pnl_pct: 3 },
    ],
    watchlist_movers: [
      { code: "000002", name: "C", price: 9, change_pct: 6, flag: "异动" },
    ],
  };
  const out = buildDecisionPriorities(data);
  assert.deepEqual(out.map((item) => item.kind), ["holding-action", "holding-flag", "watchlist-flag"]);
  assert.equal(out[0].code, "600519");
});

test("items without explicit action or flags are omitted", () => {
  const data: TodayActions = {
    ...base,
    holdings: [
      { code: "000001", name: "A", shares: 1, price: 10, advice_action: "HOLD", advice_qty: null, plan_signals_summary: "strong", flags: [] },
    ],
    watchlist_movers: [
      { code: "000002", name: "C", price: 9, change_pct: 1, flag: null },
    ],
  };
  assert.deepEqual(buildDecisionPriorities(data), []);
});
