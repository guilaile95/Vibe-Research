import { useCallback, useEffect, useState } from "react";
import {
  AlertCircle,
  ExternalLink,
  Flame,
  History,
  Loader2,
  RefreshCw,
  TrendingUp,
  X,
} from "lucide-react";
import { Link } from "react-router-dom";
import { candidateWorkspaceHref } from "@/lib/candidateCampaign";
import {
  api,
  ApiError,
  type NativeIntelHotlistItem,
  type NativeIntelHotlistSource,
  type NativeIntelItemRankHistoryResponse,
} from "@/lib/api";
import {
  filterHotlistItems,
  formatRankDelta,
  formatStateBadge,
  type HotlistFilter,
} from "@/lib/hotlistView";
import { formatShanghaiTime } from "@/lib/intelDigestView";
import { cn } from "@/lib/utils";

export function HotlistPanel() {
  const [items, setItems] = useState<NativeIntelHotlistItem[]>([]);
  const [sources, setSources] = useState<NativeIntelHotlistSource[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<HotlistFilter>("all");

  const [activeItemId, setActiveItemId] = useState<number | null>(null);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyData, setHistoryData] = useState<NativeIntelItemRankHistoryResponse | null>(null);

  const loadData = useCallback(async () => {
    try {
      setError(null);
      const res = await api.nativeIntelHotlist(100);
      setItems(res.items || []);
      setSources(res.sources || []);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "读取热榜失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  const handleRefresh = async () => {
    setRefreshing(true);
    try {
      await api.nativeIntelRefresh();
      await loadData();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "刷新热榜失败");
    } finally {
      setRefreshing(false);
    }
  };

  const handleShowHistory = async (itemId: number) => {
    setActiveItemId(itemId);
    setHistoryLoading(true);
    try {
      const res = await api.nativeIntelItemRankHistory(itemId);
      setHistoryData(res);
    } catch {
      setHistoryData(null);
    } finally {
      setHistoryLoading(false);
    }
  };

  const visibleItems = filterHotlistItems(items, filter);
  const failingSources = sources.filter((s) => s.last_run_status === "failed");

  return (
    <section className="space-y-4" data-testid="native-intel-hotlist-panel">
      {/* 顶部概览与控制栏 */}
      <div className="rounded-xl border border-border/60 bg-card/70 p-4 shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="flex items-center gap-2">
              <Flame className="h-5 w-5 text-amber-500" />
              <h2 className="text-lg font-semibold text-foreground">实时热榜追踪</h2>
              <span className="rounded-full bg-primary/10 px-2 py-0.5 text-xs font-medium text-primary">
                原生热点观测
              </span>
            </div>
            <p className="mt-1 text-xs text-muted-foreground">
              实时捕捉财联社、华尔街见闻等权威热榜，追踪位次升降与真实掉榜轨迹，不产出伪造买卖信号。
            </p>
          </div>
          <button
            type="button"
            onClick={() => void handleRefresh()}
            disabled={loading || refreshing}
            className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-background px-3 py-1.5 text-sm text-muted-foreground transition-colors hover:bg-accent hover:text-foreground disabled:opacity-50"
          >
            {refreshing ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
            {refreshing ? "抓取中…" : "刷新热榜"}
          </button>
        </div>

        {/* 来源状态提示 */}
        {failingSources.length > 0 && (
          <div className="mt-3 flex items-start gap-2 rounded-lg border border-warning/30 bg-warning/5 p-3 text-xs text-warning">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
            <div>
              <span>部分热榜来源抓取异常：</span>
              <span className="font-medium">
                {failingSources.map((s) => s.name).join("、")}
              </span>
              <span className="ml-1 text-muted-foreground">
                （失败来源条目标记为未知状态，绝不混淆为真实掉榜）
              </span>
            </div>
          </div>
        )}

        {error && (
          <div className="mt-3 flex items-center gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-xs text-destructive">
            <AlertCircle className="h-4 w-4 shrink-0" />
            <span>{error}</span>
          </div>
        )}
      </div>

      {/* 筛选选项 */}
      <div className="flex flex-wrap items-center gap-2">
        {(
          [
            { key: "all", label: "全部热榜" },
            { key: "cls", label: "财联社热门" },
            { key: "wallstreetcn", label: "华尔街见闻" },
            { key: "rising", label: "位次升温" },
            { key: "new", label: "新上榜" },
          ] as const
        ).map(({ key, label }) => (
          <button
            key={key}
            type="button"
            onClick={() => setFilter(key)}
            className={cn(
              "rounded-lg px-3 py-1.5 text-xs font-medium transition-colors",
              filter === key
                ? "bg-primary text-primary-foreground shadow"
                : "bg-muted/50 text-muted-foreground hover:bg-muted hover:text-foreground",
            )}
          >
            {label}
          </button>
        ))}
        <span className="ml-auto text-xs text-muted-foreground">
          显示 {visibleItems.length} 条热榜条目
        </span>
      </div>

      {/* 列表正文 */}
      <div className="rounded-xl border border-border/60 bg-card/50">
        {loading && items.length === 0 ? (
          <div className="flex items-center justify-center p-12 text-sm text-muted-foreground">
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            正在读取热榜与排名轨迹…
          </div>
        ) : visibleItems.length === 0 ? (
          <div className="p-12 text-center text-sm text-muted-foreground">
            暂无匹配的热榜数据。
          </div>
        ) : (
          <div className="divide-y divide-border/30">
            {visibleItems.map((item) => {
              const delta = formatRankDelta(item.rank_delta, item.previous_rank);
              const badge = formatStateBadge(item.current_state);
              return (
                <div
                  key={item.item_id}
                  className="flex flex-col gap-2 p-3 transition-colors hover:bg-muted/30 sm:flex-row sm:items-center sm:justify-between"
                >
                  <div className="flex min-w-0 items-start gap-3">
                    {/* 排名徽章 */}
                    <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-muted/60 font-mono text-xs font-bold text-foreground">
                      {item.rank ?? "-"}
                    </div>

                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-1.5">
                        <a
                          href={item.url}
                          target="_blank"
                          rel="noreferrer noopener"
                          className="group inline-flex items-center gap-1 font-medium text-foreground hover:text-primary hover:underline text-sm"
                        >
                          <span className="truncate">{item.title}</span>
                          <ExternalLink className="h-3 w-3 shrink-0 opacity-0 transition-opacity group-hover:opacity-70" />
                        </a>
                      </div>

                      <div className="mt-1 flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
                        <span>{item.source_name || item.source_id}</span>
                        <span>·</span>
                        <span>首次上榜: {formatShanghaiTime(item.first_seen_at)}</span>
                        <span>·</span>
                        <span>观测: {item.observation_count}次</span>

                        {/* 实体关联（若映射到具体 A 股） */}
                        {item.entities && item.entities.length > 0 && (
                          <div className="flex items-center gap-1 pl-1">
                            {item.entities.slice(0, 3).map((entity, idx) => {
                              const code = entity.security_code;
                              return code ? (
                                <Link
                                  key={idx}
                                  to={candidateWorkspaceHref(code)}
                                  className="rounded bg-primary/10 px-1.5 py-0.5 text-primary hover:underline"
                                  data-testid={`hotlist-candidate-${code}`}
                                >
                                  {entity.term}
                                </Link>
                              ) : (
                                <span
                                  key={idx}
                                  className="rounded bg-muted px-1.5 py-0.5 text-muted-foreground"
                                >
                                  {entity.term}
                                </span>
                              );
                            })}
                          </div>
                        )}
                      </div>
                    </div>
                  </div>

                  {/* 排名状态与轨迹动作 */}
                  <div className="flex items-center gap-2.5 sm:shrink-0">
                    <div className="flex items-center gap-1.5 text-xs font-mono">
                      {delta.type === "up" && (
                        <span className="flex items-center text-emerald-500 font-medium">
                          <TrendingUp className="mr-0.5 h-3.5 w-3.5" />
                          {delta.text}
                        </span>
                      )}
                      {delta.type === "down" && (
                        <span className="text-rose-500 font-medium">{delta.text}</span>
                      )}
                      {delta.type === "new" && (
                        <span className="rounded bg-amber-500/10 px-1 py-0.5 text-[10px] text-amber-500 font-medium">
                          新上榜
                        </span>
                      )}
                      {delta.type === "flat" && <span className="text-muted-foreground">-</span>}
                    </div>

                    <span
                      className={cn(
                        "rounded border px-1.5 py-0.5 text-[10px] font-medium",
                        badge.className,
                      )}
                    >
                      {badge.label}
                    </span>

                    <button
                      type="button"
                      onClick={() => void handleShowHistory(item.item_id)}
                      className="inline-flex items-center gap-1 rounded border border-border/70 bg-background/50 px-2 py-1 text-[11px] text-muted-foreground hover:bg-muted hover:text-foreground"
                    >
                      <History className="h-3 w-3" />
                      轨迹
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* 单条目轨迹抽屉/对话框 */}
      {activeItemId !== null && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-xs">
          <div className="w-full max-w-lg rounded-xl border border-border bg-card p-5 shadow-xl">
            <div className="flex items-center justify-between border-b border-border pb-3">
              <div className="flex items-center gap-2">
                <History className="h-4 w-4 text-primary" />
                <h3 className="font-semibold text-sm">排名历史轨迹</h3>
              </div>
              <button
                type="button"
                onClick={() => {
                  setActiveItemId(null);
                  setHistoryData(null);
                }}
                className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            <div className="mt-4 max-h-[60vh] overflow-y-auto space-y-3">
              {historyLoading ? (
                <div className="flex items-center justify-center py-8 text-sm text-muted-foreground">
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  加载历史观测…
                </div>
              ) : historyData ? (
                <div className="space-y-3">
                  <div>
                    <h4 className="font-medium text-sm text-foreground">{historyData.title}</h4>
                    <p className="mt-0.5 text-xs text-muted-foreground">
                      来源: {historyData.source_name || historyData.source_id} · 状态:{" "}
                      {historyData.current_state}
                    </p>
                  </div>

                  <div className="rounded-lg border border-border/50 bg-background/50 p-3">
                    <div className="text-xs font-medium text-muted-foreground mb-2">观测点轨迹</div>
                    {historyData.observations.length === 0 ? (
                      <p className="text-xs text-muted-foreground">暂无排名观测记录。</p>
                    ) : (
                      <div className="space-y-1.5">
                        {historyData.observations.map((obs, index) => (
                          <div
                            key={index}
                            className="flex items-center justify-between text-xs font-mono"
                          >
                            <span className="text-muted-foreground">
                              {formatShanghaiTime(obs.observed_at)}
                            </span>
                            <span className="font-semibold text-primary">第 {obs.rank} 名</span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              ) : (
                <p className="py-8 text-center text-xs text-muted-foreground">未能获取该条目轨迹。</p>
              )}
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
