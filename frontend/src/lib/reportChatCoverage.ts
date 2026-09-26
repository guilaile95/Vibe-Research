import type { ReportChatCoverage } from "./api/types.ts";

/** Shared by the stream boundary and persisted chat hydration. Older replies omit coverage. */
export function parseReportChatCoverage(value: unknown): ReportChatCoverage | undefined {
  if (!value || typeof value !== "object") return undefined;
  const data = value as Record<string, unknown>;
  for (const key of ["selected_count", "matched_report_count", "included_report_count",
    "retrieved_hit_count", "included_hit_count", "hit_limit"]) {
    if (!Number.isInteger(data[key]) || (data[key] as number) < 0) return undefined;
  }
  if (typeof data.hit_limit_reached !== "boolean" || typeof data.context_truncated !== "boolean" ||
      typeof data.excerpt_only !== "boolean" || !Array.isArray(data.uncovered_reports) ||
      data.uncovered_reports.length > 100) return undefined;
  const uncovered = [];
  for (const item of data.uncovered_reports) {
    if (!item || typeof item !== "object" || typeof item.report_id !== "string" ||
        typeof item.reason !== "string" || typeof item.message !== "string") return undefined;
    uncovered.push({ report_id: item.report_id, title: typeof item.title === "string" && item.title ? item.title : item.report_id,
      reason: item.reason, message: item.message });
  }
  return {
    selected_count: data.selected_count as number,
    matched_report_count: data.matched_report_count as number,
    included_report_count: data.included_report_count as number,
    retrieved_hit_count: data.retrieved_hit_count as number,
    included_hit_count: data.included_hit_count as number,
    hit_limit: data.hit_limit as number,
    hit_limit_reached: data.hit_limit_reached,
    context_truncated: data.context_truncated,
    excerpt_only: data.excerpt_only,
    uncovered_reports: uncovered,
  };
}
