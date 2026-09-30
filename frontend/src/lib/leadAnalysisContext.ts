export type LeadKind = "industry" | "activity" | "emotion";

export interface LeadAnalysisContext {
  schema_version: "daily-review-lead-context.v1";
  kind: LeadKind;
  subject: { code: string | null; name: string };
  source_path: string;
  source: {
    status: string;
    source: string | null;
    trade_date: string | null;
    data_time: string | null;
    fetched_at: string | null;
    is_stale: boolean | null;
  };
  review_generated_at: string | null;
  cache_stale: boolean | null;
  facts: Record<string, number | string | null>;
  unknowns: string[];
}

export function parseLeadAnalysisContext(value: unknown): LeadAnalysisContext | undefined {
  if (!value || typeof value !== "object") return;
  const v = value as Record<string, any>;
  const nullableString = (x: unknown) => x === null || typeof x === "string";
  const nullableBoolean = (x: unknown) => x === null || typeof x === "boolean";
  if (v.schema_version !== "daily-review-lead-context.v1" || !["industry", "activity", "emotion"].includes(v.kind)
      || !v.subject || typeof v.subject.name !== "string" || !nullableString(v.subject.code)
      || typeof v.source_path !== "string" || !v.source || typeof v.source.status !== "string"
      || !["source", "trade_date", "data_time", "fetched_at"].every((key) => nullableString(v.source[key]))
      || !nullableBoolean(v.source.is_stale) || !nullableBoolean(v.cache_stale) || !nullableString(v.review_generated_at)
      || !v.facts || typeof v.facts !== "object" || Array.isArray(v.facts)
      || !Object.values(v.facts).every((x) => x === null || typeof x === "string" || (typeof x === "number" && Number.isFinite(x)))
      || !Array.isArray(v.unknowns) || !v.unknowns.every((x: unknown) => typeof x === "string")) return;
  return v as LeadAnalysisContext;
}
