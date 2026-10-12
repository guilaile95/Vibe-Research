export type AnalyticsMode = "simulation" | "scenario" | "performance" | "ledger-performance";
export const analyticsModes: { id: AnalyticsMode; label: string }[] = [
  { id: "simulation", label: "假设策略模拟" },
  { id: "scenario", label: "风险与历史情景" },
  { id: "performance", label: "估值与资金收益" },
  { id: "ledger-performance", label: "正式账本只读投影" },
];
export type ResearchMetric = { status: string; value: number | null; reason?: string | null };
export function formatResearchNumber(value: unknown, percent = false): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "未定义";
  return percent ? `${(value * 100).toFixed(2)}%` : value.toLocaleString("zh-CN", { maximumFractionDigits: 4 });
}
export function parseAnalyticsInput(text: string): Record<string, unknown> {
  if (text.length > 4_000_000) throw new Error("输入超过 4 MB，请缩小窗口");
  const value: unknown = JSON.parse(text);
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("输入须为 JSON 对象");
  return value as Record<string, unknown>;
}
export const metricNames: Record<string, string> = {
  final_value: "期末净值", total_return: "区间收益", annual_return: "年化收益（短窗口不显示）",
  max_drawdown: "最大回撤", sharpe: "夏普（零无风险利率假设）", calmar: "卡玛", sortino: "索提诺",
  win_rate: "平仓胜率", profit_loss_ratio: "平均盈亏比", profit_factor: "盈利因子",
  max_consecutive_loss: "最大连续亏损平仓数", avg_holding_days: "平均持有交易时段", trade_count: "平仓交易数",
  benchmark_return: "同期基准收益", excess_return: "区间收益差", information_ratio: "信息比率",
  tracking_error: "跟踪误差", benchmark_beta: "基准贝塔", avg_turnover: "平均双边换手/2", total_turnover: "累计双边换手/2",
};
export const percentageMetrics = new Set(["total_return", "annual_return", "max_drawdown", "win_rate", "benchmark_return", "excess_return", "tracking_error", "avg_turnover", "total_turnover"]);

