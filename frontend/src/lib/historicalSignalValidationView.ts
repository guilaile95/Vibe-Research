import type { HistoricalSignalValidationWindow } from "./api/types";

export function validationStatusLabel(status: string): string {
  return {
    EVALUATED: "已评估",
    IMMATURE: "窗口未成熟",
    MISSING_EXIT: "退出值缺失",
    EXCLUDED_UNKNOWN_PRIOR: "先验未知，排除",
  }[status] || status;
}

export function benchmarkNegativeSummary(window: HistoricalSignalValidationWindow): { count: number; ratio: number } | null {
  const valid = window.excess_return?.count ?? 0;
  if (!valid || window.failures == null) return null;
  return { count: window.failures, ratio: +(window.failures / valid * 100).toFixed(2) };
}

export function metricText(value: number | null | undefined): string {
  return value == null ? "—" : `${value.toFixed(4)}%`;
}
