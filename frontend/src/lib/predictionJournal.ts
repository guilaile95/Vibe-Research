export type PredictionForecast = {
  id: string; question: string; subject: string; probability: number; deadline: string;
  evidence_context: string; evidence_kind: "USER_ASSERTION" | "SOURCE_REFERENCE"; outcome_not_known: true;
  benchmark_probability: number | null; benchmark_context: string | null;
};
export type PredictionResolution = {
  revision: number; recorded_at: string; resolution: {
    expected_revision: number; outcome: "TRUE" | "FALSE" | "INDETERMINATE";
    available_at: string; evidence: string; evidence_kind: "USER_ASSERTION" | "SOURCE_REFERENCE"; correction_reason: string;
  };
};
export type PredictionRecord = {
  schema_version: string; forecast: PredictionForecast; locked_at: string; revision: number;
  outcome: "UNRESOLVED" | PredictionResolution["resolution"]["outcome"]; history: PredictionResolution[];
};
export type PredictionJournalData = {
  schema_version: string; as_of: string; records: PredictionRecord[]; summary: {
    total: number; resolved_binary: number; unresolved: number; indeterminate: number;
    brier: number | null; benchmark_count: number; benchmark_brier: number | null; matched_forecast_brier: number | null;
    sample_caution: boolean; display_caution_minimum: number;
    bins: { lower: number; upper: number; upper_inclusive: boolean; count: number; mean_probability: number | null; observed_frequency: number | null; sample_caution: boolean }[];
  };
};
function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("预测响应不可核对");
  return value as Record<string, unknown>;
}
function requireValue(valid: boolean): asserts valid { if (!valid) throw new Error("预测响应不可核对；请重新读取"); }
const timestamp = (v: unknown) => typeof v === "string" && /(?:Z|[+-]\d\d:\d\d)$/.test(v) && Number.isFinite(Date.parse(v));
const unit = (v: unknown) => typeof v === "number" && Number.isFinite(v) && v >= 0 && v <= 1;
const count = (v: unknown) => typeof v === "number" && Number.isSafeInteger(v) && v >= 0;
const text = (v: unknown) => typeof v === "string" && v.trim().length > 0;
const evidence = (v: unknown) => v === "USER_ASSERTION" || v === "SOURCE_REFERENCE";
export function parsePredictionJournal(value: unknown): PredictionJournalData {
  const root = object(value), summary = object(root.summary);
  requireValue(root.schema_version === "manual-prediction.v1" && timestamp(root.as_of) && Array.isArray(root.records));
  const ids = new Set<string>();
  for (const raw of root.records) {
    const r = object(raw), f = object(r.forecast);
    requireValue(r.schema_version === root.schema_version && text(f.id) && !ids.has(f.id as string)); ids.add(f.id as string);
    requireValue(text(f.question) && text(f.subject) && unit(f.probability) && timestamp(f.deadline) && timestamp(r.locked_at));
    requireValue(Date.parse(r.locked_at as string) < Date.parse(f.deadline as string) && Date.parse(r.locked_at as string) <= Date.parse(root.as_of as string));
    requireValue(text(f.evidence_context) && evidence(f.evidence_kind) && f.outcome_not_known === true);
    requireValue((f.benchmark_probability === null && f.benchmark_context === null) || (unit(f.benchmark_probability) && text(f.benchmark_context)));
    requireValue(Array.isArray(r.history) && count(r.revision) && r.revision === r.history.length);
    let last = "UNRESOLVED", previous = Date.parse(r.locked_at as string);
    for (let i = 0; i < r.history.length; i++) {
      const event = object(r.history[i]), resolution = object(event.resolution);
      requireValue(event.revision === i + 1 && resolution.expected_revision === i && timestamp(event.recorded_at) && timestamp(resolution.available_at));
      const recorded = Date.parse(event.recorded_at as string), available = Date.parse(resolution.available_at as string);
      requireValue(recorded >= previous && recorded <= Date.parse(root.as_of as string) && available <= recorded && available >= Date.parse(f.deadline as string)); previous = recorded;
      requireValue(["TRUE", "FALSE", "INDETERMINATE"].includes(resolution.outcome as string) && text(resolution.evidence) && evidence(resolution.evidence_kind) && text(resolution.correction_reason));
      last = resolution.outcome as string;
    }
    requireValue(r.outcome === last);
  }
  for (const key of ["total", "resolved_binary", "unresolved", "indeterminate", "benchmark_count", "display_caution_minimum"]) requireValue(count(summary[key]));
  requireValue(summary.total === root.records.length && Number(summary.resolved_binary) + Number(summary.unresolved) + Number(summary.indeterminate) === summary.total && Number(summary.benchmark_count) <= Number(summary.resolved_binary));
  for (const key of ["brier", "benchmark_brier", "matched_forecast_brier"]) requireValue(summary[key] === null || unit(summary[key]));
  requireValue((summary.resolved_binary === 0) === (summary.brier === null) && (summary.benchmark_count === 0) === (summary.benchmark_brier === null) && (summary.benchmark_count === 0) === (summary.matched_forecast_brier === null));
  requireValue(typeof summary.sample_caution === "boolean" && Array.isArray(summary.bins) && summary.bins.length === 10);
  const records = root.records as PredictionRecord[];
  const binary = records.filter(r => r.outcome === "TRUE" || r.outcome === "FALSE");
  const matched = binary.filter(r => r.forecast.benchmark_probability !== null);
  const meanScore = (items: PredictionRecord[], benchmark = false) => items.length ? items.reduce((sum, r) => sum + ((benchmark ? r.forecast.benchmark_probability! : r.forecast.probability) - Number(r.outcome === "TRUE")) ** 2, 0) / items.length : null;
  const equalMetric = (a: unknown, b: number | null) => b === null ? a === null : typeof a === "number" && Math.abs(a - b) < 1e-12;
  requireValue(summary.resolved_binary === binary.length && summary.unresolved === records.filter(r => r.outcome === "UNRESOLVED").length && summary.indeterminate === records.filter(r => r.outcome === "INDETERMINATE").length && summary.benchmark_count === matched.length);
  requireValue(equalMetric(summary.brier, meanScore(binary)) && equalMetric(summary.benchmark_brier, meanScore(matched, true)) && equalMetric(summary.matched_forecast_brier, meanScore(matched)));
  requireValue(summary.display_caution_minimum === 20 && summary.sample_caution === (binary.length < 20));
  let total = 0;
  summary.bins.forEach((raw, index) => {
    const b = object(raw);
    requireValue(b.lower === index / 10 && b.upper === (index + 1) / 10 && b.upper_inclusive === (index === 9) && count(b.count) && typeof b.sample_caution === "boolean");
    requireValue(b.count === 0 ? b.mean_probability === null && b.observed_frequency === null : unit(b.mean_probability) && unit(b.observed_frequency));
    const members = binary.filter(r => Math.min(Math.floor(r.forecast.probability * 10), 9) === index);
    requireValue(b.count === members.length && b.sample_caution === (members.length < 20));
    requireValue(equalMetric(b.mean_probability, members.length ? members.reduce((sum, r) => sum + r.forecast.probability, 0) / members.length : null));
    requireValue(equalMetric(b.observed_frequency, members.length ? members.filter(r => r.outcome === "TRUE").length / members.length : null));
    total += b.count as number;
  });
  requireValue(total === summary.resolved_binary);
  return value as PredictionJournalData;
}
/** Invalidation happens synchronously on filter changes and unmount, before effects. */
export class PredictionGeneration {
  private value = 0;
  next() { return ++this.value; }
  current(token: number) { return token === this.value; }
  token() { return this.value; }
}
export const predictionPercent = (v: number | null) => v === null ? "不可用" : `${(v * 100).toFixed(1)}%`;

/** Verify requested content, not just the existence of a matching identity. */
export function verifyPredictionWrite(data: PredictionJournalData, identity: string, body: Record<string, unknown>, created: boolean) {
  const record = data.records.find(r => r.forecast.id === identity);
  requireValue(!!record);
  const persisted = created ? record.forecast as unknown as Record<string, unknown> : record.history.find(event => event.revision === Number(body.expected_revision) + 1)?.resolution as unknown as Record<string, unknown> | undefined;
  requireValue(!!persisted);
  for (const [key, value] of Object.entries(body)) {
    if (key === "deadline" || key === "available_at") requireValue(Date.parse(String(persisted[key])) === Date.parse(String(value)));
    else requireValue(persisted[key] === (typeof value === "string" ? value.trim() : value));
  }
}