export type AnalyticsRow = Record<string, unknown>;
export type AnalyticsReport = {
  status: string; input_fingerprint: string; limitations: string[]; missing?: unknown[];
  metrics?: Record<string, ResearchMetric>; curve?: AnalyticsRow[]; fills?: AnalyticsRow[]; rejections?: AnalyticsRow[];
  open_positions?: AnalyticsRow[]; robustness?: AnalyticsRow[]; correlation?: AnalyticsRow[]; event_study?: AnalyticsRow[];
  twr?: number | null; mwr?: { status: string; reason?: string; annual_rate: number | null; period_return: number | null };
  risk_metrics?: Record<string, ResearchMetric>;
  total_return?: number | null; coverage?: AnalyticsRow; validation?: AnalyticsRow; scope?: string;
  historical_var_95?: ResearchMetric; max_drawdown?: ResearchMetric;
  realized_pnl?: number; unrealized_pnl?: number; total_fees?: number; dividend_entitlements?: number;
};
function object(value: unknown): value is AnalyticsRow { return !!value && typeof value === "object" && !Array.isArray(value); }
export function validResearchDay(value: unknown): value is string {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value) || value.startsWith("0000")) return false;
  const parsed = new Date(value + "T00:00:00.000Z");
  return Number.isFinite(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value;
}
function finiteOrNull(value: unknown) { return value === null || typeof value === "number" && Number.isFinite(value); }
function fail(): never { throw new Error("研究结果合同校验失败"); }
function boundedJson(value: unknown) {
  let nodes = 0;
  function visit(item: unknown, depth: number) {
    if (++nodes > 700_000 || depth > 15) fail();
    if (item === null || typeof item === "boolean") return;
    if (typeof item === "number") { if (!Number.isFinite(item)) fail(); return; }
    if (typeof item === "string") { if (item.length > 4096) fail(); return; }
    if (Array.isArray(item)) { if (item.length > 40_020) fail(); item.forEach(v => visit(v, depth + 1)); return; }
    if (!object(item) || Object.keys(item).length > 100) fail();
    for (const [key, v] of Object.entries(item)) { if (key.length > 120) fail(); visit(v, depth + 1); }
  }
  visit(value, 0);
}
function checkMetric(value: unknown): asserts value is ResearchMetric {
  if (!object(value) || !["SUPPORTED", "UNDEFINED", "UNSUPPORTED"].includes(String(value.status)) || !finiteOrNull(value.value)) fail();
  if (value.status === "SUPPORTED" && typeof value.value !== "number") fail();
  if (value.status !== "SUPPORTED" && value.value !== null) fail();
  if (value.reason !== undefined && value.reason !== null && typeof value.reason !== "string") fail();
}
export function parseAnalyticsReport(value: unknown, mode: AnalyticsMode): AnalyticsReport {
  boundedJson(value);
  if (!object(value) || value.schema_version !== "research-analytics.v1" || value.research_only !== true || value.formal_writes !== 0 ||
      value.historical_availability !== "NOT_PROVEN" || value.source_authentication !== "NOT_PROVEN" ||
      typeof value.input_fingerprint !== "string" || !/^[a-f0-9]{64}$/.test(value.input_fingerprint) ||
      typeof value.status !== "string" || !["CALCULATED", "MISSING_INPUTS", "UNDEFINED", "PARTIAL_COVERAGE"].includes(value.status) ||
      !Array.isArray(value.limitations) || value.limitations.length > 20 || !value.limitations.every(v => typeof v === "string")) fail();
  const scopes: Record<AnalyticsMode, string[]> = { simulation: ["HYPOTHETICAL_LONG_ONLY_CASH_ACCOUNT"], scenario: ["HYPOTHETICAL_INITIAL_WEIGHT_BUY_HOLD_REPLAY"], performance: ["WHOLE_ACCOUNT", "STOCK_BASKET"], "ledger-performance": ["STOCK_BASKET"] };
  if (value.scope !== undefined && (typeof value.scope !== "string" || !scopes[mode].includes(value.scope))) fail();
  if (value.currency !== undefined && !["CNY", "USD", "HKD"].includes(String(value.currency))) fail();
  if (["MISSING_INPUTS", "UNDEFINED"].includes(value.status) && (!Array.isArray(value.missing) || !value.missing.length)) fail();
  const allowed = new Set(["schema_version", "research_only", "formal_writes", "historical_availability", "source_authentication", "input_fingerprint", "limitations", "status", "missing", "metrics", "curve", "fills", "rejections", "open_positions", "completed_trades", "realized_pnl", "unrealized_pnl", "dividend_entitlements", "total_fees", "slippage_cost", "benchmark_missing", "benchmark_semantics", "pnl_reconciliation_error", "strategy_version", "robustness", "validation", "scope", "currency", "gross_target_weight", "residual_cash_target", "execution_contract", "metric_inventory", "twr", "mwr", "coverage", "flow_convention", "authority", "selected_trade_ids", "opening_snapshot_incorporates_trade_ids", "basket_codes", "whole_account_performance", "opening_convention", "gross_weight", "net_weight", "cash_weight", "leverage", "total_return", "covered_contribution", "correlation", "covariance", "risk_metrics", "factor_method", "historical_var_95", "max_drawdown", "event_study", "event_summary", "sample_returns", "methods", "risk_contribution", "risk_matrix_diagnostics"]);
  if (Object.keys(value).some(k => !allowed.has(k))) fail();
  if (value.missing !== undefined && (!Array.isArray(value.missing) || !value.missing.every(v => typeof v === "string" || object(v)))) fail();
  for (const key of ["curve", "fills", "rejections", "open_positions", "completed_trades", "robustness", "correlation", "covariance", "event_study"]) {
    if (value[key] !== undefined && (!Array.isArray(value[key]) || !(value[key] as unknown[]).every(object))) fail();
  }
  let previousDay = "";
  const curveKey = mode === "simulation" ? "nav" : mode === "scenario" ? "nav_index" : "twr_index";
  for (const row of (value.curve ?? []) as AnalyticsRow[]) {
    if (!validResearchDay(row.date) || row.date <= previousDay) fail();
    previousDay = row.date;
    if (mode === "scenario" && value.status === "PARTIAL_COVERAGE") { if (row[curveKey] !== null) fail(); }
    else if (typeof row[curveKey] !== "number" || !Number.isFinite(row[curveKey]) || (row[curveKey] as number) < 0 || (mode === "simulation" && row[curveKey] === 0)) fail();
    if (Object.entries(row).some(([k, v]) => k !== "date" && !finiteOrNull(v))) fail();
  }
  if (value.metrics !== undefined && value.metrics !== null) {
    if (!object(value.metrics) || Object.keys(value.metrics).length !== 20 || Object.keys(value.metrics).some(k => !(k in metricNames))) fail();
    Object.values(value.metrics).forEach(checkMetric);
  }
  for (const key of ["twr", "total_return", "realized_pnl", "unrealized_pnl", "total_fees", "dividend_entitlements"]) if (value[key] !== undefined && !finiteOrNull(value[key])) fail();
  if (value.risk_metrics !== undefined) { if (!object(value.risk_metrics)) fail(); Object.values(value.risk_metrics).forEach(checkMetric); }
  for (const key of ["historical_var_95", "max_drawdown"]) if (value[key] !== undefined) checkMetric(value[key]);
  if (value.mwr !== undefined && value.mwr !== null) {
    if (!object(value.mwr) || !["SUPPORTED", "UNDEFINED"].includes(String(value.mwr.status)) ||
        !finiteOrNull(value.mwr.annual_rate) || !finiteOrNull(value.mwr.period_return) ||
        value.mwr.reason !== undefined && value.mwr.reason !== null && typeof value.mwr.reason !== "string") fail();
  }
  if (value.status === "CALCULATED") {
    if (!Array.isArray(value.curve) || value.curve.length < 2 || value.curve.length > 2000 || !["CNY", "USD", "HKD"].includes(String(value.currency))) fail();
    if (mode === "simulation" && (value.scope !== "HYPOTHETICAL_LONG_ONLY_CASH_ACCOUNT" || !object(value.metrics) || !Array.isArray(value.fills) || !Array.isArray(value.rejections))) fail();
    if (mode === "scenario" && (value.scope !== "HYPOTHETICAL_INITIAL_WEIGHT_BUY_HOLD_REPLAY" || !object(value.coverage) || !Array.isArray(value.correlation))) fail();
    if (mode === "performance" && (!["WHOLE_ACCOUNT", "STOCK_BASKET"].includes(String(value.scope)) || value.authority !== "EXPLICIT_UNVERIFIED_VALUATION_ADAPTER" || typeof value.twr !== "number" || !object(value.mwr))) fail();
    if (mode === "ledger-performance" && (value.scope !== "STOCK_BASKET" || value.whole_account_performance !== false || value.authority !== "TRADE_LEDGER_READ_ONLY_PLUS_UNVERIFIED_PRICE_ACTION_OPENING_ADAPTER" || !Array.isArray(value.selected_trade_ids) || typeof value.twr !== "number" || !object(value.mwr))) fail();
  }
  if (value.status === "PARTIAL_COVERAGE" && mode !== "scenario") fail();
  return value as AnalyticsReport;
}
export function parseAnalyticsExample(value: unknown, mode: AnalyticsMode): AnalyticsRow {
  boundedJson(value);
  if (!object(value) || value.synthetic !== true || !object(value.input) || typeof value.input.source_label !== "string" || !value.input.source_label.startsWith("SYNTHETIC_")) fail();
  if (mode === "performance") {
    if (!Array.isArray(value.input.valuations) || value.input.valuations.length < 2 || value.input.valuations.length > 2000 || !value.input.valuations.every(v => object(v) && validResearchDay(v.date) && typeof v.value === "number")) fail();
  } else {
    if (!Array.isArray(value.input.sessions) || value.input.sessions.length < 2 || value.input.sessions.length > 2000 || !value.input.sessions.every(v => validResearchDay(v)) || !Array.isArray(value.input.instruments) || value.input.instruments.length < 1 || value.input.instruments.length > 20 || !value.input.instruments.every(v => object(v) && typeof v.code === "string" && Array.isArray(v.bars) && v.bars.length <= 2000 && v.bars.every(object))) fail();
  }
  parseAnalyticsInput(JSON.stringify(value.input));
  return value.input;
}
