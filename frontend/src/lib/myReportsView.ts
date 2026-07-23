/**
 * My Reports 视图纯函数：筛选 / 分组 / 排序。
 * 页面所有分组与计数必须由同一份 filtered 列表派生。
 */

export type ReportViewItem = {
  id: string;
  name?: string;
  title?: string;
  industry?: string;
  institution?: string;
  publish_date?: string;
  imported_at?: string;
  sector_keys?: string[];
  ts?: number;
  [key: string]: unknown;
};

export type ReportFilters = {
  sector?: string;
  institution?: string;
  year?: string;
  month?: string;
};

export type YearMonthGroup = {
  key: string;
  label: string;
  count: number;
  months: { key: string; label: string; count: number; reports: ReportViewItem[] }[];
  reports: ReportViewItem[];
  /** 无有效日期 */
  unknownDate?: boolean;
};

export type NamedGroup = {
  key: string;
  label: string;
  count: number;
  reports: ReportViewItem[];
};

const UNKNOWN_DATE_KEY = "日期未确认";
const UNKNOWN_INST_KEY = "__unknown__";
const UNKNOWN_INST_LABEL = "未确认机构";

/** 有效排序日期：publish_date > imported_at > ts；均无则空。 */
export function effectiveDateParts(r: ReportViewItem): {
  year: string | null;
  month: string | null;
  sortKey: string;
} {
  const pd = (r.publish_date || "").trim();
  if (pd) {
    const year = pd.slice(0, 4);
    const month = pd.length >= 7 ? pd.slice(0, 7) : null;
    return { year, month, sortKey: pd };
  }
  const ia = (r.imported_at || "").trim();
  if (ia && ia.length >= 4) {
    const year = ia.slice(0, 4);
    const month = ia.length >= 7 ? ia.slice(0, 7) : null;
    return { year, month, sortKey: ia };
  }
  if (typeof r.ts === "number" && r.ts > 0) {
    try {
      const d = new Date(r.ts);
      if (!Number.isNaN(d.getTime()) && d.getFullYear() > 1970) {
        const y = String(d.getFullYear());
        const m = `${y}-${String(d.getMonth() + 1).padStart(2, "0")}`;
        return { year: y, month: m, sortKey: d.toISOString() };
      }
    } catch {
      /* ignore */
    }
  }
  return { year: null, month: null, sortKey: "" };
}

export function filterReports(
  reports: ReportViewItem[],
  filters: ReportFilters,
): ReportViewItem[] {
  return reports.filter((r) => {
    if (filters.sector && !(r.sector_keys ?? []).includes(filters.sector)) return false;
    if (filters.institution) {
      const inst = (r.institution || "").trim();
      const key = inst ? inst : UNKNOWN_INST_KEY;
      if (key !== filters.institution) return false;
    }
    if (filters.year || filters.month) {
      const { year, month } = effectiveDateParts(r);
      if (filters.year) {
        if (filters.year === UNKNOWN_DATE_KEY) {
          if (year) return false;
        } else if (year !== filters.year) {
          return false;
        }
      }
      if (filters.month && month !== filters.month) return false;
    }
    return true;
  });
}

/** 月内排序：publish_date ↓, imported_at ↓, ts ↓, id 兜底 */
export function sortReportsByEffectiveDate(reports: ReportViewItem[]): ReportViewItem[] {
  return [...reports].sort((a, b) => {
    const pa = (a.publish_date || "").trim();
    const pb = (b.publish_date || "").trim();
    if (pa !== pb) return pb.localeCompare(pa);
    const ia = (a.imported_at || "").trim();
    const ib = (b.imported_at || "").trim();
    if (ia !== ib) return ib.localeCompare(ia);
    const ta = typeof a.ts === "number" ? a.ts : 0;
    const tb = typeof b.ts === "number" ? b.ts : 0;
    if (ta !== tb) return tb - ta;
    return String(a.id).localeCompare(String(b.id));
  });
}

export function groupReportsByIndustry(reports: ReportViewItem[]): NamedGroup[] {
  const map = new Map<string, ReportViewItem[]>();
  for (const r of reports) {
    const key = (r.industry || "未分类").trim() || "未分类";
    const list = map.get(key) || [];
    list.push(r);
    map.set(key, list);
  }
  const groups: NamedGroup[] = [];
  for (const [key, list] of map) {
    groups.push({
      key,
      label: key,
      count: list.length,
      reports: sortReportsByEffectiveDate(list),
    });
  }
  groups.sort((a, b) => {
    if (a.key === "未分类") return 1;
    if (b.key === "未分类") return -1;
    if (b.count !== a.count) return b.count - a.count;
    return a.key.localeCompare(b.key, "zh-CN");
  });
  return groups;
}

export function groupReportsByInstitution(reports: ReportViewItem[]): NamedGroup[] {
  const map = new Map<string, { label: string; list: ReportViewItem[] }>();
  for (const r of reports) {
    const inst = (r.institution || "").trim();
    const key = inst ? inst : UNKNOWN_INST_KEY;
    const label = inst ? inst : UNKNOWN_INST_LABEL;
    const slot = map.get(key) || { label, list: [] };
    slot.list.push(r);
    map.set(key, slot);
  }
  const groups: NamedGroup[] = [];
  for (const [key, slot] of map) {
    groups.push({
      key,
      label: slot.label,
      count: slot.list.length,
      reports: sortReportsByEffectiveDate(slot.list),
    });
  }
  groups.sort((a, b) => {
    if (a.key === UNKNOWN_INST_KEY) return 1;
    if (b.key === UNKNOWN_INST_KEY) return -1;
    if (b.count !== a.count) return b.count - a.count;
    return a.label.localeCompare(b.label, "zh-CN");
  });
  return groups;
}

export function groupReportsByYearMonth(reports: ReportViewItem[]): YearMonthGroup[] {
  const yearMap = new Map<string, Map<string, ReportViewItem[]>>();
  const unknown: ReportViewItem[] = [];

  for (const r of reports) {
    const { year, month } = effectiveDateParts(r);
    if (!year) {
      unknown.push(r);
      continue;
    }
    if (!yearMap.has(year)) yearMap.set(year, new Map());
    const mMap = yearMap.get(year)!;
    const mKey = month || `${year}-??`;
    const list = mMap.get(mKey) || [];
    list.push(r);
    mMap.set(mKey, list);
  }

  const groups: YearMonthGroup[] = [];
  for (const [year, mMap] of yearMap) {
    const months = [...mMap.entries()]
      .map(([key, list]) => ({
        key,
        label: key,
        count: list.length,
        reports: sortReportsByEffectiveDate(list),
      }))
      .sort((a, b) => b.key.localeCompare(a.key));
    const all = sortReportsByEffectiveDate(
      months.flatMap((m) => m.reports),
    );
    groups.push({
      key: year,
      label: year,
      count: all.length,
      months,
      reports: all,
    });
  }
  groups.sort((a, b) => b.key.localeCompare(a.key));

  if (unknown.length) {
    groups.push({
      key: UNKNOWN_DATE_KEY,
      label: UNKNOWN_DATE_KEY,
      count: unknown.length,
      months: [],
      reports: sortReportsByEffectiveDate(unknown),
      unknownDate: true,
    });
  }
  return groups;
}

export { UNKNOWN_DATE_KEY, UNKNOWN_INST_KEY, UNKNOWN_INST_LABEL };
