import assert from "node:assert/strict";
import test from "node:test";
import { safeAnalysisSourceUrl, analysisCoverageReason, isCapturedAnalysisSources } from "../src/lib/analysisSources.ts";

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


test("malformed and legacy source snapshots fail closed", () => {
  const coverage = { enabled: true, available: 0, included: 0, omitted: 0, reason: "no_items" };
  const valid = { version: 1, status: "CAPTURED", submission_status: "RESPONSE_RECEIVED", items: [],
    coverage: { hotlist: coverage, rss: coverage, standalone: coverage } };
  assert.equal(isCapturedAnalysisSources(valid), true);
  for (const value of [undefined, {}, { ...valid, items: null }, { ...valid, items: [null] },
    { ...valid, coverage: {} }, { ...valid, submission_status: "SUCCESS" },
    { ...valid, coverage: { ...valid.coverage, rss: { ...coverage, included: 1 } } },
    { ...valid, coverage: { ...valid.coverage, rss: { ...coverage, included: NaN } } }]) {
    assert.equal(isCapturedAnalysisSources(value), false);
  }
});
