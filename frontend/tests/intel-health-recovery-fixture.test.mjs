import assert from "node:assert/strict";
import test from "node:test";
import vm from "node:vm";
import { recoveryFixture, recordLateDeepReads } from "./e2e/intel-health-recovery.browser.mjs";

test("deep-read fixture really keeps A pending until after B succeeds", async () => {
  const f = recoveryFixture("intel");
  let aSettled = false;
  const a = f.reply("POST", "/api/native-intel/items/1/deep-read").then(value => { aSettled = true; return value; });
  await f.oldRequested;
  const b = await f.reply("POST", "/api/native-intel/items/2/deep-read");
  assert.equal(b.json.item_id, 2);
  assert.equal(aSettled, false);
  f.releaseOld();
  assert.equal((await a).json.item_id, 1);
  assert.deepEqual(f.state.deepCalls, [1, 2]);
});

test("health refresh fixture changes overview before releasing selected detail", async () => {
  const f = recoveryFixture("health-refresh");
  assert.equal((await f.reply("GET", "/api/data-health")).json.data.overall_status, "partial");
  assert.equal((await f.reply("GET", "/api/data-health/quotes")).json.data.record.status, "partial");
  assert.equal((await f.reply("GET", "/api/data-health")).json.data.overall_status, "unavailable");
  let settled = false;
  const detail = f.reply("GET", "/api/data-health/quotes").then(value => { settled = true; return value; });
  await f.reloadRequested;
  assert.equal(settled, false);
  f.releaseReload();
  assert.equal((await detail).json.data.record.status, "unavailable");
  assert.equal(f.state.detailCalls, 2);
});

test("same-card fixture first fails and requires another detail read to recover", async () => {
  const f = recoveryFixture("health-retry");
  await f.reply("GET", "/api/data-health");
  assert.equal((await f.reply("GET", "/api/data-health/quotes")).status, 503);
  assert.equal(f.state.detailCalls, 1);
  const recovered = await f.reply("GET", "/api/data-health/quotes");
  assert.equal(recovered.status, 200);
  assert.equal(recovered.json.data.record.source_id, "quotes");
  assert.equal(f.state.detailCalls, 2);
  assert.equal(f.state.overviewCalls, 1);
});

test("fixtures reject unexpected mutations and cannot silently call a real model", async () => {
  const f = recoveryFixture("intel");
  for (const [method, path] of [["POST", "/api/native-intel/ai/analysis"], ["POST", "/api/data-health"], ["GET", "/api/unknown"]]) {
    assert.equal((await f.reply(method, path)).status, 503);
  }
  assert.equal(f.state.unexpected.length, 3);
});

test("each browser scenario gets isolated counters and release gates", async () => {
  const a = recoveryFixture("health-retry"), b = recoveryFixture("health-retry");
  await a.reply("GET", "/api/data-health/quotes");
  assert.equal(a.state.detailCalls, 1);
  assert.equal(b.state.detailCalls, 0);
  assert.equal((await b.reply("GET", "/api/data-health/quotes")).status, 503);
});

test("late-response injection preserves unrelated fetch signals and observes actual abort and parsing", async () => {
  const calls = [];
  const window = { fetch: async (input, init) => {
    calls.push({ input, init });
    return { json: async () => ({ marker: "synthetic" }) };
  } };
  vm.runInNewContext(`(${recordLateDeepReads.toString()})()`, {
    window, URL, location: { href: "http://127.0.0.1/intel" },
  });
  const controller = new AbortController();
  await window.fetch("/api/data-health", { signal: controller.signal });
  assert.equal(calls[0].init.signal, controller.signal);
  const response = await window.fetch("/api/native-intel/items/1/deep-read", { signal: controller.signal });
  assert.equal(calls[1].init.signal, undefined);
  assert.equal(window.__recoveryDeepReads["1"].parsed, false);
  controller.abort();
  assert.equal(window.__recoveryDeepReads["1"].aborted, true);
  assert.equal((await response.json()).marker, "synthetic");
  assert.equal(window.__recoveryDeepReads["1"].parsed, true);
});
