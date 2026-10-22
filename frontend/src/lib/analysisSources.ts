import { safeResearchSourceUrl } from "./researchNote.ts";

/** External navigation only; no fetching or expansion of deep-read permissions. */
export function safeAnalysisSourceUrl(value: unknown): string | null {
  if (typeof value !== "string" || !/^https?:\/\//i.test(value) || /[\s\\\x00-\x1f\x7f]/.test(value)) return null;
  return safeResearchSourceUrl(value);
}

export function analysisCoverageReason(reason: string): string {
  const labels: Record<string, string> = {
    included: "已全部纳入", disabled: "本次未开启", no_items: "本次候选输入中没有条目",
    budget_exhausted: "热榜优先占满本次条数预算", budget_truncated: "超出本次条数预算",
    source_unavailable: "来源读取失败，覆盖未知", source_limited: "来源返回数量受限",
  };
  return labels[reason] ?? "历史记录未保存原因";
}
