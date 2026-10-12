import type {
  Report, ReportListResult, ReportSourceCoverage, ReportSourceCoverageReason,
  ReportSourceStatus, SectorReportsDiscoveryResult,
} from "./api/types.ts";

const REASON_TEXT: Record<ReportSourceCoverageReason, string> = {
  REQUEST_LIMIT: "已达到本次请求页数上限",
  UNKNOWN_TOTAL: "上游总页数未知",
  TOTAL_CHANGED: "查询期间上游总页数变化",
  EMPTY_BEFORE_EXPECTED: "预期页窗结束前出现空页",
  SOURCE_ERROR: "部分来源请求失败",
  MALFORMED_RESPONSE: "部分来源响应格式异常",
};

const count = (value: unknown): value is number => Number.isSafeInteger(value) && (value as number) >= 0;

/** Keep only the bounded public metadata contract; malformed/legacy coverage remains unknown. */
export function parseReportSourceCoverage(value: unknown): ReportSourceCoverage | null {
  if (!value || typeof value !== "object") return null;
  const c = value as Record<string, unknown>;
  if (c.scope !== "provider_report_page_window" || c.historical_complete !== false ||
      !count(c.requested_pages) || c.requested_pages < 1 || !count(c.attempted_pages) ||
      !count(c.received_pages) || !count(c.returned_rows) ||
      !(c.reported_total_pages === null || count(c.reported_total_pages)) ||
      !(c.expected_pages === null || count(c.expected_pages)) ||
      !(c.reason === null || (typeof c.reason === "string" && Object.prototype.hasOwnProperty.call(REASON_TEXT, c.reason))) ||
      c.received_pages > c.attempted_pages || c.attempted_pages > c.requested_pages ||
      (c.expected_pages !== null && c.expected_pages > c.requested_pages)) return null;
  return {
    scope: "provider_report_page_window", historical_complete: false,
    requested_pages: c.requested_pages, reported_total_pages: c.reported_total_pages,
    expected_pages: c.expected_pages, attempted_pages: c.attempted_pages,
    received_pages: c.received_pages, returned_rows: c.returned_rows,
    reason: c.reason as ReportSourceCoverageReason | null,
  };
}

export function reportSourceStatus(status: unknown, coverage: ReportSourceCoverage | null): ReportSourceStatus {
  if (status === "unavailable") return "unavailable";
  return status === "normal" && coverage !== null && coverage.reason === null &&
    coverage.reported_total_pages !== null && coverage.expected_pages !== null &&
    coverage.reported_total_pages <= coverage.requested_pages &&
    coverage.expected_pages === Math.min(coverage.requested_pages, Math.max(1, coverage.reported_total_pages)) &&
    coverage.received_pages >= Math.max(1, coverage.expected_pages) ? "normal" : "partial";
}

/** Read the outer envelope so ordinary API unwrapping cannot discard source coverage. */
export function parseReportListResult(value: unknown): ReportListResult | null {
  const envelope = value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown> : null;
  const data = Array.isArray(value) ? value : envelope?.data;
  if (!Array.isArray(data) || data.some(row => !row || typeof row !== "object" || typeof row.title !== "string" || !row.title.trim())) return null;
  const source_coverage = parseReportSourceCoverage(envelope?.source_coverage);
  return { data: data as Report[], status: reportSourceStatus(envelope?.status, source_coverage), source_coverage };
}

export function reportSourceCoverageText(status: ReportSourceStatus, coverage: ReportSourceCoverage | null): string {
  const detail = coverage
    ? `请求 ${coverage.requested_pages} 页，预期 ${coverage.expected_pages ?? "未知"} 页，已尝试 ${coverage.attempted_pages} 页，收到 ${coverage.received_pages} 页；上游总页数 ${coverage.reported_total_pages ?? "未知"}${coverage.reason ? `；${REASON_TEXT[coverage.reason]}` : ""}`
    : "来源页窗覆盖信息缺失或无效，覆盖范围未知";
  const label = status === "unavailable" ? "研报来源暂不可用" : status === "normal" ? "本次请求页窗已返回" : "研报覆盖受限";
  return `${label}：${detail}；不代表完整历史${status !== "normal" ? "，不能据此判断没有记录" : ""}`;
}

/** The panel uses the same result for its notice and empty-state language. */
export function sectorReportCoverageView(result: Pick<SectorReportsDiscoveryResult, "status" | "source_coverage">): {
  status: ReportSourceStatus; notice: string; emptyText: string;
} {
  const raw = result.source_coverage;
  const coverage = Array.isArray(raw) ? raw.map(parseReportSourceCoverage) : [];
  const status: ReportSourceStatus = result.status === "unavailable" ? "unavailable"
    : result.status === "normal" && coverage.length > 0 && coverage.every((c, index) => reportSourceStatus(raw?.[index]?.status ?? "normal", c) === "normal")
      ? "normal" : "partial";
  const detail = coverage.length > 0
    ? coverage.map((c, index) => `来源 ${index + 1} · ${reportSourceCoverageText(reportSourceStatus(raw?.[index]?.status ?? status, c), c)}`).join("；")
    : reportSourceCoverageText(status, null);
  const notice = status === "normal" ? detail
    : `${status === "unavailable" ? "研报来源暂不可用" : "研报覆盖受限或未知"}，不能据此判断没有匹配研报；${detail}`;
  return {
    status, notice,
    emptyText: status === "normal"
      ? "本次已查询页窗内未返回匹配研报，不代表完整历史；可调整范围或天数后重试。"
      : "本次未返回可展示研报；来源覆盖受限或未知，不能据此判断没有匹配研报。",
  };
}
