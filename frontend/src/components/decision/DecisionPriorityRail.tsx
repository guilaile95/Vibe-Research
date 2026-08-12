import { useCallback, useEffect, useMemo, useState } from "react";
import { AlertTriangle, CheckCircle2, Loader2, RefreshCw } from "lucide-react";
import { Link } from "react-router-dom";

import { cn } from "@/lib/utils";
import { ApiError, getTodayActions, type TodayActions } from "@/lib/decisionCockpit";
import { buildDecisionPriorities } from "@/lib/decisionPriority";

function todayShanghai(): string {
  try {
    return new Intl.DateTimeFormat("en-CA", {
      timeZone: "Asia/Shanghai",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    }).format(new Date());
  } catch {
    const now = new Date();
    const local = new Date(now.getTime() - now.getTimezoneOffset() * 60000);
    return local.toISOString().slice(0, 10);
  }
}

function pct(value: number | null): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return `${value > 0 ? "+" : ""}${value.toFixed(2)}%`;
}

export function DecisionPriorityRail() {
  const [data, setData] = useState<TodayActions | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const tradeDate = useMemo(todayShanghai, []);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await getTodayActions(tradeDate));
    } catch (cause) {
      setData(null);
      setError(cause instanceof ApiError ? cause.message : "今日优先事项暂不可用");
    } finally {
      setLoading(false);
    }
  }, [tradeDate]);

  useEffect(() => {
    void load();
  }, [load]);

  const priorities = useMemo(() => buildDecisionPriorities(data).slice(0, 5), [data]);

  return (
    <aside
      aria-label="今日优先事项"
      className="order-first mb-5 border-b border-border/45 pb-4 xl:order-none xl:mb-0 xl:border-b-0 xl:border-l xl:pb-0 xl:pl-4"
    >
      <div className="sticky top-4">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold">今日优先事项</h2>
            <p className="mt-1 max-w-[28rem] text-[10px] leading-relaxed text-muted-foreground/70 xl:max-w-none">
              只排列后端已有 action / flag，不生成新的交易建议。
            </p>
          </div>
          <button
            type="button"
            onClick={() => void load()}
            disabled={loading}
            aria-label="刷新今日优先事项"
            className="rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:opacity-40"
          >
            {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
          </button>
        </div>

        {data?.as_of ? (
          <p className="mt-1.5 font-mono text-[9px] text-muted-foreground/50">截至 {data.as_of}</p>
        ) : null}

        <div aria-live="polite">
          {error ? (
            <div className="mt-3 flex gap-2 py-2 text-xs text-destructive">
              <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              <span>{error}</span>
            </div>
          ) : null}

          {!error && !loading && priorities.length === 0 ? (
            <div className="mt-3 flex gap-2 py-2 text-xs text-muted-foreground">
              <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              <span>当前没有显式 action / flag 需要置顶。</span>
            </div>
          ) : null}
        </div>

        {priorities.length ? (
          <div className="mt-3 grid gap-x-4 sm:grid-cols-2 xl:block">
            {priorities.map((item, index) => (
              <Link
                key={item.key}
                to={item.href}
                className={cn(
                  "group block border-t border-border/35 py-2.5 first:border-t-0 xl:first:border-t-0",
                  index >= 3 && "hidden xl:block",
                )}
              >
                <div className="flex items-start gap-2.5">
                  <span className="mt-0.5 font-mono text-[10px] text-muted-foreground/45">
                    {String(index + 1).padStart(2, "0")}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-baseline gap-1.5">
                      <span className="truncate text-xs font-medium transition-colors group-hover:text-foreground">
                        {item.name || item.code}
                      </span>
                      <span className="shrink-0 font-mono text-[10px] text-muted-foreground">{item.code}</span>
                    </div>
                    <p className="mt-0.5 text-[11px] font-medium text-foreground/85">{item.label}</p>
                    <p className="mt-0.5 line-clamp-2 text-[10px] leading-relaxed text-muted-foreground">{item.detail}</p>
                    <div className="mt-1.5 flex gap-2 font-mono text-[9px] text-muted-foreground/65">
                      {item.changePct != null ? (
                        <span
                          className={cn(
                            item.changePct > 0
                              ? "text-danger"
                              : item.changePct < 0
                                ? "text-success"
                                : "",
                          )}
                        >
                          日 {pct(item.changePct)}
                        </span>
                      ) : null}
                      {item.pnlPct != null ? <span>持仓 {pct(item.pnlPct)}</span> : null}
                    </div>
                  </div>
                </div>
              </Link>
            ))}
          </div>
        ) : null}

        {data?.warnings?.length ? (
          <div className="mt-3 border-t border-border/40 pt-2 text-[10px] leading-relaxed text-amber-600 dark:text-amber-400">
            {data.warnings.slice(0, 2).map((warning) => <p key={warning}>{warning}</p>)}
          </div>
        ) : null}
      </div>
    </aside>
  );
}
