export type Direction = "up" | "down" | "flat";
export const metricDefinitions = {
  limit_up_count: { unit: "家", epsilon: 5 }, failed_board_rate: { unit: "0–1 比率", epsilon: 0.05 },
  highest_board: { unit: "板", epsilon: 0.5 }, promotion_1to2: { unit: "0–1 比率", epsilon: 0.05 },
  money_effect_median: { unit: "百分点", epsilon: 0.5 }, deep_loss_count: { unit: "家", epsilon: 5 },
  theme_concentration: { unit: "0–1 比率", epsilon: 0.05 }, market_limit_down: { unit: "家", epsilon: 5 },
} as const;
export type Metric = keyof typeof metricDefinitions;
export interface VerificationCondition { metric: Metric; direction: Direction; reason: string }
export interface VerificationSummary {
  total: number; decided: number; hit: number; unknown: number; rate: number | null;
  coverage: number | null; baseline_covered: number; expected_rate: number | null; edge: number | null;
}
export interface FinalVerificationEvidence {
  values: Partial<Record<Metric, number | null>>; source_ids: string[];
  fetched_at: string; snapshot_at: string; stored_at: string;
}
export interface ResearchVerificationEvidence {
  schema_version: "verification-research-observation.v1"; trade_date: string;
  basis: "CURRENT_STORED_POSTHOC"; point_in_time_claim: "SERVER_READ_OBSERVATION_ONLY";
  snapshot_observed_at: string; values: Partial<Record<Metric, number | null>>;
  source_receipts: unknown[]; source_receipts_sha256: string; definitions: Record<string, string>;
}
export type VerificationEvidence = FinalVerificationEvidence | ResearchVerificationEvidence;
export function isResearchEvidence(value: VerificationEvidence): value is ResearchVerificationEvidence { return "schema_version" in value; }
export interface VerificationItem extends VerificationCondition {
  target_date: string | null; actual: Direction | null;
  prior_evidence: VerificationEvidence | null; current_evidence: VerificationEvidence | null;
  written_at: string; prior_value: number | null; current_value: number | null;
  state: string; verified: boolean | null;
  baseline: { rate: number | null; samples: number; possible_pairs: number; coverage: number | null;
    from: string; through: string; as_of: string; minimum_samples: number };
}
export interface VerificationView {
  schema_version: "next-day-verification.v0.1" | "next-day-verification.v0.2"; research_only: true; generated_at: string;
  trade_date: string; state: "OPEN" | "SEALED" | "CALENDAR_UNKNOWN" | "NOT_YET_OPEN";
  next_trade_date: string | null; seals_at: string | null; revision: number;
  items: VerificationItem[];
  metrics: { key: Metric; label: string; unit: string; epsilon: number }[];
  summary: VerificationSummary;
  history: { from: string | null; through: string; summary: VerificationSummary };
  limitations: string[];
}
export const directionLabels: Record<Direction, string> = { up: "上升", down: "下降", flat: "持平" };
export const boundaryLabels = {
  OPEN: "可记录，下一交易日 09:15（上海时间）封存",
  SEALED: "已封存，不能修改或删除",
  CALENDAR_UNKNOWN: "交易日历未知或日期不是支持的交易日，禁止写入",
  NOT_YET_OPEN: "尚未收盘，收盘后才可记录",
};
export function resultLabel(item: Pick<VerificationItem, "state" | "verified">): string {
  if (item.state === "VERIFIED") return item.verified === true ? "成立" : item.verified === false ? "不成立" : "待核验";
  if (item.state === "PENDING_CLOSE") return "待下一交易日收盘";
  if (item.state === "NO_EVIDENCE") return "待核验：缺少合格事前值或收盘事实";
  return "待核验：日历或事前时间不可确认";
}
export function formatMetric(metric: Metric, value: number | null): string {
  return value === null ? "未知" : metricDefinitions[metric].unit === "0–1 比率" ? `${(value * 100).toFixed(1)}%` : `${value} ${metricDefinitions[metric].unit}`;
}
export function percent(value: number | null): string {
  return value === null ? "—" : `${(value * 100).toFixed(1)}%`;
}
export function conditionDraft(view: VerificationView): VerificationCondition[] {
  return view.items.map(({ metric, direction, reason }) => ({ metric, direction, reason }));
}

/** Input dates are ISO, regardless of browser locale or the user's timezone. */
export function verificationDate(candidate?: string | null, now = new Date()): string {
  if (candidate && /^\d{4}-\d{2}-\d{2}$/.test(candidate)) {
    const parsed = new Date(`${candidate}T00:00:00Z`);
    if (Number.isFinite(parsed.getTime()) && parsed.toISOString().slice(0, 10) === candidate) return candidate;
  }
  const parts = new Intl.DateTimeFormat("en-US", { timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit" }).formatToParts(now);
  const part = (type: string) => parts.find((entry) => entry.type === type)!.value;
  return `${part("year")}-${part("month")}-${part("day")}`;
}

export function ownsVerificationDate(view: VerificationView | null, day: string): view is VerificationView {
  return view !== null && view.trade_date === day;
}


const record = (value: unknown): value is Record<string, unknown> => value !== null && typeof value === "object" && !Array.isArray(value);
const count = (value: unknown): value is number => Number.isSafeInteger(value) && (value as number) >= 0;
const finite = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value);
const ratio = (value: unknown): value is number => finite(value) && value >= 0 && value <= 1;
const nullableRatio = (value: unknown) => value === null || ratio(value);
const isoDay = (value: unknown): value is string => typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value)
  && Number.isFinite(Date.parse(`${value}T00:00:00Z`)) && new Date(`${value}T00:00:00Z`).toISOString().slice(0, 10) === value;
