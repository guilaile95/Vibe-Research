export type CapitalFlowRowLike = {
  date?: string | null;
  main_net?: number | null;
};

export type SectorCapitalFlowSummary = {
  latestDate: string;
  latestMainNet: number;
  net5d: number;
  net20d: number;
  positiveDays20: number;
  sampleSize5: number;
  sampleSize20: number;
};

function finiteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

/**
 * Normalize and summarize representative-company main-capital flow rows.
 * Rows are ordered by date descending; malformed rows are ignored rather than
 * turning one upstream defect into a sector-level failure.
 */
export function summarizeSectorCapitalFlow(
  rows: readonly CapitalFlowRowLike[],
): SectorCapitalFlowSummary | null {
  const valid = rows
    .filter((row) => typeof row?.date === "string" && row.date.trim() && finiteNumber(row.main_net))
    .map((row) => ({ date: row.date!.trim(), mainNet: row.main_net! }))
    .sort((a, b) => b.date.localeCompare(a.date));

  if (valid.length === 0) return null;

  const recent20 = valid.slice(0, 20);
  const recent5 = recent20.slice(0, 5);
  const sum = (items: readonly { mainNet: number }[]) =>
    items.reduce((total, item) => total + item.mainNet, 0);

  return {
    latestDate: valid[0].date,
    latestMainNet: valid[0].mainNet,
    net5d: sum(recent5),
    net20d: sum(recent20),
    positiveDays20: recent20.filter((item) => item.mainNet > 0).length,
    sampleSize5: recent5.length,
    sampleSize20: recent20.length,
  };
}

export function formatCapitalFlowAmount(value: number): string {
  if (!Number.isFinite(value)) return "—";
  const normalized = Object.is(value, -0) ? 0 : value;
  const sign = normalized > 0 ? "+" : "";
  const abs = Math.abs(normalized);

  if (abs >= 100_000_000) {
    return `${sign}${(normalized / 100_000_000).toFixed(abs >= 1_000_000_000 ? 1 : 2)}亿`;
  }
  if (abs >= 10_000) {
    return `${sign}${(normalized / 10_000).toFixed(abs >= 1_000_000 ? 1 : 2)}万`;
  }
  return `${sign}${normalized.toFixed(0)}`;
}
