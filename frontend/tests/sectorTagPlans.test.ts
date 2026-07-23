import assert from "node:assert/strict";
import test from "node:test";

import {
  getSectorTagCount,
  getSectorTagPlan,
  SECTOR_TAG_PLANS,
} from "../src/data/sectorResearch/sectorTagPlans.ts";

const EXPECTED_KEYS = [
  "humanoid", "ai-computing", "pcb", "hbm", "cpo", "semiconductor",
  "solid-state-battery", "low-altitude", "smart-driving", "innovative-drug",
  "power-grid", "defense", "fusion", "business-space", "ai-pharma",
  "resources", "ai-application", "ai-hardware", "energy-storage", "data-element",
];

test("all 20 sectors are registered with exactly 6 tags each", () => {
  assert.equal(Object.keys(SECTOR_TAG_PLANS).length, 20);
  for (const key of EXPECTED_KEYS) {
    const plan = getSectorTagPlan(key);
    assert.ok(plan, `missing tag plan for "${key}"`);
    assert.equal(plan!.length, 6, `"${key}" should have 6 tags`);
  }
});

test("getSectorTagCount returns 6 for registered, 0 for unknown", () => {
  assert.equal(getSectorTagCount("pcb"), 6);
  assert.equal(getSectorTagCount("ai-computing"), 6);
  assert.equal(getSectorTagCount("not-a-sector"), 0);
  assert.equal(getSectorTagPlan("not-a-sector"), undefined);
});

test("PCB tag slugs and labels match the research workspace", () => {
  const plan = getSectorTagPlan("pcb")!;
  const slugs = plan.map((t) => t.slug);
  assert.deepEqual(slugs, [
    "overview", "technology", "value", "copper-midplane", "industry", "pricing-power",
  ]);
  assert.deepEqual(plan.map((t) => t.label), [
    "总览", "原理与技术路线", "价值量", "铜中板", "产业格局", "定价权地图",
  ]);
});

test("every tag slug is unique within its sector", () => {
  for (const [key, plan] of Object.entries(SECTOR_TAG_PLANS)) {
    const slugs = plan.map((t) => t.slug);
    assert.equal(new Set(slugs).size, slugs.length, `"${key}" has duplicate slugs`);
  }
});

test("overview slug is present for every sector", () => {
  for (const [key, plan] of Object.entries(SECTOR_TAG_PLANS)) {
    assert.ok(plan.some((t) => t.slug === "overview"), `"${key}" missing overview tag`);
  }
});
