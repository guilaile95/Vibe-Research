/** Retrospective research DTO. No authorization or historical PIT claim. */
export type Stats = { denominator: number; observed: number; unknown: number; coverage_ratio: number | null;
  status: string; mean_pct: number | null; median_pct: number | null; positive_count: number; negative_count: number;
  flat_count: number; positive_ratio: number | null; loss_ge_5_count: number | null; loss_ge_5_ratio: number | null;
  loss_ge_7_count: number | null; worst_pct: number | null; limit_down_count: number | null; open_premium_mean_pct: number | null };
export type ResearchMember = { stock_code: string; previous_limit_up: boolean; previous_broken: boolean;
  previous_boards: number | null; previous_last_seal: string | null; return_pct: number | null; open_premium_pct: number | null;
  limit_up: boolean | null; limit_down: boolean | null; promotion: boolean | null; result: string; price_status: string };
export type ShortlineResearch = {
  schema_version: "shortline-research.v1"; trade_date: string; previous_trade_date: string | null;
  status: "normal" | "partial" | "unavailable"; reason_codes: string[]; message: string;
  selection_mode: "CURRENT_STORED_POSTHOC"; point_in_time_claim: "NONE"; research_only: true; fixture: boolean;
  ingestion_enabled: false; schedule_enabled: false; input_requirements: string[]; limitations: string[];
  projection: null | {
    daily: { limit_up_count: number | null; broken_count: number | null; limit_down_count: number | null;
      highest_board: number | null; broken_rate: number | null; broken_denominator: number | null;
      pool_overlap_count: number | null; ladder: { boards: number; count: number }[] | null; ladder_gaps: number[] | null;
      seal_quality: Record<string, number | null>;
      price_limit_bands?: { denominator: number | null; counts: Record<string, number>; coverage: number; share_10: number | null; share_20: number | null; interpretation: string } };
    cohort: { status: string; reason_codes: string[]; rows: ResearchMember[]; groups: Record<string, Stats>;
      union_denominator?: number; previous_limit_up_denominator?: number; previous_broken_denominator?: number;
      overlap_count?: number; promotion: { previous_boards: number; denominator: number; known: number;
        promoted: number; unknown: number; rate: number | null }[];
      matrix?: { identity: string; denominator: number; outcomes: Record<string, number> }[];
      outcome_coverage?: { classified: number; unknown: number; denominator: number } };
    history: { percentile_formula: string; windows: { sessions: number; dates: string[];
      metrics: Record<string, { current: number | null; sample_count: number; expected_sessions: number;
        missing_dates: string[]; percentile: number | null; mean: number | null; status: string }> }[];
      series: { trade_date: string; [key: string]: number | string | null }[] };
    samples: { sample_kind: string; execution_model: string; windows: { sessions: number; entry_dates: string[];
      missing_entry_dates: string[]; status: string; summary: Stats; groups: Record<string, (Stats & { label: string })[]> }[] };
    structure: { market_structure: Record<string, { dates: string[]; expected: number; samples: number; mean_limit_up_count: number | null; median_limit_up_count?: number | null; source_10pct_band_share_median?: number | null; source_20pct_band_share_median?: number | null }>;
      field_drift: { kind: string; status: string; observed_dates: string[]; added: string[]; not_observed: string[]; versions?: { since: string; until: string; samples: number; signature: string; fields: string[] }[] }[];
      interpretation: string; regime_events: { status: string; reason_codes: string[]; authority?: string; note?: string;
        events?: { id: string; effective_date: string; announcement_date: string | null; title: string; note: string; source_url: string | null; created_at: string; upcoming: boolean; authority: string; raw_payload_hash: string }[] } };
  };
  evidence: { trade_date: string; kind: string; status: string; complete: boolean; source_finality: string;
    source_total: number | null; row_count: number; reason_codes: string[];
    receipts: { observation_id: string; raw_payload_hash: string; source_ids: string[]; captured_at: string;
      locally_received_at: string; committed_at: null; provider_published_at: string | null; normalizer_version: string }[] }[];
};
const object = (v: unknown): v is Record<string, unknown> => !!v && typeof v === "object" && !Array.isArray(v);
const strings = (v: unknown): v is string[] => Array.isArray(v) && v.every(x => typeof x === "string");
const number = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);
const nullable = (v: unknown): v is number | null => v === null || number(v);
const count = (v: unknown): v is number => number(v) && Number.isSafeInteger(v) && v >= 0;
const array = (v: unknown): v is unknown[] => Array.isArray(v);
const ratio = (v: unknown) => v === null || (number(v) && v >= 0 && v <= 1);
const date = (v: unknown): v is string => typeof v === "string" && /^\d{4}-\d{2}-\d{2}$/.test(v) && Number(v.slice(0, 4)) >= 1
  && Number.isFinite(Date.parse(v + "T00:00:00Z")) && new Date(v + "T00:00:00Z").toISOString().slice(0, 10) === v;
