export interface Observation {
  slot: string; observed_at: string; cutoff_at: string; price_basis: string; status: string;
  cohort: { expected: number; samples: number; coverage: number | null; median_pct: number | null; positive: number | null; strong_ge_3pct: number | null };
  rows: { symbol: string; provider_at: string; source_id: string; pct: number; sources: string[] }[];
  missing: Record<string, string>;
}
export interface ObservationTask { id: string; kind: string; status: string; attempts: number; reason: string | null; acknowledged: boolean; output?: unknown }
export interface ObservationView {
  schema_version: "observation-workflows.v1"; trade_date: string; generated_at: string;
  calendar_state: string; collector_enabled: false; scheduler_enabled: false; external_notifications_enabled: false; research_only: true;
  synthetic?: boolean; fixture_label?: string;
  slots: { slot: string; state: string; cutoff_at: string; reason: string | null; observation: Observation | null; attempts: unknown[] }[];
  events: { id: string; symbol: string; kind: string; provider_at: string; observed_at: string; move_pct: number | null; sources: string[] }[];
  event_coverage: { total: number; returned: number; has_more: boolean };
  due_coverage: { eligible_plans: number; evaluated_plans: number; has_more: boolean; maximum: number; order: string };
  tasks: ObservationTask[]; schedule: Record<string, string>;
  due: { id: string; set_date: string; target_date: string | null; due_at: string | null; state: string; summary: { decided: number; total: number; unknown: number } }[];
}
export const observationLabels: Record<string, string> = {
  SAVED: "已取样", AVAILABLE: "窗口开放，尚未采集", UPCOMING: "未到时点", MISSING: "漏采，不允许补造",
  RETRIES_EXHAUSTED: "有限重试已用尽", CALENDAR_UNKNOWN: "日历未知，已停止", MARKET_CLOSED: "休市",
  COMPLETE: "已完成", PARTIAL: "部分完成 / 缺资料", FAILED: "失败", DUE_UNRESOLVED: "已到期，待核验", RECONCILED: "已对账",
};
export const taskLabels: Record<string, string> = { premarket: "盘前事实简报", close_digest: "收盘摘要", watch_changes: "自选公告追赶", verification_due: "条件到期对账" };
const object = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);
const count = (v: unknown): v is number => Number.isSafeInteger(v) && (v as number) >= 0;
const finite = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);
const strings = (v: unknown): v is string[] => Array.isArray(v) && v.every(x => typeof x === "string");
const instant = (v: unknown): v is string => typeof v === "string" && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)$/.test(v)
  && dayValue(v.slice(0, 10)) && v.slice(11, 13) < "24" && v.slice(14, 16) < "60" && v.slice(17, 19) < "60" && Number.isFinite(Date.parse(v));
