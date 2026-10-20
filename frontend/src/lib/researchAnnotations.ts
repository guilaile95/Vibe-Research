import type { KlineBar } from "./api/types";
import type { KlineIndicatorOverlayPoint } from "./klineIndicatorOverlay";

export type AnnotationContext = {
  code: string; bar_period: "day"; snapshot_id: string; token: string; expires_at: string;
  points: [string, string, string, string, string, string | null][];
};
export type ResearchAnnotation = {
  id: string; code: string; bar_period: string; snapshot_id: string; date: string;
  text: string; price: number | null; link_kind: "evidence" | "thesis" | null;
  link_id: string | null; link_revision: string | null; created_at: string;
};
// Metadata belongs to the exact returned array, not a new persisted browser authority.
const contexts = new WeakMap<KlineBar[], AnnotationContext>();
export function registerAnnotationContext(bars: KlineBar[], context: AnnotationContext | null | undefined): KlineBar[] {
  if (context) contexts.set(bars, context);
  return bars;
}
export function annotationContext(bars: KlineBar[], code: string, points: KlineIndicatorOverlayPoint[]): AnnotationContext | null {
  const context = contexts.get(bars);
  if (!context || context.code !== code || context.bar_period !== "day" || !/^[a-f0-9]{64}$/.test(context.snapshot_id)
    || !/^[a-f0-9]{64}$/.test(context.token) || !Array.isArray(context.points) || !points.length || context.points.length !== points.length) return null;
  return context.points.every((p, i) => Array.isArray(p) && p.length === 6 && p[0] === points[i].date
    && [points[i].open, points[i].high, points[i].low, points[i].close].every((n, j) => Number(p[j + 1]) === n)
    && (p[5] == null ? points[i].volume == null : Number(p[5]) === points[i].volume)) ? context : null;
}
export function annotationPlacement(note: ResearchAnnotation, context: AnnotationContext | null, code: string, dates: string[]): "EXACT" | "UNMAPPED" {
  return context && note.code === code && note.bar_period === context.bar_period && note.snapshot_id === context.snapshot_id
    && dates.includes(note.date) ? "EXACT" : "UNMAPPED";
}
