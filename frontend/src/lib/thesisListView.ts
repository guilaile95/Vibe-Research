import type { InvestmentThesis } from "./api/types";
import { evidenceFilterQuery, parseEvidenceListQuery } from "./evidenceListView.ts";

export const THESIS_STATUS_LABELS: Record<string, string> = {
  active: "生效中", weakened: "走弱", invalidated: "已失效", archived: "已归档",
};

// Thesis uses the same paired-subject and pagination contract as Evidence.
export function parseThesisListQuery(search: URLSearchParams) {
  const query = parseEvidenceListQuery(search);
  const status = search.get("status") ?? "";
  const error = query.error?.replace("证据", "投资逻辑") || (status && !Object.prototype.hasOwnProperty.call(THESIS_STATUS_LABELS, status) ? "请选择有效的跟踪状态。" : null);
  return { ...query, status, error };
}
export function thesisFilterQuery(current: URLSearchParams, subjectType: string, subjectId: string, status: string) {
  const next = evidenceFilterQuery(current, subjectType, subjectId);
  if (status) next.set("status", status);
  else next.delete("status");
  return next;
}
export function thesisRevisionLabel(value: number | null | undefined) {
  return typeof value === "number" && Number.isInteger(value) && value > 0 ? `v${value}` : "未知";
}
export function thesisLifecycleLabel(thesis: Pick<InvestmentThesis, "formal_state">) {
  switch (thesis.formal_state) {
    case "draft": return "正式草稿 · 未确认";
    case "confirmed": return "已确认 · 尚未冻结";
    case "frozen": return "已冻结";
    case null:
    case undefined: return "旧版记录 · 未进入正式流程";
    default: return "正式状态未知 · 需核对";
  }
}
