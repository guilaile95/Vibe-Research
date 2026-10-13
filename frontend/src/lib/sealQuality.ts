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

const object = (value: unknown): value is Record<string, unknown> => value !== null && typeof value === "object" && !Array.isArray(value);
const count = (value: unknown): value is number => Number.isSafeInteger(value) && (value as number) >= 0;
const number = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value) && value >= 0;
const strings = (value: unknown): value is string[] => Array.isArray(value) && value.every(x => typeof x === "string");
const fields = ["first_seal", "last_seal", "broken_times"] as const;
const metrics = ["never_broken_count", "never_broken_ratio", "reopened_count", "ever_opened_ratio", "average_broken_times", "first_seal_by_0935_count", "late_seal_count"];
const keysAre = (value: Record<string, unknown>, keys: readonly string[]) => Object.keys(value).length === keys.length && keys.every(key => Object.prototype.hasOwnProperty.call(value, key));
const time = (value: unknown): value is string => typeof value === "string" && /^\d{6}$/.test(value)
  && value.slice(2, 4) < "60" && value.slice(4) < "60"
  && ((value >= "092500" && value <= "113000") || (value >= "130000" && value <= "150000"));

/** Reject malformed readback before Object.entries or row rendering touches it.
 * Existing partial/unavailable observations remain valid; no missing value is filled.
 */
export function isSealQualityArchiveForDate(value: unknown, date: string): value is SealQualityArchive {
  if (!object(value)) return false;
  const item = value;
  if (item.schema_version !== "short-term-seal-quality-archive-v0.1" || item.trade_date !== date
    || item.archive_only !== true || item.ingestion_enabled !== false || typeof item.message !== "string"
    || !["normal", "partial", "unavailable"].includes(item.status as string) || !strings(item.reason_codes)) return false;
  if (item.projection === null) return item.status === "unavailable" && item.reason_codes.length > 0 && item.archive_identity === null && item.selection === null;
  const p = item.projection;
  if (!object(p) || p.source_trade_date !== date || p.finality !== "NOT_ESTABLISHED" || p.canonical_authority !== false
    || p.status !== item.status || !object(p.metrics) || !keysAre(p.metrics, metrics)
    || !object(p.coverage) || !keysAre(p.coverage, fields) || !Array.isArray(p.rows) || !strings(p.limitations)
    || !object(item.selection) || item.selection.selection_mode !== "local_latest"
    || typeof item.selection.selection_basis !== "string" || !item.selection.selection_basis
    || item.selection.point_in_time_claim !== "NONE" || item.selection.provider_revision_claim !== "NONE"
    || !object(item.archive_identity)) return false;
  const identity = item.archive_identity;
  if (![identity.publication_id, identity.source_observation_id, identity.raw_payload_hash, identity.captured_at].every(x => typeof x === "string" && x.trim())
    || !/^sha256:[0-9a-f]{64}$/.test(identity.raw_payload_hash as string)
    || !/^\d{4}-\d{2}-\d{2}T(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d(?:\.\d{1,6})?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)$/.test(identity.captured_at as string)
    || !Number.isFinite(Date.parse(`${(identity.captured_at as string).slice(0, 10)}T00:00:00Z`))
    || new Date(`${(identity.captured_at as string).slice(0, 10)}T00:00:00Z`).toISOString().slice(0, 10) !== (identity.captured_at as string).slice(0, 10)
    || !Number.isFinite(Date.parse(identity.captured_at as string))) return false;
  const n = p.sample_count;
  if (!(n === null || count(n)) || !(p.excluded_universe_count === null || count(p.excluded_universe_count))
    || p.rows.length !== (n ?? 0)) return false;
  const seen = new Set<string>();
  for (const row of p.rows) {
    if (!object(row) || typeof row.stock_code !== "string" || !/^\d{6}$/.test(row.stock_code) || seen.has(row.stock_code)
      || !count(row.lbc) || row.lbc < 1 || !(row.broken_times === null || (count(row.broken_times) && row.broken_times <= 2147483647))
      || !(row.zt_stat === null || typeof row.zt_stat === "string") || !(row.first_seal === null || time(row.first_seal))
      || !(row.last_seal === null || time(row.last_seal)) || (typeof row.first_seal === "string" && typeof row.last_seal === "string" && row.first_seal > row.last_seal)
      || !object(row.field_issues) || Object.entries(row.field_issues).some(([key, issues]) => !fields.includes(key as typeof fields[number]) || !strings(issues))) return false;
    seen.add(row.stock_code);
  }
  for (const field of fields) {
    const c = p.coverage[field];
    if (!object(c) || !count(c.known_count) || typeof c.complete !== "boolean") return false;
    if (n === null || n === 0) {
      if (c.known_count !== 0 || c.unknown_count !== null || c.complete !== false) return false;
    } else if (!count(c.unknown_count) || c.known_count + c.unknown_count !== n || c.complete !== (c.known_count === n)
      || c.known_count !== p.rows.filter(row => row[field] !== null).length) return false;
  }
  for (const [key, value] of Object.entries(p.metrics)) {
    if (value !== null && (!number(value) || (key.endsWith("_ratio") ? value > 1 : key.endsWith("_count") ? !count(value) || n === null || value > n : value > 2147483647))) return false;
    const field = key === "first_seal_by_0935_count" ? "first_seal" : key === "late_seal_count" ? "last_seal" : "broken_times";
    if ((value !== null) !== (p.coverage[field] as { complete: boolean }).complete) return false;
  }
  const available = Object.values(p.metrics).filter(value => value !== null).length;
  return item.status === (available === metrics.length ? "normal" : available ? "partial" : "unavailable")
    && (item.status === "normal" ? item.reason_codes.length === 0 : item.reason_codes.length > 0);
}
