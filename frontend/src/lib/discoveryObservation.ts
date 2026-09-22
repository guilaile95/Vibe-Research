import { formatFinancialAmount } from "./fundamentalHealthView.ts";
import { formatMatrixPercent } from "./sectorIndustryMatrix.ts";
import { formatPrice, formatVolumeRatio } from "./technicalIndicatorsView.ts";

type Unit = "ratio" | "percent" | "amount" | "price" | "multiple" | "volumeRatio";

// Exact discovery_service observation codes and their source metric names.
// RDP returns / MA distances are fractions; snapshot day changes and turnover
// already contain percentages. Never infer a unit from a suffix or label.
const SCALAR_UNITS: Readonly<Record<string, Unit | undefined>> = {
  positive_return_20d: "ratio",
  positive_return_60d: "ratio",
  return_5d: "ratio",
  return_20d: "ratio",
  return_60d: "ratio",
  close_vs_ma20: "ratio",
  close_vs_ma60: "ratio",
  positive_session_momentum: "percent",
  turnover_in_active_market_quartile: "percent",
  sector_context_supportive: "percent",
  sector_supportive: "percent",
  sector_weak: "percent",
  sector_unknown: "percent",
  change_pct: "percent",
  turnover_pct: "percent",
  average_change_pct: "percent",
  market_average_change_pct: "percent",
  liquidity_at_or_above_market_median: "amount",
  amount: "amount",
  market_cap: "amount",
  float_market_cap: "amount",
  price: "price",
  latest_close: "price",
  ma20: "price",
  ma60: "price",
  pe_ttm: "multiple",
  pb: "multiple",
  volume_ratio: "volumeRatio",
  volume_ratio_20d: "volumeRatio",
};

// Scope fields to the backend object that defines them. An unknown observation
// containing a familiar key must not silently inherit that key's unit.
const FACT_UNITS: Readonly<Record<string, Readonly<Record<string, Unit | undefined>> | undefined>> = {
  basic_valuation_available: { pe_ttm: "multiple", pb: "multiple" },
  fundamental_fact_available: {
    // astock.financials passes through THS summary percentages without / 100.
    revenue_yoy: "percent",
    net_profit_yoy: "percent",
    roe: "percent",
    operating_cash_flow: "amount",
  },
};

/** Preserve the observation shape and unknown values for the existing renderer. */
export function formatDiscoveryObservationValue(
  code: string,
  value: unknown,
  fieldPath: readonly string[] = [],
): unknown {
  if (value == null) return "未知";
  if (typeof value === "number") {
    if (!Number.isFinite(value)) return "未知";
    const normalizedCode = code.toLowerCase();
    const unit = fieldPath.length === 0
      ? SCALAR_UNITS[normalizedCode]
      : fieldPath.length === 1 ? FACT_UNITS[normalizedCode]?.[fieldPath[0]] : undefined;
    switch (unit) {
      case "ratio": return Number.isFinite(value * 100) ? formatMatrixPercent(value, true) : "未知";
      case "percent": return formatMatrixPercent(value);
      case "amount": return formatFinancialAmount(value);
      case "price": return `${formatPrice(value)} 元`;
      case "multiple": return `${formatPrice(value)} 倍`;
      case "volumeRatio": return formatVolumeRatio(value);
      default: return value;
    }
  }
  if (Array.isArray(value)) {
    return value.map((entry, index) => formatDiscoveryObservationValue(code, entry, [...fieldPath, String(index)]));
  }
  if (typeof value === "object") {
    return Object.fromEntries(Object.entries(value).map(([key, fact]) => [
      key, formatDiscoveryObservationValue(code, fact, [...fieldPath, key]),
    ]));
  }
  return value;
}
