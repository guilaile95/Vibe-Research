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
  yzt_count: number | null;
}


// 成交额排行（每日复盘 → 资金活跃度）
export interface TurnoverTop { symbol: string; name: string; turnover: number; pct: number }


// 市场宽度（参与度）
export interface MarketBreadthData {
  date: string;
  stock_count: number | null;
  valid_count: number | null;
  up_count: number | null;
  down_count: number | null;
  flat_count: number | null;
  up_ratio: number | null;
  up_3pct_count: number | null;
  down_3pct_count: number | null;
  total_amount: number | null;
  amount_valid_count: number | null;
}


// 板块轮动（行业 / 概念 / 地域）
export interface BoardRankItem {
  key: string; name: string; pct: number;
  amount: number | null; up: number; down: number; flat: number;
}

export interface BoardRankingData {
  date: string;
  industry: { top: BoardRankItem[]; bottom: BoardRankItem[] };
  concept: { top: BoardRankItem[]; bottom: BoardRankItem[] };
  region: { top: BoardRankItem[]; bottom: BoardRankItem[] };
}


// 市场快照（资金流向 / 成交额/换手率 Top）
export interface MarketSnapshotItem { code: string; name: string; value: number; pct: number | null }


/** 每日复盘数据聚合包（主指数 + 市场宽度 + 短线情绪 + 板块轮动 + 成交额 Top） */
export interface DailyReviewData {
  schema_version: string;
  trade_date: string;
  generated_at: string;
  status: DataStatus;
  warnings: string[];
  indices: { status: DataStatus; warnings: string[]; data: IndexQuote[] | null };
  market_breadth: TimedComponentEnvelope<MarketBreadthData>;
  short_term_emotion: TimedComponentEnvelope<ShortTermEmotion>;
  sector_rotation: TimedComponentEnvelope<BoardRankingData>;
  capital_activity: {
    status: DataStatus; warnings: string[];
    trade_date?: string | null; data_time?: string | null; fetched_at?: string | null;
    total_amount: number | null; amount_valid_count: number | null;
    amount_top: MarketSnapshotItem[];
    high_turnover: MarketSnapshotItem[];
  };
}


/** 可选的缓存元数据：何时过期（300s 内存缓存） */
export interface DailyReviewCacheMeta {
  generated_at: string;
  expires_in_seconds: number | null;
  is_stale: boolean;
}


/** 历史快照列表单项 */
export interface DailyReviewHistoryItem {
  id: number;
  trade_date: string;
  schema_version: string;
  generated_at: string;
  status: DataStatus;
  payload_hash: string;
  created_at: string;
}


