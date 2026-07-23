import assert from "node:assert/strict";
import test from "node:test";

import {
  checkWorkspace,
  expectedPcbTagLabels,
  expectedPcbTagSlugs,
  pcbConfigSnapshot,
  registeredResearchKeys,
  resolveOrFallback,
} from "../src/data/sectorResearch/invariants.ts";
import { pcbResearch } from "../src/data/sectorResearch/pcb.ts";
import { getSectorResearchWorkspace } from "../src/data/sectorResearch/index.ts";

test("PCB workspace is registered and only PCB is registered for now", () => {
  assert.deepEqual(registeredResearchKeys(), ["pcb"]);
  assert.ok(getSectorResearchWorkspace("pcb"));
  assert.equal(getSectorResearchWorkspace("hbm"), undefined);
  assert.equal(getSectorResearchWorkspace("ai-computing"), undefined);
});

test("PCB has exactly six tags with stable slugs and labels in order", () => {
  const snap = pcbConfigSnapshot();
  assert.equal(snap.key, "pcb");
  assert.equal(snap.defaultTag, "overview");
  assert.equal(snap.tagCount, 6);
  assert.deepEqual(snap.slugs, expectedPcbTagSlugs());
  assert.deepEqual(snap.labels, expectedPcbTagLabels());
  assert.equal(snap.allPlaceholder, true);
});

test("PCB tag slugs are unique", () => {
  const slugs = pcbResearch.tags.map((t) => t.slug);
  assert.equal(new Set(slugs).size, slugs.length);
});

test("checkWorkspace accepts PCB config", () => {
  const r = checkWorkspace(pcbResearch);
  assert.equal(r.ok, true, r.errors.join("; "));
});

test("resolveOrFallback uses default for missing or illegal tag", () => {
  assert.deepEqual(resolveOrFallback("pcb", undefined), {
    workspaceKey: "pcb",
    tagSlug: "overview",
    redirected: true,
  });
  assert.deepEqual(resolveOrFallback("pcb", "not-a-real-tag"), {
    workspaceKey: "pcb",
    tagSlug: "overview",
    redirected: true,
  });
  assert.deepEqual(resolveOrFallback("pcb", "copper-midplane"), {
    workspaceKey: "pcb",
    tagSlug: "copper-midplane",
    redirected: false,
  });
  assert.equal(resolveOrFallback("hbm", "overview"), null);
});
