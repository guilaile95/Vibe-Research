import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { createFixture, golden, DAY, JOURNAL_VIEWPORTS } from "./e2e/next-day-verification.fixture.mjs";
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


test("both real viewport suites run every flow and capture state-ready cropped evidence", () => {
  assert.deepEqual(JOURNAL_VIEWPORTS.map(({ width, height }) => [width, height]), [[1440, 1000], [390, 844]]);
  assert.equal(new Set(JOURNAL_VIEWPORTS.map(({ label }) => label)).size, 2);
  const source = readFileSync(new URL("./e2e/next-day-verification.browser.mjs", import.meta.url), "utf8");
  assert.match(source, /for \(const viewport of JOURNAL_VIEWPORTS\)/);
  assert.match(source, /viewport: \{ width: viewport.width, height: viewport.height \}/);
  assert.match(source, /state.scrollWidth <= state.clientWidth \+ 1/);
  assert.match(source, /control.right <= state.right \+ 1/);
  assert.match(source, /-card-top.png/);
  assert.match(source, /captureRegion\(card.locator\("fieldset"\), "controls"\)/);
  assert.match(source, /shot\("03a-save-error-retains-input", "验证记录不可写入，未保存修改"\)/);
  assert.match(source, /shot\("03b-revision-conflict", "记录已改变，请重新读取后再保存"\)/);
  assert.match(source, /shot\("04-sealed-missing-is-not-failure", "已封存，不能修改或删除"\)/);
  assert.match(source, /shot\("07a-read-error", "验证记录不可读取，已停止操作"\)/);
});

