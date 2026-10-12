import test from "node:test";
import assert from "node:assert/strict";
import vm from "node:vm";
import { EventEmitter } from "node:events";
import { readFileSync } from "node:fs";
import { stopBackend } from "./e2e/final-families.browser.mjs";
import { ANCILLARY_CLOCK, ANCILLARY_TRADE_DATE, ancillaryReply, realRouteAllowed, debateEvents, plan, encode, observeHistoryReads } from "./e2e/final-families.fixture.mjs";

test("new ancillary cards accept only exact fixed-date GETs with truthful unavailable readback", () => {
  const day = ANCILLARY_TRADE_DATE;
  const journalPath = `/api/next-day-verification/${day}`;
  const sealPath = "/api/market/seal-quality", sealSearch = `?trade_date=${day}`;
  const journal = ancillaryReply("GET", journalPath).data;
  assert.equal(journal.schema_version, "next-day-verification.v0.1");
  assert.equal(journal.trade_date, day); assert.equal(journal.state, "CALENDAR_UNKNOWN");
  assert.equal(journal.research_only, true); assert.equal(journal.revision, 0);
  assert.deepEqual(journal.items, []); assert.equal(journal.next_trade_date, null); assert.equal(journal.seals_at, null);
  for (const summary of [journal.summary, journal.history.summary]) {
    for (const key of ["total", "decided", "hit", "unknown", "baseline_covered"]) assert.equal(summary[key], 0);
    for (const key of ["rate", "coverage", "expected_rate", "edge"]) assert.equal(summary[key], null);
  }
  const seal = ancillaryReply("GET", sealPath, sealSearch).data;
  assert.equal(seal.schema_version, "short-term-seal-quality-archive-v0.1");
  assert.equal(seal.trade_date, day); assert.deepEqual(seal.reason_codes, ["ARCHIVE_NOT_CONNECTED"]);
  assert.equal(seal.projection, null); assert.equal(seal.archive_identity, null); assert.equal(seal.ingestion_enabled, false);
  for (const method of ["POST", "PUT", "PATCH", "DELETE", "HEAD"]) {
    assert.equal(ancillaryReply(method, journalPath), null);
    assert.equal(ancillaryReply(method, sealPath, sealSearch), null);
  }
  for (const search of ["?", "?as_of=x", "?observed_at=x", "?refresh=true", `?trade_date=${day}`, "?path=/tmp"]) assert.equal(ancillaryReply("GET", journalPath, search), null);
  for (const search of ["", "?trade_date=2026-10-12", "?trade_date=2026-09-05", "?date=2026-10-08", `${sealSearch}&trade_date=${day}`, `${sealSearch}&as_of=x`, `${sealSearch}&root=/tmp`, "?trade_date=2026%2D10%2D08"]) assert.equal(ancillaryReply("GET", sealPath, search), null);
  for (const path of ["/api/next-day-verification/2026-10-12", "/api/next-day-verification/2026-09-05", `${journalPath}/`, "/api/next-day-verification/2026%2D10%2D08", `${sealPath}/`]) assert.equal(ancillaryReply("GET", path, path.includes("seal-quality") ? sealSearch : ""), null);
  // New cards stay fixtures, never part of the real backend route allowance.
  assert.equal(realRouteAllowed("GET", journalPath, "history-late-success"), false);
  assert.equal(realRouteAllowed("GET", sealPath, "history-late-error"), false);
  journal.items.push({ synthetic: true });
  assert.deepEqual(ancillaryReply("GET", journalPath).data.items, []);
});

test("clock is fixed before any inherited DailyReview navigation, without widening accepted dates", () => {
  assert.equal(ANCILLARY_CLOCK, "2026-10-08T08:00:00Z");
  assert.equal(new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date(ANCILLARY_CLOCK)), ANCILLARY_TRADE_DATE);
  for (const filename of ["final-families.browser.mjs", "markdown-images.browser.mjs"]) {
    const source = readFileSync(new URL(`./e2e/${filename}`, import.meta.url), "utf8");
    assert.ok(source.indexOf("page.clock.setFixedTime(new Date(ANCILLARY_CLOCK))") < source.indexOf("await page.goto("));
  }
});

