import type { SectorIndustryContextData, SectorIndustryContextItem } from "./api";

export type SectorIndustrySortKey =
  | "member_aggregate_return_5d_pct"
  | "member_aggregate_return_20d_pct"
  | "up_ratio"
  | "above_ma20_ratio"
  | "turnover_pct_avg";

export function sectorIndustrySortValue(row: SectorIndustryContextItem, key: SectorIndustrySortKey): number | null {
  switch (key) {
    case "member_aggregate_return_5d_pct": return row.metrics.member_aggregate_return_5d_pct;
    case "member_aggregate_return_20d_pct": return row.metrics.member_aggregate_return_20d_pct;
    case "up_ratio": return row.breadth.up_ratio;
    case "above_ma20_ratio": return row.breadth.above_ma20_ratio;
    case "turnover_pct_avg": return row.participation.turnover_pct_avg;
  }
}

export function sortSectorIndustryRows(
  rows: SectorIndustryContextItem[],
  key: SectorIndustrySortKey,
  descending = true,
): SectorIndustryContextItem[] {
  return [...rows].sort((left, right) => {
    const a = sectorIndustrySortValue(left, key);
    const b = sectorIndustrySortValue(right, key);
    if (a == null && b == null) return left.industry_name.localeCompare(right.industry_name, "zh-CN");
    if (a == null) return 1;
    if (b == null) return -1;
    if (a !== b) return descending ? b - a : a - b;
    return left.industry_name.localeCompare(right.industry_name, "zh-CN");
  });
}

export function formatMatrixPercent(value: number | null | undefined, ratio = false): string {
  if (value == null || !Number.isFinite(value)) return "—";
  const display = ratio ? value * 100 : value;
  return `${display > 0 ? "+" : ""}${display.toFixed(2)}%`;
}

export function formatMatrixCount(value: number | null | undefined): string {
  return value == null || !Number.isFinite(value) ? "—" : String(value);
}

export function formatMatrixAmount(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "—";
  if (value >= 100_000_000) return `${(value / 100_000_000).toFixed(2)}亿`;
  if (value >= 10_000) return `${(value / 10_000).toFixed(2)}万`;
  return value.toFixed(0);
}

export function sectorIndustryMatrixState(
  data: SectorIndustryContextData | null,
  loading: boolean,
  error: boolean,
): "loading" | "error" | "unavailable" | "empty" | "normal" | "partial" {
  if (loading) return "loading";
  if (error) return "error";
  if (!data || data.status === "unavailable") return "unavailable";
  if (data.universe_status === "empty" || data.items.length === 0) return "empty";
  return data.status;
}