test("integrated cohort ancillary read keeps exact opt-in date and unknown membership", () => {
  const path = "/api/market/cohort-identity", search = `?trade_date=${DAY}`;
  const url = `${origin}${path}${search}`;
  assert.equal(createFixture(origin).handle(url).kind, "deny");
  const f = createFixture(origin, { withSealQuality: true });
  const result = f.handle(url).body.data;
  assert.equal(result.schema_version, "archived-cohort-identity.v0.1");
  assert.equal(result.trade_date, DAY); assert.equal(result.previous_trade_date, "2026-07-30");
  assert.equal(result.status, "unavailable"); assert.deepEqual(result.reason_codes, ["ARCHIVE_MISSING"]);
  assert.equal(result.projection, null); assert.equal(result.evidence, null);
  assert.equal(result.selection_mode, "CURRENT_STORED_POSTHOC");
  assert.equal(result.point_in_time_claim, "NONE"); assert.equal(result.research_only, true);
  for (const method of ["POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]) {
    assert.equal(f.handle(url, method).kind, "deny", method);
  }
  for (const query of ["", "?trade_date=2026-08-03", "?trade_date=2026-07-30", "?trade_date=2026-10-08", "?trade_date=2026-10-12",
    "?trade_date=2026%2D07%2D31", `?date=${DAY}`, `${search}&trade_date=${DAY}`, `${search}&as_of=x`,
    `${search}&observed_at=x`, `${search}&root=/tmp`, `${search}&refresh=1`]) {
    assert.equal(f.handle(`${origin}${path}${query}`).kind, "deny", query);
  }
  for (const target of [`${origin}${path}/${search}`, `http://127.0.0.1:18762${path}${search}`]) {
    assert.equal(f.handle(target).kind, "deny", target);
  }
  result.reason_codes.push("MUTATED");
  assert.deepEqual(f.handle(url).body.data.reason_codes, ["ARCHIVE_MISSING"]);
});

test("full review permits only selected golden archive dates and two exact history IDs", () => {
  const f = createFixture(origin, { withSealQuality: true, fullReview: true });
  for (const kind of ["seal-quality", "cohort-identity", "evidence-readiness"]) {
    for (const day of [DAY, "2026-07-30", "2026-07-29"]) {
      const value = f.handle(`${origin}/api/market/${kind}?trade_date=${day}`).body.data;
      assert.equal(value.trade_date, day);
      if (kind === "evidence-readiness") assert.deepEqual(value.features.map(row => row.status), ["ready", "ready", "ready"]);
      else assert.equal(value.status, "normal");
      value.trade_date = "MUTATED";
      assert.equal(f.handle(`${origin}/api/market/${kind}?trade_date=${day}`).body.data.trade_date, day);
    }
    for (const suffix of ["", "?trade_date=2026-08-03", "?trade_date=2026%2D07%2D30", "?trade_date=2026-07-30&refresh=1", "?trade_date=2026-07-30&trade_date=2026-07-30"]) {
      assert.equal(f.handle(`${origin}/api/market/${kind}${suffix}`).kind, "deny");
    }
    for (const method of ["PUT", "POST", "PATCH", "DELETE", "HEAD", "OPTIONS"]) {
      assert.equal(f.handle(`${origin}/api/market/${kind}?trade_date=${DAY}`, method).kind, "deny");
    }
  }
  assert.equal(f.handle(`${origin}/api/daily-review/history?limit=20&offset=0`).body.data.items.length, 2);
  for (const id of [701, 702]) assert.equal(f.handle(`${origin}/api/daily-review/history/${id}`).body.data.id, id);
  for (const suffix of ["700", "703", "701?refresh=1", "701/", "0701"]) {
    assert.equal(f.handle(`${origin}/api/daily-review/history/${suffix}`).kind, "deny");
  }
  assert.equal(f.handle(`http://127.0.0.1:18762/api/daily-review/history/701`).kind, "deny");
  assert.equal(f.handle(`${origin}/api/daily-review/history/701`, "POST").kind, "deny");
  assert.deepEqual(f.writes, []);
});

test("malformed journal reply is one-shot and never changes valid persisted fixture", () => {
  const f = createFixture(origin, { withSealQuality: true, fullReview: true });
  f.malformedGet(DAY, { items: null });
  assert.deepEqual(f.handle(`${origin}/api/next-day-verification/${DAY}`).body.data, { items: null });
  assert.deepEqual(f.handle(`${origin}/api/next-day-verification/${DAY}`).body.data, golden.open_empty);
  assert.deepEqual(f.writes, []);
});

test("integrated full-page acceptance retains semantic races and no local sleeps", () => {
  const source = readFileSync(new URL("./e2e/daily-review-integrated.scenarios.mjs", import.meta.url), "utf8");
  assert.match(source, /url.origin === location.origin && method === "GET"/);
  assert.match(source, /record.parsed = true/);
  assert.match(source, /signal: undefined/);
  assert.match(source, /window.__reviewReads\[index\]\?\.parsed/);
  assert.match(source, /INDEPENDENT_UNSAVED_JOURNAL/);
  assert.match(source, /history navigation and archive retry never save/);
  assert.match(source, /malformed data hides editor/);
  assert.doesNotMatch(source, /waitForTimeout|setTimeout|sleep\(/);
});

test("malformed write reply can represent one persisted write with truthful reread", () => {
  const f = createFixture(origin);
  f.expectSave(payload, "open_saved", 200, { items: null });
  assert.deepEqual(f.handle(`${origin}/api/next-day-verification/${DAY}`, "PUT", payload).body.data, { items: null });
  assert.equal(f.writes.length, 1);
  assert.deepEqual(f.handle(`${origin}/api/next-day-verification/${DAY}`).body.data, golden.open_saved);
  assert.equal(f.handle(`${origin}/api/next-day-verification/${DAY}`, "PUT", payload).kind, "deny");
});


test("readiness unavailable fixture is exact-date opt-in and malformed reads recover", () => {
  const url = `${origin}/api/market/evidence-readiness?trade_date=${DAY}`;
  assert.equal(createFixture(origin).handle(url).kind, "deny");
  const f = createFixture(origin, { withSealQuality: true });
  assert.deepEqual(f.handle(url).body.data.features.map(row => row.status), ["not_configured", "missing", "missing"]);
  f.malformedReadiness(DAY, { trade_date: "wrong" });
  assert.deepEqual(f.handle(url).body.data, { trade_date: "wrong" });
  assert.equal(f.handle(url).body.data.trade_date, DAY);
  assert.equal(f.handle(`${origin}/api/market/evidence-readiness?trade_date=2026-07-30`).kind, "deny");
  assert.equal(f.handle(url + "&refresh=1").kind, "deny");
  assert.deepEqual(f.writes, []);
});

test("saved AI basis fixtures are dated readonly restores, with explicitly separate corrupt input", () => {
  const url = `${origin}/api/ai-results/daily_review_ai?trade_date=${DAY}`;
  for (const aiMode of ["v1", "v2", "malformed_v2"]) {
    const f = createFixture(origin, { withSealQuality: true, fullReview: true, aiMode });
    const value = f.handle(url).body.data;
    assert.equal(value.trade_date, DAY);
    assert.equal(value.schema_version, `daily_review_ai.${aiMode === "v1" ? "v1" : "v2"}`);
    if (aiMode === "v1") assert.equal(value.payload.input_basis, undefined);
    else assert.equal(value.payload.input_basis.trade_date, aiMode === "v2" ? DAY : "2026-07-30");
    for (const method of ["POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]) assert.equal(f.handle(url, method).kind, "deny");
    for (const query of ["", "?trade_date=2026-07-30", `?trade_date=${DAY}&refresh=1`, `?trade_date=${DAY}&trade_date=${DAY}`]) {
      assert.equal(f.handle(`${origin}/api/ai-results/daily_review_ai${query}`).kind, "deny");
    }
    assert.equal(f.handle(`${origin}/api/daily-review/ai`, "POST").kind, "deny");
    assert.equal(f.writes.length, 0);
  }
});
