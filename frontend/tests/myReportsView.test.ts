import assert from "node:assert/strict";
import test from "node:test";

import {
  filterReports,
  groupReportsByIndustry,
  groupReportsByInstitution,
  groupReportsByYearMonth,
  sortReportsByEffectiveDate,
  UNKNOWN_DATE_KEY,
  type ReportViewItem,
} from "../src/lib/myReportsView.ts";

function r(partial: Partial<ReportViewItem> & { id: string }): ReportViewItem {
  return { ...partial, id: partial.id };
}

const SAMPLE: ReportViewItem[] = [
  r({
    id: "1",
    title: "PCB 行业",
    industry: "电子",
    institution: "中信",
    publish_date: "2025-06-15",
    sector_keys: ["pcb"],
  }),
  r({
    id: "2",
    title: "AI 算力",
    industry: "电子",
    institution: "国君",
    publish_date: "2025-06-01",
    sector_keys: ["ai-computing"],
  }),
  r({
    id: "3",
    title: "PCB 公司",
    industry: "通信",
    institution: "中信",
    publish_date: "2024-12-01",
    sector_keys: ["pcb", "optical"],
  }),
  r({
    id: "4",
    title: "无日期",
    industry: "电子",
    institution: "",
    sector_keys: ["pcb"],
  }),
  r({
    id: "5",
    title: "同月后发",
    industry: "电子",
    institution: "中信",
    publish_date: "2025-06-20",
    sector_keys: ["pcb"],
  }),
];

test("filter by sector", () => {
  const out = filterReports(SAMPLE, { sector: "pcb" });
  assert.deepEqual(out.map((x) => x.id).sort(), ["1", "3", "4", "5"]);
});

test("filter by institution", () => {
  const out = filterReports(SAMPLE, { institution: "中信" });
  assert.deepEqual(out.map((x) => x.id).sort(), ["1", "3", "5"]);
});

test("filter by year and month", () => {
  const byYear = filterReports(SAMPLE, { year: "2025" });
  assert.deepEqual(byYear.map((x) => x.id).sort(), ["1", "2", "5"]);
  const byMonth = filterReports(SAMPLE, { year: "2025", month: "2025-06" });
  assert.deepEqual(byMonth.map((x) => x.id).sort(), ["1", "2", "5"]);
});

test("filter unknown date bucket", () => {
  const out = filterReports(SAMPLE, { year: UNKNOWN_DATE_KEY });
  assert.equal(out.length, 1);
  assert.equal(out[0].id, "4");
});

test("group counts match filtered list", () => {
  const filtered = filterReports(SAMPLE, { sector: "pcb" });
  const byIndustry = groupReportsByIndustry(filtered);
  const industryTotal = byIndustry.reduce((s, g) => s + g.count, 0);
  assert.equal(industryTotal, filtered.length);

  const byInst = groupReportsByInstitution(filtered);
  const instTotal = byInst.reduce((s, g) => s + g.count, 0);
  assert.equal(instTotal, filtered.length);

  const byYm = groupReportsByYearMonth(filtered);
  const ymTotal = byYm.reduce((s, g) => s + g.count, 0);
  assert.equal(ymTotal, filtered.length);
});

test("0 results → empty groups arrays", () => {
  const empty: ReportViewItem[] = [];
  assert.deepEqual(groupReportsByIndustry(empty), []);
  assert.deepEqual(groupReportsByInstitution(empty), []);
  assert.deepEqual(groupReportsByYearMonth(empty), []);
  assert.deepEqual(filterReports(empty, { sector: "pcb" }), []);
});

test("sort by publish_date desc within month", () => {
  const filtered = filterReports(SAMPLE, { year: "2025", month: "2025-06" });
  const sorted = sortReportsByEffectiveDate(filtered);
  assert.deepEqual(sorted.map((x) => x.id), ["5", "1", "2"]);

  const groups = groupReportsByYearMonth(filtered);
  const y2025 = groups.find((g) => g.key === "2025");
  assert.ok(y2025);
  const m = y2025!.months.find((m) => m.key === "2025-06");
  assert.ok(m);
  assert.deepEqual(m!.reports.map((x) => x.id), ["5", "1", "2"]);
});

test("unknown date bucket appears at end of year-month groups", () => {
  const groups = groupReportsByYearMonth(SAMPLE);
  const unknown = groups.find((g) => g.key === UNKNOWN_DATE_KEY);
  assert.ok(unknown);
  assert.equal(unknown!.unknownDate, true);
  assert.equal(unknown!.count, 1);
  assert.equal(unknown!.reports[0].id, "4");
  assert.equal(groups[groups.length - 1].key, UNKNOWN_DATE_KEY);
});
