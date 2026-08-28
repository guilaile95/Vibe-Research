import { useEffect, useMemo, useState } from "react";
import { AlertCircle, Loader2, RefreshCw, Rss } from "lucide-react";
import { api, ApiError, type NativeIntelWatchlistContext as Context } from "@/lib/api";

const usable = (status?: string) => status === "normal" || status === "partial" || status === "stale";
const statusLabel = (status?: string) => ({ normal: "可用", partial: "部分可用", stale: "历史可用 · 已过期", unavailable: "不可用" }[status || ""] || status || "读取中");

export function NativeIntelWatchlistContext({ codes }: { codes: string[] }) {
  const [context, setContext] = useState<Context | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [retry, setRetry] = useState(0);

  useEffect(() => {
    if (!codes.length) return;
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    api.nativeIntelWatchlistContext(controller.signal)
      .then((value) => { if (!controller.signal.aborted) setContext(value); })
      .catch((cause) => { if (!controller.signal.aborted) setError(cause instanceof ApiError ? cause.message : "Native Intel 自选上下文读取失败"); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [codes, retry]);

  const byCode = useMemo(() => new Map((context?.securities ?? []).map((item) => [item.code, item])), [context]);
  if (!codes.length) return null;

  return (
    <div className="mb-3 rounded-lg border border-border/50 bg-muted/10 p-3" data-testid="native-intel-watchlist-context">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div><h4 className="flex items-center gap-1.5 text-xs font-semibold"><Rss className="h-3.5 w-3.5 text-primary" />公开资讯上下文 <span className="rounded bg-muted/50 px-1.5 py-0.5 text-[10px] font-normal">Native Intel · {loading ? "读取中" : statusLabel(context?.status)}</span></h4><p className="mt-1 text-[11px] text-muted-foreground">按后端权威自选列表聚合本地公开资讯；不修改自选、论点或决策。</p></div>
        <button type="button" onClick={() => setRetry((value) => value + 1)} disabled={loading} className="rounded border border-border/50 p-1" aria-label="刷新自选公开资讯上下文">{loading ? <Loader2 className="h-3 w-3 animate-spin" /> : <RefreshCw className="h-3 w-3" />}</button>
      </div>
      {error && <div className="mt-2 flex gap-1.5 text-[11px] text-warning" role="alert"><AlertCircle className="h-3.5 w-3.5" />{error}。行情与异动数据不受影响。</div>}
      {!loading && context && !usable(context.status) && <div className="mt-2 text-[11px] text-warning" role="status">Native Intel 暂不可用：{context.error || statusLabel(context.status)}。行情与异动数据不受影响。</div>}
      {!loading && context && usable(context.status) && <div className="mt-3 grid gap-2 sm:grid-cols-2">{codes.map((code) => { const item = byCode.get(code); return <div key={code} className="rounded border border-border/40 px-2 py-1.5 text-[11px]" data-watchlist-intel-code={code}><span className="font-mono">{code}</span><span className="ml-2 text-muted-foreground">{item?.company_name || "名称未知"}</span><span className="ml-2 text-muted-foreground">{item ? `${item.mention_count} 条 / ${item.source_count} 源` : "未返回"}</span></div>; })}</div>}
      {context?.degraded && context.degraded.length > 0 && <p className="mt-2 text-[10px] text-warning">部分股票映射不可用：{context.degraded.map((item) => item.code).join("、")}</p>}
      {context && <p className="mt-2 text-[10px] text-muted-foreground/60">authority_ref：{context.authority_ref || "vibe:native_intel:v0.1"}</p>}
    </div>
  );
}
