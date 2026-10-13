import type { Quote } from "./api/types";

// Snapshot/coverage concepts adapted from simonlin1212/Vibe-Research (MIT; root LICENSE),
// d643728e79b955dfdcdcd8b0dd362bd7c90c35c8, desktop/src/verticals/finance/lib/quoteSnapshot.ts.
// Local provider time is data_time, NOT upstream fetched_at or client completion time.
export interface QuoteSnapshotState {
  available: boolean;
  quoteTime: number | null;
  stale: boolean;
  timeIssue: "unknown" | "future" | null;
}

/** Strict provider instant: timezone and full calendar date required; no Date.parse rollover. */
export function providerQuoteTime(value: unknown): number | null {
  if (typeof value !== "string") return null;
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d{1,3})?(Z|[+-](\d{2}):(\d{2}))$/.exec(value);
  if (!match) return null;
  const [, year, month, day, hour, minute, second, zone, offsetHour, offsetMinute] = match;
  const y = Number(year), m = Number(month), d = Number(day);
  const leap = y % 4 === 0 && (y % 100 !== 0 || y % 400 === 0);
  const days = [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  if (m < 1 || m > 12 || d < 1 || d > days[m - 1] || Number(hour) > 23 || Number(minute) > 59 || Number(second) > 59) return null;
  if (zone !== "Z" && (Number(offsetHour) > 14 || Number(offsetMinute) > 59 || (Number(offsetHour) === 14 && Number(offsetMinute) !== 0))) return null;
  const time = Date.parse(value);
  return Number.isFinite(time) ? time : null;
}

export function validQuoteRows(data: Record<string, Quote>, codes: readonly string[]): Record<string, Quote> {
  return Object.fromEntries(codes.flatMap(code => {
    const row = data?.[code];
    return row && typeof row.price === "number" && Number.isFinite(row.price) && row.price > 0
      ? [[code, row]] : [];
  }));
}

export function quoteSnapshotStates(quotes: Record<string, Quote>, codes: readonly string[], failedCodes: readonly string[], now: number): Record<string, QuoteSnapshotState> {
  return Object.fromEntries(codes.map(code => {
    const q = quotes[code];
    const quoteTime = providerQuoteTime(q?.data_time);
    return [code, {
      available: !!q,
      quoteTime,
      stale: !!q && failedCodes.includes(code),
      timeIssue: quoteTime === null ? "unknown" : quoteTime > now ? "future" : null,
    }];
  }));
}

/** Minimum displayed provider time, unknown if any displayed price has unknown/future time. */
export function quoteSnapshotTime(states: Record<string, QuoteSnapshotState>): number | null {
  const displayed = Object.values(states).filter(state => state.available);
  return displayed.length && displayed.every(state => state.quoteTime !== null && !state.timeIssue)
    ? Math.min(...displayed.map(state => state.quoteTime!)) : null;
}

export function formatQuoteTime(time: number): string {
  return new Date(time).toLocaleString("zh-CN", { timeZone: "Asia/Shanghai", hour12: false }) + " 北京时间";
}

export function quoteSnapshotLabel(state: QuoteSnapshotState | undefined): string {
  if (!state?.available) return "行情未获取";
  const time = state.quoteTime === null ? "行情时间未知" : `行情时间 ${formatQuoteTime(state.quoteTime)}`;
  return `${state.stale ? "旧快照 · 刷新失败 · " : "快照 · "}${time}${state.timeIssue === "future" ? " · 时间晚于本机时钟，时效未知" : ""}`;
}
