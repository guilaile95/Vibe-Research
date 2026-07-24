import assert from "node:assert/strict";
import test from "node:test";

import {
  checkWorkspace,
  registeredResearchKeys,
  resolveOrFallback,
} from "../src/data/sectorResearch/invariants.ts";
import { getSectorResearchWorkspace } from "../src/data/sectorResearch/index.ts";

const BATCH1_KEYS = ["humanoid", "ai-computing", "hbm", "cpo"] as const;

test("Batch 1 workspaces are all registered and satisfy invariants", () => {
  const registered = registeredResearchKeys();
  for (const key of BATCH1_KEYS) {
    assert.ok(registered.includes(key), `workspace ${key} should be registered`);
    const ws = getSectorResearchWorkspace(key);
    assert.ok(ws, `workspace ${key} should exist`);
    assert.equal(ws.key, key);
    assert.equal(ws.tags.length, 6, `workspace ${key} should have 6 tags`);

    const checkRes = checkWorkspace(ws);
    assert.equal(checkRes.ok, true, `checkWorkspace for ${key} failed: ${checkRes.errors.join("; ")}`);
  }
});

test("Batch 1 workspaces source integrity and usage", () => {
  for (const key of BATCH1_KEYS) {
    const ws = getSectorResearchWorkspace(key)!;
    const sourceIds = new Set(ws.sources.map((s) => s.id));
    assert.equal(sourceIds.size, ws.sources.length, `workspace ${key} has duplicate source ids`);

    const usedSourceIds = new Set<string>();

    for (const tag of ws.tags) {
      assert.ok(tag.slug && tag.label && tag.title, `tag incomplete in ${key}`);
      assert.ok(tag.blocks.length >= 3, `tag ${tag.slug} in ${key} must have at least 3 blocks`);

      for (const block of tag.blocks) {
        if (block.type === "placeholder") continue;
        const ids = block.sourceIds ?? [];
        assert.equal(new Set(ids).size, ids.length, `tag ${tag.slug} has duplicate sourceIds`);

        for (const id of ids) {
          assert.ok(sourceIds.has(id), `tag ${tag.slug} in ${key} uses unknown sourceId "${id}"`);
          usedSourceIds.add(id);
        }

        if (block.type === "table" || block.type === "compareTable") {
          assert.ok(block.headers.length > 0, `table in ${tag.slug} has empty headers`);
          assert.ok(block.rows.length > 0, `table in ${tag.slug} has empty rows`);
          for (const row of block.rows) {
            assert.equal(row.length, block.headers.length, `table row length mismatch in ${tag.slug}`);
          }
        }
      }
    }

    // Check that all sources in sources.ts are referenced
    for (const s of ws.sources) {
      assert.ok(usedSourceIds.has(s.id), `workspace ${key} source "${s.id}" is orphaned (never referenced)`);
      assert.ok(s.url && s.url.startsWith("http"), `source ${s.id} missing valid http/https url`);
      assert.ok(s.accessedAt, `source ${s.id} missing accessedAt`);
      assert.ok(s.supports, `source ${s.id} missing supports`);
    }
  }
});

test("Batch 1 workspace required content components", () => {
  for (const key of BATCH1_KEYS) {
    const ws = getSectorResearchWorkspace(key)!;
    let hasTable = false;
    let hasCompareTable = false;
    let hasRisk = false;
    let hasFalsification = false;
    let hasPendingVerification = false;

    for (const tag of ws.tags) {
      for (const block of tag.blocks) {
        if (block.type === "table") hasTable = true;
        if (block.type === "compareTable") hasCompareTable = true;
        if (block.type === "risk") hasRisk = true;
        if (block.type === "callout" && block.tone === "warning") hasFalsification = true;
        if (block.type === "callout" && block.tone === "info") hasPendingVerification = true;
      }
    }

    assert.ok(hasTable, `workspace ${key} missing table`);
    assert.ok(hasCompareTable, `workspace ${key} missing compareTable`);
    assert.ok(hasRisk, `workspace ${key} missing risk list`);
    assert.ok(hasFalsification, `workspace ${key} missing falsification callout`);
    assert.ok(hasPendingVerification, `workspace ${key} missing pending verification callout`);
  }
});

