import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { mutateThesis } from "./e2e/thesis-mutation-readiness.mjs";

function harness({ status = 200, id = "thesis-a", revision = 2 } = {}) {
  const events = [];
  let predicate, commit;
  const committed = new Promise(resolve => { commit = resolve; });
  const page = {
    waitForResponse(match, options) {
      events.push("registered"); predicate = match;
      assert.equal(options.timeout, 15000);
      return Promise.resolve({ status: () => status, json: async () => ({ data: { thesis: { id, current_revision: revision } } }) });
    },
    locator(selector) {
      assert.equal(selector, "p");
      return { filter({ hasText }) {
        assert.equal(hasText.test("v2"), true);
        for (const stale of ["v1", "v20", "current v2"]) assert.equal(hasText.test(stale), false);
        return { waitFor(options) {
          events.push("commit-wait");
          assert.deepEqual(options, { state: "visible", timeout: 15000 });
          return committed;
        } };
      } };
    },
  };
  const button = { async click() { assert.equal(events[0], "registered"); events.push("click"); } };
  return { page, button, events, commit, predicate: () => predicate };
}

test("mutation readiness registers before click and cannot finish before committed DOM", async () => {
  const h = harness();
  let finished = false;
  const pending = mutateThesis(h.page, "thesis-a", "POST", "/api/thesis/thesis-a/evidence", h.button, 2)
    .then(result => { finished = true; return result; });
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(h.events, ["registered", "click", "commit-wait"]);
  assert.equal(finished, false);
  const response = (method, path) => ({ request: () => ({ method: () => method }), url: () => `http://fixture.invalid${path}` });
  assert.equal(h.predicate()(response("POST", "/api/thesis/thesis-a/evidence")), true);
  assert.equal(h.predicate()(response("GET", "/api/thesis/thesis-a/evidence")), false);
  assert.equal(h.predicate()(response("POST", "/api/thesis/thesis-b/evidence")), false);
  h.commit();
  assert.equal((await pending).thesis.id, "thesis-a");
});

for (const wrong of [{ status: 409 }, { id: "other-thesis" }, { revision: 1 }]) {
  test(`mutation readiness fails closed for ${JSON.stringify(wrong)}`, async () => {
    const h = harness(wrong);
    await assert.rejects(mutateThesis(h.page, "thesis-a", "PUT", "/api/thesis/thesis-a", h.button, 2));
    assert.equal(h.events.includes("commit-wait"), false);
  });
}

test("real-backend flow retains archive identity, frozen and duplicate-write checks without success sleeps", () => {
  const source = readFileSync(new URL("./e2e/evidence-thesis-real.browser.mjs", import.meta.url), "utf8");
  assert.match(source, /archiveResponse\.status\(\), 200/);
  assert.match(source, /archivePayload\.data\?\.thesis\?\.id, thesisId/);
  assert.match(source, /archivePayload\.data\?\.thesis\?\.status, "archived"/);
  assert.match(source, /getByText\("已归档，内容冻结。所有编辑\/关联\/取消关联\/归档操作均不可用。", \{ exact: true \}\)/);
  assert.match(source, /dupResp\.status !== 409/);
  assert.match(source, /aggFinal\.data\.thesis\.current_revision !== frozenRev/);
  assert.match(source, /Revision 2 should still contain evidence snapshot after delete/);
  const waits = source.split("\n").filter(line => line.includes("page.waitForTimeout("));
  assert.equal(waits.length, 1);
  assert.match(waits[0], /Reproduce the old decision point, not a success wait/);
});
