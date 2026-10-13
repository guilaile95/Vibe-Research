/** Inspection of configured archives only; never prediction or provider authority. */
export const evidenceFeatures = ["seal_quality", "cohort_identity", "next_day_verification"] as const;
export type EvidenceFeature = typeof evidenceFeatures[number];
export type EvidenceStatus = "not_configured" | "missing" | "ineligible" | "busy" | "ready";
export interface EvidenceReadiness {
  schema_version: "evidence-readiness.v0.1"; trade_date: string; generated_at: string;
  read_only: true; ingestion_enabled: false;
  features: { feature: EvidenceFeature; status: EvidenceStatus; reason_codes: string[];
    required_dates: string[]; requirements: string; next_step: string }[];
  journal: { state: "CALENDAR_UNKNOWN" | "OPEN" | "SEALED" | "NOT_YET_OPEN";
    next_trade_date: string | null; seals_at: string | null;
    prior_metric_available: { limit_up_count: boolean; failed_board_rate: boolean };
    verification_claim: "NONE" };
  limitations: string[];
}
const object = (v: unknown): v is Record<string, unknown> => !!v && typeof v === "object" && !Array.isArray(v);
const keys = (v: Record<string, unknown>, expected: string[]) => Object.keys(v).sort().join("|") === [...expected].sort().join("|");
const date = (v: unknown): v is string => typeof v === "string" && /^\d{4}-\d{2}-\d{2}$/.test(v)
  && Number.isFinite(Date.parse(v + "T00:00:00Z")) && new Date(v + "T00:00:00Z").toISOString().slice(0, 10) === v;
const stamp = (v: unknown): v is string => typeof v === "string" && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)$/.test(v)
  && date(v.slice(0, 10)) && Number(v.slice(11, 13)) < 24 && Number(v.slice(14, 16)) < 60 && Number(v.slice(17, 19)) < 60 && Number.isFinite(Date.parse(v));
const text = (v: unknown): v is string => typeof v === "string" && v.trim().length > 0 && v.length <= 1200;
export function isEvidenceReadinessForDate(value: unknown, day: string): value is EvidenceReadiness {
  if (!date(day) || !object(value) || !keys(value, ["schema_version", "trade_date", "generated_at", "read_only", "ingestion_enabled", "features", "journal", "limitations"])
    || value.schema_version !== "evidence-readiness.v0.1" || value.trade_date !== day || !stamp(value.generated_at)
    || value.read_only !== true || value.ingestion_enabled !== false || !Array.isArray(value.features) || value.features.length !== 3
    || !Array.isArray(value.limitations) || value.limitations.length < 1 || value.limitations.length > 8 || !value.limitations.every(text)) return false;
  const j = value.journal;
  if (!object(j) || !keys(j, ["state", "next_trade_date", "seals_at", "prior_metric_available", "verification_claim"])
    || !["CALENDAR_UNKNOWN", "OPEN", "SEALED", "NOT_YET_OPEN"].includes(j.state as string) || j.verification_claim !== "NONE"
    || !object(j.prior_metric_available) || !keys(j.prior_metric_available, ["limit_up_count", "failed_board_rate"])
    || typeof j.prior_metric_available.limit_up_count !== "boolean" || typeof j.prior_metric_available.failed_board_rate !== "boolean") return false;
  if (j.state === "CALENDAR_UNKNOWN") {
    if (j.next_trade_date !== null || j.seals_at !== null || Object.values(j.prior_metric_available).some(Boolean)) return false;
  } else if (!date(j.next_trade_date) || j.next_trade_date <= day || !stamp(j.seals_at)
    || !new RegExp("^" + j.next_trade_date + "T01:15:00(?:\\.0{1,6})?(?:Z|\\+00:00)$").test(j.seals_at)) return false;
  if (j.state !== "CALENDAR_UNKNOWN") {
    const now = Date.parse(value.generated_at);
    const expected = now >= Date.parse(j.seals_at as string) ? "SEALED" : now >= Date.parse(day + "T07:00:00Z") ? "OPEN" : "NOT_YET_OPEN";
    if (j.state !== expected) return false;
  }
  for (let index = 0; index < evidenceFeatures.length; index++) {
    const row = value.features[index];
    if (!object(row) || !keys(row, ["feature", "status", "reason_codes", "required_dates", "requirements", "next_step"])
      || row.feature !== evidenceFeatures[index] || !["not_configured", "missing", "ineligible", "busy", "ready"].includes(row.status as string)
      || !Array.isArray(row.reason_codes) || row.reason_codes.length > 16
      || !row.reason_codes.every(x => typeof x === "string" && /^[A-Z][A-Z0-9_]{0,79}$/.test(x))
      || new Set(row.reason_codes).size !== row.reason_codes.length
      || (row.status === "ready" ? row.reason_codes.length !== 0 : row.reason_codes.length === 0)
      || !Array.isArray(row.required_dates) || row.required_dates.length < 1 || row.required_dates.length > 2
      || !row.required_dates.every(date) || new Set(row.required_dates).size !== row.required_dates.length
      || !text(row.requirements) || !text(row.next_step)) return false;
    const days = row.required_dates as string[];
    if (index === 0 && (days.length !== 1 || days[0] !== day)) return false;
    if (index === 1 && (days[days.length - 1] !== day || (days.length === 2 && days[0] >= day)
      || (row.status === "ready" && days.length !== 2))) return false;
    if (index === 2 && (days[0] !== day || (j.next_trade_date === null ? days.length !== 1 : days.length !== 2 || days[1] !== j.next_trade_date)
      || (row.status === "ready") !== Object.values(j.prior_metric_available).some(Boolean))) return false;
    if (row.status === "not_configured" && index !== 0) return false;
  }
  return true;
}