const dayValue = (v: unknown): v is string => typeof v === "string" && /^\d{4}-\d{2}-\d{2}$/.test(v) && Number(v.slice(0, 4)) >= 1 && Number.isFinite(Date.parse(`${v}T00:00:00Z`)) && new Date(`${v}T00:00:00Z`).toISOString().slice(0, 10) === v;
// Preserve service microseconds; Date.parse alone truncates these boundaries.
const utcStamp = (v: string) => {
  const [seconds, fraction = ""] = v.replace(/(?:Z|\+00:00)$/, "").split(".");
  return `${seconds}.${fraction.padEnd(6, "0")}`;
};
const plusSeconds = (v: string, seconds: number) => `${new Date(Date.parse(v.slice(0, 19)+"Z")+seconds*1000).toISOString().slice(0, 19)}.${utcStamp(v).split(".")[1]}`;
function validObservation(v: unknown, slot: string, day: string): boolean {
  if (!object(v) || v.trade_date !== day || v.slot !== slot || v.status !== "SAVED" || !instant(v.observed_at) || !instant(v.cutoff_at)
    || !object(v.cohort) || !Array.isArray(v.rows) || !object(v.missing) || Object.keys(v.missing).length !== 0) return false;
  const start = Date.parse(`${day}T${slot}:00+08:00`), end = start + (slot === "09:25" ? 4 : 8)*60_000;
  if (!(utcStamp(v.observed_at) >= utcStamp(new Date(start).toISOString()) && utcStamp(v.observed_at) < utcStamp(new Date(end).toISOString()) && utcStamp(v.cutoff_at) === utcStamp(new Date(end).toISOString()))) return false;
  const c = v.cohort;
  if (!count(c.expected) || !c.expected || !count(c.samples) || c.samples !== c.expected || c.samples !== v.rows.length || c.coverage !== 1
    || !finite(c.median_pct) || !count(c.positive) || c.positive > c.samples || !count(c.strong_ge_3pct) || c.strong_ge_3pct > c.samples) return false;
  const identities = new Set();
  return v.rows.every(row => {
    if (!object(row) || typeof row.symbol !== "string" || !/^(sh|sz|bj)\d{6}$/.test(row.symbol) || identities.has(row.symbol)
      || !instant(row.provider_at) || utcStamp(row.provider_at) > utcStamp(v.observed_at as string) || utcStamp(v.observed_at as string) > plusSeconds(row.provider_at, 60)
      || new Date(Date.parse(row.provider_at)+8*3600_000).toISOString().slice(0, 10) !== day
      || !finite(row.pct) || Math.abs(row.pct) > 1_000_000 || typeof row.source_id !== "string" || !row.source_id || !strings(row.sources) || !row.sources.length) return false;
    identities.add(row.symbol); return true;
  });
}
export function validObservationTask(t: unknown, day?: string, kind?: string): t is ObservationTask {
  return object(t) && typeof t.id === "string" && typeof t.kind === "string" && Object.prototype.hasOwnProperty.call(taskLabels, t.kind)
    && (!day || t.trade_date === day && t.id === `${day}:${t.kind}`) && (!kind || t.kind === kind)
    && ["COMPLETE", "PARTIAL", "FAILED"].includes(String(t.status)) && count(t.attempts) && t.attempts > 0 && t.attempts <= 3
    && typeof t.acknowledged === "boolean" && t.external_delivery === "DISABLED" && instant(t.started_at) && instant(t.finished_at)
    && (t.reason === null || typeof t.reason === "string") && (t.status === "FAILED" || object(t.output) && t.output.status === t.status);
}
export function validObservationView(v: unknown, day?: string): v is ObservationView {
  if (!object(v) || v.schema_version !== "observation-workflows.v1" || !dayValue(v.trade_date) || (day && v.trade_date !== day)
    || !instant(v.generated_at) || !["TRADING_DAY", "MARKET_CLOSED", "CALENDAR_UNKNOWN"].includes(String(v.calendar_state)) || v.research_only !== true || v.collector_enabled !== false
    || v.scheduler_enabled !== false || v.external_notifications_enabled !== false
    || !Array.isArray(v.slots) || v.slots.length !== 6 || !Array.isArray(v.events) || !Array.isArray(v.tasks) || !Array.isArray(v.due) || !object(v.schedule)
    || Object.keys(v.schedule).length !== 4 || !Object.entries(v.schedule).every(([key, time]) => Object.prototype.hasOwnProperty.call(taskLabels, key) && typeof time === "string")) return false;
  if (v.synthetic !== undefined && typeof v.synthetic !== "boolean") return false;
  if (v.synthetic === true ? typeof v.fixture_label !== "string" || !v.fixture_label || v.fixture_label.length > 200 : v.fixture_label !== undefined) return false;
  const eventsCoverage = v.event_coverage, dueCoverage = v.due_coverage;
  if (!object(eventsCoverage) || !count(eventsCoverage.total) || eventsCoverage.returned !== v.events.length || v.events.length > 500
    || eventsCoverage.total < v.events.length || eventsCoverage.has_more !== (eventsCoverage.total > v.events.length)
    || !object(dueCoverage) || !count(dueCoverage.eligible_plans) || dueCoverage.evaluated_plans !== v.due.length || v.due.length > 20
    || dueCoverage.eligible_plans < v.due.length || dueCoverage.has_more !== (dueCoverage.eligible_plans > 20)
    || dueCoverage.maximum !== 20 || dueCoverage.order !== "latest_set_date_first") return false;
  const slots = ["09:25", "09:35", "10:00", "11:30", "14:00", "15:00"];
  const states = ["SAVED", "AVAILABLE", "UPCOMING", "MISSING", "RETRIES_EXHAUSTED", "CALENDAR_UNKNOWN", "MARKET_CLOSED"];
  const tasks = new Set(); const events = new Set();
  return v.slots.every((slot, i) => object(slot) && slot.slot === slots[i] && typeof slot.state === "string" && states.includes(slot.state)
    && instant(slot.cutoff_at) && (slot.reason === null || typeof slot.reason === "string") && Array.isArray(slot.attempts) && slot.attempts.length <= 3
    && (slot.state === "SAVED" ? validObservation(slot.observation, slots[i], v.trade_date as string) : slot.observation === null))
    && v.events.every(e => {
      if (!object(e) || typeof e.id !== "string" || events.has(e.id) || typeof e.symbol !== "string" || !/^(sh|sz|bj)\d{6}$/.test(e.symbol) || !["RAPID_UP", "RAPID_DOWN", "SEALED", "OPENED"].includes(String(e.kind))
        || !instant(e.provider_at) || !instant(e.observed_at) || (e.move_pct !== null && !finite(e.move_pct)) || !strings(e.sources)) return false;
      events.add(e.id); return true;
    })
    && v.tasks.every(t => {
      if (!validObservationTask(t, v.trade_date as string) || tasks.has(t.kind)) return false;
      tasks.add(t.kind); return true;
    })
    && v.due.every(d => object(d) && typeof d.id === "string" && dayValue(d.set_date) && (d.target_date === null || dayValue(d.target_date))
      && (d.due_at === null || instant(d.due_at)) && ["DUE_UNRESOLVED", "RECONCILED", "CALENDAR_UNKNOWN"].includes(String(d.state)) && object(d.summary)
      && count(d.summary.total) && count(d.summary.decided) && count(d.summary.unknown) && d.summary.decided + d.summary.unknown === d.summary.total);
}
