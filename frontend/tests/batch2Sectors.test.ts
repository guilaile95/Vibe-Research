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
  semiconductor: [
    { id: "S-SEMI-NAURA-FILING", stock: "002371", aid: "1219908921", name: "北方华创" },
    { id: "S-SEMI-AMEC-FILING", stock: "688012", aid: "1219329946", name: "中微公司" },
    { id: "S-SEMI-NSIG-FILING", stock: "688126", aid: "1219596239", name: "沪硅产业" },
    { id: "S-SEMI-ANJI-FILING", stock: "688019", aid: "1219623534", name: "安集科技" },
    { id: "S-SEMI-SMIC-FILING", stock: "688981", aid: "1219447098", name: "中芯国际" },
    { id: "S-SEMI-POTON-FILING", stock: "300054", aid: "1219553057", name: "鼎龙股份" },
  ],
  "smart-driving": [
    { id: "S-DRIVE-DESAY-FILING", stock: "002920", aid: "1219428492", name: "德赛西威" },
    { id: "S-DRIVE-JINGWEI-FILING", stock: "688326", aid: "1219885867", name: "经纬恒润" },
    { id: "S-DRIVE-THUNDER-FILING", stock: "300496", aid: "1219425324", name: "中科创达" },
    { id: "S-DRIVE-BETHEL-FILING", stock: "603596", aid: "1219430299", name: "伯特利" },
    { id: "S-DRIVE-YATAI-FILING", stock: "002284", aid: "1219646787", name: "亚太股份" },
    { id: "S-DRIVE-LENS-FILING", stock: "002036", aid: "1219915025", name: "联创电子" },
  ],
  "solid-state-battery": [
    { id: "S-SSBAT-CATL-FILING", stock: "300750", aid: "1219313047", name: "宁德时代" },
    { id: "S-SSBAT-EASPRING-FILING", stock: "300073", aid: "1219468325", name: "当升科技" },
    { id: "S-SSBAT-TINCI-FILING", stock: "002709", aid: "1219402767", name: "天赐材料" },
    { id: "S-SSBAT-CAPCHEM-FILING", stock: "300037", aid: "1219493150", name: "新宙邦" },
    { id: "S-SSBAT-GOTION-FILING", stock: "002074", aid: "1219700973", name: "国轩高科" },
    { id: "S-SSBAT-GANFENG-FILING", stock: "002460", aid: "1219453182", name: "赣锋锂业" },
  ],
  "low-altitude": [
    { id: "S-LOWALT-AVICHIGHTECH-FILING", stock: "600038", aid: "1219314145", name: "中直股份" },
    { id: "S-LOWALT-WANFENG-FILING", stock: "002085", aid: "1219800529", name: "万丰奥威" },
    { id: "S-LOWALT-CITIC-FILING", stock: "000099", aid: "1219328401", name: "中信海直" },
    { id: "S-LOWALT-ZONGHENG-FILING", stock: "688070", aid: "1219883396", name: "纵横股份" },
    { id: "S-LOWALT-LAISI-FILING", stock: "688631", aid: "1219798232", name: "莱斯信息" },
    { id: "S-LOWALT-SHENCHENGJIAO-FILING", stock: "301091", aid: "1219673881", name: "深城交" },
    { id: "S-LOWALT-ZHONGZHI-FILING", stock: "600862", aid: "1219312183", name: "中航高科" },
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
    const checkRes = checkWorkspace(ws);
    assert.equal(checkRes.ok, true, `checkWorkspace for ${key} failed: ${checkRes.errors.join("; ")}`);
  }
});

test("Batch 2 source integrity and usage", () => {
  for (const key of BATCH2_KEYS) {
    const ws = getSectorResearchWorkspace(key)!;
    const sourceIds = new Set(ws.sources.map((s) => s.id));
    assert.equal(sourceIds.size, ws.sources.length, `workspace ${key} has duplicate source ids`);
    const usedSourceIds = new Set();
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
      }
    }
    for (const s of ws.sources) {
      assert.ok(usedSourceIds.has(s.id), `workspace ${key} source "${s.id}" is orphaned`);
      assert.ok(s.url && s.url.startsWith("http"), `source ${s.id} missing valid http/https url`);
      assert.ok(s.accessedAt, `source ${s.id} missing accessedAt`);
      assert.ok(s.supports, `source ${s.id} missing supports`);
    }
  }
});

test("Batch 2 announcement ID whitelist", () => {
  for (const key of BATCH2_KEYS) {
    const ws = getSectorResearchWorkspace(key)!;
    const entries = VERIFIED_ANNOUNCEMENTS[key];
    assert.ok(entries, `no whitelist entries for ${key}`);
    for (const v of entries) {
      const src = ws.sources.find((s) => s.id === v.id);
      if (!src) continue;
      const url = src.url;
      assert.ok(url.includes(`stockCode=${v.stock}`), `${v.id} URL missing stockCode=${v.stock}: ${url}`);
      assert.ok(url.includes(`announcementId=${v.aid}`), `${v.id} URL missing announcementId=${v.aid}: ${url}`);
    }
  }
});

test("Batch 2 table/compareTable row consistency", () => {
  for (const key of BATCH2_KEYS) {
    const ws = getSectorResearchWorkspace(key)!;
    for (const tag of ws.tags) {
      for (const block of tag.blocks) {
        if (block.type === "table" || block.type === "compareTable") {
          for (const row of block.rows) {
            assert.equal(row.length, block.headers.length, `${key} ${tag.slug} row length mismatch`);
          }
        }
      }
    }
  }
});