const instant = (value: unknown): value is string => typeof value === "string"
  && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)$/.test(value)
  && isoDay(value.slice(0, 10)) && value.slice(11, 13) < "24" && value.slice(14, 16) < "60" && value.slice(17, 19) < "60"
  && Number.isFinite(Date.parse(value));
const strings = (value: unknown): value is string[] => Array.isArray(value) && value.every(x => typeof x === "string");
const metricValue = (metric: Metric, value: unknown) => value === null || (metricDefinitions[metric].unit === "百分点" ? finite(value) && value >= -100 && value <= 10000 : metricDefinitions[metric].unit === "0–1 比率" ? ratio(value) : count(value));
const direction = (value: unknown): value is Direction => value === "up" || value === "down" || value === "flat";
const metric = (value: unknown): value is Metric => typeof value === "string" && Object.prototype.hasOwnProperty.call(metricDefinitions, value);
// Canonical UTC strings preserve the service's microseconds, unlike Date.parse.
const stamp = (value: string) => {
  const [seconds, fraction = ""] = value.replace(/(?:Z|\+00:00)$/, "").split(".");
  return `${seconds}.${fraction.padEnd(6, "0")}`;
};
const closeAt = (day: string) => stamp(`${day}T07:00:00Z`);
const sameNumber = (a: unknown, b: number | null) => b === null ? a === null : finite(a) && Math.abs(a - b) < 1e-9;

function validSummary(value: unknown): value is VerificationSummary {
  if (!record(value)) return false;
  const { total, decided, hit, unknown, baseline_covered, rate, coverage, expected_rate, edge } = value;
  return count(total) && count(decided) && count(hit) && count(unknown) && count(baseline_covered)
    && decided <= total && hit <= decided && unknown === total - decided && baseline_covered <= decided
    && sameNumber(rate, decided ? hit / decided : null) && sameNumber(coverage, total ? decided / total : null)
    && (baseline_covered ? ratio(expected_rate) && finite(edge) && edge >= -1 && edge <= 1 : expected_rate === null && edge === null);
}

function validEvidence(value: unknown, day: string | null, asOf: string): value is VerificationEvidence | null {
  if (value === null) return true;
  if (record(value) && value.schema_version === "verification-research-observation.v1") {
    return value.trade_date === day && value.basis === "CURRENT_STORED_POSTHOC" && value.point_in_time_claim === "SERVER_READ_OBSERVATION_ONLY"
      && instant(value.snapshot_observed_at) && stamp(value.snapshot_observed_at) <= stamp(asOf)
      && record(value.values) && Object.keys(metricDefinitions).filter(k => k !== "limit_up_count" && k !== "failed_board_rate").every(k => metricValue(k as Metric, (value.values as Record<string, unknown>)[k]))
      && Array.isArray(value.source_receipts) && value.source_receipts.length > 0
      && typeof value.source_receipts_sha256 === "string" && /^[a-f0-9]{64}$/.test(value.source_receipts_sha256) && record(value.definitions);
  }
  if (!day || !record(value) || !record(value.values) || !strings(value.source_ids)
    || !value.source_ids.length || value.source_ids.some(x => !x.trim())
    || !instant(value.fetched_at) || !instant(value.snapshot_at) || !instant(value.stored_at)) return false;
  return metricValue("limit_up_count", value.values.limit_up_count) && metricValue("failed_board_rate", value.values.failed_board_rate)
    && closeAt(day) <= stamp(value.fetched_at) && stamp(value.fetched_at) <= stamp(value.snapshot_at)
    && stamp(value.snapshot_at) <= stamp(value.stored_at) && stamp(value.stored_at) <= stamp(asOf);
}

/** Validate the existing service contract before committing any response to UI state.
 * This checks readback consistency; it never derives a new result or changes authority.
 */
