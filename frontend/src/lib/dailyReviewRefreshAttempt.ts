import type { DailyReviewRefreshAttempt, DailyReviewSourceErrorCode } from "./api/types.ts";

const SOURCES: Record<string, string> = {
  indices: "大盘指数", global_indices: "全球指数", breadth: "市场广度", emotion: "短线情绪",
  turnover: "成交额榜", industry: "行业板块", concept: "概念板块", region: "地域板块",
};
const STAGES: Record<string, string> = { collection: "数据采集", quality: "质量校验", persistence: "结果保存", complete: "完成" };
const SOURCE_ERRORS: Record<DailyReviewSourceErrorCode, string> = {
  SOURCE_COOLDOWN: "数据源冷却保护中；不要重复刷新",
  SOURCE_BUDGET_EXHAUSTED: "数据源请求预算已用尽；不要重复刷新",
  SOURCE_READ_ONLY: "当前为只读模式，未发起数据采集",
  SOURCE_SAFETY_UNAVAILABLE: "数据源安全保护状态暂不可用",
  SOURCE_REFUSED: "数据源拒绝了本次请求",
  SOURCE_BLOCKED: "数据源请求被保护规则阻止",
};
const REASONS: Record<string, string> = {
  ...SOURCE_ERRORS,
  SOURCE_TIMEOUT: "数据采集达到时间上限", SOURCE_BUSY: "数据采集资源繁忙",
  SOURCE_UNAVAILABLE: "数据源暂不可用", SOURCE_BAD_RESPONSE: "数据源返回格式异常",
  unavailable: "市场数据不可用", critical_unavailable: "关键市场数据不可用",
  partial_with_existing_normal: "本次数据不完整，未替换上次成功结果",
  persist_failed: "结果保存失败", store_rejected: "结果未通过保存检查",
  invalid_result: "结果格式异常", invalid_status: "结果状态异常",
  build_exception: "数据整理失败", flight_timeout: "等待共享刷新超时",
  superseded: "已有更新的刷新轮次", refresh_failed: "刷新失败", unexpected: "刷新异常",
};

export function parseRefreshAttempt(value: unknown): DailyReviewRefreshAttempt | null {
  if (!value || typeof value !== "object") return null;
  const v = value as Record<string, unknown>;
  if (!["running", "succeeded", "failed"].includes(String(v.state))) return null;
  const time = (input: unknown) => typeof input === "string" && /^\d{4}-\d{2}-\d{2}[T ][\d:.+Z -]+$/.test(input) ? input : null;
  const started = time(v.started_at);
  if (!started) return null;
  const sources = (input: unknown) => Array.isArray(input)
    ? [...new Set(input.filter((key): key is string => typeof key === "string" && Object.prototype.hasOwnProperty.call(SOURCES, key)))] : [];
  const failedSources = sources(v.failed_sources);
  const sourceErrors: Record<string, DailyReviewSourceErrorCode> = {};
  if (v.source_errors && typeof v.source_errors === "object" && !Array.isArray(v.source_errors)) {
    for (const key of failedSources) {
      const code = (v.source_errors as Record<string, unknown>)[key];
      if (typeof code === "string" && Object.prototype.hasOwnProperty.call(SOURCE_ERRORS, code)) {
        sourceErrors[key] = code as DailyReviewSourceErrorCode;
      }
    }
  }
  return {
    ...(Object.keys(sourceErrors).length ? { source_errors: sourceErrors } : {}),
    ...(typeof v.stage === "string" && Object.prototype.hasOwnProperty.call(STAGES, v.stage) ? { stage: v.stage as DailyReviewRefreshAttempt["stage"] } : {}),
    state: v.state as DailyReviewRefreshAttempt["state"], started_at: started,
    finished_at: time(v.finished_at),
    reason_code: typeof v.reason_code === "string" && Object.prototype.hasOwnProperty.call(REASONS, v.reason_code) ? v.reason_code : null,
    failed_sources: failedSources, pending_sources: sources(v.pending_sources),
  };
}

export function refreshAttemptLines(value: unknown): string[] {
  const attempt = parseRefreshAttempt(value);
  if (!attempt) return [];
  const state = { running: "进行中", succeeded: "成功", failed: "失败" }[attempt.state];
  const lines = [`最近刷新尝试：${state} · 开始：${attempt.started_at}${attempt.finished_at ? ` · 结束：${attempt.finished_at}` : ""}`];
  if (attempt.stage) lines.push(`阶段：${STAGES[attempt.stage]}`);
  if (attempt.reason_code) lines.push(`原因：${REASONS[attempt.reason_code]}（${attempt.reason_code}）`);
  if (attempt.failed_sources.length) lines.push(`失败组件：${attempt.failed_sources.map(key => SOURCES[key]).join("、")}`);
  for (const [key, code] of Object.entries(attempt.source_errors || {})) lines.push(`${SOURCES[key]}：${SOURCE_ERRORS[code]}`);
  if (attempt.pending_sources.length) lines.push(`未完成组件：${attempt.pending_sources.map(key => SOURCES[key]).join("、")}`);
  return lines;
}
