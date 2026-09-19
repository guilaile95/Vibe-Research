import type { Financials } from "@/lib/api";

export const EARNINGS_SNAPSHOT_GROWTH_HEADING = "增长";
export const EARNINGS_SNAPSHOT_PROFITABILITY_HEADING = "盈利能力";
export const EARNINGS_SNAPSHOT_CASH_FLOW_QUALITY_HEADING = "现金流质量";
export const EARNINGS_SNAPSHOT_BALANCE_SHEET_QUALITY_HEADING = "资产负债表质量";
export const EARNINGS_SNAPSHOT_DATA_QUALITY_HEADING = "数据质量";

export type FundamentalHealthState = "normal" | "partial" | "empty" | "error";

export function fundamentalHealthState(
  financials: Financials | null,
  error: string | null,
): FundamentalHealthState {
  if (error) return "error";
  if (!financials || (!financials.revenue && !financials.net_profit)) return "empty";
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
