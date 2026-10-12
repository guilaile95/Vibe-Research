/** Descriptive membership evidence only; no promotion/performance fields. */
export type CohortEvidence = {
  trade_date: string; source_ids: string[]; fetched_at: string; snapshot_at: string;
  stored_at: string; envelope_sha256: string; row_count: number;
};
export type CohortMember = { stock_code: string; previous_source_code: string; current_source_code: string | null;
  previous_boards: number; current_boards: number | null; present_today: boolean };
export type CohortIdentity = {
  schema_version: "archived-cohort-identity.v0.1"; trade_date: string; previous_trade_date: string | null;
  status: "normal" | "unavailable"; reason_codes: string[]; message: string;
  selection_mode: "CURRENT_STORED_POSTHOC"; point_in_time_claim: "NONE"; research_only: true;
  projection: { rows: CohortMember[] } | null;
  evidence: { previous: CohortEvidence; current: CohortEvidence } | null;
};
export function isCohortIdentityForDate(value: unknown, day: string): value is CohortIdentity {
  if (!value || typeof value !== "object") return false;
  const v = value as CohortIdentity;
  if (v.schema_version !== "archived-cohort-identity.v0.1" || v.trade_date !== day
    || v.selection_mode !== "CURRENT_STORED_POSTHOC" || v.point_in_time_claim !== "NONE" || v.research_only !== true
    || typeof v.message !== "string" || !Array.isArray(v.reason_codes) || !v.reason_codes.every(x => typeof x === "string")) return false;
  if (v.status === "unavailable") return v.projection === null && v.evidence === null;
  if (v.status !== "normal" || !v.previous_trade_date || v.previous_trade_date >= day || !v.projection || !Array.isArray(v.projection.rows) || !v.evidence) return false;
  for (const [e, d] of [[v.evidence.previous, v.previous_trade_date], [v.evidence.current, day]] as const) {
    if (!e || e.trade_date !== d || !Number.isSafeInteger(e.row_count) || e.row_count < 1 || !/^[0-9a-f]{64}$/.test(e.envelope_sha256)
      || !Array.isArray(e.source_ids) || !e.source_ids.length || !e.source_ids.every(x => typeof x === "string" && x.length > 0)
      || ![e.fetched_at, e.snapshot_at, e.stored_at].every(x => typeof x === "string" && Number.isFinite(Date.parse(x)))) return false;
  }
  if (v.projection.rows.length !== v.evidence.previous.row_count) return false;
  const seen = new Set<string>();
  for (const row of v.projection.rows) {
    if (!row || !/^\d{6}$/.test(row.stock_code) || seen.has(row.stock_code)
      || typeof row.previous_source_code !== "string" || !Number.isSafeInteger(row.previous_boards) || row.previous_boards < 1
      || typeof row.present_today !== "boolean") return false;
    seen.add(row.stock_code);
    if (row.present_today ? (typeof row.current_source_code !== "string" || !Number.isSafeInteger(row.current_boards) || row.current_boards! < 1)
      : (row.current_source_code !== null || row.current_boards !== null)) return false;
  }
  return true;
}