/** GET /api/daily-review/history/{id} 单条快照详情 */
export interface DailyReviewHistorySnapshot {
  id: number;
  trade_date: string;
  schema_version: string;
  generated_at: string;
  status: DataStatus;
  payload_hash: string;
  created_at: string;
  payload: DailyReviewData;
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


export interface RadarData {
  updated: string;
  hotConcepts: { name: string; pct: number; count: number }[];
  northFlow: { date: string; net: number }[];
  dragonTiger: { code: string; name: string; net_buy: number; pct: number }[];
  newHighs: { code: string; name: string; pct: number; price: number }[];
}


export interface HoldingRow {
  code: string; name: string; shares: number; cost: number; price: number; current: number; profit: number; profit_pct: number;
}


export interface ClosedRow {
  code: string; name: string; date: string; shares: number; cost: number; sell_price: number; profit: number; profit_pct: number;
}


export interface PortfolioData {
  updated: string;
  holdings: HoldingRow[];
  closed: ClosedRow[];
  total_cost: number;
  total_current: number;
  total_profit: number;
  total_profit_pct: number;
}


/** 账户资金配置（总资产 / 可用现金） */
export interface AccountProfile {
  total_assets: number;
  available_cash: number;
  updated_at: string;
}


/** GET /api/account-profile 顶层响应（未配置时 configured=false） */
export interface AccountProfileResponse {
  configured: boolean;
  data: AccountProfile | null;
}


/** PUT /api/account-profile 请求体（只写 assets 和 cash） */
export interface AccountProfileRequest {
  total_assets: number;
  available_cash: number;
}


/** 结构化持仓操作建议响应 */
export interface PortfolioAdviceResult {
  llm: string;
  user_request: string | null;
  advice: string;
  suggestions: {
    action: "buy" | "sell" | "hold" | "reduce";
    symbol: string | null;
    ticker: string | null;
    target_weight: number | null;
    reason: string;
  }[];
  reasoning: string;
  risks: string[];
  model_input_tokens: number | null;
  model_output_tokens: number | null;
  total_cost_cny: number | null;
  cached_at: string | null;
  generated_at: string;
}


export interface PortfolioAdviceRequest {
  user_request: string | null;
  llm: string;
}


/** AI 生成内容类型枚举 */
export type AiResultType = "daily_review" | "portfolio_advice";


/** AI 元数据（可选，成本 / token 计数由后端记录） */
export interface AiGeneratedResultMetadata {
  model_input_tokens?: number | null;
  model_output_tokens?: number | null;
  total_cost_cny?: number | null;
}


/** AI 缓存结果（泛型 payload） */
export interface AiGeneratedResult<TPayload> {
  id: string;
  result_type: AiResultType;
  trade_date: string | null;
  llm: string;
  payload: TPayload;
  metadata: AiGeneratedResultMetadata;
  created_at: string;
}


/** 每日复盘 AI 请求（上下文由服务器生成，只传 user_request + llm） */
export interface DailyReviewAnalyzeRequest {
  user_request: string | null;
  llm: string;
}


/** NDJSON 流事件处理器 */
export interface NdjsonStreamHandlers {
  onDelta?: (text: string) => void;
  onTool?: (tool: string, args: Record<string, unknown>) => void;
}


/** NDJSON 流结果（最终聚合状态） */
export interface NdjsonStreamResult {
  content: string;
  trace: any[];
  rounds: number;
  result?: AiGeneratedResultMetadata;
}


/** NDJSON 协议状态（可序列化、可测试） */
export interface NdjsonProtocolState {
  content: string;
  trace: any[];
  rounds: number;
  sawDone: boolean;
  sawError: boolean;
  errorMessage: string | null;
  result?: AiGeneratedResultMetadata;
}


export interface MarginRow {
  date: string; rzye: number; rqye: number; rzrqye: number; rzrqye_pct: number;
}


export interface BlockTradeRow {
  date: string; price: number; volume: number; premium: number; buyer: string; seller: string;
}


export interface HolderRow {
  date: string; holder: string; shares: number; pct: number; nature: string;
}


export interface DividendRow {
  date: string; plan: string; ex_date: string; record_date: string; pay_date: string;
}


export interface FundFlowRow {
  date: string; main_net: number; small_net: number; mid_net: number; large_net: number; huge_net: number;
}


export interface DragonTiger {
  date: string; reason: string;
  buy_seats: { name: string; amount: number }[];
  sell_seats: { name: string; amount: number }[];
}


export interface Lockup {
  date: string | null;
  holders: { holder: string; shares: number; lockup_type: string; lift_date: string }[];
}


export interface Blocks {
  concept: string[];
  industry: string[];
}


export interface HotConcept {
  concept: string; date: string; avg_pct: number; stocks: string[];
}


export interface QaRow {
  date: string; question: string; answer: string; source: string;
}


export interface IndustryData {
  top: { name: string; pct: number }[];
  bottom: { name: string; pct: number }[];
  date: string;
}


export interface KlineBar {
  date: string; open: number; high: number; low: number; close: number; volume: number;
}


export interface DisclosureItem {
  date: string; title: string; category: string; url: string;
}


export interface GlobalIndex {
  symbol: string; name: string; price: number; change_pct: number;
}


export interface GlobalStock {
  symbol: string; name: string; price: number; change_pct: number;
  open: number; high: number; low: number; volume: number;
  market_cap: number; pe: number | null; div_yield: number | null;
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

/** POST /api/thesis - 创建逻辑请求 */
export interface ThesisCreateInput {
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
}

/** PUT /api/thesis/{id} - 更新逻辑请求 */
export interface ThesisUpdateInput {
  market: "CN" | "HK" | "US" | "KR" | null;
  title: string;
  summary: string;
  status: "active" | "weakened" | "invalidated" | "archived";
  core_claims: string[];
  catalysts: string[];
  risks: string[];
  invalidation_conditions: string[];
  expected_revision: number;
  change_summary?: string;
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
