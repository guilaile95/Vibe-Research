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
  COUNTERFACTUAL_COLUMN_HEADER,
  COUNTERFACTUAL_DECISION_REFERENCE_LABEL,
  COUNTERFACTUAL_EVALUATION_LABEL,
  COUNTERFACTUAL_PATH_HEADING,
  COUNTERFACTUAL_RETURN_LABEL,
  COUNTERFACTUAL_SCOPE_COPY,
  COUNTERFACTUAL_SEPARATION_COPY,
  FORMAL_OUTCOME_ACTUAL_CAPITAL_COLUMN_HEADER,
  FORMAL_OUTCOME_BOUNDARY_COLUMN_HEADER,
  FORMAL_OUTCOME_EMPTY_COPY,
  FORMAL_OUTCOME_HEADING,
  FORMAL_OUTCOME_IDENTITY_COLUMN_HEADER,
  FORMAL_OUTCOME_PROCESS_REVIEW_COLUMN_HEADER,
  FORMAL_OUTCOME_REFRESH_LABEL,
  FORMAL_OUTCOME_REPLAY_COLUMN_HEADER,
  FORMAL_OUTCOME_SUBTITLE,
  HISTORICAL_DECISION_FACT_COPY,
  PROCESS_REVIEW_BOUND_HEADING,
  PROCESS_REVIEW_COVERAGE_COPY,
  PROCESS_REVIEW_DIMENSIONS,
  PROCESS_REVIEW_ERROR_COPY,
  PROCESS_REVIEW_NONE_COPY,
  REVIEW_WORKLIST_EMPTY_COPY,
  REVIEW_WORKLIST_EVALUATION_AS_OF_LABEL,
  REVIEW_WORKLIST_HEADING,
  actualCapitalSummary,
  counterfactualSummary,
  dueStateLabel,
  formalOutcomeIdentityTitle,
  frozenDecisionNbaLabel,
  mergeOutcomeItem,
  outcomeStatusLabel,
  processReviewDimensionLabel,
  processReviewDimensionStatusLabel,
  processReviewPacketSummary,
  processReviewQualityLabel,
  processReviewTwoPassSummary,
  replayFutureFactLabel,
  worklistItems,
  worklistLabel,
  type FormalReviewWorklistFilter,
} from "@/lib/formalOutcomeWorklist";

const CARD = "rounded-xl border border-border/60 bg-card p-6 shadow-sm";

function stateLabel(value: unknown): string {
  if (typeof value !== "string" || !value) return "—";
  return value;
}

function actualCapitalCell(item: FormalDecisionOutcome) {
  const actual = actualCapitalSummary(item);
  return (
    <div data-actual-capital-state={item.actual_capital_outcome?.state || ""}>
      <div>{actual.label}</div>
      {actual.canonical ? (
        <div className="mt-1 font-mono text-[11px] text-muted-foreground">{actual.canonical}</div>
      ) : null}
    </div>
  );
}

