export interface ThemeMember {
  stock_code: string; name?: string | null; boards: number | null; first_seal?: string | null;
  tags?: string[]; theme_source_date?: string | null; theme_first_seal?: string | null;
}
export interface ThemeCell { date: string; count: number | null; rank: number | null; highest: number | null; lower_bound: boolean }
export interface ThemeProjection {
  schema_version: "short-term-theme-research-v1"; trade_date: string; sessions: string[];
  status: "complete" | "partial" | "unavailable"; fixture?: boolean;
  attribution: "PROVIDER_EDITORIAL_NOT_COMPANY_FACT"; point_in_time_claim: "NONE"; canonical_authority: false;
  days: { date: string; available: boolean; complete: boolean; limit_up: number | null; covered: number | null;
    concentration: number | null; concentration_numerator: number | null; concentration_denominator: number | null; highest_board: number | null; broken_rate: number | null; leaders: ThemeMember[]; firstboards: ThemeMember[]; source: unknown }[];
  tree: { tag: string; first_seal: string | null; first_boards: number | null; highest: number | null; cohort_broken: number | null; cohort_limit_down: number | null; count: number | null; lower_bound: boolean; members: ThemeMember[]; previous_members: ThemeMember[];
    previous_count: number | null; continued_count: number | null; continuation_rate: number | null;
    continuation_sample_only: boolean; state: string }[];
  rotation: { tag: string; cells: ThemeCell[]; observed_active_days: number; top3_days: number; streak: number | null; streak_lower_bound: boolean }[];
  lineage: { stock_code: string; name?: string | null; appear_date: string; boards_then: number; is_current_top: boolean | null;
    series: { date: string; cum_return_pct: number | null }[]; cum_return_pct: number | null;
    peak_cum_return_pct: number | null; drawdown_from_peak_pct: number | null; status: string;
    price_unit: string | null; adjustment: string | null; adjustment_basis_id: string | null; source: unknown }[];
  multi_label_policy: string; rank_policy: string;
}
export interface ThemeResearchArchive {
  schema_version: "short-term-theme-research-archive-v1"; trade_date: string;
  status: "complete" | "partial" | "unavailable"; reason_codes: string[]; message: string;
  archive_only: true; ingestion_enabled: false; point_in_time_claim: "NONE";
  projection: ThemeProjection | null;
}
const record = (v: unknown): v is Record<string, any> => typeof v === "object" && v !== null && !Array.isArray(v);
const count = (v: unknown) => v === null || typeof v === "number" && Number.isSafeInteger(v) && v >= 0;
const finite = (v: unknown) => v === null || typeof v === "number" && Number.isFinite(v);
const ratio = (v: unknown) => v === null || typeof v === "number" && Number.isFinite(v) && v >= 0 && v <= 1;
const strings = (v: unknown): v is string[] => Array.isArray(v) && v.every(x => typeof x === "string");
const isoDate = (v: unknown): v is string => {
  if (typeof v !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(v)) return false;
  const time = Date.parse(v + "T00:00:00Z");
  return Number.isFinite(time) && new Date(time).toISOString().slice(0, 10) === v;
};
const optionalText = (v: unknown) => v === undefined || v === null || typeof v === "string";
const sealTime = (v: unknown) => v === undefined || v === null || typeof v === "string" && /^(?:[01]\d|2[0-3]):?[0-5]\d:?[0-5]\d$/.test(v);
const member = (v: unknown, day: string) => record(v) && typeof v.stock_code === "string" && /^\d{6}$/.test(v.stock_code)
  && (v.boards === null || typeof v.boards === "number" && Number.isSafeInteger(v.boards) && v.boards >= 1)
  && optionalText(v.name) && sealTime(v.first_seal) && sealTime(v.theme_first_seal)
  && (v.theme_source_date === undefined || v.theme_source_date === null || v.theme_source_date === day)
  && (v.tags === undefined || strings(v.tags) && v.tags.every(t => t.length > 0 && t.length <= 256));
const members = (v: unknown, day: string) => Array.isArray(v) && v.length <= 10000 && v.every(m => member(m, day)) && new Set(v.map(x => x.stock_code)).size === v.length;

