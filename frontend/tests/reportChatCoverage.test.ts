import assert from "node:assert/strict";
import test from "node:test";
import { applyNdjsonLine, createNdjsonProtocolState, type ReportChatCoverage } from "../src/lib/api.ts";
import { parseReportChatCoverage } from "../src/lib/reportChatCoverage.ts";

const coverage: ReportChatCoverage = {
  selected_count: 1, matched_report_count: 0, included_report_count: 0,
  retrieved_hit_count: 0, included_hit_count: 0, hit_limit: 8,
  hit_limit_reached: false, context_truncated: false, excerpt_only: true,
  uncovered_reports: [{ report_id: "selected", title: "行业研究", reason: "NO_MATCH", message: "未命中相关片段" }],
};

test("sources protocol delivers zero-hit coverage and hydrates it without losing titles or reasons", () => {
  const state = createNdjsonProtocolState();
  let received: ReportChatCoverage | undefined;
  applyNdjsonLine(state, JSON.stringify({ type: "sources", items: [], coverage }), {
    onSources: (items, value) => { assert.deepEqual(items, []); received = value; },
  });
  applyNdjsonLine(state, JSON.stringify({ type: "done" }));
  assert.equal(state.sawError, false);
  assert.equal(state.sawDone, true);
  assert.deepEqual(received, coverage);
  assert.deepEqual(parseReportChatCoverage(JSON.parse(JSON.stringify(received))), coverage);
  const omittedTitle = { ...coverage, uncovered_reports: [{ ...coverage.uncovered_reports[0], title: undefined }] };
  assert.equal(parseReportChatCoverage(omittedTitle)?.uncovered_reports[0].title, "selected");
});

test("legacy sources remain usable while malformed coverage is rejected at stream and storage boundaries", () => {
  const legacy = createNdjsonProtocolState();
  let delivered = false;
  applyNdjsonLine(legacy, JSON.stringify({ type: "sources", items: [{ report_id: "a", title: "旧报告", page: null }] }), {
    onSources: (items, value) => { delivered = true; assert.equal(items.length, 1); assert.equal(value, undefined); },
  });
  assert.equal(delivered, true);
  assert.equal(legacy.sawError, false);
  for (const invalid of [{ ...coverage, selected_count: "1" }, { ...coverage, uncovered_reports: [null] }]) {
    const state = createNdjsonProtocolState();
    applyNdjsonLine(state, JSON.stringify({ type: "sources", items: [], coverage: invalid }), {
      onSources: () => assert.fail("invalid coverage must not reach the component"),
    });
    assert.equal(state.sawError, true);
    assert.match(state.errorMessage!, /研报覆盖信息格式错误/);
    assert.equal(parseReportChatCoverage(invalid), undefined);
  }
});
