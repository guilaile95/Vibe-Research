import test from "node:test";
import assert from "node:assert/strict";
import vm from "node:vm";
import { readFileSync } from "node:fs";
import { research, industry, contextFor, marketReply, rows, failure, oldDetail, ledgerFixture, observeLedgerReads } from "./e2e/market-ledger.fixture.mjs";

test("original AI-computing mismatch contract uses actual loaded labels, body and draft status", () => {
  assert.equal(research.tags.length, 6);
  assert.equal(industry.label, "芯片、服务器、网络、散热产业格局");
  for (const tag of research.tags) {
    assert.ok(tag.blocks.some(block => block.type === "paragraph"));
    assert.equal(tag.status, "draft");
    assert.ok(contextFor(tag).includes(`当前栏目：${tag.label}`));
    assert.match(contextFor(tag), /内容状态：draft/);
    assert.doesNotMatch(contextFor(tag), /DRAM、封装、设备与材料格局|内容状态：ready/);
  }
});
test("market read whitelist covers active child mounts and refuses live scans, AI and writes", () => {
  assert.deepEqual(marketReply("GET", "/api/myreports", ""), []);
  assert.deepEqual(marketReply("GET", "/api/sector-research/market-context", "?sector_key=ai-computing"), { items: [] });
  for (const [method, path, query] of [["GET", "/api/sector-research/data/ai-computing", ""], ["GET", "/api/sector-research/market-context", "?sector_key=hbm"], ["POST", "/api/chat", ""], ["POST", "/api/myreports", ""]]) assert.equal(marketReply(method, path, query), null);
  const market = readFileSync(new URL("../src/components/sectors/SectorMarketContext.tsx", import.meta.url), "utf8");
  const reports = readFileSync(new URL("../src/components/sectors/SectorReportDiscoveryPanel.tsx", import.meta.url), "utf8");
  assert.ok(market.includes("api.getSectorMarketContext(sectorKey)"));
  assert.ok(reports.includes("api.myReports()"));
});
test("ledger fixture holds exact old and current reads independently and rejects changed query/method", async () => {
  const f = ledgerFixture();
  const old = f.expect("/api/signal-ledger?stage=schema&limit=100", rows("OLD"));
  const current = f.expect("/api/signal-ledger?limit=100&stage=execution", rows("NEW", "execution"));
  let settled = false;
  const a = f.reply("GET", "http://synthetic.invalid/api/signal-ledger?limit=100&stage=schema").then(value => { settled = true; return value; });
  const b = f.reply("GET", "/api/signal-ledger?stage=execution&limit=100");
  await Promise.all([old.started, current.started]); current.release();
  assert.equal((await b).json.items[0].signal_type, "NEW"); assert.equal(settled, false);
  old.release(); assert.equal((await a).json.items[0].signal_type, "OLD");
  assert.equal((await f.reply("POST", "/api/signal-ledger")).status, 503);
  assert.equal(f.unexpected.length, 1);
  assert.equal(rows(null).json.items.length, 0);
  assert.equal(oldDetail().json.run.decision_run_id, "SYNTHETIC_OLD_RUN");
  const error = f.expect("/api/signal-ledger?limit=100", failure("FAILED")); error.release();
  assert.equal((await f.reply("GET", "/api/signal-ledger?limit=100")).status, 503); assert.equal(f.failures, 1);
});
test("ledger JSON instrumentation preserves native fetch signals and proves late parsing", async () => {
  const calls = [], window = { fetch: async (input, init) => { calls.push({ input, init }); return { status: 200, json: async () => ({ marker: "SYNTHETIC" }) }; } };
  vm.runInNewContext(`(${observeLedgerReads.toString()})()`, { window, URL, location: { href: "http://127.0.0.1/signal-ledger" } });
  const controller = new AbortController();
  const response = await window.fetch("/api/signal-ledger?limit=100", { signal: controller.signal });
  assert.equal(calls[0].init.signal, controller.signal); assert.equal(window.__ledgerReads[0].parsed, false);
  assert.equal((await response.json()).marker, "SYNTHETIC"); assert.equal(window.__ledgerReads[0].parsed, true);
  await window.fetch("/api/myreports", { signal: controller.signal }); assert.equal(window.__ledgerReads.length, 1);
});
