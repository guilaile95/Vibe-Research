import { useCallback, useEffect, useState } from "react";
import { AlertCircle, Clock, Database, Loader2, RefreshCw, Rss, TrendingUp } from "lucide-react";
import { api, ApiError, type NativeIntelItemsResponse, type NativeIntelStatus, type NativeIntelTrending } from "@/lib/api";

const statusLabel = (status?: string) => ({
  normal: "可用",
  partial: "部分来源不可用",
  stale: "历史可用 · 抓取已过期",
  unavailable: "不可用",
}[status || ""] || status || "读取中");

const displayTime = (value?: string | null) => value ? value.replace("T", " ").replace(/Z$/, "") : "未知";

export default function NativeIntelPanel() {
  const [runtime, setRuntime] = useState<NativeIntelStatus | null>(null);
  const [items, setItems] = useState<NativeIntelItemsResponse | null>(null);
  const [trending, setTrending] = useState<NativeIntelTrending | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [nextRuntime, nextItems, nextTrending] = await Promise.all([
        api.nativeIntelStatus(),
        api.nativeIntelItems(40),
        api.nativeIntelTrending(24, 20),
      ]);
      setRuntime(nextRuntime);
      setItems(nextItems);
      setTrending(nextTrending);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Native Intel 读取失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const refresh = async () => {
    setRefreshing(true);
    setError(null);
    try {
      await api.nativeIntelRefresh();
      await load();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Native Intel 刷新失败");
    } finally {
      setRefreshing(false);
    }
  };

  const status = runtime?.status || items?.status || trending?.status;
  const visibleItems = items?.items ?? [];
  const entities = trending?.entities ?? [];

  return (
    <div className="space-y-4" data-testid="native-intel-panel">
      <section className="rounded-lg border border-border/60 bg-muted/10 p-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h4 className="flex items-center gap-2 text-sm font-semibold">
              <Rss className="h-4 w-4 text-primary" /> Native Intel
              <span className="rounded bg-primary/10 px-2 py-0.5 text-[10px] font-normal text-primary">
                {loading ? "读取中" : statusLabel(status)}
              </span>
            </h4>
            <p className="mt-1 text-xs text-muted-foreground">
              Vibe 本地抓取、去重和保存的公开资讯观察；不代表投资建议。
            </p>
          </div>
          <button
            type="button"
            onClick={() => void refresh()}
            disabled={loading || refreshing}
            className="inline-flex items-center gap-1.5 rounded-md border border-border/60 px-2 py-1 text-xs hover:bg-accent disabled:opacity-50"
          >
            {refreshing ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
            抓取刷新
          </button>
        </div>

        {error && (
          <div className="mt-3 flex items-start gap-2 rounded-md border border-warning/30 bg-warning/5 p-2 text-xs text-warning" role="alert">
            <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" /> {error}
          </div>
        )}

        {!loading && runtime && (
          <div className="mt-3 grid gap-2 text-xs sm:grid-cols-4">
            <div className="rounded border border-border/40 p-2"><Database className="mr-1 inline h-3.5 w-3.5" />历史条目 {runtime.store?.item_count ?? 0}</div>
            <div className="rounded border border-border/40 p-2">来源 {runtime.sources?.healthy ?? 0}/{runtime.sources?.total ?? 0} 正常</div>
            <div className="rounded border border-border/40 p-2">失败 {runtime.sources?.failing ?? 0}</div>
            <div className="rounded border border-border/40 p-2"><Clock className="mr-1 inline h-3.5 w-3.5" />{displayTime(runtime.last_run?.finished_at || runtime.last_run?.started_at)}</div>
          </div>
        )}

        {runtime?.sources && runtime.sources.failing > 0 && (
          <p className="mt-2 text-[11px] text-warning">
            失败来源：{runtime.sources.failing_names.join("、")}。已保留其他来源结果，未把失败伪装成空数据。
          </p>
        )}
      </section>

      <section className="rounded-lg border border-border/60 p-3">
        <h4 className="flex items-center gap-1.5 text-sm font-semibold"><TrendingUp className="h-4 w-4 text-primary" />近 24 小时关注趋势</h4>
        {entities.length ? (
          <div className="mt-3 flex flex-wrap gap-2" aria-label="Native Intel 趋势实体">
            {entities.slice(0, 20).map((entity) => (
              <span key={`${entity.term_kind}:${entity.security_code || ""}:${entity.term}`} className="rounded-full bg-primary/10 px-2 py-1 text-[11px] text-primary">
                {entity.term} · {entity.item_count} 条{entity.delta ? ` · ${entity.delta > 0 ? "+" : ""}${entity.delta}` : ""}
              </span>
            ))}
          </div>
        ) : (
          <p className="mt-3 text-xs text-muted-foreground">当前窗口暂无可计算的实体趋势。</p>
        )}
        <p className="mt-2 text-[10px] text-muted-foreground/60">RSS 不提供真实排名，趋势仅使用本地观察次数、来源数和环比，不补伪造序号。</p>
      </section>

      <section className="rounded-lg border border-border/60 p-3">
        <h4 className="text-sm font-semibold">最新公开资讯</h4>
        {loading && <p className="mt-3 text-xs text-muted-foreground"><Loader2 className="mr-1 inline h-3.5 w-3.5 animate-spin" />读取本地资讯历史…</p>}
        {!loading && visibleItems.length === 0 ? (
          <p className="mt-3 rounded border border-dashed border-border/60 p-4 text-center text-xs text-muted-foreground">当前没有已保存条目；若来源失败，请查看上方来源状态。</p>
        ) : (
          <ul className="mt-2 divide-y divide-border/40">
            {visibleItems.map((item) => (
              <li key={item.item_id} className="py-2 text-sm">
                <div className="flex flex-wrap items-start gap-2">
                  <a href={item.url} target="_blank" rel="noreferrer noopener" className="min-w-0 flex-1 hover:text-primary hover:underline">{item.title}</a>
                  <span className="rounded bg-secondary px-1.5 py-0.5 text-[10px]">{item.source_name || item.hint}</span>
                </div>
                <div className="mt-1 flex flex-wrap gap-x-3 text-[10px] text-muted-foreground">
                  <span>发布：{displayTime(item.published_at)}</span>
                  <span>首次：{displayTime(item.first_seen_at)}</span>
                  <span>最近：{displayTime(item.last_seen_at)}</span>
                  <span>观察 {item.observation_count} 次</span>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
