import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { createFixture, golden, DAY } from "./e2e/next-day-verification.fixture.mjs";
const origin = "http://127.0.0.1:18761";
const payload = { revision: 0, items: [{ metric: "limit_up_count", direction: "up", reason: "Synthetic prior condition" }] };

test("fixture permits only exact same-origin static GET and expected journal PUT", () => {
  for (const [url, method, body] of [
    [`http://127.0.0.1:18762/api/next-day-verification/${DAY}`, "GET"],
    [`${origin}/api/next-day-verification/${DAY}`, "POST", payload],
    [`${origin}/api/next-day-verification/${DAY}`, "DELETE"],
    [`${origin}/api/next-day-verification/${DAY}`, "PUT", payload],
    [`${origin}/daily-review`, "POST", {}], [`${origin}/api/unknown`, "GET"],
    [`${origin}/api/next-day-verification/${DAY}?now=x`, "GET"],
  ]) assert.equal(createFixture(origin).handle(url, method, body).kind, "deny");
  const f = createFixture(origin);
  f.expectSave(payload, "open_saved");
  assert.deepEqual(f.handle(`${origin}/api/next-day-verification/${DAY}`, "PUT", payload).body.data, golden.open_saved);
  assert.equal(f.writes.length, 1);
  assert.equal(f.handle(`${origin}/api/next-day-verification/${DAY}`, "PUT", payload).kind, "deny");
});
test("golden state/date/revision and missing denominators stay honest", () => {
  assert.equal(golden.open_empty.state, "OPEN");
  assert.equal(golden.open_saved.revision, 1);
  assert.equal(golden.open_external.revision, 2);
  assert.equal(golden.open_cleared.revision, 3);
  assert.equal(golden.sealed_missing.state, "SEALED");
  assert.equal(golden.sealed_missing.items[0].state, "NO_EVIDENCE");
  assert.equal(golden.sealed_missing.summary.rate, null);
  assert.equal(golden.sealed_missing.summary.decided, 0);
  assert.equal(golden.calendar_unknown.state, "CALENDAR_UNKNOWN");
  assert.equal(golden.cold.trade_date, "2026-08-03");
});
test("fixture rejects wrong payload/time injection and simulates conflict + recovery", () => {
  const bad = createFixture(origin);
  bad.expectSave(payload, "open_saved");
  assert.equal(bad.handle(`${origin}/api/next-day-verification/${DAY}`, "PUT", { ...payload, written_at: "fake" }).kind, "deny");
  const f = createFixture(origin);
  f.expectSave({ ...payload, revision: 1 }, "open_external", 409);
  assert.equal(f.handle(`${origin}/api/next-day-verification/${DAY}`, "PUT", { ...payload, revision: 1 }).status, 409);
  assert.equal(f.handle(`${origin}/api/next-day-verification/${DAY}`).body.data.revision, 2);
  f.failGet(DAY);
  assert.equal(f.handle(`${origin}/api/next-day-verification/${DAY}`).status, 503);
  assert.equal(f.handle(`${origin}/api/next-day-verification/${DAY}`).status, 200);
});


test("integrated seal smoke is opt-in and restricted to exact archive GET", () => {
  const url = `${origin}/api/market/seal-quality?trade_date=${DAY}`;
  assert.equal(createFixture(origin).handle(url).kind, "deny");
  const f = createFixture(origin, { withSealQuality: true });
  const result = f.handle(url);
  assert.equal(result.body.data.status, "unavailable");
  assert.equal(result.body.data.ingestion_enabled, false);
  assert.equal(result.body.data.projection, null);
  assert.equal(f.handle(url + "&refresh=1").kind, "deny");
});


test("held-response hook cannot hide cross-origin or non-GET requests", () => {
  const source = readFileSync(new URL("./e2e/next-day-verification.browser.mjs", import.meta.url), "utf8");
  assert.match(source, /url.origin === location.origin && method === "GET" && window.__holdJournalDate/);
  assert.match(source, /input instanceof Request \? input.method : "GET"/);
});
