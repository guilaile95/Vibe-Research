import { useCallback, useEffect, useState } from "react";
import { AlertCircle, BookOpenCheck, ListChecks, Loader2, RefreshCw } from "lucide-react";
import { api } from "@/lib/api";
import type {
  FormalDecisionOutcome,
  FormalDecisionReviewWorklist,
  FormalPricePoint,
  FormalReviewWorklistItem,
} from "@/lib/api/types";
import {
  mergeOutcomeItem,
  worklistItems,
  worklistLabel,
  type FormalReviewWorklistFilter,
} from "@/lib/formalOutcomeWorklist";

const CARD = "rounded-xl border border-border/60 bg-card p-6 shadow-sm";

function stateLabel(value: unknown): string {
  if (typeof value !== "string" || !value) return "—";
  return value;
}

function actualSummary(item: FormalDecisionOutcome): string {
  const actual = item.actual_capital_outcome;
  if (!actual) return "—";
  if (actual.state === "NO_ACTUAL_TRADE") return "NO_ACTUAL_TRADE / NOT_APPLICABLE";
  if (actual.state === "PENDING") return "PENDING / NOT_DUE";
  const count = actual.trade_count ?? 0;
  return `${stateLabel(actual.state)} · ${count} exact attributed executed trade(s)`;
}

function counterfactualSummary(item: FormalDecisionOutcome): string {
  const value = item.counterfactual_outcome;
  if (!value) return "—";
  return stateLabel(value.state);
}

function pricePointText(point: FormalPricePoint | undefined): string {
  if (!point || typeof point !== "object") return "—";
  const tradeDate = "trade_date" in point && typeof point.trade_date === "string"
    ? point.trade_date
    : "—";
  const close = "close" in point && typeof point.close === "number"
    ? String(point.close)
    : "—";
  return `${tradeDate} @ ${close}`;
}

function returnText(value: string | number | null | undefined): string {
  if (value == null) return "—";
  const numeric = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(numeric)) return String(value);
  return `${(numeric * 100).toFixed(2)}%`;
}

const PROCESS_DIMENSIONS = [
  "STRONGEST_SUPPORTING_EVIDENCE",
  "STRONGEST_OPPOSING_EVIDENCE",
  "PRE_MORTEM",
  "INVALIDATION_FACTS",
] as const;

function reviewWorklistItem(item: FormalReviewWorklistItem, onFocus: (decisionId: string) => void) {
  return (
    <button
      key={item.decision_id}
      type="button"
      onClick={() => onFocus(item.decision_id)}
      data-testid={`review-worklist-${item.group}-${item.decision_id}`}
      className="w-full rounded-md border border-border/60 p-3 text-left hover:bg-accent/40"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="font-mono text-xs font-medium">{item.decision_id}</span>
        <span className="rounded bg-muted px-2 py-0.5 text-xs">{item.due_state}</span>
      </div>
      <div className="mt-1 text-sm">{item.security_code || "—"} · {item.strategy || "—"}</div>
      <div className="mt-1 text-xs text-muted-foreground">Campaign: {item.campaign_id || "—"}</div>
      <div className="mt-1 text-xs text-muted-foreground">review_by: {item.decision_review_by}</div>
    </button>
  );
}

function processReview(item: FormalDecisionOutcome) {
  const review = item.process_review;
  if (!review || review.state === "NONE") {
    return (
      <div data-testid={`process-review-none-${item.decision_id}`}>
        No pre-freeze Challenge was bound to this Frozen Decision.
      </div>
    );
  }
  if (review.state === "ERROR") {
    return (
      <div data-testid={`process-review-error-${item.decision_id}`}>
        Process Review unavailable; the bound Challenge authority is corrupt or unavailable.
      </div>
    );
  }
  return (
    <div data-testid={`process-review-bound-${item.decision_id}`} className="space-y-2">
      <div className="font-medium">Challenge bound</div>
      <div className="font-mono text-xs">challenge_id: {review.challenge_id || "—"}</div>
      <div className="text-xs text-muted-foreground">finalized_at: {review.finalized_at || "—"}</div>
      <div className="text-xs text-muted-foreground">
        packet: {review.packet_state || "—"} · evaluation: {review.challenge_evaluation || "—"}
      </div>
      <div className="text-xs text-muted-foreground">
        two-pass: {review.two_pass_state || "—"} · semantic independence verified: {review.two_pass_semantic_independence_verified || "—"}
      </div>
      <div className="space-y-1">
        {PROCESS_DIMENSIONS.map((name) => {
          const dimension = review.dimensions?.[name];
          return (
            <div key={name} className="rounded border border-border/50 p-2 text-xs">
              <div className="font-medium">{name}: {dimension?.status || "—"}</div>
              <div className="mt-1 whitespace-pre-wrap text-muted-foreground">{dimension?.text || ""}</div>
            </div>
          );
        })}
      </div>
      <div className="text-xs font-medium">Process quality: NOT_EVALUATED</div>
      <div className="text-xs text-muted-foreground">Challenge coverage is not decision correctness.</div>
    </div>
  );
}

