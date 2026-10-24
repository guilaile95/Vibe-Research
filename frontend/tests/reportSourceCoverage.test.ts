import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { api, ApiError } from "../src/lib/api.ts";
import type { Report, ReportListResult, ReportSourceCoverage, SectorReportsDiscoveryResult } from "../src/lib/api/types.ts";
import { parseReportSourceCoverage, sectorReportCoverageView } from "../src/lib/reportSourceCoverage.ts";
import { reportEvidenceContext, reportEvidenceStatusText, resolveEvidenceList, resolveReportEvidence } from "../src/lib/stockDataEvidence.ts";

const report: Report = { title: "Retained provider report", publishDate: "2026-10-10", orgSName: "Synthetic institution", pdfUrl: "https://example.com/report.pdf" };
const coverage: ReportSourceCoverage = {
  scope: "provider_report_page_window", requested_pages: 2, reported_total_pages: 2, expected_pages: 2,
  attempted_pages: 2, received_pages: 2, returned_rows: 1, reason: null, historical_complete: false,
};
const partial = { ...coverage, attempted_pages: 2, received_pages: 1, reason: "SOURCE_ERROR" } satisfies ReportSourceCoverage;
const requests: { url: string; method: string; body?: BodyInit | null }[] = [];
let response: unknown;
let httpStatus = 200;
const realFetch = globalThis.fetch;
globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
  requests.push({ url: String(input), method: init?.method ?? "GET", body: init?.body });
  return new Response(JSON.stringify(response), { status: httpStatus, headers: { "Content-Type": "application/json" } });
}) as typeof fetch;
test.after(() => { globalThis.fetch = realFetch; });

function reply(body: unknown, status = 200) { response = body; httpStatus = status; requests.length = 0; }

test("mocked API preserves the legacy report array and exposes sibling coverage only in the new method", async () => {
  reply({ data: [report], status: "partial", source_coverage: partial });
  const legacy: Report[] = await api.reports("600000");
  const result: ReportListResult = await api.reportsWithCoverage("600000");
  assert.deepEqual(legacy, [report]);
  assert.deepEqual(result, { data: [report], status: "partial", source_coverage: partial });
  assert.deepEqual(requests.map(r => r.url), ["/api/reports?code=600000", "/api/reports?code=600000"]);
  assert.ok(requests.every(r => r.method === "GET" && r.body === undefined));
});

test("normal reports preserve the verified window and do not imply historical completeness", async () => {
  reply({ data: [report], status: "normal", source_coverage: coverage });
  const state = await resolveReportEvidence(api.reportsWithCoverage("600000"), "研报数据暂不可用");
  assert.equal(state.status, "success");
  assert.match(reportEvidenceStatusText(state), /本次请求页窗已返回.*不代表完整历史/);
  const context = reportEvidenceContext(state);
  assert.match(context, /"status":"normal"/);
  assert.match(context, /"historical_complete":false/);
  assert.match(context, /"expected_pages":2/);
  assert.match(context, /Retained provider report/);
});

test("source-to-UI and AI context retain partial rows, warning, reason and page counters", async () => {
  for (const reason of ["SOURCE_ERROR", "REQUEST_LIMIT", "UNKNOWN_TOTAL", "TOTAL_CHANGED", "EMPTY_BEFORE_EXPECTED", "MALFORMED_RESPONSE"] as const) {
    const window = { ...partial, reason };
    reply({ data: [report], status: "partial", source_coverage: window });
    const state = await resolveReportEvidence(api.reportsWithCoverage("600000"), "研报数据暂不可用");
    assert.equal(state.status, "partial");
    assert.deepEqual(state.data, [report]);
    assert.match(reportEvidenceStatusText(state), /本次接口返回 1 条记录；研报覆盖受限/);
    const context = reportEvidenceContext(state);
    for (const field of [report.title, report.orgSName, report.publishDate, report.pdfUrl!, reason, '"received_pages":1', '"attempted_pages":2', '"requested_pages":2', '"returned_rows":1']) {
      assert.ok(context.includes(field), field);
    }
    assert.match(context, /不代表完整历史.*不能据此判断没有记录/);
  }
});

