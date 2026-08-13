/** 数据健康中心展示纯函数（可单测，无 React）。 */

export type HealthStatus = "normal" | "partial" | "unavailable";

export type DataHealthRecord = {
  source_id: string;
  module: string;
  display_name: string;
  status: HealthStatus;
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
};

export type DataHealthSummary = {
  normal: number;
  partial: number;
  unavailable: number;
  stale: number;
  not_initialized: number;
};

export type DataHealthOverview = {
  overall_status: HealthStatus;
  blocks_advice: boolean;
  block_reasons: Array<{ source_id: string; error_code: string; summary: string }>;
  summary: DataHealthSummary;
  items: DataHealthRecord[];
};

export type DataHealthDetail = {
  record: DataHealthRecord;
  calculation: {
    quality_basis?: string[];
    freshness_basis?: string;
    calendar_type?: string;
    rule_summary?: string;
    disclaimer?: string;
  };
  related_pages: Array<{ label: string; path: string }>;
};

export const STATUS_LABEL: Record<HealthStatus, string> = {
  normal: "正常",
  partial: "部分可用",
  unavailable: "不可用",
};

export const REQUEST_SCOPED = new Set([
  "quotes",
  "announcements",
  "financials",
  "sector_research",
]);

/**
 * P0-DS1 presentation 层语义：未初始化/未检测 ≠ 不可用。
 * backend 三态 contract（normal/partial/unavailable）保持不变，
 * SOURCE_NOT_INITIALIZED（尚无成功运行记录）在展示层单列为
 * not_initialized —— 绝不显示为红色「不可用」。
 */
export type PresentationState = "not_initialized" | HealthStatus;

export function presentationState(
  record: DataHealthRecord | null | undefined,
): PresentationState {
  if (!record) return "not_initialized";
  if (record.last_error_code === "SOURCE_NOT_INITIALIZED") return "not_initialized";
  return record.status;
}

export const PRESENTATION_LABEL: Record<PresentationState, string> = {
  not_initialized: "未初始化",
  normal: "正常",
  partial: "部分可用",
  unavailable: "不可用",
};

export function presentationLabel(state: PresentationState): string {
  return PRESENTATION_LABEL[state];
}

export function presentationAriaLabel(state: PresentationState): string {
  return `数据状态：${presentationLabel(state)}`;
}

/**
 * P0-DS1：Freshness 独立于质量三态显示。
 * FRESH=新鲜 / STALE=陈旧 / UNKNOWN=未初始化或未提供 stale 信号。
 */
export type FreshnessState = "FRESH" | "STALE" | "UNKNOWN";

export function freshnessState(
  record: DataHealthRecord | null | undefined,
): FreshnessState {
  if (!record) return "UNKNOWN";
  if (record.last_error_code === "SOURCE_NOT_INITIALIZED") return "UNKNOWN";
  if (record.is_stale === true) return "STALE";
  if (record.is_stale === false) return "FRESH";
  return "UNKNOWN";
}

export const FRESHNESS_LABEL: Record<FreshnessState, string> = {
  FRESH: "数据新鲜",
  STALE: "数据陈旧",
  UNKNOWN: "新鲜度未知",
};

export function freshnessLabel(state: FreshnessState): string {
  return FRESHNESS_LABEL[state];
}

export function statusLabel(status: HealthStatus | string | null | undefined): string {
  if (status === "normal" || status === "partial" || status === "unavailable") {
    return STATUS_LABEL[status];
  }
  return "不可用";
}

export function statusAriaLabel(status: HealthStatus | string | null | undefined): string {
  return `数据状态：${statusLabel(status)}`;
}

/** true → 标签文案；false → 不显示；null → 详情用「未提供」 */
export function cacheTag(is_cached: boolean | null | undefined): string | null {
  if (is_cached === true) return "缓存结果";
  return null;
}

export function degradedTag(is_degraded: boolean | null | undefined): string | null {
  if (is_degraded === true) return "降级结果";
  return null;
}

export function cacheDetailText(is_cached: boolean | null | undefined): string | null {
  if (is_cached === true) return "缓存结果";
  if (is_cached === false) return null;
  return "当前来源未提供该信息";
}

