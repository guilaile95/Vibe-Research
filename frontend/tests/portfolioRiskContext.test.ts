import assert from "node:assert/strict";
import test from "node:test";
import type { PortfolioRiskContext } from "../src/lib/api/types.ts";
import { buildRiskContextCapabilities, formatRiskMoney, formatRiskPercent, hasCompleteConcentration, riskContextStatusLabel } from "../src/lib/portfolioRiskContext.ts";

function context(overrides: Partial<PortfolioRiskContext> = {}): PortfolioRiskContext {
  return {
    schema_version: "portfolio_risk_context.v0.1",
    status: "NORMAL",
    as_of: "2026-09-09T00:00:00Z",
    fetched_at: "2026-09-09T00:00:00Z",
    holding_count: 3,
    position_authority_state: "CANONICAL",
    securities: [],
    position_context: { status: "NORMAL", authority_state: "CANONICAL", holding_count: 3 },
    quote_coverage: { status: "COMPLETE", usable_holdings: 3, total_holdings: 3, complete: true, usable_market_value: 1000 },
    account_fact_status: {
      status: "CANONICAL",
      total_assets: { status: "CANONICAL", value: 1000, confirmation_id: "c1" },
      cash: { status: "CANONICAL", value: 200, confirmation_id: "c1" },
      confirmation_id: "c1",
    },
    security_concentration: { status: "COMPLETE", evaluable: true, reason_code: null, denominator_market_value: 1000, top1_pct: 50, top3_pct: 100, top5_pct: 100, holdings_ranked: [] },
    account_exposure: { status: "AVAILABLE", denominator: { value: 1000, source: "CONFIRMED_CURRENT_TOTAL_ASSETS_ONLY", authority_state: "CANONICAL", semantics: "CURRENT_MIXED_TIME_NOT_OFFICIAL_SETTLED_NAV" }, tracked_stock_market_value: 1000, tracked_stock_account_pct: 100, known_security_count: 3 },
    cash_buffer: { status: "AVAILABLE", value: 200, ratio_pct: 20, confirmation_id: "c1", reason_code: null, semantics: "SAME_CONFIRMATION_CURRENT_FACTS_ONLY" },
    industry_exposure: { status: "AVAILABLE", provider: "EASTMONEY_INDUSTRY_CURRENT", membership_semantics: "CURRENT_MEMBERSHIP_SNAPSHOT", denominator_market_value: 1000, items: [], reason_code: null },
    industry_coverage: { status: "AVAILABLE", total_holdings: 3, quote_usable_holdings: 3, industry_classified_holdings: 3, unknown_industry_holdings: 0, coverage_ratio: 1, provider: "EASTMONEY_INDUSTRY_CURRENT", membership_semantics: "CURRENT_MEMBERSHIP_SNAPSHOT", reason_code: null },
    single_trade_risk_budget_capability: { status: "IMPLEMENTED_IN_PRE_ENTRY_CANDIDATE_FLOW", policy_version: "candidate-risk-budget.v0.1", rates: { SHORT: 0.0075, SWING: 0.01, MEDIUM: 0.0125 }, rates_pct: { SHORT: 0.75, SWING: 1, MEDIUM: 1.25 }, source: "candidate_opportunity_projection", semantics: "SINGLE_TRADE_RISK_BUDGET" },
    portfolio_aggregated_risk_budget: { status: "NOT_EVALUATED", reason_code: "UNIVERSAL_ACTIVE_HOLDING_RISK_INPUT_NOT_AVAILABLE", semantics: "NO_PORTFOLIO_AGGREGATED_RISK_BUDGET" },
    drawdown: { status: "UNAVAILABLE_NO_OFFICIAL_NAV_HISTORY", nav_authority: "SETTLED_NAV_CANDIDATE", nav_canonical: false, message: "当前没有足够的正式 NAV 历史，不能可靠计算账户回撤。" },
    stress_test: { status: "DEFERRED_NO_ACCEPTED_SCENARIO_CONTRACT", message: "尚未定义经过确认的组合压力情景，因此不输出压力损失估计。" },
    limitations: [],
    writes: { formal_state: 0, account: 0, position: 0, trade: 0, portfolio: 0 },
    ...overrides,
  };
}

