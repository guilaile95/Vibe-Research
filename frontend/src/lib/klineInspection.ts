/** Exact-date inspection of the existing daily chart; never nearest-bar selection. */
export function moveInspectionDate(dates: readonly string[], selected: string | null, key: string): string | null {
  if (!dates.length) return null;
  if (key === "Home") return dates[0];
  if (key === "End") return dates[dates.length - 1];
  const index = selected == null ? -1 : dates.indexOf(selected);
  if (key === "ArrowRight") return dates[index < 0 ? 0 : Math.min(index + 1, dates.length - 1)];
  if (key === "ArrowLeft") return dates[index < 0 ? dates.length - 1 : Math.max(0, index - 1)];
  return selected;
}

export function inspectionContextKey(code: string, period: string, points: readonly unknown[]): string {
  return JSON.stringify([code, period, points]);
}

export function formatInspectionVolume(value: unknown): string {
  return typeof value === "number" && Number.isFinite(value) && value >= 0
    ? String(value) : "未知 / 无效";
}