export function isVerificationViewForDate(value: unknown, day: string): value is VerificationView {
  if (!record(value) || !isoDay(day) || value.trade_date !== day || !["next-day-verification.v0.1", "next-day-verification.v0.2"].includes(String(value.schema_version))
    || value.research_only !== true || !instant(value.generated_at) || !count(value.revision)
    || !strings(value.limitations) || !Array.isArray(value.metrics) || value.metrics.length !== (value.schema_version === "next-day-verification.v0.1" ? 2 : 8)
    || !Array.isArray(value.items) || value.items.length > (value.schema_version === "next-day-verification.v0.1" ? 2 : 8) || !validSummary(value.summary)
    || !record(value.history) || value.history.through !== day || !validSummary(value.history.summary)
    || !(value.history.from === null || (isoDay(value.history.from) && value.history.from <= day))) return false;
  const known = value.state === "OPEN" || value.state === "SEALED" || value.state === "NOT_YET_OPEN";
  if (known) {
    if (!isoDay(value.next_trade_date) || value.next_trade_date <= day || !instant(value.seals_at)
      || stamp(value.seals_at) !== stamp(`${value.next_trade_date}T01:15:00Z`)) return false;
    const now = stamp(value.generated_at), seal = stamp(value.seals_at);
    if (value.state !== (now >= seal ? "SEALED" : now >= closeAt(day) ? "OPEN" : "NOT_YET_OPEN")) return false;
  } else if (value.state !== "CALENDAR_UNKNOWN" || value.next_trade_date !== null || value.seals_at !== null) return false;
  const metricKeys = new Set<unknown>();
  for (const m of value.metrics) {
    if (!record(m) || !metric(m.key) || metricKeys.has(m.key) || typeof m.label !== "string" || !m.label.trim()
      || m.unit !== metricDefinitions[m.key].unit || m.epsilon !== metricDefinitions[m.key].epsilon) return false;
    metricKeys.add(m.key);
  }
  const seen = new Set<Metric>();
  for (const item of value.items) {
    if (!record(item) || !metric(item.metric) || seen.has(item.metric) || !direction(item.direction)
      || typeof item.reason !== "string" || [...item.reason].length > 200 || !instant(item.written_at)
      || stamp(item.written_at) < closeAt(day) || stamp(item.written_at) > stamp(value.generated_at)
      || !metricValue(item.metric, item.prior_value) || !metricValue(item.metric, item.current_value)
      || item.target_date !== value.next_trade_date || !validEvidence(item.prior_evidence, day, item.written_at)
      || !validEvidence(item.current_evidence, value.next_trade_date as string | null, value.generated_at)) return false;
    if (item.prior_value !== (item.prior_evidence?.values[item.metric] ?? null)
      || item.current_value !== (item.current_evidence?.values[item.metric] ?? null)) return false;
    const legacy = item.metric === "limit_up_count" || item.metric === "failed_board_rate";
    for (const evidence of [item.prior_evidence, item.current_evidence]) {
      if (evidence && isResearchEvidence(evidence) === legacy) return false;
    }
    if (item.prior_evidence && isResearchEvidence(item.prior_evidence) && stamp(item.prior_evidence.snapshot_observed_at) !== stamp(item.written_at)) return false;
    const b = item.baseline;
    if (!record(b) || !count(b.samples) || !count(b.possible_pairs) || b.samples > b.possible_pairs || b.possible_pairs > 60
      || b.minimum_samples !== 12 || !nullableRatio(b.rate) || (b.rate === null) !== (b.samples < 12)
      || !sameNumber(b.coverage, b.possible_pairs ? b.samples / b.possible_pairs : null)
      || !isoDay(b.from) || b.from > day || b.through !== day || !instant(b.as_of)
      || stamp(b.as_of) !== stamp(item.written_at)) return false;
    if (!legacy && (b.samples !== 0 || b.possible_pairs !== 0)) return false;
    const priorValid = known && stamp(item.written_at) < stamp(value.seals_at as string);
    const mature = known && stamp(value.generated_at) >= closeAt(value.next_trade_date as string);
    const before = item.prior_value as number | null, after = item.current_value as number | null;
    const difference = before === null || after === null ? null : after - before;
    const expectedActual = !priorValid || !mature || difference === null ? null
      : Math.abs(difference) <= metricDefinitions[item.metric].epsilon + 1e-9 ? "flat" : difference > 0 ? "up" : "down";
    const expectedState = !known ? "CALENDAR_UNKNOWN" : !priorValid ? "INVALID_PRIOR_TIME" : !mature ? "PENDING_CLOSE" : expectedActual === null ? "NO_EVIDENCE" : "VERIFIED";
    if (item.state !== expectedState || item.actual !== expectedActual) return false;
    if (item.verified !== (expectedActual === null ? null : expectedActual === item.direction)) return false;
    seen.add(item.metric);
  }
  const items = value.items as VerificationItem[];
  const covered = items.filter(x => x.verified !== null && x.baseline.rate !== null);
  const expectedRate = covered.length ? covered.reduce((sum, x) => sum + x.baseline.rate!, 0) / covered.length : null;
  return value.summary.baseline_covered === covered.length
    && sameNumber(value.summary.expected_rate, expectedRate)
    && sameNumber(value.summary.edge, expectedRate === null ? null : covered.filter(x => x.verified === true).length / covered.length - expectedRate)
    && (value.revision !== 0 || items.length === 0) && value.summary.total === items.length
    && value.summary.decided === items.filter(x => x.verified !== null).length
    && value.summary.hit === items.filter(x => x.verified === true).length;
}
