import assert from "node:assert/strict";
import test from "node:test";

import {
  PORTFOLIO_ADVICE_DEFAULT_API_MS,
  PORTFOLIO_ADVICE_DEFAULT_CLI_MS,
  PORTFOLIO_ADVICE_DURATION_MAX_SAMPLES,
  PORTFOLIO_ADVICE_MAX_ESTIMATE_MS,
  PORTFOLIO_ADVICE_MIN_ESTIMATE_MS,
  clamp,
  getEstimatedPortfolioAdviceDuration,
  getPortfolioAdviceProviderKey,
  isAbortError,
  loadPortfolioAdviceDurationSamples,
  median,
  recordSuccessfulPortfolioAdviceDuration,
} from "../src/lib/portfolioAdviceDuration.ts";

function memoryStorage(seed: Record<string, string> = {}): Storage {
  const map = new Map<string, string>(Object.entries(seed));
  return {
    get length() {
      return map.size;
    },
    clear() {
      map.clear();
    },
    getItem(key: string) {
      return map.has(key) ? map.get(key)! : null;
    },
    key(index: number) {
      return [...map.keys()][index] ?? null;
    },
    removeItem(key: string) {
      map.delete(key);
    },
    setItem(key: string, value: string) {
      map.set(key, String(value));
    },
  };
}

test("median and clamp helpers", () => {
  assert.equal(median([10, 30, 20]), 20);
  assert.equal(median([10, 20]), 15);
  assert.equal(clamp(10, 30, 100), 30);
  assert.equal(clamp(200, 30, 100), 100);
});

test("provider key and default estimates", () => {
  assert.equal(
    getPortfolioAdviceProviderKey({ provider: "openai", model: "gpt-4o" }),
    "openai:gpt-4o",
  );
  assert.equal(
    getEstimatedPortfolioAdviceDuration({ provider: "openai", model: "gpt-4o" }, memoryStorage()),
    PORTFOLIO_ADVICE_DEFAULT_API_MS,
  );
  assert.equal(
    getEstimatedPortfolioAdviceDuration({ provider: "cli-claude", model: "opus" }, memoryStorage()),
    PORTFOLIO_ADVICE_DEFAULT_CLI_MS,
  );
});

test("records successful durations and uses median within bounds", () => {
  const storage = memoryStorage();
  const llm = { provider: "openai", model: "gpt-4o" };

  recordSuccessfulPortfolioAdviceDuration(llm, 40_000, storage);
  recordSuccessfulPortfolioAdviceDuration(llm, 50_000, storage);
  recordSuccessfulPortfolioAdviceDuration(llm, 60_000, storage);

  assert.equal(getEstimatedPortfolioAdviceDuration(llm, storage), 50_000);

  // Outliers clamp to min/max.
  recordSuccessfulPortfolioAdviceDuration(llm, 5_000, storage);
  const samples = loadPortfolioAdviceDurationSamples(storage);
  assert.equal(samples["openai:gpt-4o"].length, 4);
  // median of [40000,50000,60000,5000] => [5000,40000,50000,60000] => 45000
  assert.equal(getEstimatedPortfolioAdviceDuration(llm, storage), 45_000);

  for (let i = 0; i < 10; i++) {
    recordSuccessfulPortfolioAdviceDuration(llm, 1_000_000, storage);
  }
  const afterCap = loadPortfolioAdviceDurationSamples(storage)["openai:gpt-4o"];
  assert.equal(afterCap.length, PORTFOLIO_ADVICE_DURATION_MAX_SAMPLES);
  assert.equal(
    getEstimatedPortfolioAdviceDuration(llm, storage),
    PORTFOLIO_ADVICE_MAX_ESTIMATE_MS,
  );

  // Very small samples clamp to min.
  const tiny = memoryStorage();
  recordSuccessfulPortfolioAdviceDuration(llm, 1_000, tiny);
  assert.equal(
    getEstimatedPortfolioAdviceDuration(llm, tiny),
    PORTFOLIO_ADVICE_MIN_ESTIMATE_MS,
  );
});

test("isAbortError recognizes AbortError shape", () => {
  assert.equal(isAbortError(new DOMException("aborted", "AbortError")), true);
  assert.equal(isAbortError(Object.assign(new Error("aborted"), { name: "AbortError" })), true);
  assert.equal(isAbortError(new Error("boom")), false);
  assert.equal(isAbortError(null), false);
});
