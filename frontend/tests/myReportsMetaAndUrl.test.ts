/**
 * MyReports 元数据清空语义 + URL 查询参数纯逻辑测试。
 * 不依赖 React 渲染：锁定 patch  body 构造与过滤/URL 参数行为。
 */
import assert from "node:assert/strict";
import { describe, it } from "node:test";

/** 与 api.patchReport 一致的 body 构造：undefined 不发送，"" 必须发送。 */
function buildPatchBody(meta: Record<string, unknown>): Record<string, unknown> {
  const keys = ["title", "institution", "publish_date", "sector_keys", "source_url", "source_kind"] as const;
  const body: Record<string, unknown> = {};
  for (const k of keys) {
    if (meta[k] !== undefined) body[k] = meta[k];
  }
  return body;
}

/** 与 MyReports URL 同步 effect 一致：保留 report + 过滤参数。 */
function buildSearchParams(opts: {
  report?: string;
  sector?: string;
  institution?: string;
  year?: string;
  month?: string;
}): string {
  const next = new URLSearchParams();
  if (opts.report) next.set("report", opts.report);
  if (opts.sector) next.set("sector", opts.sector);
  if (opts.institution) next.set("institution", opts.institution);
  if (opts.year) next.set("year", opts.year);
  if (opts.month) next.set("month", opts.month);
  return next.toString();
}

type ReportLike = {
  id: string;
  sector_keys?: string[];
  institution?: string;
  publish_date?: string;
  imported_at?: string;
  ts?: number;
};

function filterReports(
  reports: ReportLike[],
  filters: { sector?: string; institution?: string; year?: string; month?: string },
): ReportLike[] {
  return reports.filter((r) => {
    if (filters.sector && !(r.sector_keys ?? []).includes(filters.sector)) return false;
    if (filters.institution) {
      const inst = r.institution || "";
      if ((inst ? inst : "__unknown__") !== filters.institution) return false;
    }
    if (filters.year || filters.month) {
      let year: string | null = null;
      let month: string | null = null;
      if (r.publish_date) {
        year = r.publish_date.slice(0, 4);
        month = r.publish_date.slice(0, 7);
      } else if (r.imported_at) {
        year = r.imported_at.slice(0, 4);
        month = r.imported_at.slice(0, 7);
      } else if (r.ts) {
        year = new Date(r.ts).getFullYear().toString();
      }
      if (filters.year && year !== filters.year) return false;
      if (filters.month && month !== filters.month) return false;
    }
    return true;
  });
}

describe("patch body clear semantics", () => {
  it("sends empty strings to clear fields", () => {
    const body = buildPatchBody({
      title: "Keep",
      institution: "",
      publish_date: "",
      sector_keys: [],
      source_url: "",
      source_kind: "",
    });
    assert.equal(body.institution, "");
    assert.equal(body.publish_date, "");
    assert.equal(body.source_url, "");
    assert.deepEqual(body.sector_keys, []);
    assert.ok("institution" in body);
  });

  it("omits only undefined keys, not empty strings", () => {
    const body = buildPatchBody({ title: "T", institution: undefined });
    assert.equal(body.title, "T");
    assert.equal("institution" in body, false);
  });
});

describe("URL query params preserve report", () => {
  it("keeps report when filters change", () => {
    const s = buildSearchParams({ report: "abc123", sector: "pcb", year: "2025" });
    const p = new URLSearchParams(s);
    assert.equal(p.get("report"), "abc123");
    assert.equal(p.get("sector"), "pcb");
    assert.equal(p.get("year"), "2025");
  });

  it("report alone survives without filters", () => {
    const s = buildSearchParams({ report: "only-me" });
    assert.equal(s, "report=only-me");
  });
});

describe("report list filtering", () => {
  const seed: ReportLike[] = [
    { id: "1", sector_keys: ["pcb"], institution: "中信", publish_date: "2025-07-10" },
    { id: "2", sector_keys: ["pcb"], institution: "", publish_date: "2025-06-01" },
    { id: "3", sector_keys: ["ai-computing"], institution: "高盛", publish_date: "2024-12-20" },
  ];

  it("filters by sector", () => {
    assert.deepEqual(filterReports(seed, { sector: "pcb" }).map((r) => r.id), ["1", "2"]);
  });

  it("filters by institution including unknown bucket", () => {
    assert.deepEqual(filterReports(seed, { institution: "__unknown__" }).map((r) => r.id), ["2"]);
    assert.deepEqual(filterReports(seed, { institution: "中信" }).map((r) => r.id), ["1"]);
  });

  it("filters by year and month", () => {
    assert.deepEqual(filterReports(seed, { year: "2025" }).map((r) => r.id), ["1", "2"]);
    assert.deepEqual(filterReports(seed, { month: "2025-07" }).map((r) => r.id), ["1"]);
  });

  it("highlight id presence", () => {
    const filtered = filterReports(seed, { sector: "pcb" });
    assert.ok(filtered.some((r) => r.id === "1"));
    assert.equal(filtered.some((r) => r.id === "3"), false);
  });
});
