import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { thesisReply, thesisViewReady } from "./e2e/thesis-list.browser.mjs";

test("thesis browser fixtures preserve filtered status and distinguish record/frozen versions", () => {
  const first = thesisReply(new URL("http://synthetic.invalid/api/thesis?subject_id=fast&status=active&offset=0&limit=50"));
  const last = thesisReply(new URL("http://synthetic.invalid/api/thesis?subject_id=fast&status=active&offset=50&limit=50"));
  assert.equal(first.items.length, 50); assert.equal(last.items.length, 1);
  assert.equal(first.items[0].formal_state, "draft"); assert.equal(first.items[0].status, "active");
  assert.equal(first.items[2].current_revision, 5); assert.equal(first.items[2].frozen_revision, 2);
  assert.equal(last.items[0].id, "synthetic-fast-active-50");
  const archived = thesisReply(new URL("http://synthetic.invalid/api/thesis?subject_id=fast&status=archived"));
  assert.ok(archived.items.every(row => row.status === "archived"));
  assert.notEqual(archived.items[0].id, first.items[0].id);
});
test("thesis browser readiness rejects URL-first old DOM and stale tracking status", () => {
  const expected = { subject: "fast", tracking: "active", page: 2, kind: "success" };
  const ready = { pathname: "/thesis", subject: "fast", subjectType: "stock", tracking: "active", page: 2, busy: "false", applied: "已应用：个股 / fast · 生效中", status: "共 51 条 · 第 2 / 2 页 · 本页 1 条", firstId: "thesis-synthetic-fast-active-50" };
  assert.equal(thesisViewReady(expected, ready), true);
  for (const mismatch of [{ busy: "true" }, { status: "共 51 条 · 第 1 / 2 页 · 本页 50 条" }, { firstId: "thesis-synthetic-fast-active-0" }, { tracking: "archived" }, { applied: "已应用：个股 / fast · 已归档" }]) {
    assert.equal(thesisViewReady(expected, { ...ready, ...mismatch }), false);
  }
});

test("Thesis code field has a responsive minimum width with 320px browser coverage", () => {
  const component = readFileSync(new URL("../src/pages/ThesisList.tsx", import.meta.url), "utf8");
  const browser = readFileSync(new URL("./e2e/thesis-list.browser.mjs", import.meta.url), "utf8");
  assert.match(component, /min-w-\[10rem\] flex-1 sm:max-w-xs/);
  assert.match(browser, /\[1440, 390, 320\]/);
  assert.match(browser, /codeWidth >= 159/);
});
