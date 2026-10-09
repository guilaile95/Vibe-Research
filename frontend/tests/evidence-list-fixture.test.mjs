import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { evidenceReply } from "./e2e/evidence-list.browser.mjs";

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
