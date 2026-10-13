import assert from "node:assert/strict";
import test from "node:test";
import { evidenceDateLabel, evidenceFilterQuery, evidencePageQuery, parseEvidenceListQuery } from "../src/lib/evidenceListView.ts";

test("subject filters must form a valid pair, including inbound links", () => {
  for (const search of ["subject_type=stock", "subject_id=600519", "subject_type=stock&subject_id=%20", "subject_type=toString&subject_id=x", "subject_type=__proto__&subject_id=x"]) {
    assert.ok(parseEvidenceListQuery(new URLSearchParams(search)).error, search);
  }
  for (const type of ["stock", "sector", "theme"]) {
    const query = parseEvidenceListQuery(new URLSearchParams(`subject_type=${type}&subject_id=%20sample%20&page=2`));
    assert.equal(query.error, null);
    assert.equal(query.subjectId, "sample");
    assert.equal(query.offset, 50);
  }
  assert.equal(parseEvidenceListQuery(new URLSearchParams()).error, null);
});

test("unsafe or malformed pagination cannot become an invalid API offset", () => {
  for (const value of ["0", "-1", "NaN", "Infinity", "1.5", "1e3", "9007199254740991", "", "junk"]) {
    assert.equal(parseEvidenceListQuery(new URLSearchParams({ page: value })).offset, 0, value);
  }
  assert.equal(parseEvidenceListQuery(new URLSearchParams("page=3")).offset, 100);
});

test("apply and clear preserve origin, reset page and do not mutate the current URL", () => {
  const current = new URLSearchParams("from=thesis&subject_type=stock&subject_id=old&page=3");
  const applied = evidenceFilterQuery(current, "theme", " new ");
  assert.equal(applied.get("from"), "thesis");
  assert.equal(applied.get("subject_type"), "theme");
  assert.equal(applied.get("subject_id"), "new");
  assert.equal(applied.has("page"), false);
  assert.equal(evidenceFilterQuery(current, "", "").toString(), "from=thesis");
  assert.equal(current.get("page"), "3");
});

test("pagination and detail return context can preserve the exact applied subject", () => {
  const current = new URLSearchParams("from=thesis&subject_type=sector&subject_id=A%26B");
  const next = evidencePageQuery(current, 2);
  assert.equal(next.get("subject_id"), "A&B");
  assert.equal(next.get("page"), "2");
  assert.equal(evidencePageQuery(next, 1).toString(), current.toString());
  const returned = new URLSearchParams({ return_to: `/evidence?${next}` }).get("return_to");
  assert.equal(returned, `/evidence?${next}`);
});

test("unknown and malformed dates never look verified or fall back to record time", () => {
  for (const value of [null, undefined, "", " "]) assert.equal(evidenceDateLabel(value), "未知");
  for (const value of ["not-a-date", "2026-02-30", "2026-99-12"]) assert.equal(evidenceDateLabel(value), "未知（日期无效）");
  assert.equal(evidenceDateLabel("2026-10-01"), "2026-10-01");
  assert.notEqual(evidenceDateLabel("2026-10-01T12:30:00Z"), "未知");
});
