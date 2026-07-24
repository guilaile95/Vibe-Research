import assert from "node:assert/strict";
import test from "node:test";

import {
  checkWorkspace,
  registeredResearchKeys,
  resolveOrFallback,
} from "../src/data/sectorResearch/invariants.ts";
import { getSectorResearchWorkspace } from "../src/data/sectorResearch/index.ts";

const BATCH2_KEYS = ["semiconductor", "smart-driving", "solid-state-battery", "low-altitude"] as const;

const VERIFIED_ANNOUNCEMENTS: Record<string, Array<{ id: string; stock: string; aid: string; name: string }>> = {
  "semiconductor": [
    { id: "S-SEMI-NAURA-FILING", stock: "002371", aid: "1219908921", name: "\u5317\u65b9\u534e\u521b" },
    { id: "S-SEMI-AMEC-FILING", stock: "688012", aid: "1219329946", name: "\u4e2d\u5fae\u516c\u53f8" },
    { id: "S-SEMI-ANJI-FILING", stock: "688019", aid: "1219623534", name: "\u5b89\u96c6\u79d1\u6280" },
    { id: "S-SEMI-SMIC-FILING", stock: "688981", aid: "1219447098", name: "\u4e2d\u82af\u56fd\u9645" },
  ],
  "smart-driving": [
    { id: "S-DRIVE-DESAY-FILING", stock: "002920", aid: "1219428492", name: "\u5fb7\u8d5b\u897f\u5a01" },
    { id: "S-DRIVE-JINGWEI-FILING", stock: "688326", aid: "1219885867", name: "\u7ecf\u7eac\u6052\u6da6" },
    { id: "S-DRIVE-THUNDERSOFT-FILING", stock: "300496", aid: "1219425324", name: "\u4e2d\u79d1\u521b\u8fbe" },
    { id: "S-DRIVE-BTL-FILING", stock: "603596", aid: "1219430299", name: "\u4f2f\u7279\u5229" },
    { id: "S-DRIVE-ASIA-FILING", stock: "002284", aid: "1219646787", name: "\u4e9a\u592a\u80a1\u4efd" },
    { id: "S-DRIVE-LIANCHUANG-FILING", stock: "002036", aid: "1219915025", name: "\u8054\u521b\u7535\u5b50" },
    { id: "S-DRIVE-HUAYU-FILING", stock: "600741", aid: "1219441581", name: "\u534e\u57df\u6c7d\u8f66" },
  ],
  "solid-state-battery": [
    { id: "S-SSBAT-CATL-FILING", stock: "300750", aid: "1219313047", name: "\u5b81\u5fb7\u65f6\u4ee3" },
    { id: "S-SSBAT-EASPRING-FILING", stock: "300073", aid: "1219468325", name: "\u5f53\u5347\u79d1\u6280" },
    { id: "S-SSBAT-TINCI-FILING", stock: "002709", aid: "1219402767", name: "\u5929\u8d50\u6750\u6599" },
    { id: "S-SSBAT-CAPCHEM-FILING", stock: "300037", aid: "1219493150", name: "\u65b0\u5b99\u90a6" },
    { id: "S-SSBAT-GOTION-FILING", stock: "002074", aid: "1219700973", name: "\u56fd\u8f69\u9ad8\u79d1" },
    { id: "S-SSBAT-GANFENG-FILING", stock: "002460", aid: "1219453182", name: "\u8d63\u950b\u9502\u4e1a" },
    { id: "S-SSBAT-LEAD-FILING", stock: "300450", aid: "1219803635", name: "\u5148\u5bfc\u667a\u80fd" },
  ],
  "low-altitude": [
    { id: "S-LOWALT-AVICHIGHTECH-FILING", stock: "600038", aid: "1219314145", name: "\u4e2d\u76f4\u80a1\u4efd" },
    { id: "S-LOWALT-WANFENG-FILING", stock: "002085", aid: "1219800529", name: "\u4e07\u4e30\u5965\u5a01" },
    { id: "S-LOWALT-CITIC-FILING", stock: "000099", aid: "1219328401", name: "\u4e2d\u4fe1\u6d77\u76f4" },
    { id: "S-LOWALT-ZONGHENG-FILING", stock: "688070", aid: "1219883396", name: "\u7eb5\u6a2a\u80a1\u4efd" },
    { id: "S-LOWALT-LAISI-FILING", stock: "688631", aid: "1219798232", name: "\u83b1\u65af\u4fe1\u606f" },
    { id: "S-LOWALT-SHENCHENGJIAO-FILING", stock: "301091", aid: "1219673881", name: "\u6df1\u57ce\u4ea4" },
    { id: "S-LOWALT-ZHONGZHI-FILING", stock: "600862", aid: "1219312183", name: "\u4e2d\u822a\u9ad8\u79d1" },
  ],
};

