// 明日决策驱动舱 API 客户端。
// 自选股：后端权威 JSON；前端 localStorage 仅作缓存/草稿。
// 前端绝不提交候选池/持仓快照/信号/证据/actions/trade_date_override（全部后端读取）。

import { get, put, request, ApiError, unwrapApiPayload } from "./api.ts";

// ---------------------------------------------------------------------------
// 共享类型
// ---------------------------------------------------------------------------

export type WatchlistStatus =
  | { status: "valid"; data: { codes: string[]; updated_at: string }; etag: string }
  | { status: "not_configured"; data: null; etag: null }
  | { status: "corrupted"; data: null; etag: null };

export interface WatchlistAnomalyItem {
  code: string;
  provider_symbol: string;
  name: string;
  type: string;
  reason: string;
  keywords: string[];
}

export interface WatchlistAnomalies {
  provider_id: "hithink_financial_api";
  provider_contract: string;
  as_of_ms: number | null;
  unavailable_codes: string[];
  items: WatchlistAnomalyItem[];
}

export interface Signal {
  plan_id: string;
  candidate_code: string;
  dimension: string;
  label: string;
  assessment: "strong" | "medium" | "weak" | "unknown";
  confidence: number | null;
  value?: unknown;
  context?: Record<string, unknown>;
}

export interface Candidate {
  code: string;
  name: string;
  sources: string[];
}

export interface Explanation {
  text: string;
  source: "llm" | "deterministic";
  model: string | null;
}

export interface TomorrowPlanMeta {
  id: number;
  trade_date: string;
  version: number;
  is_current: number;
  status: "draft" | "frozen" | "superseded";
  generated_at: string;
  payload_hash: string;
  signals?: Signal[];
}

/** 市场短线评估信封：status ∈ normal/partial/unavailable；data 为 {breadth, emotion} 或 null。 */
export interface MarketShortEnvelope {
  status: "normal" | "partial" | "unavailable" | string;
  is_stale?: boolean;
  warnings: string[];
  data: { breadth: Record<string, unknown> | null; emotion: Record<string, unknown> | null } | null;
}

/** 账户资金：未配置时 configured=false/data=null；已配置时 data 含 total_assets/available_cash/updated_at。 */
export interface AccountFundingEnvelope {
  configured: boolean;
  canonical?: boolean;
  status?: "valid" | "not_configured" | "corrupted" | string;
  reason_code?: string | null;
  canonical_reason_codes?: string[];
  confirmation_id?: string | null;
  data: { total_assets: number; available_cash: number; updated_at: string } | null;
}

/** 顶层持仓建议摘要（快照字段子集，只读展示）。 */
export interface OverviewAdviceSummary {
  result_type?: string | null;
  trade_date?: string | null;
  generated_at?: string | null;
  input_fingerprint?: string | null;
  payload_hash?: string | null;
  stale?: boolean | null;
  schema_version?: string | null;
}

export interface Overview {
  trade_date: string;
  is_latest_review_day?: boolean;
  latest_review_trade_date?: string | null;
  market_short: MarketShortEnvelope;
  account_funding: AccountFundingEnvelope;
  advice: OverviewAdviceSummary | null;
  current_plan: (TomorrowPlanMeta & { signals?: Signal[] }) | null;
  candidate_pool: Candidate[];
  plans?: TomorrowPlanMeta[];
  warnings?: string[];
}

// ---------------------------------------------------------------------------
// 自选股
// ---------------------------------------------------------------------------

export async function getWatchlist(): Promise<WatchlistStatus> {
  return get<WatchlistStatus>("/watchlist");
}

export async function getWatchlistAnomalies(): Promise<WatchlistAnomalies> {
  return get<WatchlistAnomalies>("/watchlist/anomalies");
}

export async function saveWatchlist(codes: string[], expectedEtag?: string) {
  return put<{ codes: string[]; updated_at: string; etag: string }>(
    "/watchlist",
    { codes, ...(expectedEtag ? { expected_etag: expectedEtag } : {}) },
  );
}

/** 显式把前端 localStorage 草稿并入后端（保留后端已有 + 去重并入）。 */
export async function importLocalWatchlist(codes: string[], expectedEtag?: string) {
  return request<{ codes: string[]; added: string[]; updated_at: string; etag: string }>(
    "/watchlist/import-local",
    "POST",
    { codes, ...(expectedEtag ? { expected_etag: expectedEtag } : {}) },
  );
}

// ---------------------------------------------------------------------------
// 决策舱
// ---------------------------------------------------------------------------

export interface GeneratePlanResult {
  id: number;
  trade_date: string;
  version: number;
  status: string;
  skipped?: boolean;
  reason?: string;
}

export async function getOverview(tradeDate: string): Promise<Overview> {
  return get<Overview>(`/decision-cockpit/overview?trade_date=${encodeURIComponent(tradeDate)}`);
}

export async function generateTomorrowPlan(
  tradeDate: string,
  llm?: { provider: string; baseURL: string; apiKey: string; model: string } | null,
  force = false,
): Promise<GeneratePlanResult> {
  return request<GeneratePlanResult>("/decision-cockpit/tomorrow-plan/generate", "POST", {
    trade_date: tradeDate,
    force,
    ...(llm ? { llm } : { llm: null }),
  });
}

export async function getCurrentPlan(tradeDate: string) {
  return get<(TomorrowPlanMeta & { signals: Signal[] }) | null>(
    `/decision-cockpit/tomorrow-plan/current?trade_date=${encodeURIComponent(tradeDate)}`,
  );
}

export async function getPlan(planId: number) {
  return get<(TomorrowPlanMeta & { signals: Signal[] }) | null>(
    `/decision-cockpit/tomorrow-plan/${planId}`,
  );
}

export async function listPlans(params?: {
  trade_date?: string;
  limit?: number;
  offset?: number;
}) {
  const q = new URLSearchParams();
  if (params?.trade_date) q.set("trade_date", params.trade_date);
  if (params?.limit != null) q.set("limit", String(params.limit));
  if (params?.offset != null) q.set("offset", String(params.offset));
  const qs = q.toString();
  return get<TomorrowPlanMeta[]>(`/decision-cockpit/tomorrow-plan/history${qs ? `?${qs}` : ""}`);
}

export async function freezePlan(planId: number, expectedVersion: number) {
  return request<TomorrowPlanMeta>(
    `/decision-cockpit/tomorrow-plan/${planId}/freeze`,
    "POST",
    { expected_version: expectedVersion },
  );
}

// ---------------------------------------------------------------------------
// 今日实时行动（只读）
// ---------------------------------------------------------------------------

export interface TodayHoldingAction {
  code: string;
  name: string;
  shares: number | null;
  price: number | null;
  change_pct?: number | null;
  pnl_pct?: number | null;
  plan_signals_summary: string | null;
  advice_action: string | null;
  advice_qty: number | null;
  flags: string[];
}

export interface TodayWatchlistMover {
  code: string;
  name: string;
  price: number | null;
  change_pct: number | null;
  flag: string | null;
}

export interface TodayActions {
  trade_date: string;
  as_of: string;
  plan: {
    id: number;
    status: string;
    version: number;
    generated_at: string;
    is_current: number | boolean;
  } | null;
  plan_note: string | null;
  holdings: TodayHoldingAction[];
  watchlist_movers: TodayWatchlistMover[];
  warnings: string[];
}

export async function getTodayActions(tradeDate: string): Promise<TodayActions> {
  return get<TodayActions>(
    `/decision-cockpit/today-actions?trade_date=${encodeURIComponent(tradeDate)}`,
  );
}

export { ApiError, unwrapApiPayload };
