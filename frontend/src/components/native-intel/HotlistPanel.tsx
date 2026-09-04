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
  SlidersHorizontal,
  Sparkles,
} from "lucide-react";
import { Link } from "react-router-dom";
import { candidateWorkspaceHref } from "@/lib/candidateCampaign";
import {
  api,
  ApiError,
  type NativeIntelHotlistItem,
  type NativeIntelHotlistSource,
  type NativeIntelItemRankHistoryResponse,
  type FilterMeta,
} from "@/lib/api";
import {
  filterHotlistItems,
  formatRankDelta,
  formatStateBadge,
  formatFilterBadge,
  type HotlistFilter,
} from "@/lib/hotlistView";
import { formatShanghaiTime } from "@/lib/intelDigestView";
import { cn } from "@/lib/utils";
import { FilterSettingsModal } from "./FilterSettingsModal";

export function HotlistPanel() {
  const [items, setItems] = useState<NativeIntelHotlistItem[]>([]);
  const [sources, setSources] = useState<NativeIntelHotlistSource[]>([]);
  const [boardStatus, setBoardStatus] = useState<string>("normal");
  const [filterMeta, setFilterMeta] = useState<FilterMeta | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 一级模式：全部热榜 vs 我的关注
  const [interestMode, setInterestMode] = useState<"all" | "my_interests">("all");
  // 当在“我的关注”模式时，支持切换资讯类型：全部 / 仅热榜 / 仅RSS
  const [sourceTypeFilter, setSourceTypeFilter] = useState<"all" | "hotlist" | "rss">("hotlist");
  // 二级筛选：全部 / 升温 / 新上榜 / 来源
  const [filter, setFilter] = useState<HotlistFilter>("all");

  const [settingsOpen, setSettingsOpen] = useState(false);
  const [activeItemId, setActiveItemId] = useState<number | null>(null);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyData, setHistoryData] = useState<NativeIntelItemRankHistoryResponse | null>(null);

  const loadData = useCallback(async () => {
    try {
      setError(null);
      if (interestMode === "my_interests") {
        const res = await api.nativeIntelFilteredItems(sourceTypeFilter, "my_interests");
        setItems(res.items || []);
        setFilterMeta(res.filter_meta || null);
        setBoardStatus(res.status || "normal");
        if (sources.length === 0) {
          api.nativeIntelSources().then((s) => setSources(s.sources || [])).catch(() => {});
        }
      } else {
        const res = await api.nativeIntelHotlist(100, "all");
        setItems(res.items || []);
        setSources(res.sources || []);
        setBoardStatus(res.status || "normal");
        setFilterMeta(res.filter_meta || null);
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "读取热榜失败");
    } finally {
      setLoading(false);
    }
  }, [interestMode, sourceTypeFilter, sources.length]);

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
              <h2 className="text-lg font-semibold text-foreground">
                {boardStatus === "stale" ? "热榜数据追踪（非实时）" : "实时热榜追踪"}
              </h2>
              <span
                data-testid="hotlist-freshness-badge"
                className={cn(
                  "rounded-full px-2 py-0.5 text-xs font-medium border",
                  boardStatus === "stale"
                    ? "bg-amber-500/15 text-amber-500 border-amber-500/30"
                    : "bg-primary/10 text-primary border-transparent",
                )}
              >
                {boardStatus === "stale" ? "数据已过期 (非实时)" : "原生热点观测"}
              </span>
            </div>
            <p className="mt-1 text-xs text-muted-foreground">
              {boardStatus === "stale"
                ? "当前热榜抓取数据已超出 6 小时时效窗口，展示历史最后观测位次，不代表当前实时在榜。"
                : "实时捕捉财联社、华尔街见闻等权威热榜，追踪位次升降与真实掉榜轨迹，不产出伪造买卖信号。"}
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

        {/* 过期数据提示 */}
        {boardStatus === "stale" && (
          <div
            className="mt-3 flex items-start gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-xs text-amber-500"
            data-testid="hotlist-stale-banner"
          >
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
            <div>
              <span className="font-semibold">热榜数据已过期：</span>
              <span>
                距离最近一次成功抓取已超过 6 小时，当前展示位次均为历史末次观测，非实时在榜。请点击右侧「刷新热榜」重新抓取。
              </span>
            </div>
          </div>
        )}

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

      {/* 模式选择与筛选控制栏 */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        {/* 一级模式：全部热榜 vs 我的关注 */}
        <div className="flex items-center rounded-lg border border-border bg-background p-0.5">
          <button
            type="button"
            data-testid="hotlist-mode-all"
            onClick={() => setInterestMode("all")}
            className={cn(
              "rounded-md px-3 py-1 text-xs font-medium transition-colors",
              interestMode === "all"
                ? "bg-primary text-primary-foreground shadow-xs"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            全部热榜
          </button>
          <button
            type="button"
            data-testid="hotlist-mode-interests"
            onClick={() => setInterestMode("my_interests")}
            className={cn(
              "inline-flex items-center gap-1 rounded-md px-3 py-1 text-xs font-medium transition-colors",
              interestMode === "my_interests"
                ? "bg-primary text-primary-foreground shadow-xs"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            <Sparkles className="h-3 w-3 text-amber-400" />
            我的关注
          </button>
        </div>

        {/* 筛选设置按钮 */}
        <button
          type="button"
          data-testid="hotlist-filter-settings-btn"
          onClick={() => setSettingsOpen(true)}
          className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-card px-2.5 py-1 text-xs text-muted-foreground hover:text-foreground hover:bg-muted transition-colors"
        >
          <SlidersHorizontal className="h-3.5 w-3.5" />
          筛选设置
        </button>
      </div>

      {/* 兴趣过滤异常安全降级提示 */}
      {interestMode === "my_interests" && filterMeta?.status === "UNAVAILABLE" && (
        <div
          data-testid="filter-unavailable-card"
          className="rounded-xl border border-destructive/40 bg-destructive/10 p-4 text-sm text-destructive"
        >
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-start gap-2">
              <AlertCircle className="mt-0.5 h-5 w-5 shrink-0" />
              <div>
                <p className="font-semibold">个人兴趣过滤服务不可用</p>
                <p className="mt-1 text-xs text-muted-foreground">
                  原因：{filterMeta?.error || "过滤引擎异常"}。为保证投资信息安全，已安全停用过滤（不展示模糊/不确定数据）。
                </p>
              </div>
            </div>
            <button
              type="button"
              data-testid="switch-to-all-hotlist-btn"
              onClick={() => setInterestMode("all")}
              className="rounded-lg bg-destructive px-3 py-1.5 text-xs font-medium text-destructive-foreground hover:bg-destructive/90 transition-colors shrink-0"
            >
              切回全部热榜
            </button>
          </div>
        </div>
      )}

      {/* 当处于“我的关注”模式且服务正常时的状态说明条 */}
      {interestMode === "my_interests" && filterMeta?.status !== "UNAVAILABLE" && (
        <div
          data-testid="hotlist-filter-status-pill"
          className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-primary/20 bg-primary/5 px-3 py-2 text-xs text-primary"
        >
          <div className="flex flex-wrap items-center gap-1.5">
            <Sparkles className="h-3.5 w-3.5" />
            <span>
              当前过滤规则：
              {filterMeta?.method === "ai"
                ? "AI 智能语义匹配"
                : "本地关键词 / 正则匹配"}
            </span>
            <span className="text-muted-foreground font-mono ml-2">
              (已分类 {filterMeta?.classified_count ?? visibleItems.length} · 不相关 {filterMeta?.not_relevant_count ?? 0} · 待分类 {filterMeta?.unclassified_count ?? 0} · 失败 {filterMeta?.error_count ?? 0})
            </span>
          </div>
          <span className="font-mono font-semibold">
            匹配命中 {visibleItems.length} 条
          </span>
        </div>
      )}

      {/* 我的关注模式下：资讯类型切换（热榜 vs RSS） */}
      {interestMode === "my_interests" && filterMeta?.status !== "UNAVAILABLE" && (
        <div className="flex items-center gap-1 bg-muted/40 p-1 rounded-lg w-fit text-xs">
          <span className="text-muted-foreground px-2">资讯范围:</span>
          <button
            type="button"
            data-testid="filter-source-type-hotlist"
            onClick={() => setSourceTypeFilter("hotlist")}
            className={cn(
              "px-2.5 py-1 rounded-md font-medium transition-colors",
              sourceTypeFilter === "hotlist"
                ? "bg-background text-foreground shadow-xs"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            仅热榜
          </button>
          <button
            type="button"
            data-testid="filter-source-type-rss"
            onClick={() => setSourceTypeFilter("rss")}
            className={cn(
              "px-2.5 py-1 rounded-md font-medium transition-colors",
              sourceTypeFilter === "rss"
                ? "bg-background text-foreground shadow-xs"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            仅 RSS
          </button>
          <button
            type="button"
            data-testid="filter-source-type-all"
            onClick={() => setSourceTypeFilter("all")}
            className={cn(
              "px-2.5 py-1 rounded-md font-medium transition-colors",
              sourceTypeFilter === "all"
                ? "bg-background text-foreground shadow-xs"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            全量资讯
          </button>
        </div>
      )}

      {/* 二级筛选选项 */}
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={() => setFilter("all")}
          className={cn(
            "rounded-lg px-3 py-1.5 text-xs font-medium transition-colors",
            filter === "all"
              ? "bg-primary text-primary-foreground shadow-xs"
              : "bg-muted/50 text-muted-foreground hover:bg-muted hover:text-foreground",
          )}
        >
          全部
        </button>
        <button
          type="button"
          onClick={() => setFilter("rising")}
          className={cn(
            "rounded-lg px-3 py-1.5 text-xs font-medium transition-colors",
            filter === "rising"
              ? "bg-primary text-primary-foreground shadow-xs"
              : "bg-muted/50 text-muted-foreground hover:bg-muted hover:text-foreground",
          )}
        >
          位次升温
        </button>
        <button
          type="button"
          onClick={() => setFilter("new")}
          className={cn(
            "rounded-lg px-3 py-1.5 text-xs font-medium transition-colors",
            filter === "new"
              ? "bg-primary text-primary-foreground shadow-xs"
              : "bg-muted/50 text-muted-foreground hover:bg-muted hover:text-foreground",
          )}
        >
          新上榜
        </button>

        {/* 动态来源选择器 */}
        <div className="flex items-center gap-1.5 pl-2 border-l border-border/60">
          <span className="text-xs text-muted-foreground">来源:</span>
          <select
            aria-label="热榜来源筛选"
            data-testid="hotlist-source-select"
            value={filter.startsWith("source:") ? filter.slice("source:".length) : ""}
            onChange={(e) => {
              const val = e.target.value;
              if (val) {
                setFilter(`source:${val}`);
              } else {
                setFilter("all");
              }
            }}
            className={cn(
              "rounded-lg border border-border bg-background px-2.5 py-1 text-xs text-foreground transition-colors focus:border-primary focus:outline-none",
              filter.startsWith("source:") && "border-primary font-medium text-primary",
            )}
          >
            <option value="">全部来源</option>
            {sources.map((s) => (
              <option key={s.source_id} value={s.source_id}>
                {s.name}
              </option>
            ))}
          </select>
        </div>

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
          interestMode === "my_interests" ? (
            <div
              className="p-12 text-center text-sm space-y-3"
              data-testid="hotlist-empty-interests"
            >
              <p className="text-muted-foreground">
                当前个人关注规则未匹配到任何热榜条目。
              </p>
              <button
                type="button"
                onClick={() => setSettingsOpen(true)}
                className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-background px-3 py-1.5 text-xs text-primary hover:bg-muted font-medium transition-colors"
              >
                <SlidersHorizontal className="h-3.5 w-3.5" />
                调整兴趣与关键词规则
              </button>
            </div>
          ) : (
            <div className="p-12 text-center text-sm text-muted-foreground">
              暂无匹配的热榜数据。
            </div>
          )
        ) : (
          <div className="divide-y divide-border/30">
            {visibleItems.map((item) => {
              const delta = formatRankDelta(
                item.rank_delta,
                item.previous_rank,
                item.current_state,
                item.rank,
              );
              const badge = formatStateBadge(item.current_state);
              const filterBadge = formatFilterBadge(item.filter_match);
              return (
                <div
                  key={item.item_id}
                  className="flex flex-col gap-2 p-3 transition-colors hover:bg-muted/30 sm:flex-row sm:items-center sm:justify-between"
                >
                  <div className="flex min-w-0 items-start gap-3">
                    {/* 排名徽章 */}
                    <div
                      className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-muted/60 font-mono text-xs font-bold text-foreground"
                      title={
                        item.source_type === "rss" || item.rank == null
                          ? "RSS 资讯 (无排名)"
                          : item.current_state === "DISABLED"
                          ? `末次 #${item.rank ?? "-"} (来源已停用)`
                          : item.current_state === "STALE"
                          ? `末次 #${item.rank ?? "-"} (数据已过期)`
                          : undefined
                      }
                    >
                      {item.source_type === "rss" || item.rank == null
                        ? "RSS"
                        : item.current_state === "DISABLED" || item.current_state === "STALE"
                        ? "—"
                        : (item.rank ?? "-")}
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

                        {/* 兴趣标签 / 关键词分组徽章 */}
                        {filterBadge &&
                          filterBadge.labels.map((lbl, i) => (
                            <span
                              key={i}
                              data-testid="hotlist-item-filter-badge"
                              className={cn(
                                "rounded px-1.5 py-0.2 text-[10px] font-medium border",
                                filterBadge.className,
                              )}
                            >
                              {lbl}
                            </span>
                          ))}
                      </div>

                      <div className="mt-1 flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
                        <span>{item.source_name || item.source_id}</span>
                        {item.current_state === "DISABLED" && item.rank != null && (
                          <>
                            <span>·</span>
                            <span className="text-amber-500/80">末次 #{item.rank} (已停用)</span>
                          </>
                        )}
                        {item.current_state === "STALE" && item.rank != null && (
                          <>
                            <span>·</span>
                            <span className="text-amber-500/80 font-medium">末次 #{item.rank} (已过期)</span>
                          </>
                        )}
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
                          <TrendingUp className="mr-0.5 h-3 w-3" />
                          {delta.text}
                        </span>
                      )}
                      {delta.type === "down" && (
                        <span className="text-rose-500 font-medium">{delta.text}</span>
                      )}
                      {delta.type === "new" && (
                        <span className="rounded bg-primary/15 px-1.5 py-0.5 text-[10px] text-primary font-medium">
                          新上榜
                        </span>
                      )}
                      {delta.type === "flat" && (
                        <span className="text-muted-foreground">-</span>
                      )}
                    </div>

                    <span
                      data-testid={`hotlist-state-${item.item_id}`}
                      className={cn(
                        "rounded px-2 py-0.5 text-xs font-medium border",
                        badge.className,
                      )}
                    >
                      {badge.label}
                    </span>

                    {item.source_type !== "rss" && item.rank != null && (
                      <button
                        type="button"
                        onClick={() => void handleShowHistory(item.item_id)}
                        className="inline-flex items-center gap-1 rounded-md border border-border/80 bg-background/50 px-2 py-1 text-xs text-muted-foreground hover:bg-accent hover:text-foreground transition-colors"
                      >
                        <History className="h-3 w-3" />
                        轨迹
                      </button>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* 筛选设置弹窗 */}
      <FilterSettingsModal
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        onSaved={() => void loadData()}
      />

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