test("full current-risk context exposes top1/top3 and cash", () => {
  const value = context();
  assert.equal(hasCompleteConcentration(value), true);
  assert.equal(formatRiskPercent(value.security_concentration.top1_pct), "50.00%");
  assert.equal(formatRiskPercent(value.security_concentration.top3_pct), "100.00%");
  assert.equal(formatRiskPercent(value.cash_buffer.ratio_pct), "20.00%");
});

test("partial quote is not complete concentration", () => {
  const value = context({ quote_coverage: { ...context().quote_coverage, status: "PARTIAL", complete: false, usable_holdings: 2 }, security_concentration: { ...context().security_concentration, status: "PARTIAL", evaluable: false } });
  assert.equal(hasCompleteConcentration(value), false);
  assert.equal(riskContextStatusLabel(value.security_concentration.status), "部分可读");
});

test("account unavailable stays visible as an explicit state", () => {
  const value = context({ account_exposure: { ...context().account_exposure, status: "UNAVAILABLE", denominator: { ...context().account_exposure.denominator, value: null } } });
  assert.equal(formatRiskMoney(value.account_exposure.denominator.value), "—");
  assert.equal(riskContextStatusLabel(value.account_exposure.status), "当前不可用");
});

test("industry unavailable is a separate state", () => {
  const value = context({ industry_exposure: { ...context().industry_exposure, status: "UNAVAILABLE", items: [] } });
  assert.equal(riskContextStatusLabel(value.industry_exposure.status), "当前不可用");
});

test("unknown industry remains a displayable category", () => {
  const value = context({ industry_coverage: { ...context().industry_coverage, unknown_industry_holdings: 1, industry_classified_holdings: 2, coverage_ratio: 0.67 } });
  assert.equal(value.industry_coverage.unknown_industry_holdings, 1);
  assert.equal(formatRiskPercent((value.industry_coverage.coverage_ratio ?? 0) * 100), "67.00%");
});

test("cash zero is rendered as zero rather than unavailable", () => {
  const value = context({ cash_buffer: { ...context().cash_buffer, value: 0, ratio_pct: 0 } });
  assert.equal(formatRiskPercent(value.cash_buffer.ratio_pct), "0.00%");
});

test("null and zero formatting stay distinct", () => {
  assert.equal(formatRiskPercent(null), "—");
  assert.equal(formatRiskPercent(0), "0.00%");
  assert.equal(formatRiskMoney(null), "—");
  assert.match(formatRiskMoney(0), /¥0\.00/);
});

test("drawdown wording is unavailable without official NAV history", () => {
  const value = context();
  assert.equal(buildRiskContextCapabilities(value).drawdownUnavailable, true);
  assert.match(value.drawdown.message, /正式 NAV 历史/);
});

test("stress wording is deferred without scenario contract", () => {
  const value = context();
  assert.equal(buildRiskContextCapabilities(value).stressDeferred, true);
  assert.match(value.stress_test.message, /压力情景/);
});

test("no black-box score is exposed by the view model", () => {
  const capabilities = buildRiskContextCapabilities(context());
  assert.equal(capabilities.hasRiskScore, false);
});

test("no recommendation CTA is exposed by the view model", () => {
  const capabilities = buildRiskContextCapabilities(context());
  assert.equal(capabilities.hasRecommendation, false);
});

test("single-trade capability is reused from candidate flow", () => {
  assert.equal(buildRiskContextCapabilities(context()).singleTrade, true);
});

test("portfolio aggregated budget remains not evaluated", () => {
  assert.equal(buildRiskContextCapabilities(context()).portfolioAggregated, "尚不可完整评估");
});

test("existing context can report partial overall status", () => {
  const value = context({ status: "PARTIAL" });
  assert.equal(riskContextStatusLabel(value.status), "部分可读");
});

test("empty holdings status is not mislabeled unavailable", () => {
  const value = context({ status: "NORMAL", holding_count: 0, quote_coverage: { ...context().quote_coverage, status: "EMPTY", complete: false, usable_holdings: 0, total_holdings: 0 } });
  assert.equal(riskContextStatusLabel(value.quote_coverage.status), "暂无持仓");
});
