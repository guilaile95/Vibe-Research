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

export type FullMarketMetric =
  | "code"
  | "latest_date"
  | "latest_close"
  | "return_5d"
  | "return_20d"
  | "return_60d"
  | "ma20"
  | "ma60"
  | "close_vs_ma20"
  | "close_vs_ma60"
  | "avg_volume_20d"
  | "current_volume"
  | "volume_ratio_20d";

export type FullMarketFilterOperator = "gt" | "gte" | "lt" | "lte" | "eq" | "neq";

export type FullMarketRow = {
  code: string;
  latest_date: string | null;
  latest_close: number | null;
  return_5d: number | null;
  return_20d: number | null;
  return_60d: number | null;
  ma20: number | null;
  ma60: number | null;
  close_vs_ma20: number | null;
  close_vs_ma60: number | null;
  avg_volume_20d: number | null;
  current_volume: number | null;
  volume_ratio_20d: number | null;
  observations_count: number;
  metric_status: Partial<Record<Exclude<FullMarketMetric, "code" | "latest_date">, "normal" | "INSUFFICIENT_HISTORY">>;
  [key: string]: unknown;
};

export type FullMarketBreadth = {
  breadth: number | null;
  above_count: number;
  evaluable_count: number;
  insufficient_count: number;
  status: "normal" | "INSUFFICIENT_HISTORY";
};

export type FullMarketResult = {
  schema_version: string;
  dataset_id: string;
  provider_id: string;
  adjustment: string;
  status: "normal" | "unavailable";
  fetched_at: string | null;
  as_of: string | null;
  latest_date: string | null;
  coverage: {
    start: string;
    end: string;
    row_count: number;
    code_count: number;
    universe_count: number;
  } | null;
  provenance: {
    source_kind: string | null;
    source_name: string | null;
    artifact_sha256: string | null;
    license_status: string | null;
  };
  breadth: { ma20: FullMarketBreadth; ma60: FullMarketBreadth };
  rows: FullMarketRow[];
  returned_rows: number;
  total_rows: number;
  next_offset: number | null;
  limitations: string[];
};

export type FullMarketQuery = {
  as_of?: string;
  latest?: boolean;
  filter_metric?: Exclude<FullMarketMetric, "code" | "latest_date">;
  filter_operator?: FullMarketFilterOperator;
  filter_value?: number;
  sort_by?: FullMarketMetric;
  sort_order?: "asc" | "desc";
  limit?: number;
  offset?: number;
};

export type DiscoveryStrategy = "SHORT" | "SWING" | "MEDIUM";
export type DiscoveryPriority = "HIGH" | "MEDIUM" | "LOW";
export type DiscoveryEvidenceGate =
  | "SUFFICIENT_FOR_RESEARCH"
  | "PARTIAL"
  | "INSUFFICIENT"
  | "UNKNOWN"
  | "ERROR";

export type DiscoveryObservation = {
  code: string;
  label: string;
  value: unknown;
  source_ref: string;
};

export type DiscoveryRestrictedStatus = {
  status: "CLEAR" | "RESTRICTED" | "UNKNOWN";
  reason_codes: string[];
  listing_age_status: "KNOWN" | "UNKNOWN";
};

export type DiscoveryOpportunityItem = {
  security_code: string;
  name: string;
  strategy: DiscoveryStrategy;
  sector: string | null;
  themes: string[];
  discovery_state: "QUEUED" | "BLOCKED" | "EXCLUDED";
  research_priority: DiscoveryPriority;
  reason_codes: string[];
  supporting_observations: DiscoveryObservation[];
  uncertainties: string[];
  data_health: "normal" | "partial" | "unknown" | "error";
  catalyst_status: "AVAILABLE" | "PARTIAL" | "UNKNOWN" | "ERROR";
  fundamental_status: "AVAILABLE" | "PARTIAL" | "UNKNOWN" | "ERROR";
  evidence_gate: DiscoveryEvidenceGate;
  restricted_universe: DiscoveryRestrictedStatus;
  discovered_at: string;
  as_of: string | null;
  provenance_refs: string[];
};

export type DiscoveryExcludedItem = Partial<DiscoveryOpportunityItem> & {
  security_code: string;
  name: string;
  strategy?: DiscoveryStrategy;
  reason_codes: string[];
  data_health: string;
  restricted_universe?: DiscoveryRestrictedStatus;
  as_of?: string | null;
};

export type DiscoveryDatasetStatus = {
  dataset_id: string;
  status: "normal" | "partial" | "stale" | "unavailable" | "error";
  as_of: string | null;
  fetched_at: string;
  reason_code: string | null;
  provenance_refs: string[];
};

export type DiscoverySnapshot = {
  schema_version: string;
  status: "normal" | "partial" | "stale" | "unavailable" | "error";
  as_of: string | null;
  fetched_at: string;
  last_successful_at: string | null;
  refresh_attempted_at: string | null;
  market_context: {
    status: string;
    core_universe_count: number;
    outside_core_count?: number;
    sector_count: number;
    market_average_change_pct?: number | null;
    amount_median?: number | null;
    turnover_active_threshold?: number | null;
    source_ref?: string;
  };
  funnel: {
    core_universe: number;
    cheap_scan_passed: number;
    qualification_candidates: number;
    queue_items: Record<DiscoveryStrategy, number>;
    excluded: number;
  };
  datasets: DiscoveryDatasetStatus[];
  queues: Record<DiscoveryStrategy, DiscoveryOpportunityItem[]>;
  excluded: DiscoveryExcludedItem[];
  limitations: string[];
  cache: { hit: boolean; age_seconds: number | null; refresh_failed?: boolean };
};
