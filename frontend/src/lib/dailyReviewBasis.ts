import type { AiGeneratedResult, DailyReviewAiPayload, DailyReviewInputBasis } from "./api/types";

export const basisComponents = {
  indices: "主要指数", global_indices: "外围指数", breadth: "市场广度", emotion: "短线情绪",
  turnover: "成交额", industry_boards: "行业板块", concept_boards: "概念板块", region_boards: "地域板块",
} as const;
export const basisStatuses = { normal: "可用", partial: "部分缺失", unavailable: "不可用", unknown: "未知" } as const;
const has = (value: object, key: PropertyKey) => Object.prototype.hasOwnProperty.call(value, key);
const keys = ["schema_version", "context_schema_version", "review_schema_version", "trade_date", "source_review_generated_at", "source_data_cutoff", "review_status", "component_statuses", "omitted_component_count", "warning_count", "unknown_count", "context_sha256"];

function calendarDate(value: unknown): value is string {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const [year, month, day] = value.split("-").map(Number);
  const leap = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
  const days = [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  return year >= 1 && month >= 1 && month <= 12 && day >= 1 && day <= days[month - 1];
}
export function reviewBasisTimestamp(value: unknown): value is string {
  if (typeof value !== "string" || value.length > 64) return false;
  const m = /^(\d{4}-\d{2}-\d{2})[ T](\d{2}):(\d{2}):(\d{2})(?:\.\d{1,6})?(?:Z|([+-])(\d{2}):(\d{2}))?$/.exec(value);
  return !!m && calendarDate(m[1]) && Number(m[2]) < 24 && Number(m[3]) < 60 && Number(m[4]) < 60
    && (!m[5] || (Number(m[6]) < 24 && Number(m[7]) < 60));
}

export function validatedReviewBasis(result: AiGeneratedResult<DailyReviewAiPayload>): DailyReviewInputBasis | null {
  const b = result.payload?.input_basis;
  if (result.result_type !== "daily_review_ai" || result.schema_version !== "daily_review_ai.v2" || !b || typeof b !== "object" || Array.isArray(b)
      || Object.keys(b).length !== keys.length || keys.some(k => !has(b, k))
      || b.schema_version !== "daily-review-input-basis.v1" || b.context_schema_version !== "daily-review-ai-context-v0.1"
      || !calendarDate(b.trade_date) || !reviewBasisTimestamp(b.source_review_generated_at)
      || (b.source_data_cutoff !== null && !reviewBasisTimestamp(b.source_data_cutoff))
      || b.trade_date !== result.trade_date || b.source_review_generated_at !== result.payload.source_review_generated_at
      || b.source_data_cutoff !== result.payload.source_data_cutoff
      || (b.review_schema_version !== null && (typeof b.review_schema_version !== "string" || !/^[A-Za-z0-9._-]{1,64}$/.test(b.review_schema_version)))
      || typeof b.context_sha256 !== "string" || !/^[0-9a-f]{64}$/.test(b.context_sha256)
      || typeof b.review_status !== "string" || !has(basisStatuses, b.review_status)) return null;
  const components = b.component_statuses;
  if (!components || typeof components !== "object" || Array.isArray(components)
      || Object.keys(components).length !== Object.keys(basisComponents).length
      || Object.keys(basisComponents).some(k => !has(components, k) || typeof components[k] !== "string" || !has(basisStatuses, components[k]))) return null;
  if ([b.omitted_component_count, b.warning_count, b.unknown_count].some(n => !Number.isInteger(n) || n < 0 || n > 10000)) return null;
  return b;
}
