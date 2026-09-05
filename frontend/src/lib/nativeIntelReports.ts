import { get, request } from "./api";

export type ReportMode = "CURRENT" | "DAILY" | "INCREMENTAL";
export interface IntelReportItem {
  item_id: number; title: string; url: string; source_id: string; source_name: string;
  source_type: string; rank: number | null; published_at: string | null; observed_at: string;
  highlight?: boolean; new_kind?: "NEW_ON_LIST" | "NEWLY_OBSERVED" | null; change_kind?: string | null;
}
export interface IntelReport {
  status: string; mode: ReportMode; total: number; generated_at: string; data_basis: string;
  observation_boundary: number; cursor_advanced: boolean;
  baseline: { generated_at: string; observation_boundary: number } | null;
  sections: { name: string; count: number; items: IntelReportItem[] }[];
}
export interface TimelineBehavior { fetch: boolean; report: boolean; mode: ReportMode; once: boolean }
export interface TimelineSegment extends TimelineBehavior { name: string; start: string; end: string; days: number[] }
export interface TimelineConfig {
  enabled: boolean; preset: string;
  custom: { default: TimelineBehavior; segments: TimelineSegment[] };
}
export interface IntelTimeline extends TimelineBehavior {
  preset: string; enabled: boolean; current_segment: string; segment_start: string;
  segment_end: string; next_transition: string; active: boolean; config: TimelineConfig;
  last_scheduled_report: { generated_at: string; mode: ReportMode; item_count: number; status: string; segment: string } | null;
}
export interface IntelAnalysis {
  status: string; topic: string; topics: string[]; data_basis: string;
  window: { start: string; end: string };
  trend: { date: string; mention_count: number; source_count: number; platform_count: number; change: number | null; coverage: string }[];
  rank_timeline: { source_id: string; source_name: string; item_id: number; title: string; points: { observed_at: string; rank: number }[] }[];
  lifecycle: { status: string; reason: string; topic_type: string; input_counts: number[] };
  viral: { detected: boolean | null; reason: string; current_count: number; baseline_count: number; growth: number | null };
  prediction: { direction: string; strength: number | null; reason: string; input_counts: number[] };
  platforms: { source_id: string; name: string; source_type: string; group: string; item_count: number; topic_hit_count: number;
    new_item_count: number; ranked_visibility: number; mean_observed_rank: number | null; activity_change: number | null }[];
  platform_note: string;
  cooccurrence: { pair: string[]; count: number; sample_items: IntelReportItem[] }[];
}
export interface IntelSimilar { item: IntelReportItem; similar_items: { item: IntelReportItem; similarity_score: number }[] }

export const reportApi = {
  report: (params: URLSearchParams, generate = false, signal?: AbortSignal) =>
    request<IntelReport>(`/native-intel/report?${params}`, generate ? "POST" : "GET", undefined, { unwrapData: false, signal }),
  timeline: (signal?: AbortSignal) => get<IntelTimeline>("/native-intel/timeline", { unwrapData: false, signal }),
  saveTimeline: (cfg: TimelineConfig) => request<IntelTimeline>("/native-intel/timeline", "PUT", cfg, { unwrapData: false }),
  analysis: (topic: string, days: number, basis: string, signal?: AbortSignal) =>
    get<IntelAnalysis>(`/native-intel/analytics?${new URLSearchParams({ topic, days: String(days), data_basis: basis })}`, { unwrapData: false, signal }),
  similar: (id: number, signal?: AbortSignal) => get<IntelSimilar>(`/native-intel/analytics/similar?item_id=${id}`, { unwrapData: false, signal }),
  newItems: (scope: string, signal?: AbortSignal) => get<{ status: string; items: IntelReportItem[] }>(
    `/native-intel/new-items?scope=${scope}`, { unwrapData: false, signal }),
};
