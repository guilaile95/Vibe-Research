import { useEffect, useState } from "react";
import { AlertCircle, Loader2, RefreshCw, Rss } from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { api, ApiError, type NativeIntelSecurityContext as Context } from "@/lib/api";

const usable = (status?: string) => status === "normal" || status === "partial" || status === "stale";
const statusLabel = (status?: string) => ({ normal: "可用", partial: "部分可用", stale: "历史可用 · 已过期", unavailable: "不可用" }[status || ""] || status || "读取中");
const displayTime = (value?: string | null) => value ? value.replace("T", " ").replace(/Z$/, "") : "未知";

export function NativeIntelSecurityContext({ code }: { code: string }) {
  const [context, setContext] = useState<Context | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [retry, setRetry] = useState(0);

  useEffect(() => {
    if (!/^\d{6}$/.test(code)) return;
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    api.nativeIntelSecurityContext(code, controller.signal)
      .then((value) => { if (!controller.signal.aborted) setContext(value); })
      .catch((cause) => { if (!controller.signal.aborted) setError(cause instanceof ApiError ? cause.message : "Native Intel 上下文读取失败"); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [code, retry]);

  if (!/^\d{6}$/.test(code)) return null;
  const terms = context?.mapping.terms ?? [];
  const industries = terms.filter((term) => term.term_kind === "industry").map((term) => term.term);
  const concepts = terms.filter((term) => term.term_kind === "concept").map((term) => term.term);

  return (
    <GlassCard className="mb-4" data-testid="native-intel-security-context" data-security-code={code}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h3 className="flex items-center gap-1.5 text-sm font-semibold"><Rss className="h-4 w-4 text-primary" />公开资讯上下文 <span className="rounded bg-muted/50 px-1.5 py-0.5 text-[10px] font-normal">Native Intel · {loading ? "读取中" : statusLabel(context?.status)}</span></h3>
          <p className="mt-1 text-xs text-muted-foreground">本地保存的公开资讯观察；不代表买卖建议，也不修改持仓、论点或决策。</p>
        </div>
        <button type="button" onClick={() => setRetry((value) => value + 1)} disabled={loading} className="rounded border border-border/50 p-1.5" aria-label="刷新公开资讯上下文">
          {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
        </button>
      </div>

      {error && <div className="mt-3 flex gap-2 text-xs text-warning" role="alert"><AlertCircle className="h-3.5 w-3.5" />{error}。个股其他研究数据不受影响。</div>}
      {!loading && context && !usable(context.status) && <div className="mt-3 text-xs text-warning" role="status">Native Intel 暂不可用：{context.error || statusLabel(context.status)}。个股其他研究数据不受影响。</div>}
      {!loading && context && usable(context.status) && (
        <>
          <div className="mt-4 grid gap-2 rounded-md border border-border/50 bg-muted/10 p-3 text-xs sm:grid-cols-2">
            <div>映射主体：<span className="font-mono">{context.security.company_name || "名称未知"}（{code}）</span></div>
            <div>观察窗口：最近 {Math.round(context.window_hours / 24)} 天</div>
            <div>行业：{industries.join("、") || "未知"}</div>
            <div>概念：{concepts.slice(0, 8).join("、") || "未知"}</div>
            <div>命中资讯：{context.observation.mention_count ?? context.observation.item_count} 条 / {context.observation.source_count ?? 0} 个来源</div>
            <div>最近观察：{displayTime(context.observation.last_seen_at)}</div>
          </div>
          {context.mapping.errors.length > 0 && <p className="mt-2 text-[11px] text-warning">部分映射源不可用，未据此猜测：{context.mapping.errors.map((item) => item.source).join("、")}</p>}
          {context.observation.items.length === 0 ? <p className="mt-4 rounded border border-dashed border-border/60 p-4 text-center text-xs text-muted-foreground">当前窗口没有确定匹配的公开资讯。</p> : (
            <ul className="mt-4 space-y-2">
              {context.observation.items.slice(0, 20).map((item) => <li key={item.item_id} className="border-b border-border/40 pb-2 text-sm"><a href={item.url} target="_blank" rel="noreferrer noopener" className="hover:text-primary hover:underline">{item.title}</a><div className="mt-1 flex flex-wrap gap-x-3 text-[10px] text-muted-foreground"><span>{item.source_name || item.hint}</span><span>首次 {displayTime(item.first_seen_at)}</span><span>最近 {displayTime(item.last_seen_at)}</span><span>观察 {item.observation_count} 次</span></div></li>)}
            </ul>
          )}
          <p className="mt-3 border-t border-border/40 pt-2 text-[10px] text-muted-foreground/60">authority_ref：{context.authority_ref || "vibe:native_intel:v0.1"} · RSS 无真实排名时保持 UNKNOWN</p>
        </>
      )}
    </GlassCard>
  );
}
