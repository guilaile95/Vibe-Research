import assert from "node:assert/strict";
import test from "node:test";
import type { DailyReviewComparison } from "../src/lib/api/types.ts";
import { marketComparisonCards } from "../src/lib/marketComparisonView.ts";

function comparison(): DailyReviewComparison {
  return {
    market_breadth: {
      up_ratio: { base: 0.4, target: 0.5, delta: 0.1, change_pct: 0.25 },
      total_amount: { base: 1e12, target: 1.1e12, delta: 1e11, change_pct: 0.1 },
    },
  } as DailyReviewComparison;
}

test("legacy numerical deltas cannot masquerade as verified market change", () => {
  const cards = marketComparisonCards(comparison());
  assert.ok(cards.every((card) => card.status === "unverified" && card.value === "暂不判断变化"));
  assert.match(cards[0].issues[0], /尚无行情时点和样本/);
});

test("each metric uses its own evidence and keeps ratio differences in percentage points", () => {
  const input = comparison();
  input.market_comparability = { status: "incomparable", metrics: {
    up_ratio: { status: "comparable", issues: [] },
    total_amount: { status: "incomparable", issues: ["成交额有效样本不同"] },
  } };
  const cards = marketComparisonCards(input);
  assert.equal(cards[0].value, "+10.00 个百分点");
  assert.deepEqual(cards[0].issues, []);
  assert.equal(cards[1].value, "暂不判断变化");
  assert.deepEqual(cards[1].issues, ["成交额有效样本不同"]);
  input.market_comparability.metrics.total_amount = { status: "comparable", issues: [] };
  assert.equal(marketComparisonCards(input)[1].value, "+1000.00 亿元");
});

test("verified zero survives while missing or non-finite values cannot produce a summary", () => {
  const input = comparison();
  input.market_comparability = { status: "comparable", metrics: {
    up_ratio: { status: "comparable", issues: [] }, total_amount: { status: "comparable", issues: [] },
  } };
  input.market_breadth.up_ratio = { base: 0, target: 0, delta: 0, change_pct: null };
  assert.equal(marketComparisonCards(input)[0].value, "0.00 个百分点");
  for (const invalid of [null, Number.NaN, Number.POSITIVE_INFINITY]) {
    input.market_breadth.total_amount.delta = invalid;
    assert.equal(marketComparisonCards(input)[1].status, "unverified");
    assert.equal(marketComparisonCards(input)[1].value, "暂不判断变化");
  }
});
