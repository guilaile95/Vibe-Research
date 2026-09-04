// Pure API types for Vibe-Research backend client.
// Runtime client lives in ../api.ts and re-exports these types.

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
  text_index_status?: MyReportTextIndexStatus;
  text_index_error?: string;
  indexed_at?: string;
  page_count?: number | null;
}


export type MyReportTextIndexStatus =
  | "SEARCHABLE"
  | "NOT_INDEXED"
  | "OCR_REQUIRED"
  | "ARCHIVED_NOT_SEARCHABLE"
  | "INDEX_ERROR";

export interface MyReportTextHit {
  report_id: string;
  title: string;
  name: string;
  page: number | null;
  snippet: string;
  score: number;
  publish_date: string;
  institution: string;
  source_url: string;
}

export type ReportChatSource = Pick<MyReportTextHit, "report_id" | "title" | "page">;

export interface MyReportTextIndexPreviewItem {
  report_id: string;
  title: string;
  status: MyReportTextIndexStatus;
  eligible: boolean;
  error_code: string;
}

export interface MyReportTextIndexPreview {
  items: MyReportTextIndexPreviewItem[];
  total: number;
  writes: 0;
}

export interface MyReportTextIndexBatchResult {
  items: { report_id: string; status: MyReportTextIndexStatus; error_code: string }[];
  total: number;
}


export type MyReportsBrowseGroup = "year" | "industry" | "institution";


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


export type SectorMarketIndex = {
  thscode: string;
  name: string;
  kind: "industry" | "concept";
};


export type SectorMarketMetrics = {
  trade_date: string | null;
  return_5d_pct: number | null;
  return_20d_pct: number | null;
  return_60d_pct: number | null;
  return_5d_delta_vs_previous_5d_pct: number | null;
  turnover_vs_prior_20d: number | null;
  prior_20d_return_pct: number | null;
};


export type SectorMarketBreadth = {
  constituents_total: number;
  snapshot_valid_count: number;
  coverage_ratio: number | null;
  up_count: number;
  down_count: number;
  flat_count: number;
  up_ratio: number | null;
  equal_weight_change_pct: number | null;
  constituents_sample: { code: string; name: string; change_pct: number | null }[];
  constituent_semantics: "CURRENT_CONSTITUENTS_ONLY";
};


export type SectorMarketContextItem = {
  sector_key: string;
  sector_label: string;
  mapping_status: "mapped" | "unavailable";
  index: SectorMarketIndex | null;
  status: "normal" | "partial" | "unavailable";
  warnings: string[];
  metrics: SectorMarketMetrics | null;
  breadth: SectorMarketBreadth | null;
  constituents_as_of_ms: number | null;
  constituent_snapshot_as_of_ms: number | null;
  rank_20d_within_mapped: number | null;
  rank_change_vs_5_sessions_ago: number | null;
  rank_universe_count: number | null;
};


export type SectorMarketContextData = {
  schema_version: "sector_market_context.v0.1";
  status: "normal" | "partial" | "unavailable";
  source: string;
  fetched_at: string;
  mapped_count: number;
  total_count: number;
  warnings: string[];
  items: SectorMarketContextItem[];
};

export interface IntelDigestInputItem {
  title?: string;
  source?: string;
  published_at?: string;
  url?: string;
  summary?: string;
  time?: string;
  zh?: string;
  [key: string]: unknown;
}

export interface IntelDigest {
  digest_id: string;
  digest_date: string;
  sector_key: string;
  sector_name: string;
  status: "normal" | "partial" | "unavailable";
  summary_text: string;
  source_refs: unknown;
  input_fingerprint: string;
  generated_at: string;
  created_at: string;
}

export interface IntelDigestSaveIn {
  sector_key: string;
  status: "normal" | "partial" | "unavailable";
  summary_text: string;
  source_refs?: unknown;
  input_items?: IntelDigestInputItem[];
}

export interface IntelDigestSaveResult {
  digest: IntelDigest | null;
  deduped: boolean;
  error?: string;
}

export interface IntelDigestLatestResult {
  digest: IntelDigest | null;
}


