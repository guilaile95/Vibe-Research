import type { Financials } from "@/lib/api";

export type FundamentalHealthState = "normal" | "partial" | "empty" | "error";

export function financialObservationPresent(value: unknown): value is string | number {
  return typeof value === "number" ? Number.isFinite(value)
    : typeof value === "string" && value.trim().length > 0;
}

export function fundamentalHealthState(
  financials: Financials | null,
  error: string | null,
): FundamentalHealthState {
  if (error) return "error";
  if (!financials || (!financialObservationPresent(financials.revenue) && !financialObservationPresent(financials.net_profit))) return "empty";
  return financials.data_quality?.status === "partial" ? "partial" : "normal";
}

export function formatFinancialRatio(value: number | null | undefined): string {
  return value == null || !Number.isFinite(value) ? "未知" : `${(value * 100).toFixed(1)}%`;
}

export function formatFinancialAmount(
  value: number | null | undefined,
  currency = "CNY",
): string {
  if (value == null || !Number.isFinite(value)) return "未知";
  if (currency === "CNY") return `${(value / 1e8).toFixed(2)} 亿元`;
  return `${value.toLocaleString()} ${currency}`;
}