test("Batch 2 workspaces are all registered and satisfy invariants", () => {
  const registered = registeredResearchKeys();
  for (const key of BATCH2_KEYS) {
    assert.ok(registered.includes(key), `workspace ${key} should be registered`);
    const ws = getSectorResearchWorkspace(key);
    assert.ok(ws, `workspace ${key} should exist`);
    assert.equal(ws.key, key);
    assert.equal(ws.tags.length, 6, `workspace ${key} should have 6 tags`);
    assert.equal(ws.tags[0].slug, ws.defaultTag, `${key} defaultTag should be first slug`);
    const checkRes = checkWorkspace(ws);
    assert.equal(checkRes.ok, true, `checkWorkspace for ${key} failed: ${checkRes.errors.join("; ")}`);
  }
});

test("Batch 2 source integrity, block type diversity, and sourceId rules", () => {
  const internalKeywords = ["内部分析", "分析推断", "行业预测", "待验证", "in-house analysis", "industry estimate", "pending verification", "analysis inference"];
  const externalKeywords = ["JEDEC", "OIF", "JESD", "IEEE", "IPC", "SEMI", "ISO", "CCAR", "EASA", "FAA", "DO-178C", "DO-254", "ASPICE"];
  for (const key of BATCH2_KEYS) {
    const ws = getSectorResearchWorkspace(key)!;
    const sourceIds = new Set(ws.sources.map((s) => s.id));
    assert.equal(sourceIds.size, ws.sources.length, `workspace ${key} has duplicate source ids`);
    const usedSourceIds = new Set<string>();
    for (const tag of ws.tags) {
      assert.ok(tag.slug && tag.label && tag.title, `tag incomplete in ${key}`);
      assert.ok(tag.status !== "placeholder", `tag ${tag.slug} in ${key} should not be placeholder`);

      const validTypes = ["paragraph", "bullets", "table", "compareTable", "callout", "risk", "fact"];
      const blockTypes = new Set(tag.blocks.filter((b) => b.type !== "placeholder").map((b) => b.type));
      const relevant = [...blockTypes].filter((t) => validTypes.includes(t)).length;
      assert.ok(relevant >= 3, `${key} tag "${tag.slug}" has only ${relevant} diverse block types`);

      for (const block of tag.blocks) {
        assert.notEqual(block.type, "placeholder", `tag ${tag.slug} in ${key} contains forbidden placeholder block`);
        const ids = block.sourceIds ?? [];
        assert.equal(new Set(ids).size, ids.length, `tag ${tag.slug} has duplicate sourceIds`);
        for (const id of ids) {
          assert.ok(sourceIds.has(id), `tag ${tag.slug} in ${key} uses unknown sourceId "${id}"`);
          usedSourceIds.add(id);
        }

        const hasEmptySourceIds = !block.sourceIds || block.sourceIds.length === 0;
        const blockText = JSON.stringify(block);
        const hasInternalMarker = internalKeywords.some((kw) => blockText.includes(kw));
        if (hasEmptySourceIds) {
          if (!hasInternalMarker) {
            assert.fail(`${key} tag "${tag.slug}" ${block.type} has empty sourceIds without internal marker: ${blockText.slice(0, 120)}`);
          }
          for (const kw of externalKeywords) {
            if (blockText.includes(kw)) {
              assert.fail(`${key} tag "${tag.slug}" empty sourceIds block references external standard/org "${kw}" without citation`);
            }
          }
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

    for (const s of ws.sources) {
      assert.ok(usedSourceIds.has(s.id), `workspace ${key} source "${s.id}" is orphaned`);
      assert.ok(s.url && s.url.startsWith("http"), `source ${s.id} missing valid http/https url: ${s.url}`);
      assert.ok(s.accessedAt, `source ${s.id} missing accessedAt`);
      if (s.publishedAt) assert.ok(!isNaN(Date.parse(s.publishedAt)), `${key} source "${s.id}" invalid publishedAt`);
      if (s.accessedAt) assert.ok(!isNaN(Date.parse(s.accessedAt)), `${key} source "${s.id}" invalid accessedAt`);
      assert.ok(s.supports, `source ${s.id} missing supports`);
    }
  }
});

test("Batch 2 workspace required content components", () => {
  for (const key of BATCH2_KEYS) {
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

test("Batch 2 verified announcement IDs whitelist (hard fail)", () => {
  for (const key of BATCH2_KEYS) {
    const ws = getSectorResearchWorkspace(key)!;
    const entries = VERIFIED_ANNOUNCEMENTS[key];
    assert.ok(entries && entries.length > 0, `no whitelist entries for ${key}`);
    for (const v of entries) {
      const src = ws.sources.find((s) => s.id === v.id);
      assert.ok(src, `workspace ${key} missing whitelisted source ${v.id} (${v.name})`);
      const url = src.url;
      assert.ok(url.includes(`stockCode=${v.stock}`), `${v.id} URL missing stockCode=${v.stock}: ${url}`);
      assert.ok(url.includes(`announcementId=${v.aid}`), `${v.id} URL missing announcementId=${v.aid}: ${url}`);
    }
  }
});

test("Unregistered sectors display placeholder without workspace", () => {
  assert.equal(getSectorResearchWorkspace("nonexistent"), undefined);
  assert.equal(resolveOrFallback("nonexistent", "overview"), null);
});