export interface SealQualityRow {
  stock_code: string;
  lbc: number;
  zt_stat: string | null;
  first_seal: string | null;
  last_seal: string | null;
  broken_times: number | null;
  field_issues: Record<string, string[]>;
}

export interface SealQualityArchive {
  schema_version: string;
  trade_date: string;
  status: "normal" | "partial" | "unavailable";
  reason_codes: string[];
  message: string;
  archive_only: true;
  ingestion_enabled: false;
  selection: { selection_mode: string; selection_basis: string; point_in_time_claim: "NONE"; provider_revision_claim: "NONE" } | null;
  archive_identity: { publication_id: string; source_observation_id: string; raw_payload_hash: string; captured_at: string } | null;
  projection: {
    status: "normal" | "partial" | "unavailable";
    source_trade_date: string | null;
    sample_count: number | null;
    excluded_universe_count: number | null;
    finality: "NOT_ESTABLISHED";
    canonical_authority: false;
    metrics: Record<string, number | null>;
    coverage: Record<string, { known_count: number; unknown_count: number | null; complete: boolean }>;
    rows: SealQualityRow[];
    limitations: string[];
  } | null;
}

export function sealQualityNumber(value: unknown, ratio = false): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  return ratio ? `${(value * 100).toFixed(1)}%` : String(value);
}

export function sealQualityTime(value: unknown): string {
  return typeof value === "string" && /^\d{6}$/.test(value)
    ? `${value.slice(0, 2)}:${value.slice(2, 4)}:${value.slice(4)}` : "—";
}

/** Reject wrong-date or malformed readback before the component renders it. */
export function isSealQualityArchiveForDate(value: unknown, date: string): value is SealQualityArchive {
  if (!value || typeof value !== "object") return false;
  const item = value as SealQualityArchive;
  if (item.schema_version !== "short-term-seal-quality-archive-v0.1" || item.trade_date !== date
    || item.archive_only !== true || item.ingestion_enabled !== false || typeof item.message !== "string"
    || !["normal", "partial", "unavailable"].includes(item.status)
    || !Array.isArray(item.reason_codes) || !item.reason_codes.every((reason) => typeof reason === "string")) return false;
  if (item.projection === null) return item.archive_identity === null && item.selection === null;
  const p = item.projection;
  if (!p || p.source_trade_date !== date || p.finality !== "NOT_ESTABLISHED" || p.canonical_authority !== false
    || !p.metrics || !p.coverage || !Array.isArray(p.rows) || !Array.isArray(p.limitations)
    || item.selection?.selection_mode !== "local_latest" || item.selection.point_in_time_claim !== "NONE"
    || item.selection.provider_revision_claim !== "NONE" || !item.archive_identity) return false;
  const numberOrNull = (n: unknown) => n === null || (typeof n === "number" && Number.isFinite(n));
  if (![item.archive_identity.publication_id, item.archive_identity.source_observation_id,
    item.archive_identity.raw_payload_hash, item.archive_identity.captured_at].every((x) => typeof x === "string" && x.length > 0)) return false;
  if (!numberOrNull(p.sample_count) || !numberOrNull(p.excluded_universe_count)
    || !Object.values(p.metrics).every(numberOrNull)) return false;
  for (const metric of ["never_broken_ratio", "ever_opened_ratio", "average_broken_times", "first_seal_by_0935_count", "late_seal_count"]) {
    if (!numberOrNull(p.metrics[metric])) return false;
  }
  for (const field of ["first_seal", "last_seal", "broken_times"]) {
    const c = p.coverage[field];
    if (!c || !Number.isInteger(c.known_count) || c.known_count < 0 || !numberOrNull(c.unknown_count) || typeof c.complete !== "boolean") return false;
  }
  return p.rows.every((row) => row && /^\d{6}$/.test(row.stock_code) && Number.isInteger(row.lbc)
    && row.lbc > 0 && numberOrNull(row.broken_times)
    && (row.zt_stat === null || typeof row.zt_stat === "string")
    && row.field_issues && typeof row.field_issues === "object");
}
