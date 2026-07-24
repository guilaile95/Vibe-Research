import assert from "node:assert/strict";
import test from "node:test";

import {
  checkWorkspace,
  registeredResearchKeys,
  resolveOrFallback,
} from "../src/data/sectorResearch/invariants.ts";
import { getSectorResearchWorkspace } from "../src/data/sectorResearch/index.ts";

const BATCH2_KEYS = ["semiconductor", "smart-driving", "solid-state-battery", "low-altitude"] as const;

const VERIFIED_ANNS: Record<string, Array<{ id: string; stock: string; aid: string; name: string }>> = {
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

test("Batch 2 workspace registration", () => {
  for (const key of BATCH2_KEYS) {
    assert.ok(registeredResearchKeys().includes(key), `${key} should be registered`);
    const ws = getSectorResearchWorkspace(key);
    assert.ok(ws, `${key} exists`);
    assert.equal(ws.tags.length, 6, `${key} has 6 tags`);
    const r = checkWorkspace(ws!);
    assert.equal(r.ok, true, `${key}: ${r.errors.join("; ")}`);
  }
});

test("Batch 2 source integrity and announcement whitelist", () => {
  for (const key of BATCH2_KEYS) {
    const ws = getSectorResearchWorkspace(key)!;
    const sids = new Set(ws.sources.map(s => s.id));
    assert.equal(sids.size, ws.sources.length, `${key} has duplicate source IDs`);
    const used = new Set<string>();
    for (const tag of ws.tags) {
      for (const block of tag.blocks) {
        if (block.type === "placeholder") continue;
        for (const id of (block.sourceIds ?? [])) {
          assert.ok(sids.has(id), `${key} ${tag.slug} uses unknown ID "${id}"`);
          used.add(id);
        }
        // table/compareTable row consistency
        if ((block.type === "table" || block.type === "compareTable") && block.rows) {
          assert.ok(block.headers.length > 0, `empty headers in ${key} ${tag.slug}`);
          assert.ok(block.rows.length > 0, `empty rows in ${key} ${tag.slug}`);
          for (const row of block.rows) assert.equal(row.length, block.headers.length, `row mismatch in ${key} ${tag.slug}`);
        }
      }
    }
    for (const s of ws.sources) {
      assert.ok(used.has(s.id), `${key} source "${s.id}" orphaned`);
      assert.ok(s.url?.startsWith("http"), `${s.id} invalid URL`);
      assert.ok(s.accessedAt, `${s.id} missing accessedAt`);
      assert.ok(s.supports, `${s.id} missing supports`);
    }
    // Whitelist check
    const anns = VERIFIED_ANNS[key];
    for (const a of anns) {
      const src = ws.sources.find(s => s.id === a.id);
      assert.ok(src, `${key} missing whitelist source ${a.id} (${a.name})`);
      assert.ok(src.url!.includes(`stockCode=${a.stock}`), `${a.id} wrong stockCode`);
      assert.ok(src.url!.includes(`announcementId=${a.aid}`), `${a.id} wrong announcementId`);
    }
  }
});

test("Unregistered sector shows placeholder", () => {
  assert.equal(getSectorResearchWorkspace("nonexistent"), undefined);
  assert.equal(resolveOrFallback("nonexistent", "overview"), null);
});