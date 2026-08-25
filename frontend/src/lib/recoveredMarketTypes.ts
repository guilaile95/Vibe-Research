export type NorthboundHistoryStatus = "normal" | "partial" | "unavailable";

export type NorthboundHistoryLimitation = {
  field?: string;
  reason_code?: string;
  detail?: string;
};

export type NorthboundHistoryPoint = {
  trade_date: string;
  total_turnover_mn: number;
  trade_count: number | null;
  etf_turnover_mn: number | null;
};

export type NorthboundHistoryEnvelope = {
  schema_version: string;
  source: string;
  source_tier: string;
  status: NorthboundHistoryStatus;
  fetched_at: string;
  requested_days: number;
  returned_points: number;
  limitations: NorthboundHistoryLimitation[];
  series: NorthboundHistoryPoint[];
};

export type ScreenerConditionId =
  | "price_gt_sma20"
  | "price_lt_sma20"
  | "price_gt_sma60"
  | "price_lt_sma60"
  | "sma20_gt_sma60"
  | "sma20_lt_sma60"
  | "macd_hist_positive"
  | "macd_hist_negative"
  | "breakout_20d_high"
  | "breakdown_20d_low"
  | "rsi_between"
  | "volume_ratio_gte"
  | "volume_ratio_lte";

export type ScreenerCondition = {
  id: ScreenerConditionId;
  params?: {
    min?: number;
    max?: number;
    threshold?: number;
  };
};

export type ScreenerEvaluateIn = {
  codes: string[];
  conditions: ScreenerCondition[];
};

export type ScreenerConditionResult = {
  id: ScreenerConditionId | string;
  evaluable: boolean;
  passed: boolean | null;
  evidence: Record<string, unknown>;
};

export type ScreenerStockResult = {
  code: string;
  bucket: "matched" | "rejected" | "unavailable" | string;
  matched: boolean | null;
  technical_status: string;
  trade_date: string | null;
  condition_results: ScreenerConditionResult[];
  limitations: string[];
};

export type ScreenerResearchCoverage = {
  start: string;
  end: string;
  row_count: number;
  code_count: number;
};

export type ScreenerResearchProvenance = {
  source_kind: string | null;
  source_name: string | null;
  artifact_sha256: string | null;
  license_status: string | null;
};

export type ScreenerResearchData = {
  schema_version: string;
  dataset_id: string;
  provider_id: string;
  adjustment: string;
  status: "normal" | "unavailable";
  fetched_at: string | null;
  as_of: string | null;
  coverage: ScreenerResearchCoverage | null;
  provenance: ScreenerResearchProvenance;
  limitations: string[];
};

export type ScreenerEvaluateResult = {
  status: string;
  evaluated_at: string;
  logic: string;
  matched: ScreenerStockResult[];
  rejected: ScreenerStockResult[];
  unavailable: ScreenerStockResult[];
  research_data: ScreenerResearchData;
  limitations: string[];
  schema_version: string;
};

export type ScreenerSectorRepresentativesResult = {
  codes: string[];
  count: number;
  schema_version?: string;
};
