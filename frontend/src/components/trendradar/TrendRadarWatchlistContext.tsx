import { useEffect, useMemo, useState } from "react";
import { AlertCircle, Loader2, RefreshCw, Radar } from "lucide-react";
import { api, ApiError, type TrendradarAttentionContext, type TrendradarWatchlistContext } from "@/lib/api";

const usable = (status: string) => status === "OK" || status === "PARTIAL";

function statusLabel(status: string): string {
  switch (status) {
    case "OK": return "可用";
    case "PARTIAL": return "部分可用";
    case "DISABLED": return "未启用";
    case "TIMEOUT": return "超时";
    case "CONTRACT_MISMATCH": return "契约不匹配";
    case "CONFIG_ERROR": return "配置错误";
    default: return status || "不可用";
  }
}

function itemSummary(item: TrendradarAttentionContext): string {
  if (usable(item.status)) {
    const count = item.observation.item_count;
    return count > 0 ? `${count} 条公开标题` : "当前窗口真实空态";
  }
  return statusLabel(item.status);
}

export function TrendRadarWatchlistContext({ codes }: { codes: string[] }) {
  const [context, setContext] = useState<TrendradarWatchlistContext | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [retryVersion, setRetryVersion] = useState(0);

  useEffect(() => {
    if (codes.length === 0) {
      setContext(null);
      setError(null);
      setLoading(false);
      return;
    }
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    setContext(null);
    api.trendradarWatchlistContext(controller.signal)
      .then((value) => {
        if (!controller.signal.aborted) setContext(value);
      })
      .catch((cause: unknown) => {
        if (controller.signal.aborted) return;
        setError(cause instanceof ApiError ? cause.message : "关注上下文读取失败");
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [codes, retryVersion]);

  const byCode = useMemo(
    () => new Map((context?.items ?? []).map((item) => [item.security.code, item])),
    [context],
  );
  if (codes.length === 0) return null;

  return (
    <div className="mb-3 rounded-lg border border-border/50 bg-muted/10 p-3" data-testid="trendradar-watchlist-context">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h4 className="flex items-center gap-1.5 text-xs font-semibold">
            <Radar className="h-3.5 w-3.5 text-primary" /> 公开关注上下文
            <span className="rounded bg-muted/50 px-1.5 py-0.5 text-[10px] font-normal text-muted-foreground">
              TrendRadar · {loading ? "读取中" : statusLabel(context?.status || (error ? "UNAVAILABLE" : "LOADING"))}
            </span>
          </h4>
          <p className="mt-1 text-[11px] leading-5 text-muted-foreground">
            只读公开舆情观察，用于发现值得研究的资料；不代表买卖建议，也不修改自选、论点或决策。
          </p>
        </div>
        <button
          type="button"
          onClick={() => setRetryVersion((value) => value + 1)}
          disabled={loading}
          className="rounded border border-border/50 p-1 text-muted-foreground hover:text-foreground disabled:opacity-50"
          aria-label="刷新自选公开关注上下文"
        >
          {loading ? <Loader2 className="h-3 w-3 animate-spin" /> : <RefreshCw className="h-3 w-3" />}
        </button>
      </div>

      {loading && <div className="mt-2 text-[11px] text-muted-foreground">正在读取公开关注观察…</div>}
      {error && !loading && (
        <div className="mt-2 flex items-center gap-1.5 text-[11px] text-warning" role="alert">
          <AlertCircle className="h-3.5 w-3.5" /> {error}。行情与当日异动数据不受影响。
        </div>
      )}
      {!loading && !error && context && !usable(context.status) && (
        <div className="mt-2 text-[11px] text-warning" role="status">
          公开关注上下文暂不可用：{context.error || statusLabel(context.status)}。行情与当日异动数据不受影响。
        </div>
      )}
      {!loading && !error && context && usable(context.status) && (
        <div className="mt-3 grid gap-2 sm:grid-cols-2">
          {codes.map((code) => {
            const item = byCode.get(code);
            return (
              <div key={code} className="rounded border border-border/40 px-2 py-1.5 text-[11px]" data-watchlist-attention-code={code}>
                <span className="font-mono">{code}</span>
                <span className="ml-2 text-muted-foreground">{item?.security.company_name || "名称未知"}</span>
                <span className="ml-2 text-muted-foreground">{item ? itemSummary(item) : "未返回"}</span>
              </div>
            );
          })}
        </div>
      )}
      {context && (
        <div className="mt-2 text-[10px] text-muted-foreground/60">
          来源身份：{context.upstream?.repo || "TrendRadar"}@{context.upstream?.source_commit?.slice(0, 8) || "未知"} · authority_ref：{context.authority_ref || "未知"}
        </div>
      )}
    </div>
  );
}
