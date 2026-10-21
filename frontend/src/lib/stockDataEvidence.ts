import type { Announcement, FundFlowRow, Report, ReportListResult, ReportSourceCoverage, Valuation } from "./api/types.ts";
import { parseReportSourceCoverage, reportSourceCoverageText, reportSourceStatus } from "./reportSourceCoverage.ts";

export type EvidenceState<T> =
  | { status: "idle" | "loading"; data: T }
  | { status: "success"; data: T; empty?: boolean }
  | { status: "error" | "unsupported"; data: T; error: string };

export type EvidenceListState<T> = EvidenceState<T[]>;

/** Report pagination can retain useful rows without claiming source completeness. */
export type ReportEvidenceState = (EvidenceListState<Report> & { source_coverage?: ReportSourceCoverage | null })
  | { status: "partial"; data: Report[]; source_coverage: ReportSourceCoverage | null };

/** Source errors never supply provider details or masquerade as empty evidence. */
export async function resolveEvidence<T>(
  request: Promise<T>, fallback: T, error: string,
  isEmpty: (data: T) => boolean = (data) => Array.isArray(data) ? data.length === 0 : data == null,
): Promise<EvidenceState<T>> {
  try {
    const data = await request;
    return { status: "success", data, empty: isEmpty(data) };
  } catch (cause) {
    const unsupported = typeof cause === "object" && cause !== null && "status" in cause && cause.status === 501;
    return { status: unsupported ? "unsupported" : "error", data: fallback, error };
  }
}

export function resolveEvidenceList<T>(request: Promise<T[]>, error: string): Promise<EvidenceListState<T>> {
  return resolveEvidence(request, [], error);
}

export async function resolveReportEvidence(request: Promise<ReportListResult>, error: string): Promise<ReportEvidenceState> {
  try {
    const result = await request;
    const source_coverage = parseReportSourceCoverage(result.source_coverage);
    const status = reportSourceStatus(result.status, source_coverage);
    if (status === "unavailable") return { status: "error", data: [], source_coverage, error };
    if (status === "partial") return { status, data: result.data, source_coverage };
    return { status: "success", data: result.data, source_coverage, empty: result.data.length === 0 };
  } catch (cause) {
    const unsupported = typeof cause === "object" && cause !== null && "status" in cause && cause.status === 501;
    return { status: unsupported ? "unsupported" : "error", data: [], error };
  }
}

/** Shared by the page's independent requests; both start and settlement reject stale runs. */
export async function loadEvidenceSource<T>(
  request: () => Promise<T>, fallback: T, error: string,
  commit: (state: EvidenceState<T>) => void, isCurrent: () => boolean,
  isEmpty?: (data: T) => boolean,
): Promise<void> {
  if (!isCurrent()) return;
  commit({ status: "loading", data: fallback });
  // Starting through a promise also converts synchronous adapter errors to source failures.
  const result = await resolveEvidence(Promise.resolve().then(request), fallback, error, isEmpty);
  if (isCurrent()) commit(result);
}

export function evidenceStatusText<T>(state: EvidenceState<T>): string {
  if (state.status === "idle") return "尚未查询";
  if (state.status === "loading") return "加载中，尚不能判断是否有记录";
  if (state.status === "unsupported") return "当前环境不支持此数据源（501）；不能据此判断没有记录";
  if (state.status === "error") return `${state.error}；不能据此判断没有记录`;
  if (Array.isArray(state.data)) return state.data.length ? `本次接口返回 ${state.data.length} 条记录` : "本次接口返回 0 条记录（不代表不存在相关信息，也不能排除上游缺失）";
  return state.status === "success" && state.empty ? "本次接口未返回可展示记录（不代表不存在相关信息，也不能排除上游缺失）" : "本次接口已返回数据";
}

export const evidenceListStatusText = evidenceStatusText;

export function reportEvidenceStatusText(state: ReportEvidenceState): string {
  if (state.status !== "success" && state.status !== "partial") return evidenceListStatusText(state);
  const coverage = parseReportSourceCoverage(state.source_coverage);
  const status = reportSourceStatus(state.status === "success" ? "normal" : "partial", coverage);
  return `本次接口返回 ${state.data.length} 条记录；${reportSourceCoverageText(status, coverage)}`;
}

export function reportEvidenceContext(state: ReportEvidenceState): string {
  const hasRows = state.status === "success" || state.status === "partial";
  const coverage = parseReportSourceCoverage(state.source_coverage);
  const items = hasRows ? state.data.slice(0, 5).map((r) =>
    `${r.title}（发布日期 ${r.publishDate || "未知"}；机构 ${r.orgSName || "未知"}${r.pdfUrl ? `；来源 ${r.pdfUrl}` : ""}）`,
  ).join("；") : "";
  const metadata = hasRows || coverage
    ? `\n研报来源覆盖：${JSON.stringify({
      status: reportSourceStatus(hasRows ? state.status === "success" ? "normal" : "partial" : "unavailable", coverage),
      source_coverage: coverage,
    })}` : "";
  return `近期研报：${reportEvidenceStatusText(state)}${metadata}${items ? `\n${items}` : ""}`;
}

