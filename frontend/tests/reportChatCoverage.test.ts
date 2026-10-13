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

test("source identity, title and real or missing page pass unchanged to UI callbacks", () => {
  const items = [
    { report_id: "selected-pdf", title: "Selected PDF", page: 2 },
    { report_id: "selected-text", title: "Selected text", page: null },
  ];
  const state = createNdjsonProtocolState();
  let received;
  applyNdjsonLine(state, JSON.stringify({ type: "sources", items }), { onSources: value => { received = value; } });
  assert.deepEqual(received, items);
  assert.equal(state.sawError, false);
});

for (const page of [0, -1, 1.5, "2", undefined]) {
  test(`invalid source page ${String(page)} is rejected rather than invented`, () => {
    const state = createNdjsonProtocolState();
    applyNdjsonLine(state, JSON.stringify({ type: "sources", items: [{ report_id: "selected", title: "Selected", page }] }), {
      onSources: () => assert.fail("malformed citation must not reach the UI"),
    });
    assert.equal(state.sawError, true);
    assert.match(state.errorMessage!, /研报引用格式错误/);
  });
}

const pageMeta = {
  report_id: "selected", expected_file_sha256: "a".repeat(64), page_from: 2, page_to: 3,
  full_report_read: false, requested: [2, 3], returned_chars: 28,
  coverage: { readable: [2], omitted: [], invalid: [], unreadable: [3], error: [] },
  items: [{ page: 2, status: "readable", reason: "CHAR_TRUNCATED", returned_chars: 28, indexed_chars: 40, truncated: true },
    { page: 3, status: "unreadable", reason: "NO_INDEXED_PAGE_TEXT" }],
};
const pageCoverage = { ...coverage, selected_count: 1, matched_report_count: 1, included_report_count: 1,
  retrieved_hit_count: 1, included_hit_count: 1, uncovered_reports: [], context_truncated: true, page_context: pageMeta };

test("explicit-page metadata survives stream and history without storing source text", () => {
  const input = structuredClone(pageCoverage);
  Object.assign(input.page_context.items[0], { text: "DO NOT PERSIST RAW PAGE" });
  const parsed = parseReportChatCoverage(input)!;
  assert.deepEqual(parsed.page_context, pageMeta);
  assert.equal(JSON.stringify(parsed).includes("DO NOT PERSIST"), false);
  assert.deepEqual(parseReportChatCoverage(JSON.parse(JSON.stringify(parsed))), parsed);
  const state = createNdjsonProtocolState();
  applyNdjsonLine(state, JSON.stringify({ type: "sources", items: [{ report_id: "selected", title: "Title", page: 2 }], coverage: parsed }));
  assert.equal(state.sawError, false);
});

test("malformed page coverage, invented full-read and cross-report sources fail closed", () => {
  for (const patch of [{ full_report_read: true }, { returned_chars: 0 }, { page_to: 1000000000 },
    { requested: [2] }, { expected_file_sha256: "old" }, { coverage: { ...pageMeta.coverage, readable: [3] } }]) {
    assert.equal(parseReportChatCoverage({ ...pageCoverage, page_context: { ...pageMeta, ...patch } }), undefined);
  }
  for (const source of [{ report_id: "other", title: "Other", page: 2 }, { report_id: "selected", title: "Wrong page", page: 3 }]) {
    const state = createNdjsonProtocolState();
    applyNdjsonLine(state, JSON.stringify({ type: "sources", items: [source], coverage: pageCoverage }));
    assert.equal(state.sawError, true);
  }
});
