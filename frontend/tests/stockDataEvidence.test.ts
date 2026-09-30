import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import type { FundFlowRow, Report } from "../src/lib/api/types.ts";
import {
  resolveEvidenceList, evidenceListStatusText, reportEvidenceContext,
  announcementEvidenceContext, quoteEvidenceContext, summarizeStockFundFlow,
} from "../src/lib/stockDataEvidence.ts";

const report: Report = { title: "Synthetic report", publishDate: "2026-09-01", orgSName: "Synthetic institution", pdfUrl: "https://example.com/report.pdf" };

test("evidence sources distinguish pending, successful empty, populated, and rejected states", async () => {
  const empty = await resolveEvidenceList(Promise.resolve<Report[]>([]), "研报数据暂不可用");
  const success = await resolveEvidenceList(Promise.resolve([report]), "研报数据暂不可用");
  const failure = await resolveEvidenceList(Promise.reject(new Error("private provider detail")), "研报数据暂不可用");
  assert.equal(empty.status, "success");
  assert.equal(success.status, "success");
  assert.equal(failure.status, "error");
  assert.match(reportEvidenceContext(empty), /查询成功，返回 0 条/);
  assert.match(reportEvidenceContext(success), /Synthetic report/);
  assert.match(reportEvidenceContext(failure), /暂不可用；不能据此判断没有记录/);
  assert.doesNotMatch(reportEvidenceContext(failure), /private provider detail|近期研报：无|查询成功/);
  assert.match(evidenceListStatusText({ status: "loading", data: [] }), /加载中/);
  assert.match(evidenceListStatusText({ status: "idle", data: [] }), /尚未查询/);
});

test("report and announcement context retain supplied source, date and institution", () => {
  const context = reportEvidenceContext({ status: "success", data: [report] });
  for (const value of [report.publishDate, report.orgSName, report.pdfUrl!]) assert.ok(context.includes(value));
  const announcement = announcementEvidenceContext({ status: "success", data: [{ title: "Synthetic notice", date: "2026-08-31", type: "notice", url: "https://example.com/notice" }] });
  assert.match(announcement, /2026-08-31/);
  assert.match(announcement, /https:\/\/example.com\/notice/);
  assert.match(announcementEvidenceContext({ status: "error", data: [], error: "公告数据暂不可用" }), /不能据此判断没有记录/);
  assert.match(announcementEvidenceContext({ status: "loading", data: [] }), /加载中/);
  assert.match(announcementEvidenceContext({ status: "success", data: [] }), /查询成功，返回 0 条/);
});

test("quote provenance never borrows a composite valuation date", () => {
  assert.match(quoteEvidenceContext({ quote_source: "tencent", quote_data_time: "2026-09-01T15:00:00+08:00", quote_trade_date: "2026-09-01" }), /tencent.*2026-09-01T15:00:00\+08:00.*仅适用于报价/);
  assert.match(quoteEvidenceContext({}), /报价时间 未知.*报价交易日 未知/);
});

const flow = (date: string, main_net: number | null): FundFlowRow => ({ date, main_net, small_net: null, mid_net: null, large_net: null, super_net: null });
test("fundflow preserves actual zero and rejects incomplete or nonfinite totals", () => {
  assert.deepEqual(summarizeStockFundFlow([flow("2026-09-01", 0)]), { observed: 1, valid: 1, total: 0, latestDate: "2026-09-01" });
  for (const missing of [null, NaN, Infinity]) {
    const result = summarizeStockFundFlow([flow("2026-09-01", 10), flow("2026-09-02", missing)]);
    assert.equal(result.total, null);
    assert.equal(result.valid, 1);
    assert.equal(result.observed, 2);
  }
  assert.equal(summarizeStockFundFlow([]).total, null);
});

test("fundflow uses latest observations without mutating or filling missing dates", () => {
  const rows = Array.from({ length: 21 }, (_, i) => flow(`2026-09-${String(i + 1).padStart(2, "0")}`, i + 1));
  const result = summarizeStockFundFlow(rows);
  assert.equal(result.observed, 20);
  assert.equal(result.total, 230);
  assert.equal(result.latestDate, "2026-09-21");
  assert.equal(rows[0].date, "2026-09-01");
});

test("StockData wires guarded independent source requests to both UI and AI context", () => {
  const source = readFileSync(new URL("../src/pages/StockData.tsx", import.meta.url), "utf8");
  assert.match(source, /rid === runIdRef\.current\) set\(v\)/);
  assert.match(source, /resolveEvidenceList\(api\.reports\(c\).*\.then\(ok\(setReportResult\)\)/);
  assert.match(source, /resolveEvidenceList\(api\.announcements\(c\).*\.then\(ok\(setAnnouncementResult\)\)/);
  assert.match(source, /reportEvidenceContext\(reportResult\)/);
  assert.match(source, /announcementEvidenceContext\(announcementResult\)/);
  assert.match(source, /data-source-state=\{reportResult.status\}/);
  assert.match(source, /data-source-state=\{announcementResult.status\}/);
  assert.equal((source.match(/quoteEvidenceContext\(val\)/g) || []).length, 2);
  assert.match(source, /fundFlowSummary.total === null/);
  assert.doesNotMatch(source, /api\.(reports|announcements)\(c\)\.catch\(\(\) => \[\]\)/);
});
