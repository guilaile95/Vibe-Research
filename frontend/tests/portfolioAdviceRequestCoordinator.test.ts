import assert from "node:assert/strict";
import test from "node:test";

import {
  PortfolioAdviceRequestCoordinator,
  requirePersistedPortfolioAdvice,
} from "../src/stores/portfolioAdviceRequestCoordinator.ts";

test("restore during generation is ignored without invalidating the running request", () => {
  const coordinator = new PortfolioAdviceRequestCoordinator();
  const generation = coordinator.beginGeneration(false);

  assert.ok(generation);
  assert.equal(coordinator.beginRestore(true), null);
  assert.equal(coordinator.beginGeneration(true), null);
  assert.equal(coordinator.canApplyGeneration(generation), true);
});

test("generation invalidates an older restore response", () => {
  const coordinator = new PortfolioAdviceRequestCoordinator();
  const restore = coordinator.beginRestore(false);
  const generation = coordinator.beginGeneration(false);

  assert.ok(restore);
  assert.ok(generation);
  assert.equal(coordinator.canApplyRestore(restore, false), false);
  assert.equal(coordinator.canApplyGeneration(generation), true);
});

test("generation completion requires the authoritative persisted reread", () => {
  const saved = { payload: { trade_date: "2026-07-23" } };

  assert.equal(requirePersistedPortfolioAdvice(saved), saved);
  assert.throws(
    () => requirePersistedPortfolioAdvice(null),
    /权威结果读取失败/,
  );
});