/** Date-bound runtime validation; fail closed rather than render a stale/malformed table. */
export function isThemeResearchForDate(value: unknown, day: string): value is ThemeResearchArchive {
  if (!record(value) || value.schema_version !== "short-term-theme-research-archive-v1" || value.trade_date !== day || !isoDate(day)
    || !["complete", "partial", "unavailable"].includes(value.status) || !strings(value.reason_codes) || typeof value.message !== "string"
    || value.archive_only !== true || value.ingestion_enabled !== false || value.point_in_time_claim !== "NONE") return false;
  const p = value.projection;
  if (p === null) return value.status === "unavailable";
  if (!record(p) || p.schema_version !== "short-term-theme-research-v1" || p.trade_date !== day || p.status !== value.status
    || p.attribution !== "PROVIDER_EDITORIAL_NOT_COMPANY_FACT" || p.point_in_time_claim !== "NONE" || p.canonical_authority !== false
    || !strings(p.sessions) || p.sessions.length !== 5 || p.sessions[4] !== day
    || p.sessions.some((d, i) => !isoDate(d) || i > 0 && d <= p.sessions[i - 1])
    || typeof p.multi_label_policy !== "string" || typeof p.rank_policy !== "string") return false;
  if (!Array.isArray(p.days) || p.days.length !== 5 || !p.days.every((d, i) => record(d) && d.date === p.sessions[i]
    && typeof d.available === "boolean" && typeof d.complete === "boolean" && count(d.limit_up) && count(d.covered)
    && ratio(d.concentration) && count(d.concentration_numerator) && count(d.concentration_denominator) && count(d.highest_board) && ratio(d.broken_rate) && members(d.leaders, d.date) && members(d.firstboards, d.date)
    && (!d.complete || d.available && d.covered === d.limit_up && d.limit_up !== null))) return false;
  if (!Array.isArray(p.rotation) || !p.rotation.every(r => record(r) && typeof r.tag === "string" && r.tag.length > 0 && r.tag.length <= 256 && Array.isArray(r.cells)
    && r.cells.length === 5 && r.cells.every((c: unknown, i: number) => record(c) && c.date === p.sessions[i]
      && count(c.count) && (c.rank === null || typeof c.rank === "number" && Number.isSafeInteger(c.rank) && c.rank >= 1) && count(c.highest) && typeof c.lower_bound === "boolean")
    && count(r.observed_active_days) && r.observed_active_days <= 5 && count(r.top3_days) && r.top3_days <= 5 && count(r.streak) && (r.streak === null || r.streak <= 5) && typeof r.streak_lower_bound === "boolean")) return false;
  if (!Array.isArray(p.tree) || !p.tree.every(t => record(t) && typeof t.tag === "string" && count(t.count)
    && sealTime(t.first_seal) && count(t.first_boards) && count(t.highest) && count(t.cohort_broken) && count(t.cohort_limit_down)
    && typeof t.lower_bound === "boolean" && members(t.members, day) && members(t.previous_members, p.sessions[3]) && count(t.previous_count)
    && count(t.continued_count) && ratio(t.continuation_rate) && typeof t.continuation_sample_only === "boolean" && ["unknown", "no_current_limit_up", "observed"].includes(t.state))) return false;
  if (!Array.isArray(p.lineage) || !p.lineage.every(l => record(l) && typeof l.stock_code === "string" && /^\d{6}$/.test(l.stock_code)
    && optionalText(l.name) && p.sessions.includes(l.appear_date) && typeof l.boards_then === "number" && Number.isSafeInteger(l.boards_then) && l.boards_then >= 1 && (l.is_current_top === null || typeof l.is_current_top === "boolean")
    && finite(l.cum_return_pct) && finite(l.peak_cum_return_pct) && finite(l.drawdown_from_peak_pct) && ["complete", "unknown_or_partial"].includes(l.status)
    && (l.price_unit === null || l.price_unit === "CNY/share") && (l.adjustment === null || l.adjustment === "forward_adjusted")
    && (l.adjustment_basis_id === null || typeof l.adjustment_basis_id === "string" && /^sha256:[0-9a-f]{64}$/.test(l.adjustment_basis_id))
    && Array.isArray(l.series) && l.series.length === p.sessions.filter((d: string) => d >= l.appear_date).length
    && l.series.every((s: unknown, i: number) => record(s) && s.date === p.sessions.filter((d: string) => d >= l.appear_date)[i] && finite(s.cum_return_pct))
    && l.series[l.series.length - 1]?.cum_return_pct === l.cum_return_pct
    && (l.status !== "complete" || l.series.every((s: {cum_return_pct: number | null}) => s.cum_return_pct !== null)))) return false;
  return p.rotation.length <= 1024 && new Set(p.lineage.map(l => l.stock_code)).size === p.lineage.length && new Set(p.rotation.map(r => r.tag)).size === p.rotation.length && new Set(p.tree.map(t => t.tag)).size === p.tree.length;
}
export function themeNumber(value: number | null | undefined, percent = false): string {
  return typeof value !== "number" || !Number.isFinite(value) ? "未知" : percent ? `${value.toFixed(2)}%` : String(value);
}
