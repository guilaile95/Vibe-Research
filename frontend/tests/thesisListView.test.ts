import assert from "node:assert/strict";
import test from "node:test";
import { parseThesisListQuery, thesisFilterQuery, thesisLifecycleLabel, thesisRevisionLabel } from "../src/lib/thesisListView.ts";

test("thesis subject pair and tracking status validation is fail-closed", () => {
  for (const search of ["subject_type=stock", "subject_id=000001", "subject_type=invalid&subject_id=x", "status=frozen", "status=__proto__"]) {
    assert.ok(parseThesisListQuery(new URLSearchParams(search)).error, search);
  }
  for (const status of ["active", "weakened", "invalidated", "archived"]) {
    const query = parseThesisListQuery(new URLSearchParams({ status }));
    assert.equal(query.error, null);
    assert.equal(query.status, status);
    assert.equal(query.subjectType, "");
  }
});
test("filters preserve origin, reset page, and round-trip status from URL", () => {
  const current = new URLSearchParams("from=stock-data&subject_type=stock&subject_id=000001&status=active&page=2");
  const next = thesisFilterQuery(current, "stock", " 000002 ", "archived");
  assert.equal(next.get("from"), "stock-data");
  assert.equal(next.has("page"), false);
  assert.equal(next.get("subject_id"), "000002");
  assert.equal(parseThesisListQuery(next).status, "archived");
  assert.equal(parseThesisListQuery(current).status, "active");
  assert.equal(thesisFilterQuery(current, "", "", "").toString(), "from=stock-data");
});
test("formal lifecycle is independent of business status and revision numbers", () => {
  assert.equal(thesisLifecycleLabel({ formal_state: "draft" }), "正式草稿 · 未确认");
  assert.equal(thesisLifecycleLabel({ formal_state: "confirmed" }), "已确认 · 尚未冻结");
  assert.equal(thesisLifecycleLabel({ formal_state: "frozen" }), "已冻结");
  assert.equal(thesisLifecycleLabel({ formal_state: null }), "旧版记录 · 未进入正式流程");
  assert.equal(thesisLifecycleLabel({} as { formal_state: null }), "旧版记录 · 未进入正式流程");
  assert.equal(thesisRevisionLabel(4), "v4");
  for (const value of [null, undefined, 0, -1, 1.5, NaN]) assert.equal(thesisRevisionLabel(value), "未知");
});