test("Debate fixtures distinguish original bull-only EOF, missing terminal and complete three/five stages", () => {
  for (const rounds of [1, 2]) {
    const eof = debateEvents(rounds, "bull-eof"); assert.equal(eof.length, 3); assert.ok(eof.every(e => e.stage === "bull"));
    assert.equal(debateEvents(rounds, "all-eof").some(e => e.type === "done"), false);
    const complete = debateEvents(rounds); assert.equal(complete.at(-1).type, "done"); assert.equal(complete.at(-1).stages.length, rounds === 1 ? 3 : 5);
    assert.deepEqual(complete.filter(e => e.type === "stage_done").map(e => e.stage), plan(rounds));
    assert.equal(encode(complete).trim().split("\n").length, complete.length);
  }
});
test("real production route whitelist cannot reach live providers or unrelated mutations", () => {
  for (const method of ["GET", "POST"]) assert.equal(realRouteAllowed(method, "/api/myreports", "report-upload"), true);
  assert.equal(realRouteAllowed("GET", "/api/daily-review/history", "history-late-success"), true);
  assert.equal(realRouteAllowed("GET", "/api/research-events", "calendar-422"), true);
  for (const [method, path, scenario] of [["POST", "/api/daily-review/history/save", "history-late-success"], ["GET", "/api/valuation", "report-upload"], ["POST", "/api/chat", "debate"], ["DELETE", "/api/myreports", "report-upload"], ["GET", "/api/research-events", "debate"]]) assert.equal(realRouteAllowed(method, path, scenario), false);
});
test("ancillary startup reads are inert typed fixtures with no poll/quote/campaign fanout", () => {
  const dr = ancillaryReply("GET", "/api/daily-review"); assert.equal(dr.cache_meta.stale, false);
  assert.deepEqual(ancillaryReply("GET", "/api/watchlist").data.data.codes, []);
  assert.deepEqual(ancillaryReply("GET", "/api/decision-inbox").data.campaign_items, []);
  for (const path of ["/api/daily-review", "/api/market/northbound", "/api/watchlist", "/api/native-intel/status", "/api/radar", "/api/decision-inbox", "/api/campaigns"]) {
    assert.ok(ancillaryReply("GET", path)); assert.equal(ancillaryReply("POST", path), null); assert.equal(ancillaryReply("GET", path, "?refresh=true"), null);
  }
  for (const [path, search] of [["/api/market/cloud", "?scope=all&period=today"], ["/api/ai-results/daily_review_ai", "?trade_date=2026-10-08"], ["/api/market/bk11-history", "?days=5"], ["/api/native-intel/items", "?limit=40&order_by=last_seen"], ["/api/native-intel/trending", "?window_hours=24&top_n=20"]]) {
    assert.ok(ancillaryReply("GET", path, search));
    assert.equal(ancillaryReply("POST", path, search), null);
    assert.equal(ancillaryReply("GET", path), null);
    assert.equal(ancillaryReply("GET", path, search + "&refresh=true"), null);
  }
  const bk = ancillaryReply("GET", "/api/market/bk11-history", "?days=5");
  assert.deepEqual(bk.window, { requested: 5, snapshot_count: 0 });
  for (const key of ["snapshots", "reason_codes", "warnings", "limitations"]) assert.deepEqual(bk[key], []);
  const cloud = ancillaryReply("GET", "/api/market/cloud", "?scope=all&period=today").data;
  assert.equal(cloud.status, "unavailable"); assert.equal(cloud.data, null); assert.deepEqual(cloud.warnings, []);
  assert.equal(ancillaryReply("GET", "/api/ai-results/daily_review_ai", "?trade_date=2026-10-08").data, null);
  assert.equal(ancillaryReply("GET", "/api/unknown"), null);
});
test("history observation preserves native signals and records actual JSON parsing", async () => {
  const calls = [], window = { fetch: async (input, init) => { calls.push({ input, init }); return { status: 200, json: async () => ({ data: { items: [] } }) }; } };
  vm.runInNewContext(`(${observeHistoryReads.toString()})()`, { window, URL, location: { href: "http://127.0.0.1/daily-review" } });
  const controller = new AbortController(), response = await window.fetch("/api/daily-review/history?trade_date=2026-09-06", { signal: controller.signal });
  assert.equal(calls[0].init.signal, controller.signal); assert.equal(window.__historyReads[0].parsed, false);
  await response.json(); assert.equal(window.__historyReads[0].parsed, true);
  await window.fetch("/api/research-events"); assert.equal(window.__historyReads.length, 1);
});

test("backend teardown waits for graceful and escalated exits, including signal-exited children", async () => {
  for (const escalate of [false, true]) {
    const child = new EventEmitter(); Object.assign(child, { pid: 123, exitCode: null, signalCode: null });
    const order = [];
    child.kill = signal => { order.push(signal); if (!escalate || signal === "SIGKILL") queueMicrotask(() => { child.signalCode = signal; order.push("exit"); child.emit("exit"); }); return true; };
    await stopBackend(child, 0); order.push("returned");
    assert.deepEqual(order, escalate ? ["SIGTERM", "SIGKILL", "exit", "returned"] : ["SIGTERM", "exit", "returned"]);
    await stopBackend(child, 0); assert.equal(order.at(-1), "returned");
  }
});
