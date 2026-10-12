import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import { isSealQualityArchiveForDate, sealQualityNumber, sealQualityTime } from "../src/lib/sealQuality.ts";
import { dayA, dayB, sealReply, validSealQuery, observeSealReads } from "./e2e/seal-quality.fixture.mjs";

test("captured observation readback preserves date/authority and distinguishes partial from zero", () => {
  assert.equal(isSealQualityArchiveForDate(sealReply(dayA), dayA), true);
  assert.equal(isSealQualityArchiveForDate(sealReply(dayA, "partial"), dayA), true);
  assert.equal(isSealQualityArchiveForDate(sealReply(dayA, "unconnected"), dayA), true);
  assert.equal(isSealQualityArchiveForDate(sealReply(dayA), dayB), false);
  const unsafe = sealReply(dayA); unsafe.projection.canonical_authority = true;
  assert.equal(isSealQualityArchiveForDate(unsafe, dayA), false);
  for (const value of [null, {}, [], { trade_date: dayA }]) assert.equal(isSealQualityArchiveForDate(value, dayA), false);
  assert.equal(sealQualityNumber(null), "—"); assert.equal(sealQualityNumber(0), "0");
  assert.equal(sealQualityNumber(0.5, true), "50.0%");
  assert.equal(sealQualityNumber(NaN), "—"); assert.equal(sealQualityNumber("0"), "—");
  assert.equal(sealQualityTime("093500"), "09:35:00"); assert.equal(sealQualityTime(null), "—");
});

test("fixture whitelist is exact, read-only and date-bound", () => {
  assert.equal(validSealQuery("GET", "/api/market/seal-quality", `?trade_date=${dayA}`), true);
  for (const [method, path, search] of [
    ["POST", "/api/market/seal-quality", `?trade_date=${dayA}`],
    ["GET", "/api/market/seal-quality", `?trade_date=${dayA}&root=/tmp`],
    ["GET", "/api/market/seal-quality", `?trade_date=${dayA}&trade_date=${dayA}`],
    ["GET", "/api/market/seal-quality", "?trade_date=2026-07-28"],
    ["GET", "/api/agent-runtime/status", ""],
  ]) assert.equal(validSealQuery(method, path, search), false);
});

test("browser race instrument observes abort yet delivers late parsed reply", async () => {
  const calls = [];
  const window = { fetch: async (input, init) => { calls.push(init); return { json: async () => sealReply(dayA) }; } };
  vm.runInNewContext(`(${observeSealReads.toString()})()`, { window, URL, location: { href: "http://127.0.0.1/" } });
  const controller = new AbortController();
  const response = await window.fetch(`/api/market/seal-quality?trade_date=${dayA}`, { signal: controller.signal });
  controller.abort(); await response.json();
  assert.equal(calls[0].signal, undefined);
  assert.equal(window.__sealReads[0].aborted, true); assert.equal(window.__sealReads[0].parsed, true);
});

test("actual current review and selected historical detail mount the production component", () => {
  const page = readFileSync(new URL("../src/pages/DailyReview.tsx", import.meta.url), "utf8");
  assert.match(page, /<SealQualityCard tradeDate=\{dr\?\.trade_date \?\? null\}/);
  assert.match(page, /<SealQualityCard tradeDate=\{snap\.trade_date \?\? null\}/);
  const component = readFileSync(new URL("../src/components/dailyReview/SealQualityCard.tsx", import.meta.url), "utf8");
  assert.match(component, /state\?\.date === tradeDate/);
  assert.match(component, /request !== generation\.current/);
  assert.match(component, /controller\.abort\(\)/);
  assert.doesNotMatch(component, /Date\.now|new Date|localStorage|setInterval/);
});

test("dedicated CI browser harness is bounded and build-only never launches a browser", () => {
  const browser = readFileSync(new URL("./e2e/seal-quality.browser.mjs", import.meta.url), "utf8");
  assert.ok(browser.indexOf('process.argv.includes("--build-only")') < browser.indexOf("chromium.launch"));
  assert.match(browser, /for \(const width of \[1440, 390\]\)/);
  assert.match(browser, /validSealQuery\(request\.method\(\), url\.pathname, url\.search\)/);
  assert.match(browser, /assert\.deepEqual\(audit\.external, \[\]\)/);
  assert.match(browser, /assert\.equal\(results\.length, 12\)/);
  assert.doesNotMatch(browser, /child_process|spawn\(|execFile|setTimeout\(.*sleep|fonts\.googleapis/);
});
