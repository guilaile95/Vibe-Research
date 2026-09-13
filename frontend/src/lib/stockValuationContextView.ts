export function formatValuationNumber(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(Number(value))) return "—";
  return Number(value).toFixed(2);
}

export function formatValuationDelta(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(Number(value))) return "—";
  const number = Number(value);
  return `${number > 0 ? "+" : ""}${number.toFixed(2)}`;
}

export function formatPositiveRank(
  rank: number | null | undefined,
  total: number | null | undefined,
): string {
  if (rank == null || total == null || !Number.isFinite(Number(rank)) || !Number.isFinite(Number(total)) || Number(total) <= 0) {
    return "—";
  }
  return `${Number(rank)} / ${Number(total)}`;
}