test("missing metadata on populated and empty legacy responses stays unknown, including advertised normal", async () => {
  for (const data of [[report], []]) {
    for (const payload of [data, { data }, { data, status: "normal" }, { data, source_coverage: coverage }]) {
      reply(payload);
      const result = await api.reportsWithCoverage("600000");
      assert.equal(result.status, "partial");
      const state = await resolveReportEvidence(Promise.resolve(result), "研报数据暂不可用");
      assert.equal(state.status, "partial");
      assert.deepEqual(state.data, data);
      assert.match(reportEvidenceContext(state), /研报覆盖受限.*不能据此判断没有记录/);
    }
  }
});

test("malformed coverage cannot upgrade a response or leak uncontrolled source metadata", async () => {
  for (const patch of [{ historical_complete: true }, { requested_pages: "2" }, { received_pages: 3 }, { reason: "https://private-provider/?key=secret" }, { expected_pages: -1 }, { scope: "full_history" }]) {
    assert.equal(parseReportSourceCoverage({ ...coverage, ...patch }), null);
    reply({ data: [report], status: "normal", source_coverage: { ...coverage, ...patch } });
    const state = await resolveReportEvidence(api.reportsWithCoverage("600000"), "研报数据暂不可用");
    assert.equal(state.status, "partial");
    assert.match(reportEvidenceContext(state), /覆盖范围未知/);
    assert.doesNotMatch(reportEvidenceContext(state), /private-provider|key=secret/);
  }
  for (const patch of [{ reported_total_pages: null }, { reported_total_pages: 3 }, { received_pages: 1 }, { expected_pages: 0 }, { reason: "REQUEST_LIMIT" }]) {
    reply({ data: [report], status: "normal", source_coverage: { ...coverage, ...patch } });
    assert.equal((await api.reportsWithCoverage("600000")).status, "partial");
  }
  reply({ data: [report], status: "partial", source_coverage: { ...coverage, reason: "EMPTY_BEFORE_EXPECTED" } });
  const earlyEmpty = await resolveReportEvidence(api.reportsWithCoverage("600000"), "研报数据暂不可用");
  assert.equal(earlyEmpty.status, "partial");
  assert.match(reportEvidenceStatusText(earlyEmpty), /预期 2 页.*收到 2 页.*结束前出现空页/);
});

test("malformed/no usable report failures reject with 502 and show sanitized failure rather than empty success", async () => {
  for (const body of [null, {}, { data: null }, { data: {} }, { data: [null] }, { data: [{ title: {} }] }, { data: [{ title: "" }] }, { data: [{ title: "  " }] }]) {
    reply(body);
    await assert.rejects(api.reportsWithCoverage("600000"), (error: unknown) => error instanceof ApiError && error.status === 502);
  }
  reply({ detail: "private provider request error" }, 502);
  const state = await resolveReportEvidence(api.reportsWithCoverage("600000"), "研报数据暂不可用");
  assert.equal(state.status, "error");
  assert.deepEqual(state.data, []);
  assert.match(reportEvidenceContext(state), /暂不可用；不能据此判断没有记录/);
  assert.doesNotMatch(reportEvidenceContext(state), /private provider|本次接口返回 0 条/);
});

test("empty verified page window is bounded and unavailable payload cannot masquerade as normal", async () => {
  reply({ data: [], status: "normal", source_coverage: { ...coverage, reported_total_pages: 0, expected_pages: 1, attempted_pages: 1, received_pages: 1, returned_rows: 0 } });
  const state = await resolveReportEvidence(api.reportsWithCoverage("600000"), "研报数据暂不可用");
  assert.equal(state.status, "success");
  assert.match(reportEvidenceContext(state), /本次接口返回 0 条记录.*不代表完整历史/);
  assert.match(reportEvidenceStatusText(state), /预期 1 页.*收到 1 页.*上游总页数 0/);
  reply({ data: [], status: "unavailable", source_coverage: { ...partial, received_pages: 0, returned_rows: 0 } });
  const unavailable = await resolveReportEvidence(api.reportsWithCoverage("600000"), "研报数据暂不可用");
  assert.equal(unavailable.status, "error");
  assert.match(reportEvidenceContext(unavailable), /"status":"unavailable".*"received_pages":0/);
  assert.equal((await resolveEvidenceList(Promise.resolve([]), "公告数据暂不可用")).status, "success");
});

