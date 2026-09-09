import type {
  ResearchEventCalendarEvent,
  ResearchEventType,
} from "./api/types";

export const RESEARCH_EVENT_TYPE_LABELS: Record<ResearchEventType, string> = {
  PERIODIC_REPORT: "定期报告",
  LOCKUP_EXPIRY: "限售解禁",
  DIVIDEND_BONUS: "分红送转",
  ANNOUNCEMENT: "公司公告",
};

export const RESEARCH_EVENT_STATE_LABELS: Record<string, string> = {
  EXPECTED: "预计披露",
  CONFIRMED: "已观察",
  DELAYED_SIGNAL: "预约日已过，尚未见披露",
  NO_RECORD: "无记录",
  UNAVAILABLE: "不可用",
  ERROR: "读取失败",
  UPCOMING: "即将发生",
  HISTORY: "历史记录",
  OBSERVED: "已观察（非 upcoming）",
  UNKNOWN: "未知",
};

export type ResearchEventGroupKey = "RECENT" | "TODAY" | "NEXT_7_DAYS" | "NEXT_30_DAYS" | "LATER" | "UNKNOWN";

export interface ResearchEventGroup {
  key: ResearchEventGroupKey;
  label: string;
  events: ResearchEventCalendarEvent[];
}

export const RESEARCH_EVENT_GROUP_LABELS: Record<ResearchEventGroupKey, string> = {
  RECENT: "最近发生",
  TODAY: "今天",
  NEXT_7_DAYS: "未来 7 天",
  NEXT_30_DAYS: "未来 30 天",
  LATER: "后续",
  UNKNOWN: "日期未知",
};

export function researchEventTypeLabel(type: ResearchEventType): string {
  return RESEARCH_EVENT_TYPE_LABELS[type] ?? type;
}

export function researchEventStateLabel(state: string): string {
  return RESEARCH_EVENT_STATE_LABELS[state] ?? state;
}

export function formatResearchEventDate(value: string | null): string {
  if (!value) return "日期未知";
  return value;
}

function parseDate(value: string | null | undefined): Date | null {
  if (!value) return null;
  const parsed = new Date(`${value}T00:00:00`);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function startOfDay(value: Date): Date {
  return new Date(value.getFullYear(), value.getMonth(), value.getDate());
}

export function researchEventGroupKey(eventDate: string | null, asOf: string): ResearchEventGroupKey {
  const event = parseDate(eventDate);
  const today = parseDate(asOf);
  if (!event || !today) return "UNKNOWN";
  const days = Math.round((event.getTime() - today.getTime()) / 86_400_000);
  if (days < 0) return "RECENT";
  if (days === 0) return "TODAY";
  if (days <= 7) return "NEXT_7_DAYS";
  if (days <= 30) return "NEXT_30_DAYS";
  return "LATER";
}

export function groupResearchEvents(
  events: readonly ResearchEventCalendarEvent[],
  asOf: string,
): ResearchEventGroup[] {
  const grouped = new Map<ResearchEventGroupKey, ResearchEventCalendarEvent[]>();
  for (const event of events) {
    const key = researchEventGroupKey(event.event_date, asOf);
    const bucket = grouped.get(key) ?? [];
    bucket.push(event);
    grouped.set(key, bucket);
  }
  const order: ResearchEventGroupKey[] = ["RECENT", "TODAY", "NEXT_7_DAYS", "NEXT_30_DAYS", "LATER", "UNKNOWN"];
  return order
    .filter((key) => grouped.has(key))
    .map((key) => ({
      key,
      label: RESEARCH_EVENT_GROUP_LABELS[key],
      events: [...(grouped.get(key) ?? [])].sort((a, b) =>
        (a.event_date ?? "9999-12-31").localeCompare(b.event_date ?? "9999-12-31")
        || a.security_code.localeCompare(b.security_code)
        || a.event_type.localeCompare(b.event_type)
        || a.event_id.localeCompare(b.event_id),
      ),
    }));
}

export interface ResearchEventFilters {
  securityCode: string;
  eventType: ResearchEventType | "ALL";
  state: string | "ALL";
}

export function filterResearchEvents(
  events: readonly ResearchEventCalendarEvent[],
  filters: ResearchEventFilters,
): ResearchEventCalendarEvent[] {
  return events.filter((event) =>
    (!filters.securityCode || event.security_code === filters.securityCode)
    && (filters.eventType === "ALL" || event.event_type === filters.eventType)
    && (filters.state === "ALL" || event.state === filters.state),
  );
}

export function eventNavigationHref(event: ResearchEventCalendarEvent): string {
  const campaignId = event.campaign_ids[0];
  return campaignId
    ? `/decision-inbox#campaign-${encodeURIComponent(campaignId)}`
    : `/stock-data?code=${encodeURIComponent(event.security_code)}`;
}

/** A response may only replace state if it belongs to the latest request. */
export function shouldApplyResearchEventResponse(
  responseGeneration: number,
  latestGeneration: number,
): boolean {
  return responseGeneration === latestGeneration;
}

export function dateInputToday(): string {
  const today = startOfDay(new Date());
  return `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
}
