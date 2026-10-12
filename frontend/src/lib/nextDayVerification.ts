export type Direction = "up" | "down" | "flat";
export type Metric = "limit_up_count" | "failed_board_rate";
export interface VerificationCondition { metric: Metric; direction: Direction; reason: string }
export interface VerificationSummary {
  total: number; decided: number; hit: number; unknown: number; rate: number | null;
  coverage: number | null; baseline_covered: number; expected_rate: number | null; edge: number | null;
}
export interface VerificationItem extends VerificationCondition {
  written_at: string; prior_value: number | null; current_value: number | null;
  state: string; verified: boolean | null;
  baseline: { rate: number | null; samples: number; possible_pairs: number; coverage: number | null };
}
export interface VerificationView {
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
  return value === null ? "未知" : metric === "failed_board_rate" ? `${(value * 100).toFixed(1)}%` : `${value} 家`;
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