function counterfactualCell(item: FormalDecisionOutcome) {
  const counterfactual = counterfactualSummary(item);
  return (
    <div data-counterfactual-state={item.counterfactual_outcome?.state || ""}>
      <div>{counterfactual.label}</div>
      {counterfactual.canonical ? (
        <div className="mt-1 font-mono text-[11px] text-muted-foreground">{counterfactual.canonical}</div>
      ) : null}
      {item.counterfactual_outcome?.state === "EVALUATED" && (
        <div
          className="mt-2 space-y-1 text-xs"
          data-testid={`counterfactual-detail-${item.decision_id}`}
        >
          <div className="font-medium">
            {COUNTERFACTUAL_PATH_HEADING}
          </div>
          <div className="text-muted-foreground">
            {COUNTERFACTUAL_DECISION_REFERENCE_LABEL}：{pricePointText(item.counterfactual_outcome.start_price_point)}
          </div>
          <div className="text-muted-foreground">
            {COUNTERFACTUAL_EVALUATION_LABEL}：{pricePointText(item.counterfactual_outcome.end_price_point)}
          </div>
          <div>
            {COUNTERFACTUAL_RETURN_LABEL}：{returnText(item.counterfactual_outcome.security_return)}
          </div>
          <div className="text-muted-foreground">
            {COUNTERFACTUAL_SCOPE_COPY}
          </div>
        </div>
      )}
      <div className="mt-1 text-xs text-muted-foreground">
        {COUNTERFACTUAL_SEPARATION_COPY}
      </div>
    </div>
  );
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

function reviewWorklistItem(item: FormalReviewWorklistItem, onFocus: (decisionId: string) => void) {
  const identity = formalOutcomeIdentityTitle({
    security_code: item.security_code,
    strategy: item.strategy,
    next_best_action: item.decision_next_best_action,
  });
  return (
    <button
      key={item.decision_id}
      type="button"
      onClick={() => onFocus(item.decision_id)}
      data-testid={`review-worklist-${item.group}-${item.decision_id}`}
      className="w-full rounded-md border border-border/60 p-3 text-left hover:bg-accent/40"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span
          className="text-sm font-medium"
          data-testid={`review-worklist-nba-${item.decision_id}`}
        >
          {identity}
        </span>
        <span className="rounded bg-muted px-2 py-0.5 text-xs" data-due-state={item.due_state}>
          {dueStateLabel(item.due_state)}
        </span>
      </div>
      <div className="mt-1 break-all font-mono text-[11px] text-muted-foreground">
        decision_id: {item.decision_id}
      </div>
      <div className="mt-1 break-all font-mono text-[11px] text-muted-foreground">
        campaign_id: {item.campaign_id || "—"}
      </div>
      <div className="mt-1 text-[11px] font-mono text-muted-foreground">{item.due_state}</div>
      <div className="mt-1 text-xs text-muted-foreground">review_by: {item.decision_review_by}</div>
    </button>
  );
}

function processReview(item: FormalDecisionOutcome) {
  const review = item.process_review;
  if (!review || review.state === "NONE") {
    return (
      <div data-testid={`process-review-none-${item.decision_id}`}>
        {PROCESS_REVIEW_NONE_COPY}
      </div>
    );
  }
  if (review.state === "ERROR") {
    return (
      <div data-testid={`process-review-error-${item.decision_id}`}>
        {PROCESS_REVIEW_ERROR_COPY}
      </div>
    );
  }
  const packet = processReviewPacketSummary(review);
  const twoPass = processReviewTwoPassSummary(review);
  const qualityState = review.process_quality?.state || "NOT_EVALUATED";
  return (
    <div
      data-testid={`process-review-bound-${item.decision_id}`}
      className="space-y-2"
      data-process-review-state={review.state || ""}
    >
      <div className="font-medium">{PROCESS_REVIEW_BOUND_HEADING}</div>
      <div className="font-mono text-xs">challenge_id: {review.challenge_id || "—"}</div>
      <div className="text-xs text-muted-foreground">finalized_at: {review.finalized_at || "—"}</div>
      <div
        className="text-xs text-muted-foreground"
        data-packet-state={review.packet_state || ""}
        data-challenge-evaluation={review.challenge_evaluation || ""}
      >
        <div>{packet.label}</div>
        <div className="mt-1 font-mono text-[11px]">{packet.canonical}</div>
      </div>
      <div
        className="text-xs text-muted-foreground"
        data-two-pass-state={review.two_pass_state || ""}
        data-two-pass-semantic-independence-verified={review.two_pass_semantic_independence_verified || ""}
      >
        <div>{twoPass.label}</div>
        <div className="mt-1 font-mono text-[11px]">{twoPass.canonical}</div>
      </div>
      <div className="space-y-1">
        {PROCESS_REVIEW_DIMENSIONS.map((name) => {
          const dimension = review.dimensions?.[name];
          return (
            <div key={name} className="rounded border border-border/50 p-2 text-xs">
              <div
                className="font-medium"
                data-dimension={name}
                data-status={dimension?.status || ""}
              >
                {processReviewDimensionLabel(name)}：{processReviewDimensionStatusLabel(dimension?.status)}
              </div>
              <div className="mt-1 whitespace-pre-wrap text-muted-foreground">{dimension?.text || ""}</div>
            </div>
          );
        })}
      </div>
      <div className="text-xs font-medium" data-process-quality={qualityState}>
        {processReviewQualityLabel(review.process_quality?.state)}
      </div>
      <div className="text-xs text-muted-foreground">{PROCESS_REVIEW_COVERAGE_COPY}</div>
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
    <section className={CARD} aria-label={FORMAL_OUTCOME_HEADING}>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex items-start gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-violet-500/10">
            <BookOpenCheck className="h-5 w-5 text-violet-500" />
          </div>
          <div>
            <h2 className="font-medium">{FORMAL_OUTCOME_HEADING}</h2>
            <p className="text-sm text-muted-foreground">
              {FORMAL_OUTCOME_SUBTITLE}
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
          {FORMAL_OUTCOME_REFRESH_LABEL}
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
        <section className="mt-5 rounded-lg border border-border/60 p-4" aria-label={REVIEW_WORKLIST_HEADING}>
          <div className="flex items-center gap-2">
            <ListChecks className="h-4 w-4" />
            <h3 className="font-medium">{REVIEW_WORKLIST_HEADING}</h3>
          </div>
          <div className="mt-1 text-xs text-muted-foreground">
            {REVIEW_WORKLIST_EVALUATION_AS_OF_LABEL}：{worklist.evaluation_as_of}
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
                      {REVIEW_WORKLIST_EMPTY_COPY}
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
          {FORMAL_OUTCOME_EMPTY_COPY}
        </div>
      ) : (
        <div className="mt-5 overflow-auto">
          <table className="w-full min-w-[900px] text-sm">
            <thead>
              <tr className="border-b border-border text-left text-xs uppercase tracking-widest text-muted-foreground">
                <th className="pb-3 pr-4">{FORMAL_OUTCOME_IDENTITY_COLUMN_HEADER}</th>
                <th className="pb-3 pr-4">{FORMAL_OUTCOME_BOUNDARY_COLUMN_HEADER}</th>
                <th className="pb-3 pr-4">{FORMAL_OUTCOME_REPLAY_COLUMN_HEADER}</th>
                <th className="pb-3 pr-4">{FORMAL_OUTCOME_PROCESS_REVIEW_COLUMN_HEADER}</th>
                <th className="pb-3 pr-4">{FORMAL_OUTCOME_ACTUAL_CAPITAL_COLUMN_HEADER}</th>
                <th className="pb-3">{COUNTERFACTUAL_COLUMN_HEADER}</th>
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
                    <div
                      className="space-y-1"
                      data-testid={`formal-decision-context-${item.decision_id}`}
                    >
                      <div className="font-medium">
                        {formalOutcomeIdentityTitle({
                          security_code: item.security_code,
                          strategy: item.strategy,
                          next_best_action: item.decision_next_best_action,
                        })}
                      </div>
                      <div className="text-xs text-muted-foreground">
                        冻结时操作：
                        <span className="font-medium text-foreground">
                          {frozenDecisionNbaLabel(item.decision_next_best_action)}
                        </span>
                        <span className="ml-1 font-mono">{item.decision_next_best_action || "UNKNOWN"}</span>
                      </div>
                      <div className="break-all font-mono text-xs">decision_id: {item.decision_id}</div>
                      <div className="break-all font-mono text-xs text-muted-foreground">
                        campaign_id: {item.campaign_id || "—"}
                      </div>
                      <div className="text-xs text-muted-foreground">committed_at: {item.decision_committed_at || "—"}</div>
                      <div className="text-xs text-muted-foreground">review_by: {item.decision_review_by || "—"}</div>
                      <div className="text-[11px] text-muted-foreground">{HISTORICAL_DECISION_FACT_COPY}</div>
                    </div>
                    <div className="mt-2 text-xs text-muted-foreground">
                      snapshot {item.decision_snapshot_hash || "—"}
                    </div>
                  </td>
                  <td className="py-4 pr-4 align-top">
                    <div data-outcome-status={item.outcome_status || ""}>
                      {outcomeStatusLabel(item.outcome_status)}
                    </div>
                    <div className="mt-1 font-mono text-[11px] text-muted-foreground">
                      {stateLabel(item.outcome_status)}
                    </div>
                    {item.due_state ? (
                      <div className="mt-1 text-xs text-muted-foreground" data-due-state={item.due_state}>
                        {dueStateLabel(item.due_state)}
                        <span className="ml-1 font-mono">{item.due_state}</span>
                      </div>
                    ) : null}
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
                      {replayFutureFactLabel(item.replay_future_fact_leak)}
                    </div>
                  </td>
                  <td className="py-4 pr-4 align-top">{processReview(item)}</td>
                  <td className="py-4 pr-4 align-top">{actualCapitalCell(item)}</td>
                  <td className="py-4 align-top">{counterfactualCell(item)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
