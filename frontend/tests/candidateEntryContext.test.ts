import assert from "node:assert/strict";
import test from "node:test";
import { candidateEntryContext } from "../src/lib/candidateEntryContext.ts";

function entry(overrides: Record<string, string> = {}) {
  return new URLSearchParams({
    source: "discovery",
    strategy: "SWING",
    return_to: "/screener?mode=discovery&strategy=SWING&sector=%E7%99%BD%E9%85%92&priority=HIGH#discovery-item-SWING-600519",
    ...overrides,
  });
}

test("Discovery navigation validates each strategy and preserves all return filters and hash", () => {
  for (const strategy of ["SHORT", "SWING", "MEDIUM"] as const) {
    const returnTo = `/screener?mode=discovery&strategy=${strategy}&sector=%E7%99%BD%E9%85%92&health=partial#discovery-item-${strategy}-600519`;
    assert.deepEqual(candidateEntryContext(entry({ strategy, return_to: returnTo })), {
      returnTo, discoveryStrategy: strategy,
    });
  }
  assert.deepEqual(candidateEntryContext(entry({ return_to: "/screener#queue" })), {
    returnTo: "/screener#queue", discoveryStrategy: "SWING",
  });
});

test("Discovery labels require a matching market-discovery route, otherwise retain generic safe return", () => {
  for (const returnTo of [
    "/daily-review#research-leads-title",
    "/stock-data?code=600519#facts",
    "/screener-extra?strategy=SWING",
    "/screener?mode=full-market&strategy=SWING",
    "/screener?mode=unknown&strategy=SWING",
    "/screener?mode=discovery&strategy=SHORT",
    "/screener?mode=discovery&strategy=unknown",
    "/screener?mode=discovery&mode=patterns&strategy=SWING",
  ]) {
    assert.deepEqual(candidateEntryContext(entry({ return_to: returnTo })), {
      returnTo, discoveryStrategy: null,
    });
  }
});

test("Unsafe return targets never produce a source link or a Discovery label", () => {
  for (const returnTo of ["", "https://evil.example/screener", "//evil.example/screener", "/\\evil.example/screener"]) {
    assert.deepEqual(candidateEntryContext(entry({ return_to: returnTo })), {
      returnTo: "", discoveryStrategy: null,
    });
  }
});

test("Missing, unknown or ambiguous source parameters do not claim a Discovery strategy", () => {
  for (const changes of [{ source: "today" }, { source: "" }, { strategy: "BUY" }, { strategy: "swing" }, { strategy: "" }]) {
    assert.equal(candidateEntryContext(entry(changes)).discoveryStrategy, null);
  }
  for (const key of ["source", "strategy", "return_to"]) {
    const missing = entry();
    missing.delete(key);
    assert.equal(candidateEntryContext(missing).discoveryStrategy, null);
    const duplicate = entry();
    duplicate.append(key, duplicate.get(key)!);
    assert.equal(candidateEntryContext(duplicate).discoveryStrategy, null);
  }
});

test("Untrusted ratings, reasons and campaign hints never become research context", () => {
  const original = entry();
  const claimed = entry({ rating: "BUY", reason: "verified_fact", campaign_id: "fake_campaign", priority: "HIGH" });
  assert.deepEqual(candidateEntryContext(claimed), candidateEntryContext(original));
});
