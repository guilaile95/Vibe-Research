// Vibe-Research 后端 API 客户端。/api → vite 代理到本地 FastAPI（默认 8900）。
// 后端未启动或数据源异常时抛 ApiError，页面据此优雅降级。

export class ApiError extends Error {
  readonly status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

// 后端访问密钥（对应后端部署时的 VR_API_KEY，公网部署防蹭用）。只存本地浏览器。
const ACCESS_KEY = "vr-access-key";

export function loadAccessKey(): string {
  try {
    return localStorage.getItem(ACCESS_KEY) || "";
  } catch {
    return "";
  }
}

export function saveAccessKey(key: string) {
  try {
    if (key) localStorage.setItem(ACCESS_KEY, key);
    else localStorage.removeItem(ACCESS_KEY);
  } catch {
    /* 隐私模式等场景 localStorage 不可用 */
  }
}

export function authHeaders(): Record<string, string> {
  const k = loadAccessKey();
  return k ? { Authorization: `Bearer ${k}` } : {};
}

export function unwrapApiPayload(payload: any): any {
  if (
    payload !== null
    && typeof payload === "object"
    && Object.prototype.hasOwnProperty.call(payload, "data")
  ) {
    return payload.data;
  }
  return payload;
}

export interface MyReport {
  id: string; name: string; industry: string; size: number; ext: string; ts: number;
  // 丰富元数据（可选，向后兼容：旧存档可能缺失）。
  title?: string;
  institution?: string;
  publish_date?: string;
  sector_keys?: string[];
  source_url?: string;
  source_kind?: string;
  file_sha256?: string;
  imported_at?: string;
  source_provider?: string;
  external_id?: string;
  info_code?: string;
  report_scope?: string;
  report_type?: string;
  // 同内容去重标记：上传内容与已有归档完全一致时，不写重复文件，返回既有条目 + deduped=true。
  deduped?: boolean;
}

export type MyReportsBrowseGroup = "year" | "industry" | "institution";

export interface MyReportsBrowseGroupItem {
  key: string;
  label: string;
  count: number;
  months?: { key: string; label: string; count: number }[];
  sector_keys?: string[];
}

export interface MyReportsBrowseResult {
  groups: MyReportsBrowseGroupItem[];
  total: number;
}

/** 板块研报发现 scope：行业 / 公司 / 全部 */
export type SectorReportScope = "industry" | "company" | "all";

export type DiscoveredSectorReport = {
  source_provider?: string;
  external_id: string | null;
  info_code: string | null;
  title: string | null;
  institution: string | null;
  publish_date: string | null;
  industry_name?: string | null;
  company_code?: string | null;
  company_name?: string | null;
  pdf_url?: string | null;
  report_scope?: string | null;
  report_type?: string | null;
  matched_keywords?: string[];
  relevance_score?: number;
  rating?: string | null;
  date_unknown?: boolean;
};

export type SectorReportsDiscoveryResult = {
  sector_key: string;
  discovered: DiscoveredSectorReport[];
  filtered: DiscoveredSectorReport[];
  error: string | null;
  total_discovered?: number;
  returned?: number;
  truncated?: boolean;
};

/** 动态面板摘要：仅受控字段，无原始 data 倾倒 */
export type SectorPanelSummary = {
  name?: string;
  industry?: string;
  market_cap?: string;
  business?: string;
  coverage?: string;
  year?: string;
  eps?: string;
  forecast?: string;
  record_count?: number;
  count?: number;
  latest_title?: string;
  latest_date?: string;
  note?: string;
  [key: string]: string | number | undefined;
};

export type SectorDynamicPanel = {
  status: "ok" | "error";
  summary: SectorPanelSummary;
  error: string | null;
};

export type SectorDynamicCompany = {
  code: string;
  name?: string;
  panels: Record<string, SectorDynamicPanel>;
};

export type SectorDynamicData = {
  sector_key: string;
  source: string;
  fetched_at: string;
  status: "normal" | "partial" | "unavailable";
  warnings: string[];
  companies: SectorDynamicCompany[];
  error?: string;
};

// 下载/预览研报：带鉴权头 fetch → blob → 触发浏览器下载（<a download> 无法带 Authorization，故走 blob）。
export async function downloadReport(id: string, name: string): Promise<void> {
  const resp = await fetch(`/api/myreports/file/${id}`, { headers: authHeaders() });
  if (!resp.ok) throw new ApiError(`下载失败 HTTP ${resp.status}`, resp.status);
  const blob = await resp.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export async function request<T>(
  path: string,
  method: "GET" | "POST" | "PUT" | "PATCH" | "DELETE" = "GET",
  body?: unknown,
  options?: { unwrapData?: boolean; signal?: AbortSignal },
): Promise<T> {
  const unwrapData = options?.unwrapData ?? true;
  let resp: Response;
  const headers: Record<string, string> = { ...authHeaders() };
  const opts: RequestInit = { method };
  if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  if (options?.signal) opts.signal = options.signal;
  if (Object.keys(headers).length > 0) opts.headers = headers;
  try {
    resp = await fetch(`/api${path}`, opts);
  } catch (e) {
    if (e instanceof DOMException && e.name === "AbortError") throw e;
    if (typeof e === "object" && e !== null && "name" in e && (e as { name: string }).name === "AbortError") {
      throw e;
    }
    throw new ApiError("连接不到后端，请先启动 backend（uvicorn app:app --port 8900）", 0);
  }
  let payload: any = null;
  try {
    payload = await resp.json();
  } catch {
    /* 非 JSON 响应 */
  }
  if (!resp.ok) {
    if (resp.status === 401) {
      throw new ApiError("后端开启了访问鉴权（VR_API_KEY）：请在「接入 AI」页底部填写后端访问密钥", 401);
    }
    throw new ApiError(payload?.detail || `HTTP ${resp.status}`, resp.status);
  }
  const result = unwrapData ? unwrapApiPayload(payload) : payload;
  return result as T;
}

export const get = <T>(path: string, options?: { unwrapData?: boolean; signal?: AbortSignal }) =>
  request<T>(path, "GET", undefined, options);
export const put = <T>(path: string, body: unknown, options?: { unwrapData?: boolean; signal?: AbortSignal }) =>
  request<T>(path, "PUT", body, options);

export interface Quote {
  name: string; price: number; last_close: number; change_pct: number;
  pe_ttm: number; pb: number; mcap_yi: number; turnover_pct: number;
  limit_up: number; limit_down: number;
}

export interface Valuation {
  name: string; code: string; price: number; mcap_yi: number;
  pe_ttm: number; pb: number;
  eps_26e: number | null; eps_27e: number | null; pe_26e: number | null;
  cagr_pct: number | null; peg: number | null; digest_years: number | null;
  analyst_count: number; forecast_note?: string;
}

export interface Report {
  title: string; publishDate: string; orgSName: string;
  emRatingName?: string; indvInduName?: string; pdfUrl?: string | null;
}

export interface ValMetric {
  current: number; percentile: number; min: number; max: number;
  p20: number; p50: number; p80: number; n: number;
}
export interface ValPercentile {
  period: string; metrics: { pe_ttm?: ValMetric; pb?: ValMetric };
}

export interface Announcement {
  date: string; title: string; type: string; url: string;
}

export interface Financials {
  period: string | null;
  revenue: string | null; revenue_yoy: string | null;
  net_profit: string | null; net_profit_yoy: string | null;
  eps: string | null; bvps: string | null; roe: string | null;
  gross_margin: string | null; net_margin: string | null; op_cf_ps: string | null;
}

export interface NewsItem {
  新闻标题?: string; 发布时间?: string; 文章来源?: string; 新闻链接?: string;
}

export interface IndexQuote {
  name: string; price: number; change_pct: number; change_amt: number;
}

/** 市场 / 每日复盘组件数据状态 */
export type MarketDataStatus = "normal" | "partial" | "unavailable";
export type DataStatus = MarketDataStatus;

export interface ComponentEnvelope<T> {
  status: DataStatus;
  source: string;
  warnings: string[];
  data: T | null;
}

export interface TimedComponentEnvelope<T> extends ComponentEnvelope<T> {
  trade_date?: string | null;
  data_time?: string | null;
  fetched_at?: string | null;
  is_stale?: boolean;
}

/** 兼容旧 overview.sentiment（其他页面可能仍用 marketOverview） */
export interface MarketSentiment {
  status?: MarketDataStatus;
  source?: string;
  warnings?: string[];
  up: number | null;
  down: number | null;
  flat: number | null;
  zt: number | null;
  zt_real?: number | null;
  dt: number | null;
  dt_real?: number | null;
  active: string;
  active_metric?: string;
  up_ratio?: number | null;
  breadth: string | null;
  speculation: string | null;
  stock_count?: number | null;
  valid_count?: number | null;
  up_3pct_count?: number | null;
  down_3pct_count?: number | null;
  total_amount?: number | null;
  date: string;
  limit_count_source?: string;
}
export interface SectorFlow {
  name: string; pct: number; net: number; inflow: number; outflow: number; firms: number;
}
export interface MarketOverview {
  sentiment: MarketSentiment; sectors: SectorFlow[]; updated: string;
}

// 短线情绪：连板梯队 / 最高连板 / 炸板率 / 封板率 / 晋级率 / 涨跌停家数 + 连板股清单
export interface EmotionTier { boards: number; count: number; plus: boolean }
export interface LianbanStock {
  code: string; name: string; boards: number;
  price: number; pct: number; amount: number | null; float_cap: number | null; industry: string;
}
export interface ShortTermEmotion {
  date: string;
  zt_count: number; dt_count: number; zb_count: number;
  max_boards: number; lianban_count: number;
  ladder: EmotionTier[];
  lianban_stocks: LianbanStock[];
  seal_rate: number | null; break_rate: number | null; promotion_rate: number | null;
  yzt_count: number;
}
/** 与 ShortTermEmotion 同构，供每日复盘聚合包使用 */
export type ShortTermEmotionData = ShortTermEmotion;

// 全市场成交额榜（旧榜单 / 快照榜）
export interface TurnoverStock {
  code: string; name: string;
  price: number | null; pct: number | null;
  amount: number | null; mcap: number | null; float_cap: number | null; industry: string;
}
export interface TurnoverTop { stocks: TurnoverStock[]; updated: string }

/** 全 A 快照个股条目（amount_top / high_turnover） */
export interface MarketSnapshotItem {
  code: string;
  name: string;
  price: number | null;
  change_pct: number | null;
  amount: number | null;
  turnover_pct: number | null;
  market_cap: number | null;
}

export interface MarketBreadthData {
  stock_count: number;
  valid_count: number;
  up_count: number;
  down_count: number;
  flat_count: number;
  up_ratio: number | null;
  up_3pct_count: number;
  down_3pct_count: number;
  total_amount: number | null;
  amount_valid_count: number;
  amount_top: MarketSnapshotItem[];
  high_turnover: MarketSnapshotItem[];
}

export interface BoardRankItem {
  code: string;
  name: string;
  change_pct: number | null;
  turnover_pct: number | null;
  market_cap: number | null;
  up_count: number | null;
  down_count: number | null;
  up_ratio: number | null;
  leader: string | null;
  leader_change_pct: number | null;
}

export interface BoardRankingData {
  type: "industry" | "concept" | "region" | string;
  total: number;
  ranked_count: number;
  unknown_count: number;
  top: BoardRankItem[];
  bottom: BoardRankItem[];
}

/** GET /api/daily-review 可选缓存元数据（stale-while-revalidate） */
export interface DailyReviewCacheMeta {
  source: "live" | "memory" | "persisted" | string;
  stale: boolean;
  refreshing: boolean;
  saved_at: string | null;
  age_seconds: number | null;
  /** 后台刷新失败：继续展示旧结果 */
  refresh_failed?: boolean;
  refresh_error?: string | null;
}

/** 结构化每日复盘（GET /api/daily-review 的 data 字段） */
export interface DailyReviewData {
  schema_version: string;
  generated_at: string;
  trade_date: string | null;
  data_cutoff: string | null;
  status: DataStatus;
  warnings: string[];
  data_health: {
    components: {
      indices: DataStatus;
      global_indices: DataStatus;
      breadth: DataStatus;
      emotion: DataStatus;
      turnover: DataStatus;
      industry_boards: DataStatus;
      concept_boards: DataStatus;
      region_boards: DataStatus;
    };
  };
  market_environment: {
    indices: ComponentEnvelope<IndexQuote[]>;
    global_indices: ComponentEnvelope<GlobalIndex[]>;
    breadth: TimedComponentEnvelope<MarketBreadthData>;
  };
  sector_rotation: {
    industry: TimedComponentEnvelope<BoardRankingData>;
    concept: TimedComponentEnvelope<BoardRankingData>;
    region: TimedComponentEnvelope<BoardRankingData>;
    highlights: {
      strongest_industry: BoardRankItem | null;
      weakest_industry: BoardRankItem | null;
      strongest_concept: BoardRankItem | null;
      weakest_concept: BoardRankItem | null;
      strongest_region: BoardRankItem | null;
      weakest_region: BoardRankItem | null;
    };
  };
  short_term_emotion: ComponentEnvelope<ShortTermEmotionData>;
  capital_activity: {
    turnover_top: ComponentEnvelope<TurnoverTop>;
    total_amount: number | null;
    amount_valid_count: number | null;
    amount_top: MarketSnapshotItem[];
    high_turnover: MarketSnapshotItem[];
  };
}

/** 历史列表元数据（不含完整 review） */
export interface DailyReviewHistoryItem {
  id: number;
  trade_date: string;
  schema_version: string;
  generated_at: string;
  data_cutoff: string | null;
  status: DataStatus;
  payload_hash: string;
  created_at: string;
}

/** 历史快照详情（含完整 review） */
export interface DailyReviewHistorySnapshot extends DailyReviewHistoryItem {
  review: DailyReviewData;
}

/** POST /api/daily-review/history/save 结果 */
export interface SaveDailyReviewHistoryResult {
  snapshot: {
    id: number;
    inserted: boolean;
    trade_date: string;
    schema_version: string;
    generated_at: string;
    status: DataStatus;
    payload_hash: string;
    created_at: string;
  };
  review_status: "normal" | "partial";
  review_warnings: string[];
}

/** GET /api/daily-review/history 列表响应 */
export interface DailyReviewHistoryList {
  items: DailyReviewHistoryItem[];
  trade_date: string | null;
  limit: number;
  offset: number;
  count: number;
}

/** 快照比较元数据 */
export interface DailyReviewComparisonMeta {
  id: number | null;
  trade_date: string | null;
  schema_version: string | null;
  generated_at: string | null;
  status: DataStatus | null;
}

/** 通用数值比较 */
export interface NumericComparison {
  base: number | null;
  target: number | null;
  delta: number | null;
  change_pct: number | null;
}

export interface RankingEntered<T> {
  key: string;
  target_rank: number;
  item: T;
}

export interface RankingExited<T> {
  key: string;
  base_rank: number;
  item: T;
}

export interface RankingChange<T> {
  key: string;
  base_rank: number;
  target_rank: number;
  rank_delta: number;
  base_item: T;
  target_item: T;
}

export interface RankingComparison<T> {
  base_count: number;
  target_count: number;
  entered: RankingEntered<T>[];
  exited: RankingExited<T>[];
  rank_changes: RankingChange<T>[];
}

export interface HighlightComparison<T> {
  base: T | null;
  target: T | null;
  changed: boolean | null;
}

/** GET /api/daily-review/history/compare 结果 */
export interface DailyReviewComparison {
  schema_version: string;
  base: DailyReviewComparisonMeta;
  target: DailyReviewComparisonMeta;
  comparison_status: DataStatus;
  schema_compatible: boolean;
  warnings: string[];
  market_breadth: {
    available: boolean;
    stock_count: NumericComparison;
    valid_count: NumericComparison;
    up_count: NumericComparison;
    down_count: NumericComparison;
    flat_count: NumericComparison;
    up_ratio: NumericComparison;
    up_3pct_count: NumericComparison;
    down_3pct_count: NumericComparison;
    total_amount: NumericComparison;
    amount_valid_count: NumericComparison;
  };
  short_term_emotion: {
    available: boolean;
    zt_count: NumericComparison;
    dt_count: NumericComparison;
    zb_count: NumericComparison;
    max_boards: NumericComparison;
    lianban_count: NumericComparison;
    seal_rate: NumericComparison;
    break_rate: NumericComparison;
    promotion_rate: NumericComparison;
    yzt_count: NumericComparison;
  };
  sector_rotation: {
    industry: {
      top: RankingComparison<BoardRankItem>;
      bottom: RankingComparison<BoardRankItem>;
    };
    concept: {
      top: RankingComparison<BoardRankItem>;
      bottom: RankingComparison<BoardRankItem>;
    };
    region: {
      top: RankingComparison<BoardRankItem>;
      bottom: RankingComparison<BoardRankItem>;
    };
    highlights: {
      strongest_industry: HighlightComparison<BoardRankItem>;
      weakest_industry: HighlightComparison<BoardRankItem>;
      strongest_concept: HighlightComparison<BoardRankItem>;
      weakest_concept: HighlightComparison<BoardRankItem>;
      strongest_region: HighlightComparison<BoardRankItem>;
      weakest_region: HighlightComparison<BoardRankItem>;
    };
  };
  capital_activity: {
    total_amount: NumericComparison;
    amount_valid_count: NumericComparison;
    amount_top: RankingComparison<MarketSnapshotItem>;
    high_turnover: RankingComparison<MarketSnapshotItem>;
  };
  unknowns: string[];
}

export interface RadarItem {
  title: string; url: string; time: string; source: string; summary?: string; zh?: string;
}
export interface Industry {
  key: string; name: string; accent: string; total: number; items: RadarItem[];
}
export interface RadarData {
  generated_at: string | null; recent_days: number; industries: Industry[];
  stats: { industries: number; total_sources: number; failed_sources?: number };
}

export interface Holding {
  code: string; name: string; price: number | null; shares: number; cost: number;
  market_value: number | null; pnl: number | null; pnl_pct: number | null;
  data_status?: "normal" | "unavailable";
}
export interface ClosedPosition {
  code: string; name: string; date: string; price: number; shares: number; cost: number;
  pnl: number; pnl_pct: number;
}
export interface PortfolioData {
  holdings: Holding[];
  totals: { market_value: number | null; cost: number; pnl: number | null; pnl_pct: number | null };
  closed: ClosedPosition[];
  realized_pnl: number;
  updated: string; last_refresh: string | null;
  data_status?: "normal" | "partial" | "unavailable";
  quote_coverage?: { valid_holdings: number; total_holdings: number; complete: boolean };
}

// ---------------------------------------------------------------------------
// 账户资金（手工填写，GET /api/account-profile 与 PUT /api/account-profile）
// ---------------------------------------------------------------------------

export interface AccountProfileData {
  total_assets: number;
  available_cash: number;
  updated_at: string;
}

export interface AccountProfileResponse {
  configured: boolean;
  data: AccountProfileData | null;
}

export interface AccountProfileRequest {
  total_assets: number;
  available_cash: number;
}

// ---------------------------------------------------------------------------
// 持仓操作建议（POST /api/portfolio/advice，普通 JSON，非流式）
// 契约与 backend portfolio_advice_validator 权威结果对齐
// ---------------------------------------------------------------------------

export type PortfolioAdviceHoldingAction =
  | "add"
  | "hold"
  | "reduce"
  | "sell"
  | "watch"
  | "avoid";

export type PortfolioAdviceAccountAction =
  | "hold"
  | "reduce_risk"
  | "selective_add"
  | "defensive";

export type PortfolioAdviceConfidence = "high" | "medium" | "low";

export interface PortfolioAdviceSummary {
  holding_count: number;
  market_value: number | null;
  cost: number;
  pnl: number | null;
  pnl_pct: number | null;
}

export interface PortfolioAdviceAccountDecision {
  action: PortfolioAdviceAccountAction;
  reason: string;
  confidence: PortfolioAdviceConfidence;
}

export interface AccountFundingQuoteCoverage {
  valid_holdings: number;
  total_holdings: number;
  complete: boolean;
}

export interface AccountFundingData {
  configured: boolean;
  total_assets: number | null;
  available_cash: number | null;
  available_cash_pct: number | null;
  updated_at: string | null;
  tracked_stock_market_value: number | null;
  tracked_stock_weight_pct: number | null;
  quote_coverage: AccountFundingQuoteCoverage;
}

export interface PortfolioAdviceHoldingAccountMetrics {
  market_value: number | null;
  account_weight_pct: number | null;
}

export interface PortfolioAdviceHoldingAdvice {
  code: string;
  name: string;
  shares: number;
  cost_price: number;
  current_price: number | null;
  market_value: number | null;
  pnl_amount: number | null;
  pnl_pct: number | null;
  holding_weight_pct: number | null;
  account_metrics?: PortfolioAdviceHoldingAccountMetrics | null;
  action: PortfolioAdviceHoldingAction;
  /** 相对当前持股数量的操作比例（add/reduce/sell）；非账户总仓位比例 */
  execution_size_pct_of_holding: number | null;
  /** 后端重算的建议操作股数；不足交易单位或不可算时为 null */
  execution_quantity: number | null;
  /**
   * reduce/sell 建议可卖上限（理论/advisory，非券商真可卖）。
   * 一般为 min(execution_quantity, shares)；不可算时为 null。
   */
  sellable_quantity_advisory?: number | null;
  /** 仅 add：后端按 quantity×现价估算的预计所需金额；不可算时为 null */
  estimated_amount?: number | null;
  trigger_conditions: string[];
  price_conditions: string[];
  execution_plan: string[];
  risk_conditions: string[];
  invalidation_conditions: string[];
  confidence: PortfolioAdviceConfidence;
  data_limitations: string[];
}

export interface PortfolioAdviceResult {
  schema_version: "portfolio-advice-v0.1";
  generated_at: string;
  /** 复盘交易日；缺失时为 null/undefined，前端不伪造 */
  trade_date?: string | null;
  market_status: MarketDataStatus | string;
  portfolio_summary: PortfolioAdviceSummary;
  account_action: PortfolioAdviceAccountDecision;
  account_funding?: AccountFundingData | null;
  holdings: PortfolioAdviceHoldingAdvice[];
  warnings: string[];
  data_limitations: string[];
}

export interface PortfolioAdviceRequest {
  user_request: string | null;
  llm: StreamLlmConfig;
}

export type AiResultType = "daily_review_ai" | "portfolio_advice";

export interface DailyReviewAiPayload {
  markdown: string;
  source_review_generated_at: string;
  source_data_cutoff: string | null;
}

export interface AiGeneratedResult<TPayload> {
  result_type: AiResultType;
  trade_date: string;
  schema_version: string;
  payload: TPayload;
  generated_at: string;
  model_provider: string;
  model_name: string;
  stale: boolean;
  stale_message?: string;
}

export interface AiGeneratedResultMetadata {
  result_type: AiResultType;
  trade_date: string;
  schema_version: string;
  generated_at: string;
}

// 资金面 / 筹码 / 信号（v3.3 并入，均为「用户查的那只股」的公开数据）
export interface MarginRow { date: string; rzye: number; rzmre: number; rzche: number; rqye: number; rqmcl: number; rzrqye: number }
export interface BlockTradeRow { date: string; price: number; close: number; premium_pct: number; vol: number; amount: number; buyer: string; seller: string }
export interface HolderRow { date: string; holder_num: number; change_ratio: number; avg_shares: number }
export interface DividendRow { date: string; bonus_rmb: number; transfer_ratio: number; bonus_ratio: number | null; plan: string }
export interface FundFlowRow { date: string; main_net: number; small_net: number; mid_net: number; large_net: number; super_net: number }
export interface DtSeat { name: string; buy_amt: number; sell_amt: number; net: number }
export interface DragonTiger {
  records: { date: string; reason: string; net_buy: number; turnover: number }[];
  seats: { buy: DtSeat[]; sell: DtSeat[] };
  institution: { buy_amt: number; sell_amt: number; net_amt: number };
}
export interface LockupRow { date: string; type: string; shares: number; able_shares: number; ratio: number }
export interface Lockup { history: LockupRow[]; upcoming: LockupRow[] }
export interface Board { name: string; code: string; change_pct: number | string; lead_stock: string }
export interface Blocks { total: number; boards: Board[]; concept_tags: string[] }
export interface HotConcept { concept: string; bk: string; hit: number }
export interface QaRow { company: string; question: string; answer: string | null; answerer: string; ask_time: string }
export interface IndustryRow { rank: number; name: string; change_pct: number; code: string; up_count: number; down_count: number }
export interface IndustryData { top: IndustryRow[]; bottom: IndustryRow[]; total: number }

// 全球市场（美股 / 港股，移植自 global-stock-data · 东财域内源）
export interface GlobalIndex {
  key: string; name: string; region: string;
  price: number | null; change_pct: number | null;
}
export interface GlobalQuote {
  code: string; name: string;
  price: number | null; open: number | null; high: number | null; low: number | null;
  prev_close: number | null; amount: number | null; mcap: number | null; change_pct: number | null;
}
export interface GlobalMetrics {
  report_date: string;
  revenue: number | null; revenue_yoy: number | null; net_profit: number | null;
  eps: number | null; roe: number | null; gross_margin: number | null;
  net_margin: number | null; debt_ratio: number | null;
}
export interface GlobalStock {
  code: string; name: string; market: string;
  quote: GlobalQuote; metrics: GlobalMetrics | null;
}

// ---------------------------------------------------------------------------
// NDJSON 流式（/api/chat 与 /api/daily-review/analyze 共用同一解析协议）
// ---------------------------------------------------------------------------

/** 与后端 LLMConfig / 前端 LlmConfig 字段对齐（避免 api↔llm 循环依赖） */
export interface StreamLlmConfig {
  provider: string;
  baseURL: string;
  apiKey: string;
  model: string;
}

export interface DailyReviewAnalyzeRequest {
  user_request?: string | null;
  llm: StreamLlmConfig;
}

export interface NdjsonStreamHandlers {
  onDelta?: (text: string) => void;
  onTool?: (tool: string, args: Record<string, unknown>) => void;
}

export interface NdjsonStreamResult {
  content: string;
  trace: { tool: string; args: Record<string, unknown> }[];
  rounds: number;
  result?: AiGeneratedResultMetadata;
}

export interface NdjsonProtocolState extends NdjsonStreamResult {
  sawDone: boolean;
  sawError: boolean;
  errorMessage: string | null;
}

export function createNdjsonProtocolState(): NdjsonProtocolState {
  return {
    content: "",
    trace: [],
    rounds: 0,
    sawDone: false,
    sawError: false,
    errorMessage: null,
  };
}

/** Pure protocol transition used by streamNdjson and suitable for isolated tests. */
export function applyNdjsonLine(
  state: NdjsonProtocolState,
  line: string,
  handlers: NdjsonStreamHandlers = {},
): void {
  const text = line.trim();
  if (!text) return;
  let event: any;
  try {
    event = JSON.parse(text);
  } catch {
    state.sawError = true;
    state.errorMessage = "后端响应格式错误";
    return;
  }
  if (!event || typeof event !== "object") {
    state.sawError = true;
    state.errorMessage = "后端响应格式错误";
    return;
  }
  if (event.type === "delta") {
    if (state.sawDone || typeof event.text !== "string") {
      state.sawError = true;
      state.errorMessage = "后端响应完成顺序异常";
      return;
    }
    state.content += event.text;
    handlers.onDelta?.(event.text);
  } else if (event.type === "tool") {
    if (state.sawDone) {
      state.sawError = true;
      state.errorMessage = "后端响应完成顺序异常";
      return;
    }
    handlers.onTool?.(String(event.tool || ""), event.args || {});
  } else if (event.type === "done") {
    if (state.sawDone) {
      state.sawError = true;
      state.errorMessage = "后端重复发送完成信号";
      return;
    }
    state.sawDone = true;
    state.trace = Array.isArray(event.trace) ? event.trace : [];
    state.rounds = Number.isInteger(event.rounds) ? event.rounds : 0;
    if (event.result && typeof event.result === "object") {
      state.result = event.result as AiGeneratedResultMetadata;
    }
  } else if (event.type === "error") {
    state.sawError = true;
    state.errorMessage = typeof event.message === "string" && event.message.trim()
      ? event.message
      : "后端返回错误";
  } else {
    state.sawError = true;
    state.errorMessage = "后端响应包含未知事件";
  }
}

/**
 * 共享 NDJSON 流解析：每行一个事件 {type: tool|delta|done|error}。
 * path 为 /api 之后的路径，如 "/chat"、"/daily-review/analyze"。
 */
export async function streamNdjson(
  path: string,
  body: unknown,
  handlers: NdjsonStreamHandlers = {},
  signal?: AbortSignal,
): Promise<NdjsonStreamResult> {
  let resp: Response;
  try {
    resp = await fetch(`/api${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify(body),
      signal,
    });
  } catch (e) {
    if (e instanceof DOMException && e.name === "AbortError") throw e;
    throw new ApiError("连接不到后端，请先启动 backend（uvicorn app:app --port 8900）", 0);
  }
  // 配置错误 / 上下文准备失败等：流开始前以 HTTP 状态返回
  if (!resp.ok) {
    let payload: any = null;
    try {
      payload = await resp.json();
    } catch {
      /* ignore */
    }
    if (resp.status === 401) {
      throw new ApiError("后端开启了访问鉴权（VR_API_KEY）：请在「接入 AI」页底部填写后端访问密钥", 401);
    }
    throw new ApiError(payload?.detail || `HTTP ${resp.status}`, resp.status);
  }
  if (!resp.body) throw new ApiError("后端无响应流", 502);

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  const state = createNdjsonProtocolState();
  let buf = "";
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const lines = buf.split("\n");
      buf = lines.pop() ?? "";
      for (const line of lines) applyNdjsonLine(state, line, handlers);
    }
    buf += decoder.decode();
    if (buf.trim()) applyNdjsonLine(state, buf, handlers);
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    if (typeof error === "object" && error !== null && "name" in error && error.name === "AbortError") {
      throw error;
    }
    throw new ApiError("后端响应流意外中断", 502);
  } finally {
    reader.releaseLock();
  }
  if (state.sawError) throw new ApiError(state.errorMessage || "后端返回错误", 502);
  if (!state.sawDone) throw new ApiError("后端响应流未返回完成信号", 502);
  return { content: state.content, trace: state.trace, rounds: state.rounds, result: state.result };
}

/**
 * 每日复盘 AI 流式分析。只发送 user_request + llm；
 * 市场上下文与 system prompt 由服务器生成，客户端不可注入。
 */
export async function dailyReviewAnalyzeStream(
  request: DailyReviewAnalyzeRequest,
  handlers: NdjsonStreamHandlers = {},
  signal?: AbortSignal,
): Promise<NdjsonStreamResult> {
  return streamNdjson(
    "/daily-review/analyze",
    {
      user_request: request.user_request ?? null,
      llm: request.llm,
    },
    handlers,
    signal,
  );
}

export const api = {
  health: () => get<{ ok: boolean }>("/health"),
  indices: () => get<IndexQuote[]>("/indices"),
  marketOverview: () => get<MarketOverview>("/market/overview"),
  emotion: () => get<ShortTermEmotion>("/market/emotion"),
  turnoverTop: () => get<TurnoverTop>("/market/turnover-top"),
  /**
   * 结构化每日复盘聚合包（一次请求覆盖指数/广度/情绪/成交/板块）。
   * 保留 data；附带可选 cache_meta（stale 时前端可轮询）。
   */
  dailyReview: async (): Promise<{
    data: DailyReviewData;
    cache_meta?: DailyReviewCacheMeta | null;
  }> => {
    let resp: Response;
    const headers: Record<string, string> = { ...authHeaders() };
    const opts: RequestInit = { method: "GET" };
    if (Object.keys(headers).length > 0) opts.headers = headers;
    try {
      resp = await fetch("/api/daily-review", opts);
    } catch {
      throw new ApiError("连接不到后端，请先启动 backend（uvicorn app:app --port 8900）", 0);
    }
    let payload: any = null;
    try {
      payload = await resp.json();
    } catch {
      /* 非 JSON */
    }
    if (!resp.ok) {
      if (resp.status === 401) {
        throw new ApiError("后端开启了访问鉴权（VR_API_KEY）：请在「接入 AI」页底部填写后端访问密钥", 401);
      }
      throw new ApiError(payload?.detail || `HTTP ${resp.status}`, resp.status);
    }
    const data = (payload?.data ?? payload) as DailyReviewData;
    const cache_meta = (payload?.cache_meta ?? null) as DailyReviewCacheMeta | null;
    return { data, cache_meta };
  },
  /**
   * 用户显式刷新每日复盘完整包（绕过 300s 内存缓存）。
   * 与 GET 返回形状一致：{ data, cache_meta }；不写历史、不调用 AI。
   */
  dailyReviewRefresh: async (): Promise<{
    data: DailyReviewData;
    cache_meta?: DailyReviewCacheMeta | null;
  }> => {
    let resp: Response;
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
      ...authHeaders(),
    };
    try {
      resp = await fetch("/api/daily-review/refresh", {
        method: "POST",
        headers,
        body: "{}",
      });
    } catch {
      throw new ApiError("连接不到后端，请先启动 backend（uvicorn app:app --port 8900）", 0);
    }
    let payload: any = null;
    try {
      payload = await resp.json();
    } catch {
      /* 非 JSON */
    }
    if (!resp.ok) {
      if (resp.status === 401) {
        throw new ApiError("后端开启了访问鉴权（VR_API_KEY）：请在「接入 AI」页底部填写后端访问密钥", 401);
      }
      throw new ApiError(payload?.detail || `HTTP ${resp.status}`, resp.status);
    }
    const data = (payload?.data ?? payload) as DailyReviewData;
    const cache_meta = (payload?.cache_meta ?? null) as DailyReviewCacheMeta | null;
    return { data, cache_meta };
  },
  /** 显式保存当前复盘快照（无请求体；服务器自行聚合校验） */
  saveDailyReviewHistory: () =>
    request<SaveDailyReviewHistoryResult>("/daily-review/history/save", "POST"),
  /** 历史元数据列表 */
  listDailyReviewHistory: (params?: {
    trade_date?: string;
    limit?: number;
    offset?: number;
  }) => {
    const q = new URLSearchParams();
    if (params?.trade_date) q.set("trade_date", params.trade_date);
    if (params?.limit != null) q.set("limit", String(params.limit));
    if (params?.offset != null) q.set("offset", String(params.offset));
    const qs = q.toString();
    return get<DailyReviewHistoryList>(`/daily-review/history${qs ? `?${qs}` : ""}`);
  },
  /** 历史快照详情 */
  getDailyReviewHistorySnapshot: (snapshotId: number) =>
    get<DailyReviewHistorySnapshot>(`/daily-review/history/${snapshotId}`),
  /** 历史快照结构化比较（服务端计算 delta/排名变化） */
  compareDailyReviewHistory: (params: {
    base_id: number;
    target_id: number;
    board_limit?: number;
    stock_limit?: number;
  }) => {
    const q = new URLSearchParams();
    q.set("base_id", String(params.base_id));
    q.set("target_id", String(params.target_id));
    if (params.board_limit != null) q.set("board_limit", String(params.board_limit));
    if (params.stock_limit != null) q.set("stock_limit", String(params.stock_limit));
    return get<DailyReviewComparison>(`/daily-review/history/compare?${q.toString()}`);
  },
  marketBreadth: () => get<TimedComponentEnvelope<MarketBreadthData>>("/market/breadth"),
  marketBoards: (type: "industry" | "concept" | "region" = "industry", topN = 20) =>
    get<TimedComponentEnvelope<BoardRankingData>>(`/market/boards?type=${type}&top_n=${topN}`),
  globalIndices: () => get<GlobalIndex[]>("/global/indices"),
  globalStock: (symbol: string) => get<GlobalStock>(`/global/stock?symbol=${encodeURIComponent(symbol)}`),
  radar: () => get<RadarData>("/radar"),
  radarRefresh: () => request<RadarData>("/radar/refresh", "POST"),
  portfolio: () => get<PortfolioData>("/portfolio"),
  addHolding: (code: string, shares: number, cost: number) => request<PortfolioData>("/portfolio/holding", "POST", { code, shares, cost }),
  updateHolding: (code: string, shares: number, cost: number) =>
    request<PortfolioData>("/portfolio/holding", "PUT", { code, shares, cost }),
  removeHolding: (code: string) => request<PortfolioData>(`/portfolio/holding?code=${code}`, "DELETE"),
  refreshPortfolio: () => request<PortfolioData>("/portfolio/refresh", "POST"),
  closePosition: (code: string, date: string, price: number, shares: number, cost: number) =>
    request<PortfolioData>("/portfolio/close", "POST", { code, date, price, shares, cost }),
  removeClosed: (index: number) => request<PortfolioData>(`/portfolio/close?index=${index}`, "DELETE"),
  /** 账户资金。未配置 → configured=false, data=null；不把未配置解释为 0。 */
  getAccountProfile: () => get<AccountProfileResponse>("/account-profile", { unwrapData: false }),
  /**
   * 保存账户资金（后端校验 + 生成 updated_at）。
   * 返回 { configured: true, data: { total_assets, available_cash, updated_at } }。
   */
  saveAccountProfile: (data: AccountProfileRequest) =>
    put<AccountProfileResponse>("/account-profile", {
      total_assets: data.total_assets,
      available_cash: data.available_cash,
    }, { unwrapData: false }),
  /**
   * 结构化持仓操作建议（普通 JSON）。
   * 只发送 user_request + llm；持仓与市场上下文由服务器读取，不注入 portfolio/context/messages。
   */
  portfolioAdvice: (req: PortfolioAdviceRequest, signal?: AbortSignal) =>
    request<PortfolioAdviceResult>("/portfolio/advice", "POST", {
      user_request: req.user_request ?? null,
      llm: req.llm,
    }, { signal }),
  aiResult: <TPayload>(
    resultType: AiResultType,
    tradeDate?: string | null,
    signal?: AbortSignal,
  ) => {
    const query = tradeDate ? `?trade_date=${encodeURIComponent(tradeDate)}` : "";
    return get<AiGeneratedResult<TPayload> | null>(`/ai-results/${resultType}${query}`, { signal });
  },
  valuation: (code: string) => get<Valuation>(`/valuation?code=${code}`),
  percentile: (code: string) => get<ValPercentile>(`/valuation/percentile?code=${code}`),
  financials: (code: string) => get<Financials>(`/financials?code=${code}`),
  announcements: (code: string) => get<Announcement[]>(`/announcements?code=${code}`),
  quote: (codes: string) => get<Record<string, Quote>>(`/quote?codes=${codes}`),
  reports: (code: string) => get<Report[]>(`/reports?code=${code}`),
  news: (code: string) => get<NewsItem[]>(`/news?code=${code}`),
  margin: (code: string) => get<MarginRow[]>(`/margin?code=${code}`),
  blockTrade: (code: string) => get<BlockTradeRow[]>(`/block-trade?code=${code}`),
  holders: (code: string) => get<HolderRow[]>(`/holders?code=${code}`),
  dividend: (code: string) => get<DividendRow[]>(`/dividend?code=${code}`),
  fundFlow: (code: string) => get<FundFlowRow[]>(`/fund-flow?code=${code}`),
  dragonTiger: (code: string) => get<DragonTiger>(`/dragon-tiger?code=${code}`),
  lockup: (code: string) => get<Lockup>(`/lockup?code=${code}`),
  blocks: (code: string) => get<Blocks>(`/blocks?code=${code}`),
  hotConcepts: (code: string) => get<HotConcept[]>(`/hot-concepts?code=${code}`),
  investorQa: (code: string) => get<QaRow[]>(`/investor-qa?code=${code}`),
  industry: (top = 20) => get<IndustryData>(`/industry?top=${top}`),
  myReports: () => get<MyReport[]>("/myreports"),
  uploadReport: (name: string, contentB64: string, meta?: {
    title?: string; institution?: string; publish_date?: string;
    sector_keys?: string[]; source_url?: string; source_kind?: string;
  }) =>
    request<MyReport>("/myreports", "POST", {
      name, content_b64: contentB64,
      ...(meta?.title != null ? { title: meta.title } : {}),
      ...(meta?.institution != null ? { institution: meta.institution } : {}),
      ...(meta?.publish_date != null ? { publish_date: meta.publish_date } : {}),
      ...(meta?.sector_keys != null ? { sector_keys: meta.sector_keys } : {}),
      ...(meta?.source_url != null ? { source_url: meta.source_url } : {}),
      ...(meta?.source_kind != null ? { source_kind: meta.source_kind } : {}),
    }),
  deleteReport: (id: string) => request<{ ok: boolean }>(`/myreports/${id}`, "DELETE"),
  // 注意：get()/request() 已自动加 /api 前缀，这里只传 /myreports/... 即可，禁止重复 /api。
  browseMyReports: (group: MyReportsBrowseGroup, sectorKey?: string) => {
    const q = new URLSearchParams({ group });
    if (sectorKey) q.set("sector_key", sectorKey);
    return get<MyReportsBrowseResult>(`/myreports/browse?${q.toString()}`);
  },
  searchMyReports: (q: string) =>
    get<MyReport[]>(`/myreports/search?q=${encodeURIComponent(q)}`),
  patchReport: (id: string, meta: {
    title?: string; institution?: string; publish_date?: string;
    sector_keys?: string[]; source_url?: string; source_kind?: string;
  }) => {
    const body: Record<string, unknown> = {};
    for (const k of ["title", "institution", "publish_date", "sector_keys", "source_url", "source_kind"] as const) {
      if (meta[k] !== undefined) body[k] = meta[k];
    }
    return request<MyReport>(`/myreports/${id}`, "PATCH", body);
  },

  /**
   * 板块研报发现（不自动归档）。
   * 注意：get()/request() 已自动加 /api 前缀，路径禁止写 /api/...
   */
  discoverSectorReports: (
    sectorKey: string,
    opts?: { days?: number; maxPages?: number; scope?: SectorReportScope },
  ) => {
    const q = new URLSearchParams();
    if (opts?.days != null) q.set("days", String(opts.days));
    if (opts?.maxPages != null) q.set("max_pages", String(opts.maxPages));
    if (opts?.scope) q.set("scope", opts.scope);
    const qs = q.toString();
    return get<SectorReportsDiscoveryResult>(
      `/sector-research/reports/${encodeURIComponent(sectorKey)}${qs ? `?${qs}` : ""}`,
    );
  },

  /** 导入发现研报到我的研报：body 仅 { external_id } */
  importSectorReport: (sectorKey: string, externalId: string) =>
    request<MyReport>(`/sector-research/import/${encodeURIComponent(sectorKey)}`, "POST", {
      external_id: externalId,
    }),

  /** 板块动态数据（一致预期 / 公告等） */
  getSectorResearchData: (sectorKey: string) =>
    get<SectorDynamicData>(`/sector-research/data/${encodeURIComponent(sectorKey)}`),
};