export function announcementEvidenceContext(state: EvidenceListState<Announcement>): string {
  const items = state.status === "success" ? state.data.slice(0, 5).map((a) =>
    `${a.title}（公告日期 ${a.date || "未知"}${a.url ? `；来源 ${a.url}` : ""}）`,
  ).join("；") : "";
  return `近期公告：${evidenceListStatusText(state)}${items ? `\n${items}` : ""}`;
}

/** These timestamps describe the quote only, not forecasts or the composite valuation. */
export function quoteEvidenceContext(val: Pick<Valuation, "quote_source" | "quote_data_time" | "quote_trade_date">): string {
  return `报价来源 ${val.quote_source || "未知"} · 报价时间 ${val.quote_data_time || "未知"} · 报价交易日 ${val.quote_trade_date || "未知"}（仅适用于报价，不代表估值或预测整体时效）`;
}

export function summarizeStockFundFlow(rows: readonly FundFlowRow[]) {
  const recent = [...rows].sort((a, b) => b.date.localeCompare(a.date)).slice(0, 20);
  const valid = recent.filter((row) => typeof row.main_net === "number" && Number.isFinite(row.main_net));
  return {
    observed: recent.length,
    valid: valid.length,
    total: recent.length > 0 && valid.length === recent.length
      ? valid.reduce((sum, row) => sum + row.main_net!, 0) : null,
    latestDate: recent[0]?.date ?? null,
  };
}

/** Capital fields can be unavailable without being a reported zero. */
export function formatStockCapitalValue(value: unknown, kind: "balance" | "count" | "percent"): string {
  if (typeof value !== "number" && typeof value !== "string") return "—";
  if (typeof value === "string" && !value.trim()) return "—";
  const number = Number(value);
  if (!Number.isFinite(number)) return "—";
  if (kind === "balance") return `${(number / 1e8).toFixed(2)} 亿`;
  if (kind === "percent") return `${number.toFixed(2)}%`;
  return number.toLocaleString();
}

/** Snapshot observations only. Missing or malformed values never become zero. */
export function financialEvidenceContext(value: unknown): string {
  if (!value || typeof value !== "object" || Array.isArray(value)) return "财务快照：未知；未取得合格来源。";
  const f = value as Record<string, unknown>;
  const q = f.data_quality as Record<string, unknown> | null;
  if (!q || typeof q !== "object" || Array.isArray(q) ||
      q.source !== "tonghuashun_via_akshare" || q.fetch_mode !== "snapshot" ||
      q.report_basis !== "cumulative_report_period" || q.point_in_time_supported !== false ||
      q.publication_date_known !== false || (q.status !== "normal" && q.status !== "partial"))
    return "财务快照：未知；来源契约未通过校验。";
  const scalar = (v: unknown): string => {
    if (typeof v === "number") return Number.isFinite(v) ? String(v) : "未知";
    if (typeof v !== "string" || v.length > 128) return "未知";
    const s = v.trim();
    const m = /^([+-]?(?:\d+(?:\.\d+)?|\.\d+))(%|％|亿元|万元|亿|万|元)?$/.exec(s);
    return m && Number.isFinite(Number(m[1])) ? s : "未知";
  };
  const date = (v: unknown): string => {
    if (typeof v !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(v) || Number(v.slice(0, 4)) < 1) return "未知";
    const n = Date.parse(v + "T00:00:00Z");
    return Number.isFinite(n) && new Date(n).toISOString().slice(0, 10) === v ? v : "未知";
  };
  const fields = [
    ["营收", "revenue"], ["营收同比", "revenue_yoy"], ["净利润", "net_profit"],
    ["净利润同比", "net_profit_yoy"], ["扣非净利润同比", "deduct_net_profit_yoy"],
    ["ROE", "roe"], ["毛利率", "gross_margin"], ["经营现金流", "operating_cash_flow"],
    ["现金转化率", "cash_conversion_ratio"], ["自由现金流", "free_cash_flow"], ["资产负债率", "debt_ratio"],
  ];
  return `财务快照（报告期末 ${date(f.period_end)}；披露日期未知；非PIT；来源 ${q.source}；状态 ${q.status}）：` +
    fields.map(([label, key]) => `${label} ${scalar(f[key])}`).join("、") +
    "。币种、单位、统计口径与修订版本未核验；不得据此跨公司或跨期间比较数字。";
}
