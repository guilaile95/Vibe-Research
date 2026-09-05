import { useCallback, useEffect, useMemo, useRef, useState } from "react";
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
  type NativeIntelConfig,
} from "@/lib/api";
import { Rss } from "lucide-react";
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
  const [rssItems, setRssItems] = useState<NativeIntelHotlistItem[]>([]);
  const [standaloneItems, setStandaloneItems] = useState<NativeIntelHotlistItem[]>([]);
  const [config, setConfig] = useState<NativeIntelConfig | null>(null);
  const [sources, setSources] = useState<NativeIntelHotlistSource[]>([]);
  const [hotlistStatus, setHotlistStatus] = useState<string>("normal");
  const [rssStatus, setRssStatus] = useState<string>("normal");
  const [hotlistFilterMeta, setHotlistFilterMeta] = useState<FilterMeta | null>(null);
  const [rssFilterMeta, setRssFilterMeta] = useState<FilterMeta | null>(null);
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

  const reqIdRef = useRef(0);

  const loadData = useCallback(async () => {
    const currentReqId = ++reqIdRef.current;
    try {
      setError(null);
      const [cfg, standaloneRes] = await Promise.all([
        api.nativeIntelConfig().catch(() => null),
        api.nativeIntelStandalone().catch(() => ({ items: [] as NativeIntelHotlistItem[] })),
      ]);
      if (currentReqId !== reqIdRef.current) return;
      if (cfg) setConfig(cfg);
      setStandaloneItems(standaloneRes.items || []);

      if (interestMode === "my_interests") {
        const [hotlistRes, rssRes] = await Promise.all([
          api.nativeIntelFilteredItems("hotlist", "my_interests").catch((err) => ({
            status: "unavailable" as const,
            items: [] as NativeIntelHotlistItem[],
            sources: [] as NativeIntelHotlistSource[],
            filter_meta: { status: "UNAVAILABLE" as const, error: String(err?.message || err || "热榜过滤服务异常") },
          })),
          api.nativeIntelFilteredItems("rss", "my_interests").catch((err) => ({
            status: "unavailable" as const,
            items: [] as NativeIntelHotlistItem[],
            sources: [] as NativeIntelHotlistSource[],
            filter_meta: { status: "UNAVAILABLE" as const, error: String(err?.message || err || "RSS 过滤服务异常") },
          })),
        ]);
        if (currentReqId !== reqIdRef.current) return;
        setItems(hotlistRes.items || []);
        setRssItems(rssRes.items || []);
        setHotlistFilterMeta(hotlistRes.filter_meta || null);
        setRssFilterMeta(rssRes.filter_meta || null);
        setHotlistStatus(hotlistRes.status || "normal");
        setRssStatus(rssRes.status || "normal");
        api.nativeIntelSources().then((s) => {
          if (currentReqId === reqIdRef.current) setSources(s.sources || []);
        }).catch(() => {});
      } else {
        const [hotlistRes, rssRes] = await Promise.all([
          api.nativeIntelHotlist(100, "all"),
          api.nativeIntelFilteredItems("rss", "all"),
        ]);
        if (currentReqId !== reqIdRef.current) return;
        setItems(hotlistRes.items || []);
        setRssItems(rssRes.items || []);
        setSources(hotlistRes.sources || []);
        setHotlistStatus(hotlistRes.status || "normal");
        setRssStatus(rssRes.status || "normal");
        setHotlistFilterMeta(hotlistRes.filter_meta || null);
        setRssFilterMeta(rssRes.filter_meta || null);
      }
    } catch (err) {
      if (currentReqId !== reqIdRef.current) return;
      setError(err instanceof ApiError ? err.message : "读取资讯失败");
    } finally {
      if (currentReqId === reqIdRef.current) {
        setLoading(false);
      }
    }
  }, [interestMode]);

  const effectiveFilterMeta = useMemo(() => {
    if (interestMode !== "my_interests") return hotlistFilterMeta;
    if (sourceTypeFilter === "hotlist") return hotlistFilterMeta;
    if (sourceTypeFilter === "rss") return rssFilterMeta;

    // "all": 若任一侧失败或两者都失败，UNAVAILABLE card 必须诚实暴露失败信息，不得吞掉任一侧错误
    const hotlistFailed = hotlistFilterMeta?.status === "UNAVAILABLE";
    const rssFailed = rssFilterMeta?.status === "UNAVAILABLE";
    if (hotlistFailed && rssFailed) {
      return {
        status: "UNAVAILABLE" as const,
        error: `热榜与 RSS 过滤均不可用: [热榜: ${hotlistFilterMeta?.error || "异常"}] [RSS: ${rssFilterMeta?.error || "异常"}]`,
      };
    }
    if (hotlistFailed) {
      return {
        status: "UNAVAILABLE" as const,
        error: `热榜过滤不可用: ${hotlistFilterMeta?.error || "异常"}`,
      };
    }
    if (rssFailed) {
      return {
        status: "UNAVAILABLE" as const,
        error: `RSS 过滤不可用: ${rssFilterMeta?.error || "异常"}`,
      };
    }
    if (!hotlistFilterMeta && !rssFilterMeta) return null;
    return {
      status: "NORMAL" as const,
      method: hotlistFilterMeta?.method || rssFilterMeta?.method || "keyword",
      profile_name: hotlistFilterMeta?.profile_name || rssFilterMeta?.profile_name,
      classified_count: (hotlistFilterMeta?.classified_count ?? 0) + (rssFilterMeta?.classified_count ?? 0),
      not_relevant_count: (hotlistFilterMeta?.not_relevant_count ?? 0) + (rssFilterMeta?.not_relevant_count ?? 0),
      unclassified_count: (hotlistFilterMeta?.unclassified_count ?? 0) + (rssFilterMeta?.unclassified_count ?? 0),
      error_count: (hotlistFilterMeta?.error_count ?? 0) + (rssFilterMeta?.error_count ?? 0),
    };
  }, [interestMode, sourceTypeFilter, hotlistFilterMeta, rssFilterMeta]);

  const boardStatus = useMemo(() => {
    if (sourceTypeFilter === "hotlist") return hotlistStatus;
    if (sourceTypeFilter === "rss") return rssStatus;
    if (hotlistStatus === "stale" || rssStatus === "stale") return "stale";
    if (hotlistStatus === "unavailable" || rssStatus === "unavailable") return "unavailable";
    if (hotlistStatus === "partial" || rssStatus === "partial") return "partial";
    return "normal";
  }, [sourceTypeFilter, hotlistStatus, rssStatus]);

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

      {/* 我的关注模式下：资讯范围选择器（热榜 vs RSS vs 全量）始终可见可用，即使处于 UNAVAILABLE 状态 */}
      {interestMode === "my_interests" && (
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

      {/* 兴趣过滤异常安全降级提示 */}
      {interestMode === "my_interests" && effectiveFilterMeta?.status === "UNAVAILABLE" && (
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
                  原因：{effectiveFilterMeta?.error || "过滤引擎异常"}。为保证投资信息安全，已安全停用过滤（不展示模糊/不确定数据）。
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
      {interestMode === "my_interests" && effectiveFilterMeta?.status !== "UNAVAILABLE" && (
        <div
          data-testid="hotlist-filter-status-pill"
          className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-primary/20 bg-primary/5 px-3 py-2 text-xs text-primary"
        >
          <div className="flex flex-wrap items-center gap-1.5">
            <Sparkles className="h-3.5 w-3.5" />
            <span>
              当前过滤规则：
              {effectiveFilterMeta?.method === "ai"
                ? "AI 智能语义匹配"
                : "本地关键词 / 正则匹配"}
            </span>
            <span className="text-muted-foreground font-mono ml-2">
              (已分类 {effectiveFilterMeta?.classified_count ?? (visibleItems.length + (sourceTypeFilter === "all" ? rssItems.length : 0))} · 不相关 {effectiveFilterMeta?.not_relevant_count ?? 0} · 待分类 {effectiveFilterMeta?.unclassified_count ?? 0} · 失败 {effectiveFilterMeta?.error_count ?? 0})
            </span>
          </div>
          <span className="font-mono font-semibold">
            匹配命中 {sourceTypeFilter === "rss" ? rssItems.length : sourceTypeFilter === "hotlist" ? visibleItems.length : visibleItems.length + rssItems.length} 条
          </span>
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

      {/* 区域渲染逻辑：支持 hotlist, rss, standalone 按照 region_order 动态排序 */}
      {(() => {
        const isUnavailable = interestMode === "my_interests" && effectiveFilterMeta?.status === "UNAVAILABLE";
        const isHotlistEnabled =
          !isUnavailable &&
          config?.regions_enabled?.hotlist !== false &&
          (interestMode !== "my_interests" || sourceTypeFilter === "all" || sourceTypeFilter === "hotlist");
        const isRssEnabled =
          !isUnavailable &&
          config?.regions_enabled?.rss !== false &&
          (interestMode !== "my_interests" || sourceTypeFilter === "all" || sourceTypeFilter === "rss");
        const isStandaloneEnabled =
          config?.regions_enabled?.standalone !== false && config?.standalone_enabled !== false;
        const allRegionsConfigDisabled =
          Boolean(config) &&
          config?.regions_enabled?.hotlist === false &&
          config?.regions_enabled?.rss === false &&
          (config?.regions_enabled?.standalone === false || config?.standalone_enabled === false);

        if (allRegionsConfigDisabled) {
          return (
            <div
              data-testid="all-regions-disabled-empty"
              className="rounded-xl border border-border/60 bg-card/50 p-12 text-center text-sm text-muted-foreground space-y-2"
            >
              <p className="font-medium text-foreground">
                当前所有资讯展示区域均已关闭，可到设置中重新开启。
              </p>
              <Link to="/settings" className="text-primary hover:underline text-xs inline-block">
                前往系统设置
              </Link>
            </div>
          );
        }

        const renderItemRow = (
          item: NativeIntelHotlistItem,
          testIdPrefix: string,
        ) => {
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
              data-testid={`${testIdPrefix}-item`}
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
                    {item.first_seen_at && (
                      <>
                        <span>·</span>
                        <span>首次上榜: {formatShanghaiTime(item.first_seen_at)}</span>
                      </>
                    )}
                    {item.published_at && (
                      <>
                        <span>·</span>
                        <span>发布: {formatShanghaiTime(item.published_at)}</span>
                      </>
                    )}
                    <span>·</span>
                    <span>观测: {item.observation_count ?? 1}次</span>

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
        };

        const activeOrder = (config?.region_order || ["hotlist", "rss", "standalone"]).filter(
          (r) => ["hotlist", "rss", "standalone"].includes(r),
        );

        return (
          <div className="space-y-4">
            {activeOrder.map((regionKey) => {
              if (regionKey === "hotlist" && isHotlistEnabled) {
                return (
                  <div
                    key="hotlist"
                    data-testid="display-region-hotlist"
                    className="rounded-xl border border-border/60 bg-card/50"
                  >
                    <div className="flex items-center justify-between border-b border-border/40 p-3 bg-muted/20">
                      <div className="flex items-center gap-2">
                        <Flame className="h-4 w-4 text-amber-500" />
                        <h3 className="font-semibold text-sm">实时热榜</h3>
                        <span className="rounded-full bg-amber-500/10 text-amber-500 border border-amber-500/20 px-2 py-0.2 text-[10px]">
                          Hotlist
                        </span>
                      </div>
                      <span className="text-xs text-muted-foreground">
                        共 {visibleItems.length} 条
                      </span>
                    </div>

                    {loading && items.length === 0 ? (
                      <div className="flex items-center justify-center p-8 text-sm text-muted-foreground">
                        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                        正在读取热榜与排名轨迹…
                      </div>
                    ) : visibleItems.length === 0 ? (
                      interestMode === "my_interests" ? (
                        <div
                          className="p-8 text-center text-sm space-y-2"
                          data-testid="hotlist-empty-interests"
                        >
                          <p className="text-muted-foreground">
                            当前个人关注规则未匹配到任何热榜条目。
                          </p>
                        </div>
                      ) : (
                        <div className="p-8 text-center text-sm text-muted-foreground">
                          暂无匹配的热榜数据。
                        </div>
                      )
                    ) : (
                      <div className="divide-y divide-border/30">
                        {visibleItems.map((item) => renderItemRow(item, "hotlist"))}
                      </div>
                    )}
                  </div>
                );
              }

              if (regionKey === "rss" && isRssEnabled) {
                return (
                  <div
                    key="rss"
                    data-testid="display-region-rss"
                    className="rounded-xl border border-border/60 bg-card/50"
                  >
                    <div className="flex items-center justify-between border-b border-border/40 p-3 bg-muted/20">
                      <div className="flex items-center gap-2">
                        <Rss className="h-4 w-4 text-primary" />
                        <h3 className="font-semibold text-sm">RSS 资讯</h3>
                        <span className="rounded-full bg-primary/10 text-primary border border-primary/20 px-2 py-0.2 text-[10px]">
                          RSS
                        </span>
                      </div>
                      <span className="text-xs text-muted-foreground">
                        共 {rssItems.length} 条
                      </span>
                    </div>

                    {loading && rssItems.length === 0 ? (
                      <div className="flex items-center justify-center p-8 text-sm text-muted-foreground">
                        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                        正在读取 RSS 资讯…
                      </div>
                    ) : rssItems.length === 0 ? (
                      <div className="p-8 text-center text-sm text-muted-foreground">
                        暂无符合条件的 RSS 资讯。
                      </div>
                    ) : (
                      <div className="divide-y divide-border/30">
                        {rssItems.map((item) => renderItemRow(item, "rss"))}
                      </div>
                    )}
                  </div>
                );
              }

              if (regionKey === "standalone" && isStandaloneEnabled) {
                return (
                  <div
                    key="standalone"
                    data-testid="display-region-standalone"
                    className="rounded-xl border border-primary/30 bg-card/50"
                  >
                    <div className="flex items-center justify-between border-b border-border/40 p-3 bg-primary/5">
                      <div className="flex items-center gap-2">
                        <Sparkles className="h-4 w-4 text-purple-400" />
                        <h3 className="font-semibold text-sm">重点独立展示区</h3>
                        <span className="rounded-full bg-purple-500/15 text-purple-400 border border-purple-500/30 px-2 py-0.2 text-[10px] font-medium">
                          免过滤
                        </span>
                      </div>
                      <span className="text-xs text-muted-foreground">
                        共 {standaloneItems.length} 条
                      </span>
                    </div>

                    {standaloneItems.length === 0 ? (
                      <div className="p-8 text-center text-sm text-muted-foreground">
                        独立展示区暂无条目（可在设置中选择重点来源）。
                      </div>
                    ) : (
                      <div className="divide-y divide-border/30">
                        {standaloneItems.map((item) => renderItemRow(item, "standalone"))}
                      </div>
                    )}
                  </div>
                );
              }

              return null;
            })}
          </div>
        );
      })()}

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
