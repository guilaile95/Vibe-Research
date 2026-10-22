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

/** API/cache payloads are runtime data; never let malformed provenance break results. */
export function isCapturedAnalysisSources(value: unknown): value is import("./api/types").NativeIntelAnalysisSources {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const source = value as Record<string, unknown>;
  if (source.version !== 1 || source.status !== "CAPTURED"
    || !["PREPARED", "RESPONSE_RECEIVED", "UNKNOWN"].includes(String(source.submission_status))
    || !Array.isArray(source.items) || !source.coverage || typeof source.coverage !== "object") return false;
  const sections = ["hotlist", "rss", "standalone"];
  const nullableString = (v: unknown) => v === null || typeof v === "string";
  if (!source.items.every((entry: unknown) => {
    if (!entry || typeof entry !== "object") return false;
    const item = entry as Record<string, unknown>;
    return typeof item.id === "string" && !!item.id && sections.includes(String(item.section))
      && typeof item.title === "string" && nullableString(item.source_id) && nullableString(item.source_name)
      && nullableString(item.published_at) && nullableString(item.original_url);
  })) return false;
  const count = (v: unknown) => typeof v === "number" && Number.isSafeInteger(v) && v >= 0;
  const coverage = source.coverage as Record<string, unknown>;
  return sections.every((section) => {
    const raw = coverage[section];
    if (!raw || typeof raw !== "object") return false;
    const entry = raw as Record<string, unknown>;
    return typeof entry.enabled === "boolean" && count(entry.included)
      && (entry.available === null || count(entry.available))
      && (entry.omitted === null || count(entry.omitted)) && typeof entry.reason === "string"
      && entry.included === (source.items as Array<Record<string, unknown>>).filter((item) => item.section === section).length;
  });
}
