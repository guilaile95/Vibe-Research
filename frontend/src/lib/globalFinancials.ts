import type { GlobalMetrics } from "./api/types";

export function reportingCurrencyLabel(metrics: GlobalMetrics): string {
  return ({ CNY: "人民币", HKD: "港元", USD: "美元" } as Record<string, string>)[metrics.reporting_currency ?? ""] ?? "报告币种未知";
}

// A quote's listing currency never establishes the currency or scale of a report.
export function financialAmount(value: number | null, metrics: GlobalMetrics): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  const currency = reportingCurrencyLabel(metrics);
  const scale = metrics.amount_scale_to_currency_units;
  if (metrics.amount_unit !== "CURRENCY_UNITS" || typeof scale !== "number" || !Number.isFinite(scale) || scale <= 0) {
    return `${value.toLocaleString("zh-CN", { maximumFractionDigits: 8 })}（${currency}，原始值；金额单位比例未验证）`;
  }
  const amount = value * scale;
  if (!Number.isFinite(amount)) return "—";
  return Math.abs(amount) >= 1e8
    ? `${(amount / 1e8).toFixed(2)} 亿${currency}`
    : `${amount.toLocaleString("zh-CN", { maximumFractionDigits: 2 })} ${currency}`;
}

export function financialEps(value: number | null, metrics: GlobalMetrics): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  return `${value.toFixed(2)} ${reportingCurrencyLabel(metrics)}/股`;
}