export function FormalOutcomeSection() {
  const [items, setItems] = useState<FormalDecisionOutcome[]>([]);
  const [worklist, setWorklist] = useState<FormalDecisionReviewWorklist | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [worklistError, setWorklistError] = useState<string | null>(null);
  const [pendingFocusDecisionId, setPendingFocusDecisionId] = useState<string | null>(null);
  const [evaluationAsOf] = useState(() => (
    new URLSearchParams(window.location.search).get("evaluation_as_of") || undefined
  ));

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    setWorklistError(null);
    const [outcomeResult, worklistResult] = await Promise.allSettled([
      api.listFormalDecisionOutcomes({
        evaluation_as_of: evaluationAsOf,
        limit: 50,
        offset: 0,
      }),
      api.getFormalDecisionReviewWorklist(),
    ]);
    if (outcomeResult.status === "fulfilled") {
      setItems(outcomeResult.value);
    } else {
      setError(outcomeResult.reason?.message || "Formal Decision Outcome authority unavailable");
      setItems([]);
    }
    if (worklistResult.status === "fulfilled") {
      setWorklist(worklistResult.value);
    } else {
      setWorklistError(worklistResult.reason?.message || "Review Due Worklist authority unavailable");
      setWorklist(null);
    }
    setLoading(false);
  }, [evaluationAsOf]);

  const focusOutcome = useCallback(async (decisionId: string) => {
    const existing = document.getElementById(`formal-outcome-${decisionId}`);
    if (existing) {
      existing.scrollIntoView({ behavior: "smooth", block: "center" });
      if (existing instanceof HTMLElement) existing.focus({ preventScroll: true });
      return;
    }
    setPendingFocusDecisionId(decisionId);
    try {
      const outcome = await api.getFormalDecisionOutcome(decisionId, evaluationAsOf);
      setItems((current) => mergeOutcomeItem(current, outcome));
    } catch (err: any) {
      setPendingFocusDecisionId(null);
      setError(err?.message || "Formal Decision Outcome authority unavailable");
    }
  }, [evaluationAsOf]);

  useEffect(() => {
    if (!pendingFocusDecisionId) return;
    const row = document.getElementById(`formal-outcome-${pendingFocusDecisionId}`);
    if (!row) return;
    row.scrollIntoView({ behavior: "smooth", block: "center" });
    if (row instanceof HTMLElement) row.focus({ preventScroll: true });
    setPendingFocusDecisionId(null);
  }, [items, pendingFocusDecisionId]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <section className={CARD} aria-label="Formal Decision Outcome">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex items-start gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-violet-500/10">
            <BookOpenCheck className="h-5 w-5 text-violet-500" />
          </div>
          <div>
            <h2 className="font-medium">Formal Decision Outcome</h2>
            <p className="text-sm text-muted-foreground">
              Frozen Decision 的真实结果复盘；与 legacy advice analytics 分开。
            </p>
          </div>
        </div>
        <button
          type="button"
          onClick={load}
          disabled={loading}
          className="flex items-center gap-2 rounded-md border border-border px-3 py-2 text-sm hover:bg-accent/50 disabled:opacity-50"
        >
          {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
          刷新 Formal Outcome
        </button>
      </div>

      {error && (
        <div className="mt-4 flex items-center gap-2 rounded-md bg-red-500/10 p-3 text-sm text-red-500">
          <AlertCircle className="h-4 w-4" />
          <span>{error}</span>
        </div>
      )}

      {worklistError && (
        <div className="mt-4 flex items-center gap-2 rounded-md bg-amber-500/10 p-3 text-sm text-amber-600">
          <AlertCircle className="h-4 w-4" />
          <span>{worklistError}</span>
        </div>
      )}

      {worklist && (
        <section className="mt-5 rounded-lg border border-border/60 p-4" aria-label="Review Due Worklist">
          <div className="flex items-center gap-2">
            <ListChecks className="h-4 w-4" />
            <h3 className="font-medium">Review Due Worklist</h3>
          </div>
          <div className="mt-1 text-xs text-muted-foreground">
            Server evaluation_as_of: {worklist.evaluation_as_of}
          </div>
          <div className="mt-4 grid gap-4 lg:grid-cols-3">
            {(["due", "upcoming", "unavailable"] as FormalReviewWorklistFilter[]).map((filter) => {
              const entries = worklistItems(worklist, filter);
              return (
                <div key={filter} data-testid={`review-worklist-group-${filter}`}>
                  <div className="mb-2 flex items-center justify-between text-sm font-medium">
                    <span>{worklistLabel(filter)}</span>
                    <span className="text-xs text-muted-foreground">{entries.length}</span>
                  </div>
                  {entries.length === 0 ? (
                    <div className="rounded-md border border-dashed border-border/50 p-3 text-xs text-muted-foreground">
                      None
                    </div>
                  ) : (
                    <div className="space-y-2">
                      {entries.map((entry) => reviewWorklistItem(entry, focusOutcome))}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </section>
      )}

      {loading ? (
        <div className="flex h-24 items-center justify-center text-muted-foreground">
          <Loader2 className="h-6 w-6 animate-spin" />
        </div>
      ) : items.length === 0 && !error ? (
        <div className="mt-5 rounded-md border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
          暂无已提交 Frozen Decision；Outcome coverage 会保留无实际交易的决策。
        </div>
      ) : (
        <div className="mt-5 overflow-auto">
          <table className="w-full min-w-[900px] text-sm">
            <thead>
              <tr className="border-b border-border text-left text-xs uppercase tracking-widest text-muted-foreground">
                <th className="pb-3 pr-4">Decision / Security</th>
                <th className="pb-3 pr-4">Boundary</th>
                <th className="pb-3 pr-4">Replay</th>
                <th className="pb-3 pr-4">Process Review</th>
                <th className="pb-3 pr-4">Actual Capital</th>
                <th className="pb-3">Counterfactual</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {items.map((item) => (
                <tr
                  key={item.decision_id}
                  id={`formal-outcome-${item.decision_id}`}
                  tabIndex={-1}
                  data-testid={`formal-outcome-${item.decision_id}`}
                >
                  <td className="py-4 pr-4 align-top">
                    <div className="font-mono font-medium">{item.decision_id}</div>
                    <div className="mt-1 text-muted-foreground">
                      {item.security_code || "—"} · {item.strategy || "—"}
                    </div>
                    <div className="mt-1 text-xs text-muted-foreground">{item.campaign_id || "—"}</div>
                    <div className="mt-1 text-xs text-muted-foreground">
                      snapshot {item.decision_snapshot_hash || "—"}
                    </div>
                  </td>
                  <td className="py-4 pr-4 align-top">
                    <div>{stateLabel(item.outcome_status)}</div>
                    <div className="mt-1 text-xs text-muted-foreground">
                      committed_at {item.decision_committed_at || "—"}
                    </div>
                    <div className="mt-1 text-xs text-muted-foreground">
                      review_by {item.decision_review_by || "—"}
                    </div>
                    <div className="mt-1 text-xs text-muted-foreground">
                      as_of {item.evaluation_as_of || "—"}
                    </div>
                  </td>
                  <td className="py-4 pr-4 align-top">
                    <div>{item.decision_time_replay?.replay_hash || "—"}</div>
                    <div className="mt-1 text-xs text-muted-foreground">
                      {item.replay_future_fact_leak === false ? "future facts excluded" : "replay status unknown"}
                    </div>
                  </td>
                  <td className="py-4 pr-4 align-top">{processReview(item)}</td>
                  <td className="py-4 pr-4 align-top">{actualSummary(item)}</td>
                  <td className="py-4 align-top">
                    <div>{counterfactualSummary(item)}</div>
                    {item.counterfactual_outcome?.state === "EVALUATED" && (
                      <div
                        className="mt-2 space-y-1 text-xs"
                        data-testid={`counterfactual-detail-${item.decision_id}`}
                      >
                        <div className="font-medium">
                          Security close-to-close path
                        </div>
                        <div className="text-muted-foreground">
                          decision reference: {pricePointText(item.counterfactual_outcome.start_price_point)}
                        </div>
                        <div className="text-muted-foreground">
                          evaluation: {pricePointText(item.counterfactual_outcome.end_price_point)}
                        </div>
                        <div>
                          return: {returnText(item.counterfactual_outcome.security_return)}
                        </div>
                        <div className="text-muted-foreground">
                          security path only; not portfolio P&amp;L or decision quality
                        </div>
                      </div>
                    )}
                    <div className="mt-1 text-xs text-muted-foreground">
                      Security path is separate from Actual Capital Outcome.
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
