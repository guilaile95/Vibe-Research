import assert from "node:assert/strict";
import test from "node:test";
import { safeAnalysisSourceUrl, analysisCoverageReason } from "../src/lib/analysisSources.ts";

test("original links only allow clean external http(s), including legacy payload defense", () => {
  for (const value of [null, "javascript:alert(1)", "data:text/html,x", "//evil.test", "/evidence/1", "https://u:p@example.com", "https://example.com\\@evil.test", "https://example.com\n/test", "https://["]) {
    assert.equal(safeAnalysisSourceUrl(value), null);
  }
  assert.equal(safeAnalysisSourceUrl("https://example.com/article"), "https://example.com/article");
});

test("coverage describes missing input rather than no insight", () => {
  assert.match(analysisCoverageReason("budget_exhausted"), /预算/);
  assert.match(analysisCoverageReason("disabled"), /未开启/);
  assert.match(analysisCoverageReason("no_items"), /候选输入/);
  assert.match(analysisCoverageReason("legacy_unknown"), /未保存/);
});
