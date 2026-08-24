import type { SectorMarketContextItem } from "./api";

export function formatSectorPercent(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return `${value > 0 ? "+" : ""}${value.toFixed(2)}%`;
}

export function formatActivity(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return `${value.toFixed(2)}×`;
}

export function mappedSectorRows(items: SectorMarketContextItem[]): SectorMarketContextItem[] {
  return items
    .filter((item) => item.mapping_status === "mapped")
    .sort((a, b) => (a.rank_20d_within_mapped ?? Number.MAX_SAFE_INTEGER) - (b.rank_20d_within_mapped ?? Number.MAX_SAFE_INTEGER));
}