test("sector API keeps per-source coverage and discovery/import authority unchanged", async () => {
  const discovered = { source_provider: "eastmoney", external_id: "synthetic-report", info_code: "synthetic-report", title: report.title, institution: report.orgSName, publish_date: report.publishDate };
  const data: SectorReportsDiscoveryResult = {
    sector_key: "pcb", discovered: [discovered], filtered: [discovered], error: null,
    status: "partial", source_coverage: [{ ...coverage, source_key: "industry", status: "normal" }, { ...partial, source_key: "company:600000", status: "partial" }],
    total_discovered: 1, returned: 1, truncated: false,
  };
  reply({ data });
  const result = await api.discoverSectorReports("pcb", { scope: "all", maxPages: 2 });
  assert.deepEqual(result, data);
  const view = sectorReportCoverageView(result);
  assert.equal(view.status, "partial");
  assert.match(view.notice, /来源 1.*来源 2.*部分来源请求失败/);
  assert.match(view.emptyText, /不能据此判断没有匹配研报/);
  assert.match(requests[0].url, /max_pages=2&scope=all/);
  reply({ data: { id: "saved", external_id: "synthetic-report" } });
  await api.importSectorReport("pcb", "synthetic-report");
  assert.equal(requests[0].method, "POST");
  assert.deepEqual(JSON.parse(String(requests[0].body)), { external_id: "synthetic-report" });
});

test("sector empty-state formatter fails closed for legacy, missing, partial and unavailable coverage", () => {
  for (const value of [{}, { status: "normal" }, { status: "normal", source_coverage: [] }, { status: "partial", source_coverage: [partial] }, { status: "unavailable", source_coverage: [partial] }, { status: "normal", source_coverage: [{ ...coverage, status: "unavailable" }] }] satisfies Pick<SectorReportsDiscoveryResult, "status" | "source_coverage">[]) {
    const view = sectorReportCoverageView(value);
    assert.notEqual(view.status, "normal");
    assert.match(view.emptyText, /覆盖受限或未知.*不能据此判断没有匹配研报/);
    assert.doesNotMatch(view.emptyText, /^未发现匹配研报/);
    assert.match(view.notice, /不代表完整历史/);
  }
  const normal = sectorReportCoverageView({ status: "normal", source_coverage: [coverage] });
  assert.equal(normal.status, "normal");
  assert.match(normal.emptyText, /本次已查询页窗内.*不代表完整历史/);
  for (const status of [undefined, "partial", "unavailable"] as const) {
    const view = sectorReportCoverageView({ status, source_coverage: [{ ...coverage, status: "normal" }] });
    assert.notEqual(view.status, "normal");
    assert.match(view.notice, /覆盖受限或未知|来源暂不可用/);
    assert.match(view.notice, /不能据此判断没有匹配研报/);
  }
});

test("coverage UI wiring retains partial rows and existing stale-run guard with shared context warning", () => {
  const stock = readFileSync(new URL("../src/pages/StockData.tsx", import.meta.url), "utf8");
  assert.match(stock, /resolveReportEvidence\(context\.read\("reportsWithCoverage", signal => api\.reportsWithCoverage\(c, signal\)\).*\.then\(ok\(setReportResult\)\)/);
  assert.match(stock, /rid === runIdRef\.current && !context\.signal\.aborted\) set\(v\)/);
  assert.match(stock, /reportEvidenceStatusText\(reportResult\)/);
  assert.match(stock, /reportEvidenceContext\(reportResult\)/);
  assert.match(stock, /reports\.slice\(0, 12\)\.map/);
  assert.match(stock, /reportResult.status === "partial" \? `（\$\{reports.length\}）`/);
  const sector = readFileSync(new URL("../src/components/sectors/SectorReportDiscoveryPanel.tsx", import.meta.url), "utf8");
  assert.match(sector, /setCoverage\(\{ status: result.status, source_coverage: result.source_coverage \}\)/);
  assert.match(sector, /\{coverageView.emptyText\}/);
  assert.match(sector, /\{coverageView.notice\}/);
  assert.doesNotMatch(sector, />未发现匹配研报/);
  assert.match(sector, /api\.importSectorReport\(sectorKey, ext\)/);
});
