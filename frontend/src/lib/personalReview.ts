/** Local personal context. Do not register this data in AI page/tool context. */
export type AssessmentContent = {
  environment: string; closing_board_rank: number | null;
  judgment: "unknown" | "correct" | "incorrect";
  execution: "unknown" | "followed" | "deviated";
  violations: string[]; stop_price: number | null;
  pattern_id: string | null; pattern_revision: number | null; note: string;
};
export type AssessmentRevision = { revision: number; content: AssessmentContent; saved_at: string; stop_recorded_at: string | null; classification: string };
export type PatternContent = { name: string; setup: string; entry_rule: string; exit_rule: string; invalidation: string };
export type ReviewSummary = { requested: number | null; closed_count: number; insufficient_samples: boolean; money_scored: number; wins: number; losses: number; flat: number; win_rate_excluding_flat: number | null; net_pnl: number | null; self_assessed_count: number; self_reported_deviations: number; self_reported_violations: number };
export type PatternRevision = { pattern_id: string; revision: number; content: PatternContent; saved_at: string; effective_from: string; effective_until: string | null; statistics: ReviewSummary };
export type PersonalEpisode = { episode_id: string; code: string; name: string; trade_ids: string[]; opened_at: string; closed_at: string; holding_calendar_days: number; state: string; gross_pnl: number; net_pnl: number | null; fees: number | null; fee_coverage: string; assessment: AssessmentRevision | null; formal_attributions: ({ decision_id: string; campaign_id: string; decision_committed_at: string; trade_executed_at: string } | null)[] };
export type PersonalReview = { weekly?: { from: string; through_exclusive: string; summary: ReviewSummary }; schema_version: string; privacy: string; as_of: string; data_time: string | null; trade_count: number; closed_episodes: PersonalEpisode[]; diagnostics: { code: string | null; reason: string }[]; windows: ReviewSummary[]; patterns: PatternRevision[]; risk: { open_episodes: { code: string; remaining_quantity: number; entry_reference_stop_scenario: number | null; stop_recorded_at: string | null }[]; equity_reference: number | null; equity_effective_at: string | null; equity_confirmation: string; boundary: string }; assessment_history: Record<string, AssessmentRevision[]>; limitations: string[] };
export type Excursion = { adjusted_bound: { state: string; bounded_mfe_pct?: number; bounded_mae_pct?: number; interior_sessions?: number; adjusted_entry_reference?: number; limitations?: string; source?: { captured_at: string; archived_at: string; provider_revision: string; adjustment_basis_id: string } } | null; state: string; mfe_pct: number | null; mae_pct: number | null; raw_interior_high: number | null; raw_interior_low: number | null; boundary: string; reason: string; source: { as_of: string; fetched_at: string; sessions: number; adjustment: string } | null };
export const emptyAssessment = (): AssessmentContent => ({ environment: "", closing_board_rank: null, judgment: "unknown", execution: "unknown", violations: [], stop_price: null, pattern_id: null, pattern_revision: null, note: "" });
export const emptyPattern = (): PatternContent => ({ name: "", setup: "", entry_rule: "", exit_rule: "", invalidation: "" });
export function reviewNumber(value: number | null | undefined): string { return typeof value === "number" && Number.isFinite(value) ? value.toFixed(2) : "未知"; }
export function eligiblePatterns(patterns: PatternRevision[], executedAt: string): PatternRevision[] {
  const instant = new Date(executedAt).getTime();
  if (!Number.isFinite(instant)) return [];
  const day = new Date(instant + 8 * 3600 * 1000).toISOString().slice(0, 10);
  return patterns.filter(p => p.effective_from <= day && (!p.effective_until || day < p.effective_until));
}
export function localWeekSummary(episodes: PersonalEpisode[], from: string, through: string) {
  // Local-only UI helper: never passed to market review/model endpoints.
  const rows = episodes.filter(e => e.state === "CLOSED" && new Date(e.closed_at).getTime() >= new Date(from).getTime() && new Date(e.closed_at).getTime() < new Date(through).getTime());
  const scored = rows.filter(e => e.net_pnl !== null);
  return { closed: rows.length, moneyScored: scored.length, net: scored.length ? scored.reduce((sum, e) => sum + e.net_pnl!, 0) : null };
}
