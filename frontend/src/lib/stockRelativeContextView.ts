export function formatStockRelativePercent(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(Number(value))) return "—";
  const number = Number(value);
  return `${number > 0 ? "+" : ""}${number.toFixed(2)}%`;
}

export function formatSampleCoverage(
  validCount: number,
  totalCount: number,
  coverage: number | null | undefined,
): string {
  const sample = `${validCount} / ${totalCount}`;
  if (coverage == null || !Number.isFinite(Number(coverage))) return sample;
  return `${sample}（${(Number(coverage) * 100).toFixed(1)}%）`;
}
