import type { PortfolioRiskContext } from "./api/types.ts";

export function formatRiskPercent(value: number | null | undefined): string {
  return typeof value === "number" && Number.isFinite(value) ? `${value.toFixed(2)}%` : "—";
}

export function formatRiskMoney(value: number | null | undefined): string {
  return typeof value === "number" && Number.isFinite(value) ? `¥${value.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : "—";
}

export function riskContextStatusLabel(status: string): string {
  return {
    NORMAL: "当前事实可读",
    PARTIAL: "部分可读",
    UNAVAILABLE: "当前不可用",
    COMPLETE: "完整覆盖",
    AVAILABLE: "可用",
    UNKNOWN: "不可完整评估",
    EMPTY: "暂无持仓",
  }[status] ?? status;
}

export function isLegacyPositionAuthority(context: PortfolioRiskContext): boolean {
  return context.position_authority_state === "LEGACY" || context.position_context.authority_state === "LEGACY";
}

export function positionAuthorityLabel(context: PortfolioRiskContext): string {
  if (isLegacyPositionAuthority(context)) return "Legacy fallback";
  if (context.position_authority_state === "CANONICAL" && context.position_context.authority_state === "CANONICAL") {
    return "Canonical Position Reality";
  }
  return context.position_authority_state || "Unknown authority";
}

export function buildRiskContextCapabilities(context: PortfolioRiskContext) {
  return {
    singleTrade: context.single_trade_risk_budget_capability.status === "IMPLEMENTED_IN_PRE_ENTRY_CANDIDATE_FLOW",
    portfolioAggregated: context.portfolio_aggregated_risk_budget.status === "NOT_EVALUATED" ? "尚不可完整评估" : context.portfolio_aggregated_risk_budget.status,
    drawdownUnavailable: context.drawdown.status === "UNAVAILABLE_NO_OFFICIAL_NAV_HISTORY",
    stressDeferred: context.stress_test.status === "DEFERRED_NO_ACCEPTED_SCENARIO_CONTRACT",
    hasRiskScore: false,
    hasRecommendation: false,
  };
}

export function hasCompleteConcentration(context: PortfolioRiskContext): boolean {
  return context.quote_coverage.complete && context.security_concentration.status === "COMPLETE" && context.security_concentration.evaluable;
}