const stamp = (v: unknown) => typeof v === "string" && date(v.slice(0, 10))
  && /^\d{4}-\d{2}-\d{2}[T ](?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d(?:\.\d{1,6})?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)$/.test(v) && Number.isFinite(Date.parse(v));
// Normalize seconds to UTC while retaining all six service fractional digits.
const instantKey = (value: string) => `${new Date(value).toISOString().slice(0, 19)}.${(value.match(/\.(\d{1,6})/)?.[1] ?? "").padEnd(6, "0")}`;
const optional = (v: unknown, check: (v: unknown) => boolean) => v === undefined || check(v);
const nullableCount = (v: unknown) => v === null || count(v);
const oneOf = (v: unknown, choices: string[]) => typeof v === "string" && choices.includes(v);
function stats(v: unknown): boolean {
  if (!object(v) || ![v.denominator, v.observed, v.unknown, v.positive_count, v.negative_count, v.flat_count].every(count)) return false;
  if ((v.observed as number) + (v.unknown as number) !== v.denominator) return false;
  if (!oneOf(v.status, ["normal", "partial", "empty"]) || ![v.coverage_ratio, v.positive_ratio, v.loss_ge_5_ratio].every(ratio)
    || ![v.loss_ge_5_count, v.loss_ge_7_count, v.limit_down_count].every(nullableCount)
    || (v.positive_count as number) + (v.negative_count as number) + (v.flat_count as number) !== v.observed) return false;
  return ["coverage_ratio", "mean_pct", "median_pct", "positive_ratio", "loss_ge_5_count", "loss_ge_5_ratio", "loss_ge_7_count", "worst_pct", "limit_down_count", "open_premium_mean_pct"].every(k => nullable(v[k]));
}
export function isShortlineResearchForDate(value: unknown, day: string): value is ShortlineResearch {
  if (!date(day) || !object(value) || value.schema_version !== "shortline-research.v1" || value.trade_date !== day
    || value.selection_mode !== "CURRENT_STORED_POSTHOC" || value.point_in_time_claim !== "NONE" || value.research_only !== true
    || value.ingestion_enabled !== false || value.schedule_enabled !== false || typeof value.fixture !== "boolean"
    || typeof value.message !== "string" || !strings(value.reason_codes) || !strings(value.limitations)
    || !strings(value.input_requirements) || !array(value.evidence)) return false;
  if (!value.evidence.every(e => object(e) && date(e.trade_date) && e.trade_date <= day && typeof e.kind === "string"
    && typeof e.status === "string" && typeof e.complete === "boolean" && typeof e.source_finality === "string"
    && nullable(e.source_total) && count(e.row_count) && strings(e.reason_codes) && array(e.receipts)
    && e.receipts.every(r => object(r) && typeof r.observation_id === "string" && typeof r.raw_payload_hash === "string"
      && /^sha256:[0-9a-f]{64}$/.test(r.raw_payload_hash) && strings(r.source_ids) && r.committed_at === null
      && [r.captured_at, r.locally_received_at].every(stamp)
      && instantKey(r.locally_received_at as string) >= instantKey(r.captured_at as string)
      && typeof r.normalizer_version === "string"))) return false;
  if (value.status === "unavailable") return value.projection === null && value.evidence.length === 0;
  if (!["normal", "partial"].includes(String(value.status)) || !date(value.previous_trade_date) || value.previous_trade_date >= day || !object(value.projection)) return false;
  const p = value.projection;
  if (!object(p.daily) || !object(p.daily.seal_quality) || !Object.values(p.daily.seal_quality).every(nullable)
    || !["limit_up_count", "broken_count", "limit_down_count", "highest_board", "broken_rate", "broken_denominator", "pool_overlap_count"].every(k => nullable((p.daily as Record<string, unknown>)[k]))) return false;
  if (!(p.daily.ladder_gaps === null || (array(p.daily.ladder_gaps) && p.daily.ladder_gaps.length <= 10000 && p.daily.ladder_gaps.every(count)))) return false;
  if (!object(p.cohort) || !array(p.cohort.rows) || p.cohort.rows.length > 10000 || !object(p.cohort.groups)
    || !Object.values(p.cohort.groups).every(stats) || !array(p.cohort.promotion) || typeof p.cohort.status !== "string") return false;
  const seen = new Set<string>();
  for (const r of p.cohort.rows) {
    if (!object(r) || typeof r.stock_code !== "string" || !/^\d{6}$/.test(r.stock_code) || seen.has(r.stock_code)
      || typeof r.previous_limit_up !== "boolean" || typeof r.previous_broken !== "boolean"
      || !nullableCount(r.previous_boards) || !nullable(r.return_pct) || !nullable(r.open_premium_pct)
      || typeof r.result !== "string" || typeof r.price_status !== "string") return false;
    seen.add(r.stock_code);
  }
  if (p.cohort.status !== "unavailable" && p.cohort.union_denominator !== seen.size) return false;
  if (!p.cohort.promotion.every(r => object(r) && [r.previous_boards, r.denominator, r.known, r.promoted, r.unknown].every(count) && nullable(r.rate))) return false;
  if (!object(p.history) || !array(p.history.windows) || !p.history.windows.every(w => object(w) && count(w.sessions) && strings(w.dates)
    && w.dates.every(d => d < day) && object(w.metrics) && Object.values(w.metrics).every(m => object(m)
      && nullable(m.current) && count(m.sample_count) && count(m.expected_sessions) && strings(m.missing_dates) && nullable(m.percentile) && nullable(m.mean)))) return false;
  if (!object(p.samples) || !array(p.samples.windows) || !p.samples.windows.every(w => object(w) && count(w.sessions)
    && strings(w.entry_dates) && w.entry_dates.every(d => d < day) && strings(w.missing_entry_dates) && stats(w.summary)
    && object(w.groups) && Object.values(w.groups).every(g => array(g) && g.every(s => object(s) && typeof s.label === "string" && stats(s))))) return false;
  if (!object(p.structure) || !object(p.structure.market_structure) || !Object.values(p.structure.market_structure).every(w => object(w)
    && strings(w.dates) && count(w.expected) && count(w.samples) && nullable(w.mean_limit_up_count))
    || !array(p.structure.field_drift) || !p.structure.field_drift.every(d => object(d) && typeof d.kind === "string" && typeof d.status === "string"
      && strings(d.observed_dates) && strings(d.added) && strings(d.not_observed)) || typeof p.structure.interpretation !== "string") return false;
  const bands = p.daily.price_limit_bands;
  if (bands !== undefined && (!object(bands) || !nullableCount(bands.denominator) || !count(bands.coverage)
    || !nullable(bands.share_10) || !nullable(bands.share_20) || !object(bands.counts) || !Object.values(bands.counts).every(count))) return false;
  if (!p.structure.field_drift.every(d => object(d) && (d.versions === undefined || (array(d.versions)
    && d.versions.length <= 100 && d.versions.every(v => object(v) && typeof v.since === "string" && typeof v.until === "string"
      && v.since <= v.until && v.until <= day && count(v.samples) && typeof v.signature === "string" && strings(v.fields) && v.fields.length <= 512))))) return false;
  // Every value consumed by JSX or numeric formatting is checked before render.
  if (!["limit_up_count", "broken_count", "limit_down_count", "highest_board", "broken_denominator", "pool_overlap_count"].every(k => nullableCount((p.daily as Record<string, unknown>)[k]))
    || !ratio(p.daily.broken_rate) || !(p.daily.ladder === null || (array(p.daily.ladder) && p.daily.ladder.every(r => object(r) && count(r.boards) && count(r.count))))) return false;
  if (!strings(p.cohort.reason_codes) || !oneOf(p.cohort.status, ["normal", "partial", "unavailable"])
    || !["union_denominator", "previous_limit_up_denominator", "previous_broken_denominator", "overlap_count"].every(k => optional((p.cohort as Record<string, unknown>)[k], count))) return false;
  if (!optional(p.cohort.outcome_coverage, v => object(v) && [v.classified, v.unknown, v.denominator].every(count)
    && (v.classified as number) + (v.unknown as number) === v.denominator)) return false;
  if (!p.cohort.rows.every(r => object(r) && [r.limit_up, r.limit_down, r.promotion].every(v => v === null || typeof v === "boolean")
    && (r.previous_last_seal === null || typeof r.previous_last_seal === "string")
    && oneOf(r.result, ["unknown", "limit_up", "limit_down", "deep_loss", "positive", "flat", "negative"]))) return false;
  if (!p.cohort.promotion.every(r => object(r) && ratio(r.rate) && (r.known as number) + (r.unknown as number) === r.denominator
    && (r.promoted as number) <= (r.known as number))) return false;
  if (!p.history.windows.every(w => object(w) && (w.dates as unknown[]).every(date)
    && Object.values(w.metrics as Record<string, unknown>).every(m => object(m) && ratio(m.percentile)
      && oneOf(m.status, ["normal", "insufficient_samples"]) && (m.missing_dates as unknown[]).every(date)))) return false;
  if (!p.samples.windows.every(w => object(w) && oneOf(w.status, ["normal", "partial"])
    && (w.entry_dates as unknown[]).every(date) && (w.missing_entry_dates as unknown[]).every(date))) return false;
  if (!Object.values(p.structure.market_structure).every(w => object(w) && (w.dates as unknown[]).every(date)
    && optional(w.median_limit_up_count, nullable) && optional(w.source_10pct_band_share_median, ratio)
    && optional(w.source_20pct_band_share_median, ratio))) return false;
  if (!p.structure.field_drift.every(d => object(d) && (d.observed_dates as unknown[]).every(date)
    && (d.versions === undefined || (d.versions as Record<string, unknown>[]).every(v => date(v.since) && date(v.until))))) return false;
  if (!object(p.structure.regime_events) || !oneOf(p.structure.regime_events.status, ["normal", "empty", "unavailable"])
    || !strings(p.structure.regime_events.reason_codes)) return false;
  if (bands !== undefined && (!object(bands) || !ratio(bands.share_10) || !ratio(bands.share_20))) return false;
  const events = (p.structure.regime_events as Record<string, unknown> | undefined)?.events;
  if (events !== undefined && (!array(events) || events.length > 512 || !events.every(e => object(e)
    && typeof e.id === "string" && typeof e.effective_date === "string" && typeof e.title === "string"
    && date(e.effective_date) && (e.announcement_date === null || date(e.announcement_date)) && stamp(e.created_at)
    && typeof e.raw_payload_hash === "string" && /^sha256:[0-9a-f]{64}$/.test(e.raw_payload_hash)
    && typeof e.note === "string" && typeof e.upcoming === "boolean" && e.authority === "USER_AUTHORED_UNVERIFIED"
    && (e.source_url === null || (typeof e.source_url === "string" && /^https?:\/\//.test(e.source_url)))))) return false;
  return true;
}