export interface Quote {
  name: string; price: number; last_close: number; change_pct: number;
  pe_ttm: number; pb: number; mcap_yi: number; turnover_pct: number;
  limit_up: number; limit_down: number;
  amount_wan?: number;
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


export interface FinancialPeriod {
  period: string | null;
  period_end: string | null;
  report_date: string | null;
  revenue: string | null; revenue_yoy: string | null;
  net_profit: string | null; net_profit_yoy: string | null;
  deduct_net_profit: string | null; deduct_net_profit_yoy: string | null;
  eps: string | null; bvps: string | null; roe: string | null;
  gross_margin: string | null; net_margin: string | null; op_cf_ps: string | null;
  current_ratio: string | null; quick_ratio: string | null;
  debt_to_equity_ratio: string | null; debt_ratio: string | null;
  revenue_amount: number | null; net_profit_amount: number | null;
  parent_holder_net_profit_amount: number | null;
  operating_cash_flow: number | null; capital_expenditure: number | null;
  free_cash_flow: number | null; assets_total: number | null;
  cash: number | null; accounts_receivable: number | null;
  total_debt: number | null; holder_equity_total: number | null;
  cash_conversion_ratio: number | null; free_cash_flow_margin: number | null;
  accrual_ratio: number | null; receivables_pressure: number | null;
  net_cash_ratio: number | null;
}

export interface Financials extends FinancialPeriod {
  history: FinancialPeriod[];
  data_quality: {
    status: "normal" | "partial";
    source: "tonghuashun_via_akshare";
    fetch_mode: "snapshot";
    report_basis: "cumulative_report_period";
    point_in_time_supported: false;
    publication_date_known: false;
    missing_fields: string[];
    warnings: string[];
  };
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


export interface SectorFlow {
  name: string; pct: number; net: number; inflow: number; outflow: number; firms: number;
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
  title: string;
  url: string;
  time: string;
  source: string;
  summary?: string;
  zh?: string;
  /** Authoritative ISO-8601 publish time with timezone; null when unknown. */
  published_at?: string | null;
  /** Unix epoch seconds; used only when published_at is missing (old cache migration). */
  ts?: number;
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
  holding_authority?: "LEDGER_DERIVED" | "LEGACY_PORTFOLIO" | "UNKNOWN";
  ledger_view?: {
    bootstrap_status?: string;
    canonical?: boolean;
    data_limitations?: string[];
    reconciliation?: {
      summary?: { match: number; mismatch: number; missing_in_ledger: number; missing_in_portfolio: number };
      items?: Array<{
        code: string;
        status: string;
        reason: string | null;
        ledger_shares?: number | null;
        ledger_cost?: number | null;
        portfolio_shares?: number | null;
        portfolio_cost?: number | null;
      }>;
    };
  };
}


// ---------------------------------------------------------------------------
// 账户资金（手工填写，GET /api/account-profile 与 PUT /api/account-profile）
// ---------------------------------------------------------------------------

export interface AccountProfileData {
  total_assets: number;
  available_cash: number;
  updated_at: string;
  confirmation_status: "CONFIRMED" | "LEGACY_UNPROVEN";
  confirmation_id: string | null;
  effective_at: string | null;
  recorded_at: string | null;
  authority: "MANUAL_EXPLICIT_CONFIRMATION" | null;
}


export type AccountProfileStatus = "valid" | "not_configured" | "corrupted";

export interface AccountProfileResponse {
  configured: boolean;
  status: AccountProfileStatus;
  reason_code: string | null;
  data: AccountProfileData | null;
}


export interface AccountProfileRequest {
  total_assets: number;
  available_cash: number;
  confirm_current: true;
}


// P1-CASH1：GET /api/account/reality 只读账户现实（canonical cash readback 用其 cash 段）。
// current_fact = account_profile 手工快照（MANUAL）；ledger_candidate = bootstrap 期初现金
// + 成交/现金事件推演（DERIVED）。两者语义不同，UI 必须区分，不得互相当作对方。
export interface AccountRealityCashFact {
  value: number | null;
  source: string;
  fact_type: string;
  status: "AVAILABLE" | "STALE" | "UNKNOWN" | "CORRUPTED";
  reason_code?: string;
  updated_at?: string | null;
  recorded_at?: string | null;
  effective_at?: string | null;
  confirmation_id?: string | null;
  authority?: string | null;
  authority_state?: "CANONICAL" | "UNPROVEN" | "STALE" | "UNKNOWN" | "CORRUPTED" | string;
  temporal_status?: "PROVEN" | "UNPROVEN" | "STALE" | string;
  temporal_reason_code?: string;
  coverage?: string;
}

export interface AccountRealityPosition {
  code: string;
  name: string;
  shares: number;
  price: number | null;
  price_date: string | null;
  pricing_status: "PRICED" | "UNPRICED" | string;
  market_value: number | null;
}

export interface AccountReality {
  account_status?: string;
  bootstrap_status?: string;
  canonical?: boolean;
  canonical_reason_codes?: string[];
  account_authority?: {
    state: "CANONICAL" | "UNPROVEN" | "STALE" | "UNKNOWN" | "CORRUPTED" | string;
    source: string;
    confirmation_id: string | null;
    effective_at: string | null;
    recorded_at: string | null;
    latest_relevant_mutation_at: string | null;
    reason_codes: string[];
  };
  account_total_assets?: {
    current_fact: AccountRealityCashFact;
  };
  cash: {
    current_fact: AccountRealityCashFact;
    ledger_candidate: AccountRealityCashFact;
    reconciliation: "MATCH" | "MISMATCH" | "UNKNOWN";
    coverage?: string;
    cash_subfact_canonical?: boolean;
  };
  positions?: AccountRealityPosition[];
  pricing?: {
    mode: string;
    status: "COMPLETE" | "PARTIAL" | "UNAVAILABLE" | "MIXED_CUTOFF" | string;
    priced_holdings: number;
    total_holdings: number;
    unified_price_date: string | null;
  };
  market_value?: number | null;
  settled_nav?: number | null;
  nav_authority?: string | null;
  nav_canonical?: boolean;
  nav_cash_source?: string | null;
  nav_reconciliation?: {
    status: "MATCH" | "MISMATCH" | "UNKNOWN";
    account_profile_total_assets: number | null;
    computed_nav: number | null;
  };
  nav_temporal_state?: "MIXED_UNPROVEN" | "UNAVAILABLE" | string;
  nav_temporal_reason_codes?: string[];
  data_cutoff?: string | null;
  confidence?: string;
  reason_codes?: string[];
  as_of?: string;
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
  canonical?: boolean;
  status?: AccountProfileStatus | "partial";
  reason_code?: string | null;
  canonical_reason_codes?: string[];
  authority_state?: string | null;
  confirmation_id?: string | null;
  effective_at?: string | null;
  recorded_at?: string | null;
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


// ---------------------------------------------------------------------------
// 数据健康中心
// ---------------------------------------------------------------------------

export type DataHealthStatus = "normal" | "partial" | "unavailable";

export interface DataHealthRecordDto {
  source_id: string;
  module: string;
  display_name: string;
  status: DataHealthStatus;
  is_stale: boolean;
  observed_at: string | null;
  last_success_at: string | null;
  data_trade_date: string | null;
  data_cutoff: string | null;
  stale_after_seconds: number | null;
  is_cached: boolean | null;
  is_degraded: boolean | null;
  coverage_current: number | null;
  coverage_expected: number | null;
  last_error_code: string | null;
  last_error_summary: string | null;
  last_error_at: string | null;
  blocks_advice: boolean;
  block_reason: string | null;
  detail_path: string | null;
}

export interface DataHealthOverviewResult {
  overall_status: DataHealthStatus;
  blocks_advice: boolean;
  block_reasons: Array<{ source_id: string; error_code: string; summary: string }>;
  summary: {
    normal: number;
    partial: number;
    unavailable: number;
    stale: number;
    not_initialized: number;
  };
  items: DataHealthRecordDto[];
}

export interface DataHealthDetailResult {
  record: DataHealthRecordDto;
  calculation: {
    quality_basis?: string[];
    freshness_basis?: string;
    calendar_type?: string;
    rule_summary?: string;
    disclaimer?: string;
  };
  related_pages: Array<{ label: string; path: string }>;
}



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
  stale_reason_code?: string;
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


/** K 线 Bar（mootdx）：标准 OHLC；字段名按 mootdx DataFrame 列。 */
export interface KlineBar {
  date?: string; datetime?: string; open?: number; close?: number;
  high?: number; low?: number; volume?: number; amount?: number;
  [key: string]: string | number | undefined;
}

/** 巨潮公告全文项（akshare cninfo）。 */
export interface DisclosureItem {
  title?: string; info?: string; date?: string; url?: string;
  [key: string]: string | number | boolean | null | undefined;
}


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

// 港股现金流量表（GET /api/global/hk/cashflow，东财 RPT_HKSK_FN_CASHFLOW）
export interface HkCashflowItem { amount: number | null; yoy: number | null }
export interface HkCashflowPeriod {
  report_date: string; report: string | null;
  currency: string | null; account_standard: string | null;
  items: Record<string, HkCashflowItem>;
}
export interface HkCashflow {
  code: string; name: string; market: string;
  currency: string | null; item_order: string[]; periods: HkCashflowPeriod[];
}

// ---------------------------------------------------------------------------
// 产业信号 · GPU 租金（GET /api/signals/gpu-rent）
// ---------------------------------------------------------------------------

export interface GpuSpot {
  gpu: string; median?: number; asof_ts?: number;
  available_gpus?: number | null; total_gpus?: number | null;
  unavailable?: boolean; note?: string; err?: string;
  stale?: boolean; fetch_error?: string; observed_at?: string | null;
}
export interface GpuHistSeries {
  gpu: string; n_points?: number; points?: [number, number][]; latest?: number;
  unavailable?: boolean; note?: string; err?: string;
  stale?: boolean; fetch_error?: string; observed_at?: string | null;
}
export interface ForwardRung { strike: number; p_above: number; open_interest: number | null }
export interface DistBin { label: string; lo: number | null; hi: number | null; p: number }
export interface ImpliedMedian { value: number; bound: "exact" | "above" | "below" }
export interface ForwardMonth {
  month: string; close_date: string; rungs: ForwardRung[];
  lowest_strike: number; p_below_lowest: number;
  implied_median: ImpliedMedian | null;
  distribution: DistBin[]; most_likely: DistBin;
}
export interface SettledMonth { month: string; lo: number | null; hi: number | null }
export interface GpuForward {
  months?: ForwardMonth[]; n_contracts?: number; n_months?: number;
  settled?: SettledMonth[]; settled_error?: string | null;
  unavailable?: boolean; note?: string; err?: string;
  stale?: boolean; fetch_error?: string; observed_at?: string | null;
}
export interface GpuRentData {
  generated_at: string | null;
  how_to_read: string[];
  spot_source: string; history_source: string; forward_source: string;
  spot: { gpus: GpuSpot[] };
  history: { gpus: GpuHistSeries[]; days: number };
  forward: GpuForward | null;
  errors: string[] | null;
}


// ---------------------------------------------------------------------------
// 北向资金（GET /api/market/northbound）
// ---------------------------------------------------------------------------

export type NorthboundLimitation = {
  field: string;
  reason_code: string;
  detail: string;
};

export type NorthboundMarketLeg = {
  market: "SSE" | "SZSE";
  total_turnover_mn: number | null;
  trade_count: number | null;
  etf_turnover_mn: number | null;
  daily_quota_balance_mn: number | null;
  net_buy_mn: null;
};

export type NorthboundActiveStock = {
  market: "SSE" | "SZSE";
  rank: number;
  code: string;
  name: string;
  total_turnover_yuan: number | null;
  net_buy_yuan: null;
};

export type NorthboundCapitalFlow = {
  schema_version: string;
  source: string;
  source_tier: "authoritative" | "reference";
  trade_date: string | null;
  fetched_at: string;
  status: "normal" | "partial" | "unavailable";
  is_stale: boolean;
  currency: string;
  amount_unit: string;
  warnings: string[];
  limitations: NorthboundLimitation[];
  data: {
    northbound: {
      total_turnover_mn: number | null;
      trade_count: number | null;
      etf_turnover_mn: number | null;
      net_buy_mn: null;
    };
    shanghai_connect: NorthboundMarketLeg;
    shenzhen_connect: NorthboundMarketLeg;
    active_stocks: NorthboundActiveStock[];
  };
};



// ---------------------------------------------------------------------------
// 技术指标与价格触发（GET /api/market/technical-indicators）
// ---------------------------------------------------------------------------

export type TechnicalIndicatorTriggerType =
  | "close_above_20d_high"
  | "close_below_20d_low"
  | "sma_golden_cross"
  | "sma_death_cross"
  | "volume_spike";

export interface TechnicalIndicatorTrigger {
  type: TechnicalIndicatorTriggerType | string;
  message: string;
  value: number | null;
}

export interface TechnicalIndicatorLatest {
  close: number | null;
  sma5: number | null;
  sma10: number | null;
  sma20: number | null;
  sma60: number | null;
  ema12: number | null;
  ema26: number | null;
  macd_dif: number | null;
  macd_dea: number | null;
  macd_histogram: number | null;
  rsi14: number | null;
  bollinger_upper: number | null;
  bollinger_middle: number | null;
  bollinger_lower: number | null;
  volume_ratio_5_20: number | null;
}

export interface TechnicalIndicatorSeriesPoint {
  date: string;
  sma20: number | null;
  sma60: number | null;
  bollinger_upper: number | null;
  bollinger_middle: number | null;
  bollinger_lower: number | null;
  macd_dif: number | null;
  macd_dea: number | null;
  macd_histogram: number | null;
  rsi14: number | null;
  volume_ratio_5_20: number | null;
}

export interface TechnicalIndicators {
  schema_version: string;
  code: string;
  period: string;
  trade_date: string | null;
  fetched_at: string;
  status: "normal" | "partial" | "unavailable";
  warnings: string[];
  limitations: Array<string | { field?: string; reason_code?: string; detail?: string }>;
  latest: TechnicalIndicatorLatest;
  triggers: TechnicalIndicatorTrigger[];
  series: TechnicalIndicatorSeriesPoint[];
}
// 顶部风险分析（GET /api/market/top-risk，影子模式 Phase 1）
// 契约与 backend top_risk_schema.TopRiskEnvelope 对齐
// ---------------------------------------------------------------------------

export type TopRiskStatus = "normal" | "partial" | "unavailable";

export type TopRiskDirection = "RISK" | "SAFE" | "NEUTRAL";

export type TopRiskLimitation = {
  field: string;
  reason_code: string;
  detail: string;
};

export type TopRiskStepTrace = {
  step_id: string;
  label: string;
  direction: TopRiskDirection | string;
  weight: number;
  step_risk: number;
  confidence: number;
  skipped: boolean;
  skip_reason?: string | null;
  reasons: string[];
  details: Record<string, unknown>;
};

export type TopRiskData = {
  name?: string | null;
  completed_steps: number;
  total_steps: number;
  risk_drivers: string[];
  safety_signals: string[];
  narrative?: string | null;
};

export type TopRiskAnalysis = {
  schema_version: string;
  source: string;
  source_tier: string;
  code: string;
  name?: string | null;
  trade_date?: string | null;
  fetched_at: string;
  status: TopRiskStatus | string;
  is_stale: boolean;
  risk_score: number | null;
  confidence: number | null;
  coverage: { completed: number; total: number; ratio: number } | null;
  signal: string;
  signal_eligible: boolean;
  /** 影子模式接入主项目决策追踪层：决策运行 id（unavailable 时为 null） */
  config_hash?: string | null;
  decision_run_id?: string | null;
  /** archived=已归档 / failed=归档异常（不影响分析） / skipped=unavailable 明确不归档 */
  trace_archive_status?: "archived" | "failed" | "skipped" | string | null;
  warnings: string[];
  limitations: TopRiskLimitation[];
  data: TopRiskData | null;
  trace: TopRiskStepTrace[];
};


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
  onSources?: (items: ReportChatSource[]) => void;
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


// ============================================================================
// 投资逻辑与证据账本（Investment Thesis & Evidence Ledger）
// ============================================================================

export interface EvidenceRecord {
  id: string;
  subject_type: "stock" | "sector" | "theme";
  subject_id: string;
  evidence_type: "news" | "announcement" | "report" | "research_note" | "financial_filing" | "other";
  claim: string;
  source_title: string;
  source_url: string | null;
  source_date: string | null;
  accessed_at: string;
  classification: "fact" | "inference" | "unknown";
  confidence: "high" | "medium" | "low";
  created_at: string;
  updated_at: string;
  deleted: number;
  deleted_at: string | null;
}

export type TemporalAuthorityState = "PROVEN" | "UNPROVEN" | "ERROR";
export type TemporalAuthorityBasis = "SOURCE_PUBLISHED_AT" | "EVENT_OCCURRED_AT" | "NONE";

export interface EvidenceTemporalAuthority {
  schema_version: string;
  evidence_id: string;
  temporal_state: TemporalAuthorityState;
  effective_at: string | null;
  temporal_basis: TemporalAuthorityBasis;
  authority_refs: string[];
  reason_codes: string[];
  ec1_evaluation: "EVALUATED" | "NOT_EVALUATED";
  ec1_safe_item: {
    evidence_id: string;
    scope_kind: string;
    scope_id: string;
    effective_at: string | null;
    retrieved_at: string | null;
    time_semantics: string;
    authority_refs: string[];
  } | null;
  observed_time_is_not_effective_time: true;
}

export interface EvidenceTemporalIntakeInput {
  source_identity?: string | null;
  event_identity?: string | null;
  source_published_at?: string | null;
  event_occurred_at?: string | null;
  observed_at?: string | null;
  created_at?: string | null;
  ingested_at?: string | null;
}

// P0-CT1：Thesis 交易策略枚举（与 backend THESIS_STRATEGIES / Campaign strategy 逐字一致）
export type ThesisStrategy = "SHORT" | "SWING" | "MEDIUM";

// P0-CT1：预期持有周期（backend expected_horizon JSON 结构，anchor 恒为 FREEZE_AT）
export interface ExpectedHorizon {
  unit: "TRADING_DAY";
  min: number;
  max: number;
  anchor: "FREEZE_AT";
}

// 投资逻辑（主表字段）
export interface InvestmentThesis {
  id: string;
  subject_type: "stock" | "sector" | "theme";
  subject_id: string;
  market: "CN" | "HK" | "US" | "KR" | null;
  title: string;
  summary: string;
  status: "active" | "weakened" | "invalidated" | "archived";
  core_claims: string[];
  catalysts: string[];
  risks: string[];
  invalidation_conditions: string[];
  created_at: string;
  updated_at: string;
  current_revision: number;
  // P0-CT1 Formal 化生命周期（与 backend 五态 matrix 逐字一致；legacy 行缺失视为 null）
  formal_state: "draft" | "confirmed" | "frozen" | null;
  formalization_started_at: string | null;
  confirmed_at: string | null;
  frozen_at: string | null;
  frozen_revision: number | null;
  archived_at: string | null;
  strategy: ThesisStrategy | null;
  expected_horizon: ExpectedHorizon | null;
  free_notes: string | null;
}

// 证据关联（含证据快照字段）
export interface EvidenceLink {
  evidence_id: string;
  evidence_type: string;
  stance: "support" | "oppose" | "neutral";
  claim: string;
  classification: string;
  confidence: string;
  source_title: string;
  source_url: string | null;
  source_date: string | null;
  accessed_at: string;
}

// 投资逻辑聚合状态（thesis 详情返回）
export interface ThesisAggregate {
  thesis: InvestmentThesis;
  evidence_links: EvidenceLink[];
}

// 版本快照
export interface ThesisRevision {
  id: string;
  thesis_id: string;
  revision_number: number;
  snapshot: ThesisAggregate;
  change_summary: string;
  created_at: string;
}

// 版本列表项
export interface ThesisRevisionListItem {
  id: string;
  thesis_id: string;
  revision_number: number;
  change_summary: string;
  created_at: string;
}

// Diff 结果
export interface ThesisDiff {
  from_revision: number;
  to_revision: number;
  thesis_changes: Record<string, { from: any; to: any }>;
  evidence_added: { evidence_id: string; to: EvidenceLink }[];
  evidence_removed: { evidence_id: string; from: EvidenceLink }[];
  evidence_changed: { evidence_id: string; changes: Record<string, { from: any; to: any }> }[];
}

// 列表响应
export interface EvidenceListResult { items: EvidenceRecord[]; total: number; limit: number; offset: number; }
export interface ThesisListResult { items: InvestmentThesis[]; total: number; limit: number; offset: number; }
export interface RevisionListResult { items: ThesisRevisionListItem[]; total: number; }

// ============================================================================
// 严格请求类型：Evidence & Thesis 操作契约
// ============================================================================

/** POST /api/evidence - 创建证据请求 */
export interface EvidenceCreateInput {
  subject_type: "stock" | "sector" | "theme";
  subject_id: string;
  evidence_type: "news" | "announcement" | "report" | "research_note" | "financial_filing" | "other";
  claim: string;
  source_title: string;
  source_url: string | null;
  source_date: string | null;  // YYYY-MM-DD or null
  accessed_at: string;          // ISO datetime
  classification: "fact" | "inference" | "unknown";
  confidence: "high" | "medium" | "low";
}

/** PUT /api/evidence/{id} - 更新证据请求 */
export interface EvidenceUpdateInput {
  evidence_type: "news" | "announcement" | "report" | "research_note" | "financial_filing" | "other";
  claim: string;
  source_title: string;
  source_url: string | null;
  source_date: string | null;  // YYYY-MM-DD or null
  accessed_at: string;          // ISO datetime
  classification: "fact" | "inference" | "unknown";
  confidence: "high" | "medium" | "low";
}

/** POST /api/thesis - 创建逻辑请求（服务端自动设置 market 和 status） */
export interface ThesisCreateInput {
  subject_type: "stock" | "sector" | "theme";
  subject_id: string;
  title: string;
  summary: string;
  core_claims: string[];
  catalysts: string[];
  risks: string[];
  invalidation_conditions: string[];
  change_summary?: string;
}

/** PUT /api/thesis/{id} - 更新逻辑请求（服务端自动设置 market） */
export interface ThesisUpdateInput {
  title: string;
  summary: string;
  status: "active" | "weakened" | "invalidated";
  core_claims: string[];
  catalysts: string[];
  risks: string[];
  invalidation_conditions: string[];
  expected_revision: number;
  change_summary?: string;
  // P0-CT1 Formal 字段：仅 draft thesis 由服务端落库；legacy/confirmed/frozen 忽略（后端行为）。
  strategy?: ThesisStrategy | null;
  expected_horizon?: ExpectedHorizon | null;
  free_notes?: string | null;
}

/** POST /api/thesis/{id}/evidence - 关联证据请求 */
export interface LinkEvidenceInput {
  evidence_id: string;
  stance: "support" | "oppose" | "neutral";
  expected_revision: number;
  change_summary?: string;
}

/** PUT /api/thesis/{id}/evidence/{evidence_id} - 更新立场请求 */
export interface UpdateStanceInput {
  stance: "support" | "oppose" | "neutral";
  expected_revision: number;
  change_summary?: string;
}

// P0-CT1：Formal 化快照（POST /thesis/{id}/freeze 返回的 vNext flat snapshot：
// 保留 thesis 嵌套聚合 + 顶层 flat 字段，后端两者为同一内容）。
export interface FormalThesisSnapshot extends ThesisAggregate {
  formal_state: "frozen";
  formalization_started_at: string;
  confirmed_at: string;
  frozen_at: string;
  frozen_revision: number;
  archived_at: string | null;
  status: "active" | "archived";
  current_revision: number;
  updated_at: string;
}


// ---- 交易流水 (P1-1 / P1-2) ----

export type TradeOperation = "buy" | "add" | "reduce" | "sell";

export type TradeExecutionStatus = "full" | "partial" | "not_executed";

export interface TradeAdviceSnapshot {
  action: "add" | "hold" | "reduce" | "sell" | "watch" | "avoid";
  execution_quantity: number | null;
  price_conditions: string[];
  execution_plan: string[];
  risk_conditions: string[];
  invalidation_conditions: string[];
  confidence: "high" | "medium" | "low";
}

export interface TradeRecord {
  trade_id: string;
  code: string;
  name: string;

