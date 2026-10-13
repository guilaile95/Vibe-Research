import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { assertHr1InboxAuthority, hr1CommittedInboxState, waitForHr1Inbox, createHr1BackendDrain } from "./e2e/hr1-readiness.fixture.mjs";
const expected = [{ campaign_id: "synthetic-a", hard_risk_state: "CONFIRMED", hard_risk_evaluation: "EVALUATED", hard_risk_reason_codes: ["THESIS_CORE_FACT_DISPROVEN"], hard_risk_authority_refs: ["current_thesis:synthetic-a:1"] }, { campaign_id: "synthetic-b", hard_risk_state: "UNKNOWN", hard_risk_evaluation: "UNKNOWN", hard_risk_reason_codes: [], hard_risk_authority_refs: [] }];
const payload = () => ({ data: { canonical: true, campaign_items: structuredClone(expected) } });
const committed = { pathname: "/decision-inbox", title: "决策待办", alerts: [], overlay: false, worklist: true, tabs: 3 };

test("real response gate rejects missing campaign or changed hard-risk authority", () => {
  assert.doesNotThrow(() => assertHr1InboxAuthority(payload(), expected));
  for (const key of ["hard_risk_state", "hard_risk_evaluation", "hard_risk_reason_codes", "hard_risk_authority_refs"]) {
    const value = payload(); value.data.campaign_items[0][key] = "wrong";
    assert.throws(() => assertHr1InboxAuthority(value, expected), /authority changed/);
  }
  assert.throws(() => assertHr1InboxAuthority({ canonical: true, campaign_items: [expected[0]] }, expected), /missing seeded campaign/);
  assert.throws(() => assertHr1InboxAuthority({ canonical: false, campaign_items: expected }, expected), /canonical/);
});
test("readiness requires committed UI and returns explicit errors rather than false success", () => {
  assert.equal(hr1CommittedInboxState({ ...committed, worklist: false }), null);
  assert.equal(hr1CommittedInboxState({ ...committed, tabs: 0 }), null);
  assert.equal(hr1CommittedInboxState({ ...committed, title: "" }), null);
  assert.deepEqual(hr1CommittedInboxState(committed), { ready: true });
  assert.match(hr1CommittedInboxState({ ...committed, alerts: ["Load failed"] }).error, /Load failed/);
  assert.match(hr1CommittedInboxState({ ...committed, overlay: true }).error, /overlay/);
  assert.match(hr1CommittedInboxState({ ...committed, pathname: "/notes" }).error, /Unexpected/);
});
test("response listener precedes navigation and only accepts the real GET inbox path", async () => {
  const calls = [];
  const page = {
    waitForResponse(predicate, options) {
      calls.push("listen"); assert.equal(options.timeout, 90000);
      const response = (method, path) => ({ request: () => ({ method: () => method }), url: () => `http://synthetic.invalid${path}` });
      assert.equal(predicate(response("POST", "/api/decision-inbox")), false);
      assert.equal(predicate(response("GET", "/api/campaigns")), false);
      assert.equal(predicate(response("GET", "/api/decision-inbox")), true);
      return Promise.resolve({ status: () => 200, json: async () => payload() });
    },
    waitForFunction(fn) { calls.push("ui"); assert.equal(fn, hr1CommittedInboxState); return Promise.resolve({ jsonValue: async () => ({ ready: true }), dispose: async () => calls.push("dispose") }); },
  };
  await waitForHr1Inbox(page, async () => calls.push("navigate"), expected);
  assert.deepEqual(calls, ["listen", "navigate", "ui", "dispose"]);
});
test("failed HTTP and rendered alerts fail the readiness gate", async () => {
  let uiReads = 0;
  const page = {
    waitForResponse: async () => ({ status: () => 503, json: async () => payload() }),
    waitForFunction: async () => { uiReads++; return { jsonValue: async () => ({ error: "UI failed" }), dispose: async () => {} }; },
  };
  await assert.rejects(waitForHr1Inbox(page, async () => {}, expected), /request failed/); assert.equal(uiReads, 0);
  page.waitForResponse = async () => ({ status: () => 200, json: async () => payload() });
  await assert.rejects(waitForHr1Inbox(page, async () => {}, expected), /UI failed/);
});
test("initial and reload use the same data/UI gate, preserving real-backend read-only proof", () => {
  const source = readFileSync(new URL("./e2e/hr1-production-vertical.browser.mjs", import.meta.url), "utf8");
  assert.doesNotMatch(source, /waitUntil: "networkidle"/);
  assert.equal((source.match(/await waitForHr1Inbox\(page/g) || []).length, 2);
  assert.match(source, /route\.fetch\(\{ url: `\$\{backendUrl\}/);
  assert.match(source, /route\.fulfill\(\{ response \}\)/);
  assert.equal((source.match(/await settleBackendReads\(\)/g) || []).length, 2);
  assert.match(source, /assert\.deepEqual\(mutationRequests, \[\]/);
  assert.match(source, /assert\.equal\(baselineAfterBrowser, baselineBeforeRead/);
  assert.match(source, /assert\.deepEqual\(runtimeErrors, \[\]/);
});

test("backend drain waits for independent and browser-canceled work to finish", async () => {
  const drain = createHr1BackendDrain(); let complete; let settled = false;
  const backend = drain.track("GET /calendar (browser canceled)", () => new Promise(done => { complete = done; }));
  const finish = drain.settle(async () => {}).then(() => { settled = true; });
  await new Promise(done => setImmediate(done));
  assert.equal(settled, false);
  complete(); await backend; await finish; assert.equal(settled, true);
});
test("dependent reads issued by rendering restart settlement rather than racing DB snapshot", async () => {
  const drain = createHr1BackendDrain(); let renders = 0, complete; let settled = false;
  const finish = drain.settle(async () => {
    if (++renders === 1) void drain.track("GET /dependent", () => new Promise(done => { complete = done; }));
  }).then(() => { settled = true; });
  await new Promise(done => setImmediate(done)); assert.equal(settled, false);
  complete(); await finish; assert.ok(renders >= 2);
});
test("failed proxy reads and bounded unsettled work cannot pass final no-write gate", async () => {
  const failed = createHr1BackendDrain();
  await assert.rejects(failed.track("GET /broken", async () => { throw new Error("transport failure"); }));
  await assert.rejects(failed.settle(async () => {}), /backend proxy failed/);
  const pending = createHr1BackendDrain(); let complete;
  const backend = pending.track("GET /never-ready", () => new Promise(done => { complete = done; }));
  await assert.rejects(pending.settle(async () => {}, 10), /reads did not settle: GET \/never-ready/);
  complete(); await backend;
});

test("HR1 uses isolated provider harness and audits outbound attempts", () => {
  const source = readFileSync(new URL("./e2e/hr1-production-vertical.browser.mjs", import.meta.url), "utf8");
  assert.match(source, /hr1_offline_harness_app:app/);
  assert.match(source, /assert\.deepEqual\(networkAudit.attempts, \[\]/);
  const harness = readFileSync(new URL("./e2e/hr1_offline_harness_app.py", import.meta.url), "utf8");
  assert.doesNotMatch(harness, /assemble_current_decision_inbox\s*=|hard_risk_evaluator\s*=/);
});
