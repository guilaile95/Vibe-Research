import type { ReportChatCoverage, ReportPageContextMeta, ReportPageReadStatus } from "./api/types.ts";

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
  const page_context = data.page_context === undefined ? undefined : parseReportPageContext(data.page_context);
  if (data.page_context !== undefined && !page_context) return undefined;
  return {
    ...(page_context ? { page_context } : {}),
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


/** No browser text is retained. Validate both persisted metadata and stream shape. */
export function parseReportPageContext(value: unknown): ReportPageContextMeta | undefined {
  if (!value || typeof value !== "object") return undefined;
  const data = value as Record<string, any>;
  const statuses: ReportPageReadStatus[] = ["readable", "omitted", "invalid", "unreadable", "error"];
  if (typeof data.report_id !== "string" || !data.report_id || data.report_id.length > 128 ||
    typeof data.expected_file_sha256 !== "string" || !/^[0-9a-f]{64}$/.test(data.expected_file_sha256) ||
    !Number.isInteger(data.page_from) || !Number.isInteger(data.page_to) || data.page_from < 1 ||
    data.page_to > 1000000 || data.page_to < data.page_from || data.page_to - data.page_from >= 200 ||
    data.full_report_read !== false || !Number.isInteger(data.returned_chars) || data.returned_chars < 1 || data.returned_chars > 12000 ||
    !Array.isArray(data.requested) || !Array.isArray(data.items) || !data.coverage || typeof data.coverage !== "object") return undefined;
  const requested = Array.from({ length: data.page_to - data.page_from + 1 }, (_, i) => data.page_from + i);
  if (JSON.stringify(data.requested) !== JSON.stringify(requested) || data.items.length !== requested.length) return undefined;
  const coverage = Object.fromEntries(statuses.map(status => [status, [] as number[]])) as Record<ReportPageReadStatus, number[]>;
  const items: ReportPageContextMeta["items"] = [];
  let total = 0;
  for (const [index, item] of data.items.entries()) {
    if (!item || item.page !== requested[index] || !statuses.includes(item.status) ||
      typeof item.reason !== "string" || !item.reason || item.reason.length > 100) return undefined;
    const status = item.status as ReportPageReadStatus;
    coverage[status].push(item.page);
    if (status === "readable") {
      if (!Number.isInteger(item.returned_chars) || item.returned_chars < 1 || item.returned_chars > 6000 ||
        !Number.isInteger(item.indexed_chars) || item.indexed_chars < item.returned_chars ||
        item.truncated !== (item.returned_chars < item.indexed_chars)) return undefined;
      total += item.returned_chars;
      items.push({ page: item.page, status, reason: item.reason, returned_chars: item.returned_chars,
        indexed_chars: item.indexed_chars, truncated: item.truncated });
    } else items.push({ page: item.page, status, reason: item.reason });
  }
  if (total !== data.returned_chars || coverage.readable.length < 1 || coverage.readable.length > 8 || coverage.error.length > 0 ||
    statuses.some(status => JSON.stringify(data.coverage[status]) !== JSON.stringify(coverage[status]))) return undefined;
  return { report_id: data.report_id, expected_file_sha256: data.expected_file_sha256,
    page_from: data.page_from, page_to: data.page_to, full_report_read: false,
    requested, coverage, returned_chars: total, items };
}
