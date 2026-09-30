import type { Announcement, FundFlowRow, Report, Valuation } from "./api/types.ts";

export type EvidenceState<T> =
  | { status: "idle" | "loading"; data: T }
  | { status: "success"; data: T; empty?: boolean }
  | { status: "error" | "unsupported"; data: T; error: string };

export type EvidenceListState<T> = EvidenceState<T[]>;

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

export function reportEvidenceContext(state: EvidenceListState<Report>): string {
  const items = state.status === "success" ? state.data.slice(0, 5).map((r) =>
    `${r.title}（发布日期 ${r.publishDate || "未知"}；机构 ${r.orgSName || "未知"}${r.pdfUrl ? `；来源 ${r.pdfUrl}` : ""}）`,
  ).join("；") : "";
  return `近期研报：${evidenceListStatusText(state)}${items ? `\n${items}` : ""}`;
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
