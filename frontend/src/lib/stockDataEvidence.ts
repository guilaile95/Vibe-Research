import type { Announcement, FundFlowRow, Report, Valuation } from "./api/types.ts";

export type EvidenceListState<T> =
  | { status: "idle" | "loading"; data: T[] }
  | { status: "success"; data: T[] }
  | { status: "error"; data: T[]; error: string };

/** A rejected source is unknown, never a successfully empty evidence set. */
export async function resolveEvidenceList<T>(request: Promise<T[]>, error: string): Promise<EvidenceListState<T>> {
  try {
    return { status: "success", data: await request };
  } catch {
    return { status: "error", data: [], error };
  }
}

export function evidenceListStatusText<T>(state: EvidenceListState<T>): string {
  if (state.status === "idle") return "尚未查询";
  if (state.status === "loading") return "加载中，尚不能判断是否有记录";
  if (state.status === "error") return `${state.error}；不能据此判断没有记录`;
  return state.data.length ? `本次查询返回 ${state.data.length} 条记录` : "本次查询成功，返回 0 条记录（不代表不存在相关信息）";
}

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
