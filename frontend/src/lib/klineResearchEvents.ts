import type { EvidenceRecord, ResearchEventCalendarEvent } from "./api/types";

export interface KlineResearchEvent {
  key: string;
  id: string;
  kind: "calendar" | "evidence";
  title: string;
  date: string | null;
  rawDate: string | null;
  campaignIds: string[];
  state: string;
  source: string;
}

/** Calendar dates only: never substitute fetched_at, created_at or today. */
export function researchDate(value: unknown): string | null {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return null;
  const parsed = new Date(`${value}T00:00:00Z`);
  return Number.isFinite(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value ? value : null;
}

export function klineResearchEvents(
  code: string,
  calendar: readonly ResearchEventCalendarEvent[],
  evidence: readonly EvidenceRecord[],
): KlineResearchEvent[] {
  const records: KlineResearchEvent[] = [
    ...calendar.filter((e) => e.security_code === code && e.event_id).map((e) => ({
      key: `calendar:${e.event_id}`, id: e.event_id, kind: "calendar" as const,
      title: e.title, date: e.date_semantics === "DATE_ONLY" ? researchDate(e.event_date) : null,
      rawDate: e.event_date, campaignIds: [...new Set(e.campaign_ids.filter(Boolean))],
      state: e.state, source: e.source,
    })),
    ...evidence.filter((e) => e.subject_type === "stock" && e.subject_id === code && !e.deleted && e.id).map((e) => ({
      key: `evidence:${e.id}`, id: e.id, kind: "evidence" as const,
      title: e.source_title || e.claim, date: researchDate(e.source_date),
      rawDate: e.source_date, campaignIds: [], state: e.classification, source: e.source_title,
    })),
  ];
  return [...new Map(records.map((record) => [record.key, record])).values()]
    .sort((a, b) => (a.date ?? "9999").localeCompare(b.date ?? "9999") || a.key.localeCompare(b.key));
}

export interface PositionedResearchEvent {
  event: KlineResearchEvent;
  barDate: string | null;
  placement: "EXACT" | "NEXT_AVAILABLE_BAR" | "OUTSIDE_WINDOW" | "UNKNOWN_DATE";
}

/** A missing bar is not proof of a market holiday; no extrapolation outside the window. */
export function positionResearchEvents(events: readonly KlineResearchEvent[], barDates: readonly string[]): PositionedResearchEvent[] {
  const dates = [...new Set(barDates.filter((date) => researchDate(date)))].sort();
  return events.map((event) => {
    if (!event.date) return { event, barDate: null, placement: "UNKNOWN_DATE" };
    if (!dates.length || event.date < dates[0] || event.date > dates[dates.length - 1]) {
      return { event, barDate: null, placement: "OUTSIDE_WINDOW" };
    }
    const eventDate = event.date;
    const barDate = dates.find((date) => date >= eventDate)!;
    return { event, barDate, placement: barDate === event.date ? "EXACT" : "NEXT_AVAILABLE_BAR" };
  });
}
