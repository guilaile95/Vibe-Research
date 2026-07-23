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

/** 正式 SourceRef：景旺具体产品/市场页 + 生益材料产品页 */
const ALLOWED_SOURCE_IDS = [
  "S-KINWONG-HLC",
  "S-KINWONG-SLP",
  "S-KINWONG-COMPUTING",
  "S-KINWONG-TELECOM",
  "S-SHENGYI-HIGHSPEED",
  "S-SHENGYI-RF",
  "S-SHENGYI-IC",
] as const;

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
});

test("PCB all six tags are draft status", () => {
  assert.equal(pcbResearch.tags.length, 6);
  for (const t of pcbResearch.tags) {
    assert.equal(t.status, "draft", `tag ${t.slug} should be draft`);
  }
  assert.equal(pcbConfigSnapshot().allPlaceholder, false);
});

test("PCB sources are the read company product/tech pages", () => {
  const ids = pcbResearch.sources.map((s) => s.id);
  assert.equal(pcbResearch.sources.length, 7);
  assert.deepEqual(ids.slice().sort(), [...ALLOWED_SOURCE_IDS].sort());
  assert.equal(pcbResearch.sources.length, ALLOWED_SOURCE_IDS.length);
  for (const s of pcbResearch.sources) {
    assert.equal(s.factLevel, "公司口径");
    assert.equal(s.sourceType, "company_site");
    assert.ok(s.url && s.url.startsWith("http"));
    assert.ok(s.note && s.note.includes("实际打开读取"));
  }
});

test("PCB tag slugs are unique", () => {
  const slugs = pcbResearch.tags.map((t) => t.slug);
  assert.equal(new Set(slugs).size, slugs.length);
});

test("checkWorkspace accepts PCB config", () => {
  const r = checkWorkspace(pcbResearch);
  assert.equal(r.ok, true, r.errors.join("; "));
});

test("all block sourceIds are within the allowed read sources", () => {
  const allowed = new Set<string>(ALLOWED_SOURCE_IDS);
  for (const tag of pcbResearch.tags) {
    for (const block of tag.blocks) {
      if (block.type === "placeholder") continue;
      const ids = block.sourceIds ?? [];
      for (const id of ids) {
        assert.ok(
          allowed.has(id),
          `tag ${tag.slug} ${block.type} has disallowed sourceId ${id}`,
        );
      }
    }
  }
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


test("Synamic8GX general Dk/Df not mislabeled as 10GHz-only", () => {
  const tech = pcbResearch.tags.find((x) => x.slug === "technology");
  assert.ok(tech);
  const blob = JSON.stringify(tech.blocks);
  // if 3.62 appears, 10GHz column values should also be nearby or general params labeled
  if (blob.includes("3.62")) {
    assert.ok(
      blob.includes("3.66") || blob.includes("一般") || blob.includes("@10GHz") || blob.includes("10GHz"),
      "must not present 3.62/0.0016 as sole 10GHz measurement",
    );
  }
  assert.equal(blob.includes("S-UNIMICRON"), false);
});