test("Unregistered sectors display placeholder without workspace", () => {
  assert.equal(getSectorResearchWorkspace("semiconductor"), undefined);
  assert.equal(resolveOrFallback("semiconductor", "overview"), null);
});

test("Batch 1 source metadata formats", () => {
  for (const key of BATCH1_KEYS) {
    const ws = getSectorResearchWorkspace(key)!;
    for (const s of ws.sources) {
      // accessedAt must be valid ISO date
      assert.ok(s.accessedAt && !isNaN(Date.parse(s.accessedAt)), `${key} source "${s.id}" missing valid accessedAt`);
      // publishedAt if present must be valid
      if (s.publishedAt) assert.ok(!isNaN(Date.parse(s.publishedAt)), `${key} source "${s.id}" invalid publishedAt`);
      // supports must be non-empty string or array
      const supp = typeof s.supports === "string" ? [s.supports] : s.supports;
      assert.ok(Array.isArray(supp) && supp.length > 0 && supp.every((x) => typeof x === "string" && x.trim().length > 0), `${key} source "${s.id}" missing supports`);
      // URL must be http/https
      assert.ok(/^https?:\/\//.test(s.url), `${key} source "${s.id}" URL not http/https: ${s.url}`);
      // Forbidden domains
      assert.equal(s.url.includes("onboardoptics.org"), false, `${key} source "${s.id}" uses forbidden domain`);
    }
  }
});


test("Batch 1 block type diversity: each tag has at least 3 different non-placeholder block types", () => {
  for (const key of BATCH1_KEYS) {
    const ws = getSectorResearchWorkspace(key)!;
    const typeNames = new Set(["paragraph", "bullets", "table", "compareTable", "callout", "risk", "fact"]);
    for (const tag of ws.tags) {
      const blockTypes = new Set(tag.blocks.filter((b) => b.type !== "placeholder").map((b) => b.type));
      const relevant = [...blockTypes].filter((t) => typeNames.has(t)).length;
      const typesStr = [...blockTypes].join(", ");
      assert.ok(relevant >= 3, `${key} tag "${tag.slug}" has only ${relevant} diverse block types (types: ${typesStr})`);
    }
  }
});

test("Batch 1 content block sourceId requirements", () => {
  const internalKeywords = ["内部分析", "分析推断", "行业预测", "待验证", "in-house analysis", "industry estimate", "pending verification", "analysis inference"];
  const forbiddenKeywords = ["JEDEC", "OIF", "JESD", "IEEE", "IPC", "SEMI", "ISO"];
  for (const key of BATCH1_KEYS) {
    const ws = getSectorResearchWorkspace(key)!;
    for (const tag of ws.tags) {
      for (const block of tag.blocks) {
        if (block.type === "placeholder") continue;
        const hasEmptySourceIds = !block.sourceIds || block.sourceIds.length === 0;
        if (hasEmptySourceIds) {
          const blockText = JSON.stringify(block);
          const hasInternalMarker = internalKeywords.some((kw) => blockText.includes(kw));
          if (!hasInternalMarker) {
            const header = `${key} tag "${tag.slug}" ${block.type} has empty sourceIds without internal analysis marker`;
            const titles = block.type === "table" || block.type === "compareTable" ? (block.caption || "") : (block.text || "");
            assert.ok(titles.length > 0, `${header}: ${JSON.stringify(block).slice(0, 80)}`);
          }
          for (const fw of forbiddenKeywords) {
            if (blockText.includes(fw)) {
              assert.fail(`${key} tag "${tag.slug}" references "${fw}" without source`);
            }
          }
        }
      }
    }
  }
});

test("Batch 1 table/compareTable row consistency", () => {
  for (const key of BATCH1_KEYS) {
    const ws = getSectorResearchWorkspace(key)!;
    for (const tag of ws.tags) {
      for (const block of tag.blocks) {
        if (block.type === "table" || block.type === "compareTable") {
          for (const row of block.rows) {
            assert.equal(row.length, block.headers.length, `${key} ${tag.slug} ${block.type} row length mismatch`);
          }
        }
      }
    }
  }
});