export function degradedDetailText(is_degraded: boolean | null | undefined): string | null {
  if (is_degraded === true) return "降级结果";
  if (is_degraded === false) return null;
  return "当前来源未提供该信息";
}

export function staleTag(is_stale: boolean | null | undefined): string | null {
  return is_stale ? "数据陈旧" : null;
}

export function coverageText(
  current: number | null | undefined,
  expected: number | null | undefined,
): string {
  if (current == null && expected == null) return "未提供";
  if (current != null && expected != null) return `${current} / ${expected}`;
  if (current != null) return String(current);
  return "未提供";
}

export type GateAdviceState = "allowed" | "blocked" | "not_evaluated" | "runtime_failed";

export function gateAdviceState(record: DataHealthRecord | null | undefined): GateAdviceState {
  if (!record) return "not_evaluated";
  if (record.last_error_code === "SOURCE_NOT_INITIALIZED") return "not_evaluated";
  if (record.status === "unavailable" && !record.blocks_advice) return "runtime_failed";
  if (record.blocks_advice) return "blocked";
  return "allowed";
}

export function gateAdviceLabel(state: GateAdviceState): string {
  switch (state) {
    case "allowed":
      return "允许生成";
    case "blocked":
      return "当前阻止";
    case "not_evaluated":
      return "尚未评估";
    case "runtime_failed":
      return "最近 Gate 运行失败";
  }
}

export function isProblemSource(r: DataHealthRecord): boolean {
  // P0-DS1：未初始化/未检测不是「问题」——不是红色不可用。
  if (r.last_error_code === "SOURCE_NOT_INITIALIZED") return false;
  return r.status === "partial" || r.status === "unavailable" || r.is_stale;
}

export function filterItems(
  items: DataHealthRecord[],
  opts: {
    module?: string | null;
    status?: string | null;
    is_stale?: boolean | null;
    blocks_advice?: boolean | null;
  },
): DataHealthRecord[] {
  return items.filter((it) => {
    if (opts.module && it.module !== opts.module) return false;
    if (opts.status && it.status !== opts.status) return false;
    if (opts.is_stale != null && it.is_stale !== opts.is_stale) return false;
    if (opts.blocks_advice != null && it.blocks_advice !== opts.blocks_advice) return false;
    return true;
  });
}

const VALID_STATUS = new Set(["normal", "partial", "unavailable"]);

export type HealthUrlFilters = {
  module: string | null;
  status: string | null;
  is_stale: boolean | null;
  blocks_advice: boolean | null;
};

/** 非法 query 清理为默认 null */
export function parseHealthSearchParams(sp: URLSearchParams): HealthUrlFilters {
  const module = sp.get("module");
  const status = sp.get("status");
  const is_stale_raw = sp.get("is_stale");
  const blocks_raw = sp.get("blocks_advice");

  let is_stale: boolean | null = null;
  if (is_stale_raw === "true") is_stale = true;
  else if (is_stale_raw === "false") is_stale = false;

  let blocks_advice: boolean | null = null;
  if (blocks_raw === "true") blocks_advice = true;
  else if (blocks_raw === "false") blocks_advice = false;

  return {
    module: module && module.trim() && !module.includes(",") ? module.trim() : null,
    status: status && VALID_STATUS.has(status) ? status : null,
    is_stale,
    blocks_advice,
  };
}

export function summaryQualityTotal(s: DataHealthSummary): number {
  return s.normal + s.partial + s.unavailable;
}

export function requestScopeCardHint(source_id: string): string | null {
  if (!REQUEST_SCOPED.has(source_id)) return null;
  return "最近一次真实调用";
}

export function requestScopeDetailDisclaimer(source_id: string, calcDisclaimer?: string): string | null {
  if (calcDisclaimer) return calcDisclaimer;
  if (!REQUEST_SCOPED.has(source_id)) return null;
  return "该状态来自此数据源最近一次真实业务调用，不代表全部股票或板块均已验证。";
}

export function emptySystemGuide(summary: DataHealthSummary): boolean {
  return summary.not_initialized === 11;
}
