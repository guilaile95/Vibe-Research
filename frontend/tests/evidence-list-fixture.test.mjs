import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { evidenceReply, evidenceViewReady } from "./e2e/evidence-list.browser.mjs";

test("browser fixture has disjoint production-shaped pages and explicit missing provenance", () => {
  const first = evidenceReply(new URL("http://synthetic.invalid/api/evidence?limit=50&offset=0&subject_type=stock&subject_id=fast"));
  const last = evidenceReply(new URL("http://synthetic.invalid/api/evidence?limit=50&offset=50&subject_type=stock&subject_id=fast"));
  assert.equal(first.items.length, 50);
  assert.equal(first.total, 51);
  assert.equal(last.items.length, 1);
  assert.equal(last.offset, 50);
  assert.equal(first.items.some(row => row.id === last.items[0].id), false);
  assert.equal(first.items[0].source_date, null);
  assert.equal(first.items[0].source_title, "");
  assert.notEqual(first.items[0].created_at, null);
  assert.equal(first.items[0].subject_id, "fast");
});
test("browser fixture provides empty and out-of-range pages without fabricated evidence", () => {
  for (const query of ["subject_id=empty", "subject_id=fast&offset=100"]) {
    const result = evidenceReply(new URL(`http://synthetic.invalid/api/evidence?${query}`));
    assert.deepEqual(result.items, []);
  }
});

// Structural guard only; the exact accessible-name interaction is exercised by browser CI.
test("subject select has an explicit text-only label separate from its options", () => {
  const source = readFileSync(new URL("../src/pages/EvidenceList.tsx", import.meta.url), "utf8");
  assert.match(source, /<label htmlFor="evidence-subject-type">主体类型<\/label>/);
  assert.match(source, /<select id="evidence-subject-type"/);
  const browser = readFileSync(new URL("./e2e/evidence-list.browser.mjs", import.meta.url), "utf8");
  assert.match(browser, /getByLabel\("主体类型", \{ exact: true \}\)\.selectOption\("stock"\)/);
});

function readySnapshot(subject = "fast", page = 1) {
  return {
    pathname: "/evidence", subject, subjectType: subject ? "stock" : "", page, busy: "false",
    applied: subject ? `已应用：个股 / ${subject}` : "已应用：全部标的",
    status: `共 51 条 · 第 ${page} / 2 页 · 本页 ${page === 1 ? 50 : 1} 条`,
    firstId: `evidence-synthetic-${subject || "sample"}-${(page - 1) * 50}`,
  };
}

test("page 2 readiness rejects changed URL with page 1 DOM, loading, and stale first row", () => {
  const expected = { subject: "fast", page: 2, kind: "success" };
  const page2 = readySnapshot("fast", 2);
  assert.equal(evidenceViewReady(expected, { ...readySnapshot(), page: 2 }), false);
  assert.equal(evidenceViewReady(expected, { ...page2, busy: "true" }), false);
  assert.equal(evidenceViewReady(expected, { ...page2, firstId: "evidence-synthetic-fast-0" }), false);
  assert.equal(evidenceViewReady(expected, { ...page2, applied: "已应用：全部标的" }), false);
  assert.equal(evidenceViewReady(expected, page2), true);
});

test("Back, cancel and clear readiness requires matching route and committed subject/page", () => {
  const expected = { subject: "fast", page: 1, kind: "success" };
  const state = readySnapshot();
  for (const changed of [{ pathname: "/evidence/new" }, { subject: "empty" }, { page: 2 }, { subjectType: "" }]) {
    assert.equal(evidenceViewReady(expected, { ...state, ...changed }), false);
  }
  assert.equal(evidenceViewReady(expected, state), true);
  assert.equal(evidenceViewReady({ subject: "", page: 1, kind: "success" }, readySnapshot("")), true);
});

test("loading, empty and error readiness cannot be satisfied by previous success DOM", () => {
  for (const [kind, subject, heading] of [["error", "failed", "证据加载失败"], ["empty", "empty", "此筛选下暂无证据"]]) {
    const expected = { subject, page: 1, kind };
    const previous = readySnapshot(subject);
    assert.equal(evidenceViewReady(expected, previous), false);
    assert.equal(evidenceViewReady(expected, { ...previous, heading, status: undefined, firstId: undefined }), true);
    assert.equal(evidenceViewReady(expected, { ...previous, heading, busy: "true" }), false);
  }
  const expected = { subject: "slow", page: 1, kind: "loading" };
  const state = readySnapshot("slow");
  assert.equal(evidenceViewReady(expected, state), false);
  assert.equal(evidenceViewReady(expected, { ...state, busy: "true", status: "正在加载证据…" }), true);
});
