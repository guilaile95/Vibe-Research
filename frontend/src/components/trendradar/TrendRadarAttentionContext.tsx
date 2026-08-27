import { useEffect, useState } from "react";
import { AlertCircle, Loader2, RefreshCw, Radar } from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { api, ApiError, type TrendradarAttentionContext, type TrendradarAttentionItem } from "@/lib/api";

const isSupportedStatus = (status: string) => status === "OK" || status === "PARTIAL";

function displayTime(value: string | null | undefined): string {
  return value ? value.replace("T", " ").replace(/Z$/, "") : "未知";
}

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

function rankLabel(item: TrendradarAttentionItem): string {
  if (item.off_list === true || item.rank === 0) return "已脱榜";
  return item.rank == null ? "排名未知" : `排名 ${item.rank}`;
}

function AttentionItem({ item }: { item: TrendradarAttentionItem }) {
  return (
    <li className="border-b border-border/40 pb-2 last:border-0">
      <div className="flex items-start gap-2 text-sm">
        <span className="mt-0.5 shrink-0 rounded bg-primary/10 px-1.5 py-0.5 text-[10px] font-semibold text-primary">
          {rankLabel(item)}
        </span>
        {item.url ? (
          <a href={item.url} target="_blank" rel="noreferrer" className="min-w-0 flex-1 truncate hover:text-primary">
            {item.title}
          </a>
        ) : (
          <span className="min-w-0 flex-1 truncate">{item.title}</span>
        )}
      </div>
      <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-[10px] text-muted-foreground/70">
        <span>来源：{item.platform || "未知"}</span>
        <span>观察：{displayTime(item.timestamp)}</span>
        <span>首次：{displayTime(item.first_seen)}</span>
        <span>最近：{displayTime(item.last_seen)}</span>
        <span>抓取：{item.crawl_count == null ? "未知" : `${item.crawl_count} 次`}</span>
        {item.matched_terms.length > 0 && <span>命中：{item.matched_terms.join("、")}</span>}
      </div>
      {Array.isArray(item.rank_timeline) && item.rank_timeline.length > 0 && (
        <div className="mt-1 text-[10px] text-muted-foreground/60">
          排名轨迹：{item.rank_timeline.slice(0, 8).map((point) => {
            const rank = typeof point.rank === "number" ? point.rank : "未知";
            const time = typeof point.crawl_time === "string" ? displayTime(point.crawl_time) : "未知时间";
            return `${time} ${rank === 0 ? "脱榜" : `#${rank}`}`;
          }).join(" · ")}
        </div>
      )}
    </li>
  );
}

export function TrendRadarAttentionContext({ code }: { code: string }) {
  const [context, setContext] = useState<TrendradarAttentionContext | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [retryVersion, setRetryVersion] = useState(0);

  useEffect(() => {
    if (!/^\d{6}$/.test(code)) {
      setContext(null);
      setError(null);
      setLoading(false);
      return;
    }
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    setContext(null);
    api.trendradarAttentionContext(code, controller.signal)
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
  }, [code, retryVersion]);

  if (!/^\d{6}$/.test(code)) return null;

  const status = context?.status || (error ? "UNAVAILABLE" : "LOADING");
  const usable = context && isSupportedStatus(context.status);
  const items = context?.observation.items ?? [];

  return (
    <GlassCard className="mb-4" data-testid="trendradar-attention-context" data-security-code={code}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h3 className="flex items-center gap-1.5 text-sm font-semibold">
            <Radar className="h-4 w-4 text-primary" /> 公开关注上下文
            <span className="rounded bg-muted/50 px-1.5 py-0.5 text-[10px] font-normal text-muted-foreground">
              TrendRadar · {statusLabel(status)}
            </span>
          </h3>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">
            只读公开舆情观察，用于发现值得关注的资料；不代表买卖建议，也不修改持仓、论点或决策。
          </p>
        </div>
        <button
          type="button"
          onClick={() => setRetryVersion((value) => value + 1)}
          disabled={loading}
          className="rounded border border-border/50 p-1.5 text-muted-foreground hover:text-foreground disabled:opacity-50"
          aria-label="刷新公开关注上下文"
        >
          {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
        </button>
      </div>

      {loading && (
        <div className="mt-4 flex items-center gap-2 text-xs text-muted-foreground" aria-busy="true">
          <Loader2 className="h-3.5 w-3.5 animate-spin" /> 正在读取公开关注观察…
        </div>
      )}

      {error && !loading && (
        <div className="mt-4 flex items-start gap-2 rounded-md border border-warning/30 bg-warning/5 p-3 text-xs text-warning" role="alert">
          <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {!loading && !error && context && !usable && (
        <div className="mt-4 rounded-md border border-warning/30 bg-warning/5 p-3 text-xs text-warning" role="status">
          公开关注上下文暂不可用：{context.error || statusLabel(context.status)}。个股行情与其他研究数据不受影响。
        </div>
      )}

      {!loading && !error && usable && context && (
        <>
          <div className="mt-4 grid gap-2 rounded-md border border-border/50 bg-muted/10 p-3 text-xs sm:grid-cols-2">
            <div>映射主体：<span className="font-mono">{context.security.company_name || code}（{code}）</span></div>
            <div>观察窗口：最近 {context.observation.window_days} 天</div>
            <div>行业依据：{context.mapping.sector?.value || "未知"}</div>
            <div>主题依据：{context.mapping.topics.length ? context.mapping.topics.slice(0, 6).map((item) => item.term).join("、") : "未知"}</div>
            <div className="sm:col-span-2">检索词：{context.mapping.matched_terms.join("、")}</div>
          </div>

          {context.mapping.errors.length > 0 && (
            <p className="mt-2 text-[11px] text-warning">
              部分元数据源不可用，未据此猜测行业或主题归属：{context.mapping.errors.map((item) => item.source).join("、")}
            </p>
          )}

          {context.observation.items.length === 0 ? (
            <div className="mt-4 rounded-md border border-dashed border-border/60 p-4 text-center text-xs text-muted-foreground/70">
              最近 {context.observation.window_days} 天未返回匹配的公开标题；这是当前窗口的真实空态。
            </div>
          ) : (
            <ul className="mt-4 space-y-2 text-sm">
              {items.slice(0, 20).map((item) => (
                <AttentionItem key={`${item.url || item.title}:${item.platform || ""}`} item={item} />
              ))}
            </ul>
          )}

          {context.status === "PARTIAL" && (
            <p className="mt-3 text-[11px] text-warning">部分检索词未成功返回；未把失败来源当作空结果。</p>
          )}

          <div className="mt-4 border-t border-border/40 pt-2 text-[10px] leading-5 text-muted-foreground/60">
            <div>来源身份：{context.upstream?.repo || "TrendRadar"}@{context.upstream?.source_commit?.slice(0, 8) || "未知"}</div>
            <div>检索时间：{displayTime(context.retrieved_at)} · authority_ref：{context.authority_ref || "未知"}</div>
            <div>排名轨迹：{context.observation.rank_history_semantics}</div>
          </div>
        </>
      )}
    </GlassCard>
  );
}