  operation: TradeOperation;
  execution_status: TradeExecutionStatus;

  planned_price: number | null;
  planned_quantity: number | null;

  actual_price: number | null;
  actual_quantity: number;
  executed_at: string | null;

  fee: number;
  other_cost: number;
  unexecuted_reason: string | null;
  note: string | null;

  advice_trade_date: string | null;
  advice_generated_at: string | null;
  advice_snapshot: TradeAdviceSnapshot | null;

  thesis_id: string | null;
  thesis_revision: number | null;

  created_at: string;
  voided_at: string | null;
  void_reason: string | null;

  gross_amount: number;
  total_cost: number;
  net_cash_flow: number;

  price_variance: number | null;
  price_variance_pct: number | null;
  quantity_completion_pct: number | null;
}

export interface TradeCreateInput {
  code: string;
  name: string;
  operation: TradeOperation;
  execution_status: TradeExecutionStatus;

  planned_price?: number | null;
  planned_quantity?: number | null;

  actual_price?: number | null;
  actual_quantity?: number;
  executed_at?: string | null;

  fee?: number;
  other_cost?: number;
  unexecuted_reason?: string | null;
  note?: string | null;

  advice_ref?: {
    trade_date: string;
    generated_at: string;
  };

  thesis_ref?: {
    thesis_id: string;
    revision_number: number;
  };
}

export interface TradeAttributionCandidate {
  decision_id: string;
  campaign_id: string;
  security_code: string;
  strategy: string;
  thesis_id: string;
  thesis_revision: number;
  committed_at: string;
  review_by: string;
  next_best_action: string;
  snapshot_hash: string;
}

export type TradeAttributionCandidateScanState = "COMPLETE" | "COMPLETE_EMPTY" | "INVALID_WITNESS" | "NOT_APPLICABLE";

export interface TradeAttributionCandidateScan {
  candidates: TradeAttributionCandidate[];
  scan_state: TradeAttributionCandidateScanState;
  reason_codes: string[];
}

export interface TradeReconciliationResult {
  trade_id: string;
  security_code: string;
  execution_status: TradeExecutionStatus;
  allocation_state: "ALLOCATED" | "UNALLOCATED" | "UNPLANNED" | "NOT_APPLICABLE" | "UNKNOWN" | "NOT_EVALUATED" | "ERROR";
  reconciliation_requirement: "NOT_REQUIRED" | "REQUIRED" | "NOT_APPLICABLE" | "UNKNOWN" | "NOT_EVALUATED" | "ERROR";
  attribution_coverage: "COMPLETE" | "UNKNOWN" | "NOT_EVALUATED" | "ERROR";
  campaign_id: string | null;
  decision_id: string | null;
  attribution_id: string | null;
  origin: "UNPLANNED" | null;
  pre_trade_decision: "NONE" | null;
  pre_trade_thesis: "NONE" | null;
  origin_resolution_id?: string;
  reason_codes: string[];
  authority_refs: string[];
  [key: string]: unknown;
}

// ---- 决策反馈 (Decision Feedback P1-3) ----

export type DecisionFeedbackAdoptionStatus =
  | "followed"
  | "partially_followed"
  | "not_followed"
  | "not_applicable";

export type DecisionFeedbackOutcomeStatus =
  | "better_than_expected"
  | "as_expected"
  | "worse_than_expected"
  | "not_evaluated";

export interface DecisionFeedbackRecord {
  feedback_id: string;
  code: string;
  advice_trade_date: string;
  advice_generated_at: string;
  trade_id: string | null;
  adoption_status: DecisionFeedbackAdoptionStatus;
  outcome_status: DecisionFeedbackOutcomeStatus;
  note: string | null;
  created_at: string;
  voided_at: string | null;
  void_reason: string | null;
}

export interface DecisionFeedbackCreateInput {
  code: string;
  advice_ref: {
    trade_date: string;
    generated_at: string;
  };
  trade_id?: string | null;
  adoption_status: DecisionFeedbackAdoptionStatus;
  outcome_status: DecisionFeedbackOutcomeStatus;
  note?: string | null;
}

// ---- Formal Decision Outcome (P0-OL1) ----

export type FormalOutcomeStatus =
  | "PENDING"
  | "EVALUATED"
  | "UNKNOWN"
  | "NOT_EVALUATED"
  | "ERROR";

export interface FormalPricePoint {
  state?: string;
  security_code?: string;
  exchange?: string | null;
  provider_alias?: string | null;
  as_of?: string;
  trade_date?: string | null;
  close?: number | null;
  publication_id?: string | null;
  source_observation_id?: string | null;
  observation_fetched_at?: string | null;
  authority_refs?: string[];
  reason_codes?: string[];
  [key: string]: unknown;
}

export interface DecisionProcessReviewDimension {
  status?: "ANSWERED" | "UNKNOWN" | string;
  text?: string;
  [key: string]: unknown;
}

export interface DecisionProcessReview {
  schema_version?: string;
  state?: "BOUND" | "NONE" | "ERROR" | string;
  challenge_id?: string | null;
  finalized_at?: string | null;
  packet_state?: string | null;
  challenge_evaluation?: string | null;
  challenge_coverage_state?: string | null;
  dimensions?: Record<string, DecisionProcessReviewDimension>;
  covered_dimensions?: string[];
  unknown_dimensions?: string[];
  two_pass_state?: string | null;
  two_pass_semantic_independence_verified?: string | null;
  first_pass_ref?: string | null;
  first_pass_at?: string | null;
  second_pass_ref?: string | null;
  second_pass_at?: string | null;
  reason_codes?: string[];
  authority_refs?: string[];
  process_quality?: {
    state?: string;
    reason_codes?: string[];
    [key: string]: unknown;
  };
  [key: string]: unknown;
}

export type FormalDueState = "DUE" | "NOT_DUE" | "ERROR";

export type FormalReviewWorklistGroup = "due" | "upcoming" | "unavailable";

export interface FormalReviewWorklistItem {
  decision_id: string;
  decision_snapshot_hash?: string;
  security_code?: string;
  strategy?: string;
  campaign_id?: string;
  decision_committed_at?: string;
  decision_next_best_action?: string | null;
  decision_review_by: string;
  due_state: FormalDueState;
  outcome_status?: string;
  reason_codes?: string[];
  group: FormalReviewWorklistGroup;
  error_code?: string;
}

export interface FormalDecisionReviewWorklist {
  schema_version: string;
  evaluation_as_of: string;
  due: FormalReviewWorklistItem[];
  upcoming: FormalReviewWorklistItem[];
  unavailable: FormalReviewWorklistItem[];
  counts: {
    due: number;
    upcoming: number;
    unavailable: number;
    total: number;
  };
  authority_refs?: string[];
}

export interface FormalDecisionOutcome {
  schema_version: string;
  decision_id: string;
  decision_snapshot_hash?: string;
  security_code?: string;
  strategy?: string;
  campaign_id?: string;
  thesis_id?: string;
  thesis_revision?: number;
  decision_committed_at?: string;
  decision_review_by?: string;
  decision_next_best_action?: string;
  evaluation_as_of?: string | null;
  outcome_status: FormalOutcomeStatus | string;
  due_state?: string;
  decision_time_replay?: {
    replay_hash?: string;
    snapshot?: Record<string, unknown>;
    [key: string]: unknown;
  };
  replay_future_fact_leak?: boolean;
  outcome_reveal?: Record<string, unknown> | null;
  actual_capital_outcome?: {
    state?: string;
    pnl_state?: string;
    trade_count?: number;
    trade_ids?: string[];
    pnl?: Record<string, unknown> | null;
    reason_codes?: string[];
    [key: string]: unknown;
  };
  counterfactual_outcome?: {
    state?: string;
    metric_kind?: string;
    start_price_point?: FormalPricePoint;
    end_price_point?: FormalPricePoint;
    security_return?: string | number | null;
    reason_codes?: string[];
    authority_refs?: string[];
    [key: string]: unknown;
  };
  process_quality?: {
    state?: string;
    reason_codes?: string[];
    [key: string]: unknown;
  };
  process_review?: DecisionProcessReview;
  reason_codes?: string[];
  [key: string]: unknown;
}


// ---- 决策依据与可解释性 (Decision Evidence & Explainability P2-1) ----

export type DecisionTraceStatus = "complete" | "partial" | "failed" | "archived";

export type EvidenceQualityStatus = "valid" | "partial" | "missing" | "stale" | "unavailable";

export type EvidenceScope = "market" | "sector" | "stock" | "portfolio" | "account" | "risk";

export interface DecisionRunRecord {
  id?: string;
  decision_run_id?: string;
  advice_id?: string | null;
  symbol?: string | null;
  code?: string | null;
  trade_date: string;
  generated_at: string;
  trace_status: DecisionTraceStatus | string;
  quality_status?: EvidenceQualityStatus | string;
  summary?: string | null;
  decision_type?: string | null;
  action?: string | null;
  evidence_count?: number;
  missing_count?: number;
  created_at?: string | null;
}

export interface EvidenceItemRecord {
  id?: string;
  evidence_id?: string;
  decision_run_id: string;
  scope: EvidenceScope | string;
  category?: string | null;
  evidence_key?: string | null;
  evidence_type?: string | null;
  code?: string | null;
  symbol?: string | null;
  name?: string | null;
  metric_name?: string | null;
  title?: string | null;
  content?: string | Record<string, any> | null;
  value_json?: string | Record<string, any> | null;
  source?: string | null;
  source_ref_json?: any;
  quality_status: EvidenceQualityStatus | string;
  observation_time?: string | null;
  data_timestamp?: string | null;
  is_missing?: boolean;
  missing_reason?: string | null;
  impact_weight?: number | null;
  created_at?: string | null;
}

export interface ExplanationItemRecord {
  id?: string;
  explanation_id?: string;
  decision_run_id: string;
  code?: string | null;
  claim?: string | null;
  conclusion?: string | null;
  conclusion_type?: string | null;
  conclusion_value?: string | null;
  explanation_text?: string | null;
  supporting_evidence_ids?: string[];
  limiting_evidence_ids?: string[];
  reasoning?: string | null;
  confidence_score?: number | null;
  created_at?: string | null;
}

export interface DecisionEvidenceDetailResult {
  run?: DecisionRunRecord;
  decision_run?: DecisionRunRecord;
  evidence_items: EvidenceItemRecord[];
  explanations?: ExplanationItemRecord[];
  explanation_items?: ExplanationItemRecord[];
  missing_evidences?: EvidenceItemRecord[];
}

export interface DecisionEvidenceListResult {
  items: Array<DecisionRunRecord | EvidenceItemRecord | Record<string, any>>;
  total: number;
  page?: number;
  limit?: number;
  offset?: number;
  total_pages?: number;
}


// ---- 信号账本 (Signal Ledger P2-2) ----

export type SignalStage =
  | "schema"
  | "compatibility"
  | "fact_reconciliation"
  | "policy_audit"
  | "execution"
  | "narrative_audit"
  | "account_constraint";

export type SignalSeverity = "info" | "warning" | "error";

export interface SignalEntryRecord {
  entry_id: string;
  decision_run_id: string;
  stage: SignalStage | string;
  code?: string | null;
  signal_type: string;
  severity: SignalSeverity | string;
  payload_json: Record<string, any>;
  created_at: string;
}

export interface DecisionOutcomeRecord {
  outcome_id: string;
  decision_run_id: string;
  code: string;
  action: string;
  target_ratio?: number | null;
  reason: string;
  constraints_applied_json: string[];
  created_at: string;
}

export interface SignalLedgerRunDetailResult {
  run: DecisionRunRecord;
  signal_entries: SignalEntryRecord[];
  decision_outcomes: DecisionOutcomeRecord[];
}

export interface SignalLedgerQueryResult {
  items: SignalEntryRecord[];
  total: number;
  limit: number;
  offset: number;
}


// ---------------------------------------------------------------------------
// 账户资金执行策略（GET/PUT /api/account-execution-policy）
// ---------------------------------------------------------------------------

export interface AccountExecutionPolicy {
  lot_size: number;
  min_cash_reserve_pct: number;
  max_single_stock_allocation_pct: number;
  tie_breaker_order: "code_asc" | "code_desc" | "proportional";
  allow_partial_execution: boolean;
}

export type AccountExecutionPolicyStatus = "default" | "configured" | "corrupted";

export interface AccountExecutionPolicyResponse {
  status: AccountExecutionPolicyStatus;
  reason_code: string | null;
  data: AccountExecutionPolicy | null;
}


// ---- 决策绩效分析 (Decision Feedback Analytics P2-4A) ----

export interface AdoptionSummary {
  total: number;
  counts: {
    followed: number;
    partially_followed: number;
    not_followed: number;
    not_applicable: number;
  };
  adoption_rate: number | null;
  date_from: string | null;
  date_to: string | null;
}

export interface OutcomeSummary {
  total: number;
  counts: {
    better_than_expected: number;
    as_expected: number;
    worse_than_expected: number;
    not_evaluated: number;
  };
  positive_rate: number | null;
  adoption_status: string | null;
  date_from: string | null;
  date_to: string | null;
}

export interface StockAnalyticsItem {
  code: string;
  total: number;
  adoption_followed_count: number;
  adoption_rate: number | null;
  outcome_positive_count: number;
  outcome_positive_rate: number | null;
}

// ---- 收益归因 (P2-4B) ----

export interface AttributionPosition {
  code: string;
  name: string;
  closed_quantity: number;
  realized_pnl: number;
  remaining_quantity: number;
  avg_cost: number | null;
  cost_basis: number;
  total_fees: number;
  unrealized_pnl: number | null;
  data_limitations: string[];
}

export interface AttributionTotals {
  total_realized_pnl: number;
  total_unrealized_pnl: number | null;
  total_fees: number;
  total_cost_basis: number;
  position_count: number;
}

export interface AttributionResult {
  as_of_date: string;
  date_from: string | null;
  date_to: string | null;
  positions: AttributionPosition[];
  totals: AttributionTotals;
  data_limitations: string[];
}

export interface AttributionSnapshotSummary {
  snapshot_id: string;
  as_of_date: string;
  created_at: string;
  total_realized_pnl: number;
  total_unrealized_pnl: number | null;
  total_fees: number;
  total_cost_basis: number;
  position_count: number;
}

export interface AttributionSnapshotListResult {
  items: AttributionSnapshotSummary[];
  limit: number;
  offset: number;
}

export interface AttributionSnapshotDetailResult {
  snapshot: AttributionSnapshotSummary & { payload: AttributionResult };
  positions: AttributionPosition[];
}

// ---------------------------------------------------------------------------
// BK-11 短线市场历史（只读查询）
// ---------------------------------------------------------------------------

export type Bk11HistoryStatus =
  | "empty"
  | "normal"
  | "partial"
  | "unavailable"
  | "error";

export interface Bk11HistoryWindow {
  requested: number;
  snapshot_count: number;
}

export interface Bk11HistorySnapshotMeta {
  trade_date: string;
  session: string;
  schema_version: string;
  stored_at: string;
}

/** 真实后端 daily-facts 合同：facts 段为 {schema_version, status, facts:{...}} */
export interface Bk11FactSection {
  schema_version: string;
  status: string;
  facts: Record<string, unknown>;
}

export interface Bk11LadderRow {
  boards: number;
  count: number;
}

/** 真实后端 daily-facts 合同：ladder 段为 {schema_version, status, metrics:{...}} */
export interface Bk11LadderSection {
  schema_version: string;
  status: string;
  metrics: {
    max_boards: number | null;
    lianban_count: number | null;
    ladder: Bk11LadderRow[] | null;
  };
}

/** 真实后端 daily-facts 合同：gap 段为 {schema_version, status, metrics:{...}} */
export interface Bk11GapSection {
  schema_version: string;
  status: string;
  metrics: {
    gap_level_count: number | null;
    gap_segment_count: number | null;
    largest_gap_width: number | null;
    first_gap_board: number | null;
    is_continuous: boolean | null;
  };
}

export interface Bk11DailyFactsSections {
  facts: Bk11FactSection | null;
  ladder: Bk11LadderSection | null;
  gap: Bk11GapSection | null;
}

export interface Bk11DailyFactsEnvelope {
  schema_version: string;
  trade_date: string;
  session: string;
  is_final: boolean;
  source_ids: string[];
  fetched_at: string | null;
  snapshot_at: string | null;
  status: "normal" | "partial" | "unavailable" | "invalid";
  reason_codes: string[];
  warnings: string[];
  limitations: string[];
  source_schema_version: string | null;
  source_status: string | null;
  source_reason_codes: string[];
  sections: Bk11DailyFactsSections;
}

export interface Bk11HistoryEnvelope {
  schema_version: string;
  status: Bk11HistoryStatus;
  window: Bk11HistoryWindow;
  trade_date: string | null;
  data_time: string | null;
  snapshots: Bk11HistorySnapshotMeta[];
  latest: Bk11DailyFactsEnvelope | null;
  delta: Record<string, unknown> | null;
  summary: Record<string, unknown> | null;
  digest: Record<string, unknown> | null;
  reason_codes: string[];
  warnings: string[];
  limitations: string[];
}

// ---------------------------------------------------------------------------
// 账户初始化（Bootstrap，P0-AB2）：契约与 backend position_reality_service 对齐。
// LEGACY_POSITION_OPENING != BUY；PRE-VIBE 历史保持 UNKNOWN。
// ---------------------------------------------------------------------------

export interface PositionBootstrapPosition {
  code: string;
  name?: string;
  shares: number;
  cost_basis?: number;
}

export interface PositionBootstrapInput {
  ledger_start_at: string;
  opening_cash?: number;
  note?: string;
  positions: PositionBootstrapPosition[];
}

export interface PositionBootstrapOpeningEvent {
  event_id: string;
  event_type: string;
  opening_cash: number | null;
  ledger_start_at: string;
  historical_trades: string;
  provenance: string;
  created_at: string;
  [key: string]: unknown;
}

export interface PositionBootstrapPreviewPositionEvent {
  event_id: string;
  event_type: string;
  code: string;
  name: string | null;
  shares: number;
  cost_basis: number | null;
  origin: string;
  acquired_before_vibe: number;
  historical_trades: string;
  provenance: string;
  created_at: string;
  [key: string]: unknown;
}

export interface PositionBootstrapPreview {
  preview: boolean;
  validation: string;
  opening: PositionBootstrapOpeningEvent;
  positions: PositionBootstrapPreviewPositionEvent[];
}

export interface PositionBootstrapCommitResult {
  status: string;
  opening: PositionBootstrapOpeningEvent;
  positions: PositionBootstrapPreviewPositionEvent[];
}

/** GET /api/position/derived（只读推导结果；当前 UI 不强依赖，类型最小化） */
export interface DerivedPositionsResult {
  derivation_status: string;
  bootstrap_status: string;
  canonical: boolean;
  ledger_start: {
    ledger_start_at: string | null;
    opening_cash: number | null;
    pre_vibe_history: string;
    bootstrapped_at: string | null;
  } | null;
  positions: Array<{
    code: string;
    name: string;
    shares: number;
    cost_basis: number | null;
    avg_cost: number | null;
    status: string;
    origin: string;
    cost_known: boolean;
  }>;
  data_limitations: string[];
}


// ---------------------------------------------------------------------------
// Campaign（P0-CS1）：strategy / status 为 frozen 枚举，与 backend 逐字一致。
// 前端绝不重新定义 transition graph；下一合法动作只来自 next-actions API。
// ---------------------------------------------------------------------------

export type CampaignStrategy = ThesisStrategy;

export type CampaignStatus =
  | "DRAFT"
  | "RESEARCHING"
  | "PRE-ENTRY"
  | "ACTIVE"
  | "REDUCING"
  | "CLOSED"
  | "REJECTED"
  | "EXPIRED";

export interface CampaignRecord {
  campaign_id: string;
  security_code: string;
  strategy: CampaignStrategy;
  status: CampaignStatus;
  created_at: string;
}

export interface CampaignTransitionRecord {
  transition_id: string;
  campaign_id: string;
  from_status: CampaignStatus;
  to_status: CampaignStatus;
  transitioned_at: string;
}

export interface CampaignTransitionResult {
  campaign: CampaignRecord;
  transition: CampaignTransitionRecord;
}

export interface CampaignTradeActivationResult extends CampaignTransitionResult {
  trade_id: string;
  decision_id: string;
  attribution_id: string | null;
  position_authority: "CANONICAL" | "LEGACY";
}

export interface CampaignNextActions {
  campaign_id: string;
  security_code: string;
  strategy: CampaignStrategy;
  status: CampaignStatus;
  next_actions: CampaignStatus[];
}

// P0-CT1：Campaign ↔ Formal Thesis 不可变绑定（POST/GET /campaigns/{id}/thesis-binding）
export interface CampaignThesisBinding {
  campaign_id: string;
  thesis_id: string;
  thesis_revision_at_bind: number;
  campaign_strategy_at_bind: CampaignStrategy;
  bound_at: string;
}

/** GET /api/campaigns/{campaign_id}/current-thesis 只读投影中的 binding audit */
export interface CampaignThesisBindingAudit {
  thesis_revision_at_bind: number;
  campaign_strategy_at_bind: CampaignStrategy;
  bound_at: string;
}

/** 投影未就绪（已绑定但 thesis 未冻结）：只给 audit facts，不伪造 Formal Original */
export interface CurrentThesisNotReady {
  campaign_id: string;
  thesis_id: string;
  binding: CampaignThesisBindingAudit;
  formal_state: string | null;
  frozen_revision: number | null;
  ready: false;
  formal_status: "NOT_READY";
  reason: string;
}

/** 投影就绪（frozen）：Formal Original（frozen_revision 快照）+ deltas + effective_state */
export interface CurrentThesisReady {
  campaign_id: string;
  thesis_id: string;
  binding: CampaignThesisBindingAudit;
  frozen_revision: number;
  original_snapshot: FormalThesisSnapshot;
  deltas: unknown[];
  effective_state: string;
  ready: true;
  formal_status: "READY";
}

export type CampaignCurrentThesis = CurrentThesisNotReady | CurrentThesisReady;

export type ResearchContinuityChangeType =
  | "ADDED" | "CHANGED" | "SOURCE_CONFLICT";

export interface ResearchContinuityEvidenceSnapshot {
  record_key: string;
  claim_identity: string;
  source: string | null;
  field_states: Record<string, "UNKNOWN" | "EMPTY" | "VALUE">;
  values: Record<string, string | null>;
}

export interface ResearchContinuityChange {
  change_type: ResearchContinuityChangeType;
  record_key: string;
  changed_fields?: string[];
  before?: ResearchContinuityEvidenceSnapshot | null;
  after?: ResearchContinuityEvidenceSnapshot | null;
  sources?: string[];
  records?: ResearchContinuityEvidenceSnapshot[];
}

export interface ResearchContinuity {
  schema_version: "research_continuity.v0.1";
  status: "NORMAL" | "PARTIAL";
  campaign_id: string;
  security_code: string;
  strategy: CampaignStrategy;
  fetched_at: string;
  baseline: {
    status: "READY" | "NO_BASELINE" | "UNAVAILABLE";
    authority_type: "FROZEN_DECISION" | "CANDIDATE_RESEARCH_FORMAL_ORIGINAL" | null;
    decision_id?: string | null;
    as_of?: string | null;
    snapshot_hash?: string | null;
  };
  changes: {
    status: "NORMAL" | "NO_BASELINE" | "UNAVAILABLE" | "NOT_EVALUATED";
    items: ResearchContinuityChange[];
    observation_count: number;
  };
  decision_calendar: {
    state: "EXPECTED" | "CONFIRMED" | "DELAYED_SIGNAL" | "NO_RECORD" | "UNAVAILABLE" | "ERROR";
    next: { report_date: string; appointment_date: string | null; actual_date: string | null; semantics: string } | null;
    latest_actual: { report_date: string; appointment_date: string | null; actual_date: string | null; semantics: "CONFIRMED" } | null;
    fetched_at: string;
    source: string;
  };
  authority_refs: string[];
  writes: { thesis: 0; decision: 0; campaign: 0; trade: 0 };
}

export interface ResearchContinuityBatch {
  items: ResearchContinuity[];
}

// ---------------------------------------------------------------------------
// Decision Inbox（P0-CS1）：只读快照，前端只展示 + 调用正式写 API。
// ---------------------------------------------------------------------------

export interface DecisionInboxHoldingSetupItem {
  item_kind: "UNASSIGNED_HOLDING";
  security_code: string;
  security_name: string;
  holding: Record<string, unknown>;
  reason_codes: string[];
  next_workflow_action: string;
  as_of: string;
}

/** P0-HR1：shared Hard Risk contract 的 hard_risk_state（DI1 已输出 4 态）。 */
export type HardRiskState = "CLEAR" | "CONFIRMED" | "UNKNOWN" | "NOT_EVALUATED";
/** P0-HR1：shared Hard Risk contract 的 hard_risk_evaluation（O lane 接入后输出）。 */
export type HardRiskEvaluation = "EVALUATED" | "UNKNOWN" | "NOT_EVALUATED" | "ERROR";

export type FormalDecisionEvaluation = "EVALUATED" | "UNKNOWN" | "NOT_EVALUATED" | "ERROR";

export interface DecisionInboxFrozenDecision {
  decision_id: string;
  committed_at: string;
  review_by: string;
  /** Historical user-frozen action; never a newly generated current recommendation. */
  previous_next_best_action: string;
}

export type SellEngineState =
  | "HOLD"
  | "WATCH_TO_REDUCE"
  | "REDUCE"
  | "EXIT"
  | "THESIS_INVALIDATED";

export interface DecisionInboxSellEngine {
  schema_version: "sell_engine.projection.vnext.v0.1";
  authority_ref: "sell_engine:projection:vnext.v0.1";
  security_code: string;
  strategy: CampaignStrategy;
  campaign_id: string;
  as_of: string;
  sell_state: SellEngineState | null;
  sell_evaluation: FormalDecisionEvaluation;
  primary_reason: string | null;
  reason_codes: string[];
  supporting_reasons: string[];
  opposing_reasons: string[];
  uncertainties: string[];
  hold_positive_proof: boolean;
  review_pressure: boolean;
  thesis_id: string | null;
  thesis_revision: number | null;
  authority_refs: string[];
  dimensions: Record<string, unknown>;
}

export interface DecisionInboxCampaignItem {
  schema_version: string;
  visible_state: string;
  reason_codes: string[];
  security_code: string;
  strategy: CampaignStrategy;
  campaign_id: string;
  campaign_status: CampaignStatus;
  as_of: string;
  /**
   * P0-HR1：runtime 输出 hard_risk_state（DI1 已输出）。
   * 缺失 / null → UI fail closed（按未知处理，绝不显示安全）。
   */
  hard_risk_state?: HardRiskState | null;
  /**
   * P0-HR1：runtime 输出 hard_risk_evaluation（contract 字段）。
   * 缺失时 fail closed；ERROR 必须明确呈现失败。
   */
  hard_risk_evaluation?: HardRiskEvaluation | null;
  /**
   * P0-HR1：Hard Risk 专属 reason codes（O lane 输出）。
   * 绝不使用 item.reason_codes（Campaign-level generic）充当 Hard Risk reasons。
   */
  hard_risk_reason_codes?: string[] | null;
  /**
   * P0-HR1：Hard Risk 专属 positive-proof authority refs（O lane 输出）。
   * 绝不使用 item.authority_refs / explainability.authority_refs（generic
   * projection provenance，可能含 Critical Data / Thesis / Decision）充当
   * Hard Risk 证明。
   */
  hard_risk_authority_refs?: string[] | null;
  /** P0-DC1 additive RA1 / Formal Decision runtime fields. */
  formal_thesis_evaluation?: FormalDecisionEvaluation;
  formal_decision_evaluation?: FormalDecisionEvaluation;
  material_change_evaluation?: FormalDecisionEvaluation;
  material_change_reason_codes?: string[];
  decision_assurance?: Record<string, unknown>;
  /** Last user-frozen decision. It is historical unless formal_decision_evaluation proves applicability. */
  last_frozen_decision?: DecisionInboxFrozenDecision | null;
  /** Read-only current Sell Engine projection. It never mutates the Frozen Decision or creates a Trade. */
  sell_engine?: DecisionInboxSellEngine | null;
}

export interface DecisionInboxSnapshot {
  schema_version: string;
  as_of: string;
  evaluation_status: "EVALUATED" | "NOT_EVALUATED";
  canonical: boolean;
  reason_codes: string[];
  holding_setup_items: DecisionInboxHoldingSetupItem[];
  campaign_items: DecisionInboxCampaignItem[];
  total_holdings: number;
  total_campaign_items: number;
}

// ---------------------------------------------------------------------------
// P0-DC1：Current Thesis → uncommitted Decision Proposal → explicit Freeze
// ---------------------------------------------------------------------------

export type PortfolioCapitalAvailabilityState = "AVAILABLE" | "CONSTRAINED" | "UNKNOWN";
export type PortfolioFitState = "SUPPORTIVE" | "CONSTRAINED" | "UNKNOWN";
export type ReplacementReviewState = "NOT_REQUIRED" | "WORTH_REVIEW" | "NOT_PROVEN" | "UNKNOWN";

export interface PortfolioCapitalReplacementCandidate {
  security_code: string;
  campaign_id: string;
  strategy: CampaignStrategy;
  reason_codes: string[];
}

export interface PortfolioCapitalContext {
  schema_version: "portfolio_capital_context.v0.1";
  capital_availability: {
    state: PortfolioCapitalAvailabilityState;
    confirmed_cash: number | null;
    reason_codes: string[];
  };
  portfolio_fit: {
    state: PortfolioFitState;
    existing_position_count: number | null;
    reason_codes: string[];
  };
  replacement_review: {
    state: ReplacementReviewState;
    reason_codes: string[];
    candidates: PortfolioCapitalReplacementCandidate[];
  };
  position_sizing_status: string;
  authority_refs: string[];
}

export interface DecisionProposalPortfolioView extends Record<string, unknown> {
  portfolio_capital_context?: PortfolioCapitalContext | null;
}

export interface DecisionProposalProjection {
  schema_version: string;
  proposal_status: "UNCOMMITTED";
  constraint_evaluation: "EVALUATED" | "UNKNOWN" | "NOT_EVALUATED" | "ERROR";
  security_code: string;
  strategy: CampaignStrategy;
  campaign_id: string;
  thesis_id: string;
  thesis_revision: number;
  as_of: string;
  asset_view: Record<string, unknown>;
  trade_view: Record<string, unknown>;
  portfolio_view: DecisionProposalPortfolioView;
  view_provenance: Record<string, { view_origin?: string; provenance_refs?: string[] } | unknown>;
  next_best_action: string;
  action_envelope: Record<string, unknown>;
  maintain_conditions: string[];
  upgrade_conditions: string[];
  downgrade_conditions: string[];
  invalidation_conditions: string[];
  authority_facts: Record<string, unknown>;
  authority_refs: string[];
}

export interface DecisionProposalCommitFields {
  review_by: string;
  key_assumptions: unknown[];
  event_invalidation_conditions: unknown[];
  strategy_horizon: string;
}

export interface DecisionProposalDraftWitness {
  schema_version: string;
  draft_id: string;
  campaign_id: string;
  thesis_id: string;
  thesis_revision: number;
  context_fingerprint: string;
  generated_fields: DecisionProposalDraftInput;
}

export interface DecisionProposalDraftInput extends DecisionProposalCommitFields {
  asset_view: Record<string, unknown>;
  trade_view: Record<string, unknown>;
  portfolio_view: Record<string, unknown>;
  draft_witness?: DecisionProposalDraftWitness | null;
}

export interface CampaignAIDraftGenerateResult {
  schema_version: string;
  draft_status: "AI_DRAFT";
  proposal_status: "UNCOMMITTED";
  draft_id: string;
  campaign_id: string;
  thesis_id: string;
  thesis_revision: number;
  context_fingerprint: string;
  generated_fields: DecisionProposalDraftInput;
  draft_witness: DecisionProposalDraftWitness;
}

export interface DecisionProposalPreview {
  schema_version: string;
  proposal: DecisionProposalProjection;
  proposal_fingerprint: string;
  commit_fields: DecisionProposalCommitFields;
  authority_evaluations: Record<string, unknown>;
  decision_assurance: Record<string, unknown>;
  commit_requirements: {
    user_confirmed: true;
    expected_proposal_fingerprint: string;
    challenge_required?: boolean;
  };
  draft_witness?: DecisionProposalDraftWitness;
}

export interface DecisionProposalCommitResult {
  schema_version: string;
  proposal_fingerprint: string;
  idempotent: boolean;
  committed: Record<string, unknown>;
  formal_decision: Record<string, unknown>;
  critical_data: Record<string, unknown>;
  decision_assurance: Record<string, unknown>;
  re_read_required: true;
}

export interface CommittedDecisionRuntimeRead {
  schema_version: string;
  as_of: string;
  committed: Record<string, unknown>;
  formal_thesis: Record<string, unknown>;
  critical_data: Record<string, unknown>;
  formal_decision: Record<string, unknown>;
  hard_risk: Record<string, unknown>;
  material_change: Record<string, unknown>;
  sell_engine: Record<string, unknown>;
  decision_assurance: Record<string, unknown>;
}

// ---------------------------------------------------------------------------
// Native Intel（NATIVE-INTEL1）：Vibe 自有本地资讯数据面。
// ---------------------------------------------------------------------------

export type NativeIntelStatusValue = "normal" | "partial" | "stale" | "unavailable";

export interface NativeIntelItem {
  item_id: number;
  title: string;
  summary?: string | null;
  url: string;
  canonical_url?: string;
  source_id: string;
  source_name?: string | null;
  source_type?: string | null;
  hint: string;
  published_at?: string | null;
  first_seen_at: string;
  last_seen_at: string;
  observation_count: number;
  rank?: number | null;
  rank_history?: Array<{ observed_at: string; rank: number }>;
}

export interface NativeIntelStatus {
  status: NativeIntelStatusValue;
  error?: string | null;
  authority_ref?: string;
  usage_boundary?: string;
  generated_at?: string;
  store?: { readable: boolean; schema_version?: string | null; item_count?: number };
  scheduler?: { started: boolean; enabled: boolean; interval_seconds: number };
  last_run?: {
    run_id: string;
    status: string;
    started_at: string;
    finished_at?: string | null;
    source_ok: number;
    source_failed: number;
    item_seen: number;
    item_new: number;
  } | null;
  sources?: {
    total: number;
    healthy: number;
    failing: number;
    never_run: number;
    failing_names: string[];
  };
  source_health?: Array<{
    source_id: string;
    name: string;
    hint: string;
    last_status: string;
    last_item_count: number;
    last_error_kind?: string | null;
  }>;
}

export interface NativeIntelItemsResponse {
  status: NativeIntelStatusValue;
  error?: string | null;
  items: NativeIntelItem[];
  total: number;
  limit: number;
  offset: number;
}

export interface NativeIntelTrendEntity {
  term: string;
  term_kind: string;
  security_code?: string | null;
  item_count: number;
  source_count: number;
  previous_item_count: number;
  delta: number;
}

export interface NativeIntelTrending {
  status: NativeIntelStatusValue;
  error?: string | null;
  generated_at?: string;
  window_hours: number;
  item_count: number;
  items: NativeIntelItem[];
  entities: NativeIntelTrendEntity[];
  rank_history?: { available: boolean; reason: string; semantics?: string };
}

export interface NativeIntelEntityTerm {
  term: string;
  term_kind: "security_code" | "company_name" | "industry" | "concept";
  source_ref: string;
}

export interface NativeIntelSecurityContext {
  status: NativeIntelStatusValue;
  error?: string | null;
  retrieved_at?: string;
  authority_ref?: string;
  usage_boundary?: string;
  window_hours: number;
  security: { code: string; company_name: string | null };
  mapping: {
    status: string;
    term_count: number;
    terms: NativeIntelEntityTerm[];
    errors: Array<{ source: string; error: string }>;
    refreshed?: boolean;
  };
  observation: {
    items: NativeIntelItem[];
    item_count: number;
    mention_count?: number;
    source_count?: number;
    first_seen_at?: string | null;
    last_seen_at?: string | null;
  };
  rank_history?: { available: boolean; reason: string; semantics?: string };
}

export interface NativeIntelWatchlistSecurity {
  code: string;
  company_name: string | null;
  mention_count: number;
  source_count: number;
  first_seen_at?: string | null;
  last_seen_at?: string | null;
  items: NativeIntelItem[];
}

export interface NativeIntelWatchlistContext {
  status: NativeIntelStatusValue;
  error?: string | null;
  retrieved_at?: string;
  authority_ref?: string;
  usage_boundary?: string;
  watchlist_status: string;
  codes: string[];
  securities: NativeIntelWatchlistSecurity[];
  degraded?: Array<{ code: string; error: string }>;
}

export interface NativeIntelRefreshResult {
  status: NativeIntelStatusValue;
  accepted: boolean;
  run_id?: string;
  source_total?: number;
  source_ok?: number;
  source_failed?: number;
  item_seen?: number;
  item_new?: number;
  failed_sources?: string[];
  error?: string;
}

// ---------------------------------------------------------------------------
// TREND-PARITY Wave 1: Hotlist, Rank History & Source Registry
// ---------------------------------------------------------------------------

export type NativeIntelRankState = "ON_LIST" | "OFF_LIST" | "UNKNOWN" | "DISABLED" | "STALE" | "NO_RANK_SEMANTICS";

export interface NativeIntelHotlistItem {
  item_id: number;
  title: string;
  url: string;
  canonical_url?: string;
  source_id: string;
  source_name?: string | null;
  source_type?: string | null;
  hint: string;
  published_at?: string | null;
  first_seen_at: string;
  last_seen_at: string;
  observation_count: number;
  rank?: number | null;
  previous_rank?: number | null;
  rank_delta?: number | null;
  current_state: NativeIntelRankState;
  last_run_id?: string | null;
  entities?: Array<{
    term: string;
    term_kind: string;
    security_code?: string | null;
  }>;
  filter_match?: FilterMatch | null;
}

export interface NativeIntelHotlistSource {
  source_id: string;
  name: string;
  hint: string;
  enabled: boolean;
  origin: "system" | "user";
  last_run_status?: string | null;
  last_run_error_kind?: string | null;
}

export interface NativeIntelHotlistBoardResponse {
  status: NativeIntelStatusValue;
  error?: string | null;
  authority_ref?: string;
  usage_boundary?: string;
  generated_at?: string;
  sources: NativeIntelHotlistSource[];
  items: NativeIntelHotlistItem[];
  filter_meta?: FilterMeta | null;
}

// ---------------------------------------------------------------------------
// TREND-PARITY Wave 2: Personal Interest & Keyword Filtering
// ---------------------------------------------------------------------------

export type FilterMethod = "keyword" | "ai";

export interface KeywordGroup {
  name: string;
  includes: string[];
  required: string[];
  excludes: string[];
  max_count?: number | null;
}

export interface KeywordRules {
  global_excludes: string[];
  filter_terms?: string[];
  groups: KeywordGroup[];
}

export interface InterestTag {
  id: number;
  tag: string;
  description: string;
}

export interface FilterProfile {
  profile_id: string;
  name: string;
  method: FilterMethod;
  interests_text: string;
  min_score: number;
  keyword_rules: KeywordRules;
  tags: InterestTag[];
  profile_fingerprint: string;
  reclassify_threshold: number;
  created_at: string;
  updated_at: string;
}

export type FilterMatch =
  | { method: "keyword"; matched_groups: string[] }
  | { method: "ai"; primary_tag: string; relevance_score: number };

export interface FilterMeta {
  profile_id?: string;
  profile_name?: string;
  method?: FilterMethod;
  mode?: "all" | "my_interests";
  profile_fingerprint?: string;
  total_evaluated?: number;
  matched_count?: number;
  classified_count?: number;
  not_relevant_count?: number;
  unclassified_count?: number;
  error_count?: number;
  status?: "OK" | "UNAVAILABLE" | "normal";
  error?: string;
}

export interface NativeIntelRankObservation {
  observed_at: string;
  rank: number;
}

export interface NativeIntelItemRankHistoryResponse {
  item_id: number;
  source_id: string;
  source_name?: string | null;
  source_type?: string | null;
  has_real_rank: boolean;
  first_seen_at: string;
  last_seen_at: string;
  observation_count: number;
  observations: NativeIntelRankObservation[];
  current_state: NativeIntelRankState;
  current_rank?: number | null;
  previous_rank?: number | null;
  rank_delta?: number | null;
  last_run_id?: string | null;
  title?: string | null;
  url?: string | null;
  hint?: string | null;
  state_semantics?: Record<string, string>;
}

export interface NativeIntelSourceRecord {
  source_id: string;
  name: string;
  hint: string;
  url: string;
  source_type: string;
  has_real_rank: boolean;
  enabled: boolean;
  origin: "system" | "user";
  updated_at?: string;
  last_run_status?: string | null;
  max_age_days?: number | null;
}

export interface NativeIntelSourcesResponse {
  status: NativeIntelStatusValue;
  sources: NativeIntelSourceRecord[];
  error?: string | null;
}

export interface CreateUserSourceInput {
  name: string;
  url: string;
  hint?: string;
  enabled?: boolean;
  max_age_days?: number | null;
}

export interface UpdateSourceInput {
  enabled?: boolean;
  name?: string;
  max_age_days?: number | null;
}

export interface NativeIntelConfig {
  rss_freshness_enabled: boolean;
  rss_global_max_age_days: number;
  crawler_proxy_enabled: boolean;
  crawler_proxy_url: string;
  rss_proxy_enabled: boolean;
  rss_proxy_url: string;
  standalone_enabled: boolean;
  standalone_source_ids: string[];
  standalone_max_items: number;
  region_order: string[];
  regions_enabled: Record<string, boolean>;
}

export interface NativeIntelStandaloneResponse {
  status: string;
  items: NativeIntelHotlistItem[];
  total: number;
  configured_sources: string[];
  freshness_excluded_count?: number;
}
