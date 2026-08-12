import type {
  BoardRankingData,
  BoardRankItem,
  ComponentEnvelope,
  DataStatus,
  GlobalIndex,
  IndexQuote,
  MarketBreadthData,
  MarketSnapshotItem,
  ShortTermEmotionData,
  StreamLlmConfig,
  TimedComponentEnvelope,
  TurnoverTop,
} from "../types.ts";

/** GET /api/daily-review 可选缓存元数据（stale-while-revalidate） */
export interface DailyReviewCacheMeta {
  source: "live" | "memory" | "persisted" | string;
  stale: boolean;
  refreshing: boolean;
  saved_at: string | null;
  age_seconds: number | null;
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
  data_health: { components: Record<"indices" | "global_indices" | "breadth" | "emotion" | "turnover" | "industry_boards" | "concept_boards" | "region_boards", DataStatus> };
  market_environment: {
    indices: ComponentEnvelope<IndexQuote[]>;
    global_indices: ComponentEnvelope<GlobalIndex[]>;
    breadth: TimedComponentEnvelope<MarketBreadthData>;
  };
  sector_rotation: {
    industry: TimedComponentEnvelope<BoardRankingData>;
    concept: TimedComponentEnvelope<BoardRankingData>;
    region: TimedComponentEnvelope<BoardRankingData>;
    highlights: Record<"strongest_industry" | "weakest_industry" | "strongest_concept" | "weakest_concept" | "strongest_region" | "weakest_region", BoardRankItem | null>;
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

export interface DailyReviewHistorySnapshot extends DailyReviewHistoryItem { review: DailyReviewData; }

export interface SaveDailyReviewHistoryResult {
  snapshot: { id: number; inserted: boolean; trade_date: string; schema_version: string; generated_at: string; status: DataStatus; payload_hash: string; created_at: string };
  review_status: "normal" | "partial";
  review_warnings: string[];
}

export interface DailyReviewHistoryList {
  items: DailyReviewHistoryItem[];
  trade_date: string | null;
  limit: number;
  offset: number;
  count: number;
}

export interface DailyReviewComparisonMeta {
  id: number | null;
  trade_date: string | null;
  schema_version: string | null;
  generated_at: string | null;
  status: DataStatus | null;
}

export interface NumericComparison { base: number | null; target: number | null; delta: number | null; change_pct: number | null; }
export interface RankingEntered<T> { key: string; target_rank: number; item: T; }
export interface RankingExited<T> { key: string; base_rank: number; item: T; }
export interface RankingChange<T> { key: string; base_rank: number; target_rank: number; rank_delta: number; base_item: T; target_item: T; }
export interface RankingComparison<T> { base_count: number; target_count: number; entered: RankingEntered<T>[]; exited: RankingExited<T>[]; rank_changes: RankingChange<T>[]; }
export interface HighlightComparison<T> { base: T | null; target: T | null; changed: boolean | null; }

export interface DailyReviewComparison {
  schema_version: string;
  base: DailyReviewComparisonMeta;
  target: DailyReviewComparisonMeta;
  comparison_status: DataStatus;
  schema_compatible: boolean;
  warnings: string[];
  market_breadth: { available: boolean; stock_count: NumericComparison; valid_count: NumericComparison; up_count: NumericComparison; down_count: NumericComparison; flat_count: NumericComparison; up_ratio: NumericComparison; up_3pct_count: NumericComparison; down_3pct_count: NumericComparison; total_amount: NumericComparison; amount_valid_count: NumericComparison };
  short_term_emotion: { available: boolean; zt_count: NumericComparison; dt_count: NumericComparison; zb_count: NumericComparison; max_boards: NumericComparison; lianban_count: NumericComparison; seal_rate: NumericComparison; break_rate: NumericComparison; promotion_rate: NumericComparison; yzt_count: NumericComparison };
  sector_rotation: {
    industry: { top: RankingComparison<BoardRankItem>; bottom: RankingComparison<BoardRankItem> };
    concept: { top: RankingComparison<BoardRankItem>; bottom: RankingComparison<BoardRankItem> };
    region: { top: RankingComparison<BoardRankItem>; bottom: RankingComparison<BoardRankItem> };
    highlights: Record<"strongest_industry" | "weakest_industry" | "strongest_concept" | "weakest_concept" | "strongest_region" | "weakest_region", HighlightComparison<BoardRankItem>>;
  };
  capital_activity: { total_amount: NumericComparison; amount_valid_count: NumericComparison; amount_top: RankingComparison<MarketSnapshotItem>; high_turnover: RankingComparison<MarketSnapshotItem> };
  unknowns: string[];
}

export interface DailyReviewAiPayload {
  markdown: string;
  source_review_generated_at: string;
  source_data_cutoff: string | null;
}

export interface DailyReviewAnalyzeRequest {
  user_request?: string | null;
  llm: StreamLlmConfig;
}
