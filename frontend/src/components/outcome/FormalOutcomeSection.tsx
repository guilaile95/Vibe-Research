import { useCallback, useEffect, useState } from "react";
import { AlertCircle, BookOpenCheck, Loader2, RefreshCw } from "lucide-react";
import { api } from "@/lib/api";
import type { FormalDecisionOutcome, FormalPricePoint } from "@/lib/api/types";

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

export function FormalOutcomeSection() {
  const [items, setItems] = useState<FormalDecisionOutcome[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [evaluationAsOf] = useState(() => (
    new URLSearchParams(window.location.search).get("evaluation_as_of") || undefined
  ));

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setItems(await api.listFormalDecisionOutcomes({
        evaluation_as_of: evaluationAsOf,
        limit: 50,
        offset: 0,
      }));
    } catch (err: any) {
      setError(err?.message || "Formal Decision Outcome authority unavailable");
      setItems([]);
    } finally {
      setLoading(false);
    }
  }, []);

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
                <th className="pb-3 pr-4">Actual Capital</th>
                <th className="pb-3">Counterfactual</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {items.map((item) => (
                <tr key={item.decision_id} data-testid={`formal-outcome-${item.decision_id}`}>
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
