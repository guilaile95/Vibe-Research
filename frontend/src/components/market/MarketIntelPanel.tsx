import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  Activity,
  AlertCircle,
  Clock,
  Database,
  ExternalLink,
  Lightbulb,
  Loader2,
  RefreshCw,
  Sparkles,
  TrendingUp,
  XCircle,
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { SaveNoteButton } from "@/components/ui/SaveNoteButton";
import {
  api,
  ApiError,
  type Industry,
  type NativeIntelItemsResponse,
  type NativeIntelStatus,
  type NativeIntelTrending,
  type RadarData,
} from "@/lib/api";
import { runIntelDigestGeneration } from "@/lib/intelDigestOrchestrator";
import { formatShanghaiTime } from "@/lib/intelDigestView";
import { hasLlm } from "@/lib/llm";
import {
  deriveMarketIntelStatus,
  knownCountText,
  knownHistoryItemCount,
  sourceHealthText,
  trendEmptyReason,
  TREND_EMPTY_LABELS,
} from "@/lib/marketIntelStatus";
import { cn } from "@/lib/utils";
import { selectResearchSourceItems } from "@/lib/marketIntelBrief";
import { ArticleAssociation } from "@/components/native-intel/ArticleAssociation";
import { candidateWorkspaceHref } from "@/lib/candidateCampaign";

export type DigestPhase = "idle" | "generating" | "saving" | "saved" | "cancelled" | "error" | "save_failed" | "empty";

interface Digest {
  phase?: DigestPhase;
  loading?: boolean;
  saving?: boolean;
  text?: string;
  err?: string;
  needKey?: boolean;
  saved?: boolean;
  deduped?: boolean;
  digest_date?: string;
}

const errorMessage = (cause: unknown, fallback: string) => cause instanceof ApiError ? cause.message : fallback;

interface MarketIntelPanelProps {
  embedded?: boolean;
  compact?: boolean;
}

export default function MarketIntelPanel({ embedded = false, compact = false }: MarketIntelPanelProps) {
  const [radar, setRadar] = useState<RadarData | null>(null);
  const [runtime, setRuntime] = useState<NativeIntelStatus | null>(null);
  const [items, setItems] = useState<NativeIntelItemsResponse | null>(null);
  const [trending, setTrending] = useState<NativeIntelTrending | null>(null);
  const [nativeError, setNativeError] = useState<string | null>(null);
  const [radarError, setRadarError] = useState<string | null>(null);
  const [active, setActive] = useState("ai");
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [digests, setDigests] = useState<Record<string, Digest>>({});
  const [bulk, setBulk] = useState<{ running: boolean; done: number; total: number }>({ running: false, done: 0, total: 0 });

  const isMountedRef = useRef(true);
  const generationIdsRef = useRef<Record<string, number>>({});
  const abortControllersRef = useRef<Record<string, AbortController>>({});
  const latestLoadIdsRef = useRef<Record<string, number>>({});
  const sectorStateVersionRef = useRef<Record<string, number>>({});
  const generatingSectorsRef = useRef<Set<string>>(new Set());

  const readNative = useCallback(async () => {
    const [nextRuntime, nextItems, nextTrending] = await Promise.all([
      api.nativeIntelStatus(),
      api.nativeIntelItems(40),
      api.nativeIntelTrending(24, 20),
    ]);
    if (!isMountedRef.current) return;
    setRuntime(nextRuntime);
    setItems(nextItems);
    setTrending(nextTrending);
  }, []);

  useEffect(() => {
    isMountedRef.current = true;

    const load = async () => {
      setLoading(true);
      const [nativeResult, radarResult] = await Promise.allSettled([readNative(), api.radar()]);
      if (!isMountedRef.current) return;

      setNativeError(nativeResult.status === "rejected" ? errorMessage(nativeResult.reason, "公开资讯读取失败") : null);
      if (radarResult.status === "fulfilled") {
        setRadar(radarResult.value);
        setRadarError(null);
      } else {
        setRadarError(errorMessage(radarResult.reason, "赛道要点读取失败"));
      }
      setLoading(false);
    };

    void load();
    return () => {
      isMountedRef.current = false;
      Object.values(abortControllersRef.current).forEach((controller) => controller.abort());
    };
  }, [readNative]);

  const refresh = async () => {
    setRefreshing(true);
    setNativeError(null);
    setRadarError(null);

    const [nativeResult, radarResult] = await Promise.allSettled([
      api.nativeIntelRefresh(),
      api.radarRefresh(),
    ]);
    if (!isMountedRef.current) return;

    if (radarResult.status === "fulfilled") {
      setRadar(radarResult.value);
    } else {
      setRadarError(errorMessage(radarResult.reason, "赛道要点刷新失败"));
    }

    if (nativeResult.status === "fulfilled") {
      if (!nativeResult.value.accepted) {
        setNativeError(nativeResult.value.error || "公开资讯刷新失败：刷新请求未被接受");
      } else if (nativeResult.value.status === "unavailable") {
        setNativeError(nativeResult.value.error || "公开资讯刷新后不可用");
      }
      try {
        await readNative();
      } catch (cause) {
        if (isMountedRef.current) setNativeError(errorMessage(cause, "公开资讯状态读取失败"));
      }
    } else {
      setNativeError(errorMessage(nativeResult.reason, "公开资讯刷新失败"));
    }

    if (isMountedRef.current) setRefreshing(false);
  };

  const fetchLatestDigest = useCallback(async (sectorKey: string) => {
    const loadId = (latestLoadIdsRef.current[sectorKey] || 0) + 1;
    latestLoadIdsRef.current[sectorKey] = loadId;
    const capturedVersion = sectorStateVersionRef.current[sectorKey] || 0;

    try {
      const res = await api.getIntelDigestLatest(sectorKey);
      if (!isMountedRef.current || latestLoadIdsRef.current[sectorKey] !== loadId) return;
      if ((sectorStateVersionRef.current[sectorKey] || 0) !== capturedVersion) return;

      const savedDigest = res?.digest;
      if (savedDigest) {
        setDigests((current) => {
          const currentPhase = current[sectorKey]?.phase;
          if (currentPhase && currentPhase !== "idle") return current;
          return {
            ...current,
            [sectorKey]: {
              phase: "saved",
              text: savedDigest.summary_text,
              digest_date: savedDigest.digest_date,
              saved: true,
            },
          };
        });
      }
    } catch {
      // Saved digest lookup is optional; the live sector remains usable.
    }
  }, []);

  const industries: Industry[] = radar?.industries || [];
  const currentIndustry = industries.find((industry) => industry.key === active) || industries[0];
  const hasRadarData = Boolean(radar?.generated_at);

  useEffect(() => {
    if (currentIndustry?.key) void fetchLatestDigest(currentIndustry.key);
  }, [currentIndustry?.key, fetchLatestDigest]);

  const cancelGeneration = (sectorKey: string) => {
    if (digests[sectorKey]?.phase === "saving") return;
    sectorStateVersionRef.current[sectorKey] = (sectorStateVersionRef.current[sectorKey] || 0) + 1;

    abortControllersRef.current[sectorKey]?.abort();
    delete abortControllersRef.current[sectorKey];
    generatingSectorsRef.current.delete(sectorKey);
    setDigests((current) => ({
      ...current,
      [sectorKey]: {
        ...current[sectorKey],
        phase: "cancelled",
        loading: false,
        saving: false,
        err: "生成已取消",
      },
    }));
  };

  const generateDigest = async (industry: Industry) => {
    if (!hasLlm()) {
      setDigests((current) => ({ ...current, [industry.key]: { needKey: true } }));
      return;
    }
    if (bulk.running || generatingSectorsRef.current.has(industry.key)) return;

    abortControllersRef.current[industry.key]?.abort();
    sectorStateVersionRef.current[industry.key] = (sectorStateVersionRef.current[industry.key] || 0) + 1;

    const controller = new AbortController();
    abortControllersRef.current[industry.key] = controller;
    generatingSectorsRef.current.add(industry.key);

    const generationId = (generationIdsRef.current[industry.key] || 0) + 1;
    generationIdsRef.current[industry.key] = generationId;
    setDigests((current) => ({
      ...current,
      [industry.key]: { phase: "generating", loading: true, saving: false, err: undefined, needKey: false },
    }));

    const result = await runIntelDigestGeneration({
      industry,
      signal: controller.signal,
      generationId,
      getCurrentGenerationId: () => generationIdsRef.current[industry.key] || 0,
      isMounted: () => isMountedRef.current,
      onPhaseChange: (phase) => {
        if (isMountedRef.current && generationIdsRef.current[industry.key] === generationId) {
          setDigests((current) => ({
            ...current,
            [industry.key]: {
              ...current[industry.key],
              phase,
              loading: true,
              saving: phase === "saving",
            },
          }));
        }
      },
      onDelta: (text) => {
        if (isMountedRef.current && generationIdsRef.current[industry.key] === generationId) {
          setDigests((current) => ({ ...current, [industry.key]: { ...current[industry.key], text } }));
        }
      },
    });

    generatingSectorsRef.current.delete(industry.key);
    if (!isMountedRef.current || generationIdsRef.current[industry.key] !== generationId) return;

    if (result.status === "cancelled") {
      setDigests((current) => ({
        ...current,
        [industry.key]: { ...current[industry.key], phase: "cancelled", loading: false, saving: false, err: "生成已取消" },
      }));
    } else if (result.status === "saved" || result.status === "deduped") {
      setDigests((current) => ({
        ...current,
        [industry.key]: {
          phase: "saved",
          loading: false,
          saving: false,
          text: result.summaryText,
          saved: true,
          deduped: result.status === "deduped",
          digest_date: result.digest?.digest_date,
        },
      }));
    } else if (result.status === "save_failed") {
      setDigests((current) => ({
        ...current,
        [industry.key]: {
          phase: "save_failed",
          loading: false,
          saving: false,
          text: result.summaryText,
          err: result.error || "保存失败",
        },
      }));
    } else if (result.status === "unavailable") {
      setDigests((current) => ({
        ...current,
        [industry.key]: { phase: "empty", loading: false, saving: false, err: result.error || "没有可用于摘要的有效带日期资讯" },
      }));
    } else if (result.status === "error") {
      setDigests((current) => ({
        ...current,
        [industry.key]: { phase: "error", loading: false, saving: false, err: result.error || "生成失败" },
      }));
    } else if (result.status === "empty") {
      setDigests((current) => ({
        ...current,
        [industry.key]: { phase: "empty", loading: false, saving: false, err: "生成结果为空" },
      }));
    }
  };

  const generateAll = async () => {
    if (!hasLlm()) {
      if (currentIndustry) setDigests((current) => ({ ...current, [currentIndustry.key]: { needKey: true } }));
      return;
    }
    if (bulk.running) return;

    const targets = industries.filter((industry) => industry.items.length > 0 && !generatingSectorsRef.current.has(industry.key));
    setBulk({ running: true, done: 0, total: targets.length });
    for (const industry of targets) {
      if (!isMountedRef.current) break;
      await generateDigest(industry);
      setBulk((current) => ({ ...current, done: current.done + 1 }));
    }
    if (isMountedRef.current) setBulk((current) => ({ ...current, running: false }));
  };

  const visibleItems = items?.items ?? [];
  const entities = trending?.entities ?? [];
  const trendEmpty = trendEmptyReason({ loading, trending });
  const digest = currentIndustry ? digests[currentIndustry.key] : undefined;
  const nativeStatuses = [runtime?.status, items?.status, trending?.status].filter((status): status is NativeIntelStatus["status"] => Boolean(status));
  const hasNativeData = nativeStatuses.some((status) => status !== "unavailable");
  const nativeStatus = nativeStatuses.length === 0
    ? undefined
    : !hasNativeData
      ? "unavailable"
      : nativeStatuses.some((status) => status === "partial" || status === "unavailable")
        ? "partial"
        : nativeStatuses.some((status) => status === "stale")
          ? "stale"
          : "normal";
  const hasAnyData = hasNativeData || hasRadarData;
  const radarFailedSources = radar?.stats.failed_sources ?? 0;
  const overallStatus = deriveMarketIntelStatus({
    loading,
    hasNativeData,
    hasRadarData,
    nativeStatus,
    nativeError,
    radarError,
    radarFailedSources,
  });
  const statusLabel = {
    loading: "读取中",
    normal: "NORMAL · 可用",
    partial: "PARTIAL · 部分可用",
    stale: "STALE · 历史可用",
    unavailable: "UNAVAILABLE · 不可用",
  }[overallStatus];
  const updatedAt = runtime?.last_run?.finished_at || runtime?.last_run?.started_at || runtime?.generated_at;
  const nativeStatusNotice = !nativeError && nativeStatus && nativeStatus !== "normal"
    ? runtime?.error || {
      partial: "部分公开来源不可用，其他来源和本地历史仍可读取",
      stale: "公开资讯历史可用，但抓取状态已过期",
      unavailable: "公开资讯当前不可用",
    }[nativeStatus]
    : null;

  const sourceStats = loading && !hasAnyData ? (
    <p className="mt-3 flex items-center gap-2 text-xs text-muted-foreground"><Loader2 className="h-3.5 w-3.5 animate-spin" />正在读取市场情报…</p>
  ) : (
    <div className="mt-3 grid gap-2 text-xs sm:grid-cols-2 lg:grid-cols-4">
      <div data-testid="market-intel-stat-history" className="rounded-lg border border-border/50 bg-background/60 p-2"><Database className="mr-1 inline h-3.5 w-3.5" />历史资讯 {knownCountText(knownHistoryItemCount({ store: runtime?.store, items }))}</div>
      <div data-testid="market-intel-stat-sources" className="rounded-lg border border-border/50 bg-background/60 p-2">公开来源 {sourceHealthText(runtime?.sources)}</div>
      <div data-testid="market-intel-stat-radar" className="rounded-lg border border-border/50 bg-background/60 p-2">赛道来源 {knownCountText(radar?.stats.total_sources)} · {knownCountText(radar?.stats.industries)} 赛道</div>
      <div className="rounded-lg border border-border/50 bg-background/60 p-2"><Clock className="mr-1 inline h-3.5 w-3.5" />{formatShanghaiTime(updatedAt || radar?.generated_at)}</div>
    </div>
  );
  const trendPanel = (
    <section className="rounded-xl border border-border/60 bg-card/50 p-4">
      <h3 className="flex items-center gap-1.5 text-sm font-semibold text-foreground"><TrendingUp className="h-4 w-4 text-primary" />近 24 小时关注趋势</h3>
      {entities.length ? (
        <div className="mt-3 flex flex-wrap gap-2" aria-label="近 24 小时关注趋势">
          {entities.slice(0, 20).map((entity) => {
            const candidateCode = /^\d{6}$/.test(entity.security_code || "") ? entity.security_code : null;
            return (
              <span key={`${entity.term_kind}:${entity.security_code || ""}:${entity.term}`} className="rounded-full bg-primary/10 px-2.5 py-1 text-xs text-primary">
                {entity.term}<span className="ml-1 text-muted-foreground">· {entity.item_count} 条{entity.delta ? ` · ${entity.delta > 0 ? "+" : ""}${entity.delta}` : ""}</span>
                {candidateCode && (
                  <Link
                    to={candidateWorkspaceHref(candidateCode)}
                    className="ml-2 font-medium hover:underline"
                    data-testid={`market-intel-candidate-${candidateCode}`}
                  >
                    候选研究
                  </Link>
                )}
              </span>
            );
          })}
        </div>
      ) : (
        <p
          className="mt-3 text-xs text-muted-foreground"
          data-testid="market-intel-trending-empty"
          data-trend-empty-reason={trendEmpty}
        >
          {TREND_EMPTY_LABELS[trendEmpty]}
        </p>
      )}
      <p className="mt-2 text-[10px] text-muted-foreground/70">趋势仅使用本地观察次数、来源数和环比，不补伪造排名。</p>
    </section>
  );
  const researchItems = selectResearchSourceItems(visibleItems);

  return (
    <section className={compact ? "space-y-3" : "space-y-5"} data-testid="market-intel-panel">
      <div className="rounded-xl border border-border/60 bg-card/70 p-4 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <Activity className="h-5 w-5 text-primary" />
              <h2 className="text-lg font-semibold text-foreground">{compact ? "研究资讯" : "市场情报"}</h2>
              <span className={cn(
                "rounded-full px-2 py-0.5 text-[10px] font-medium",
                overallStatus === "normal" && "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400",
                overallStatus === "loading" && "bg-muted text-muted-foreground",
                overallStatus === "partial" && "bg-warning/10 text-warning",
                overallStatus === "stale" && "bg-amber-500/10 text-amber-600 dark:text-amber-400",
                overallStatus === "unavailable" && "bg-destructive/10 text-destructive",
              )}>{statusLabel}</span>
            </div>
            <p className="mt-1 text-xs text-muted-foreground">来源状态与本地保存历史 · 更新时间 {formatShanghaiTime(updatedAt || radar?.generated_at)}</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {(embedded || compact) && (
              <Link
                to="/intel"
                className="text-xs text-primary hover:underline"
                data-testid="today-intel-link"
              >
                进入完整资讯中心
              </Link>
            )}
            <button
              type="button"
              onClick={() => void refresh()}
              disabled={loading || refreshing || bulk.running}
              className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-background px-3 py-1.5 text-sm text-muted-foreground transition-colors hover:bg-accent hover:text-foreground disabled:opacity-50"
            >
              {refreshing ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
              {refreshing ? "刷新中…" : "刷新"}
            </button>
          </div>
        </div>

        {!compact && sourceStats}

        {(nativeError || radarError || radarFailedSources > 0 || nativeStatusNotice || (!loading && !hasRadarData) || (runtime?.sources?.failing ?? 0) > 0) && (
          <div className="mt-3 space-y-1 rounded-lg border border-warning/30 bg-warning/5 p-3 text-xs text-warning" role="alert">
            {nativeError && <p className="flex items-start gap-2"><AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />公开资讯：{nativeError}。已保留赛道要点和已有历史。</p>}
            {nativeStatusNotice && <p className="flex items-start gap-2"><AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />公开资讯：{nativeStatusNotice}。</p>}
            {radarError && <p className="flex items-start gap-2"><AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />赛道摘要：{radarError}。已保留公开资讯和已有摘要。</p>}
            {radarFailedSources > 0 && <p>赛道来源部分失败：{radarFailedSources} 个来源未成功。已有赛道要点仍可使用。</p>}
            {!loading && !hasRadarData && !radarError && <p>赛道摘要：当前还没有已生成的赛道资讯，公开资讯仍可使用。</p>}
            {(runtime?.sources?.failing ?? 0) > 0 && <p>失败来源：{runtime!.sources!.failing_names.join("、")}。其他来源结果仍可用。</p>}
          </div>
        )}
      </div>

      {compact && (
        <>
          <div className="rounded-xl border border-border/60 bg-card/50 px-4 py-3" data-testid="market-intel-brief">
              <p className="text-xs text-muted-foreground">行业来源的近期动态 · 同链接去重 · 最多 4 条</p>
              <p className="mt-1 text-[11px] text-muted-foreground">按来源类别选取，文章与具体公司的关联仍需核对。</p>
            {items?.status === "stale" && <p className="mt-2 text-xs text-warning" role="alert">资讯列表为历史数据：{items.error || "当前来源未提供新鲜资讯"}。</p>}
            {items?.status === "partial" && <p className="mt-2 text-xs text-warning" role="alert">资讯列表部分可用：{items.error || "可能缺少部分来源结果"}。</p>}
            {(items?.status === "unavailable" || items?.error && items.status === "normal") && <p className="mt-2 text-xs text-warning" role="alert">资讯列表当前不可用或读取异常：{items.error || "不能判断是否有匹配资讯"}。</p>}
            {loading && !items ? (
              <p className="mt-3 text-xs text-muted-foreground"><Loader2 className="mr-1 inline h-3.5 w-3.5 animate-spin" />正在读取资讯…</p>
            ) : researchItems.length > 0 ? (
              <ul className="mt-2 divide-y divide-border/40">
                {researchItems.map((item) => (
                  <li key={item.item_id} className="py-2.5" data-testid="market-intel-brief-item">
                    <a href={item.url} target="_blank" rel="noreferrer noopener" className="group flex items-start gap-1.5 text-sm leading-relaxed hover:text-primary hover:underline">
                      <span className="min-w-0 break-words">{item.title}</span><ExternalLink className="mt-1 h-3 w-3 shrink-0 text-muted-foreground" />
                    </a>
                    <ArticleAssociation entities={item.entities} className="mt-1" />
                    <p className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground">
                      <span>{item.source_name || item.hint}</span>
                      <span>发布于 {item.published_at ? formatShanghaiTime(item.published_at) : "未提供"}</span>
                      <span>首次发现 {formatShanghaiTime(item.first_seen_at)}</span>
                    </p>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="mt-3 text-sm text-muted-foreground" data-testid="market-intel-brief-empty">
                {!items || items.status === "unavailable" || items.error
                  ? "资讯尚未成功读取，暂不能判断是否有匹配的行业资讯。"
                  : "本次资讯中暂无行业来源动态，可前往完整资讯中心查看全部。"}
              </p>
            )}
          </div>
          {trending && (trending.status !== "normal" || trending.error) && (
            <p className="text-xs text-warning" role="alert">关注趋势{trending.status === "stale" ? "为历史数据" : trending.status === "unavailable" ? "暂不可用" : "部分可用或读取异常"}{trending.error ? `：${trending.error}` : "，可展开来源与趋势查看详情"}。</p>
          )}
          <details className="rounded-xl border border-border/60 px-4 py-3" data-testid="market-intel-brief-diagnostics">
            <summary className="cursor-pointer text-xs text-muted-foreground hover:text-foreground">来源与关注趋势</summary>
            <div className="space-y-3">{sourceStats}{trendPanel}</div>
          </details>
        </>
      )}

      {!compact && trendPanel}

      {!compact && <>
      <section className="rounded-xl border border-border/60 bg-card/50 p-4">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <div>
            <h3 className="text-sm font-semibold text-foreground">今日赛道要点</h3>
            <p className="mt-0.5 text-xs text-muted-foreground">选择赛道，查看已保存摘要或让 AI 提炼今天的要点。</p>
          </div>
          {hasRadarData && (
            <button
              type="button"
              onClick={() => void generateAll()}
              disabled={bulk.running || refreshing}
              className="inline-flex items-center gap-1.5 rounded-lg bg-primary/15 px-3 py-1.5 text-sm font-medium text-primary shadow-glow hover:bg-primary/25 disabled:opacity-50"
            >
              {bulk.running ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
              {bulk.running ? `提炼中 ${bulk.done}/${bulk.total}` : "提炼全部赛道"}
            </button>
          )}
        </div>

        {!hasRadarData ? (
          <div className="rounded-lg border border-dashed border-border/70 p-6 text-center text-sm text-muted-foreground">
            {loading ? "正在读取赛道资讯…" : "当前没有可用的赛道资讯。"}
          </div>
        ) : (
          <>
            <div className="mb-4 flex flex-wrap gap-2" aria-label="赛道筛选">
              {industries.map((industry) => (
                <button
                  key={industry.key}
                  type="button"
                  onClick={() => setActive(industry.key)}
                  className={cn(
                    "inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs transition-colors",
                    active === industry.key
                      ? "border-primary bg-primary/15 font-medium text-primary shadow-glow"
                      : "border-primary/25 text-muted-foreground hover:border-primary/60 hover:text-foreground",
                  )}
                >
                  <span className="h-2 w-2 rounded-full" style={{ background: industry.accent }} />
                  {industry.name}<span className="text-muted-foreground/60">{industry.items.length}</span>
                </button>
              ))}
            </div>

            {currentIndustry && (
              <div className="rounded-xl border border-primary/30 bg-primary/5 p-4">
                <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="flex items-center gap-1.5 text-sm font-semibold text-primary"><Lightbulb className="h-4 w-4" />{currentIndustry.name} · 今日要点</span>
                    {digest?.digest_date && <span className="font-mono text-xs text-muted-foreground">{digest.digest_date}</span>}
                    {digest?.saved && <span className="rounded bg-emerald-500/10 px-1.5 py-0.5 text-xs font-medium text-emerald-600 dark:text-emerald-400">已保存</span>}
                    {digest?.deduped && <span className="rounded bg-blue-500/10 px-1.5 py-0.5 text-xs font-medium text-blue-600 dark:text-blue-400">已去重</span>}
                    {digest?.phase === "cancelled" && <span className="rounded bg-destructive/10 px-1.5 py-0.5 text-xs font-medium text-destructive">生成已取消</span>}
                  </div>
                  {digest?.phase === "saving" ? (
                    <span className="inline-flex items-center gap-1.5 text-xs font-medium text-primary"><Loader2 className="h-3.5 w-3.5 animate-spin" />保存中…</span>
                  ) : digest?.phase === "generating" ? (
                    <button type="button" onClick={() => cancelGeneration(currentIndustry.key)} className="inline-flex items-center gap-1 text-xs font-medium text-destructive hover:underline"><XCircle className="h-3.5 w-3.5" />取消生成</button>
                  ) : (digest?.text || digest?.err || digest?.needKey) ? (
                    <button type="button" onClick={() => void generateDigest(currentIndustry)} disabled={bulk.running || generatingSectorsRef.current.has(currentIndustry.key)} className="text-xs text-muted-foreground hover:text-primary disabled:opacity-50">重新提炼</button>
                  ) : null}
                </div>

                {digest?.phase === "generating" ? (
                  <p className="flex items-center gap-2 text-sm text-muted-foreground"><Loader2 className="h-3.5 w-3.5 animate-spin" />AI 正在读这个赛道的资讯…</p>
                ) : digest?.phase === "saving" ? (
                  <div className="space-y-2">
                    <p className="flex items-center gap-2 text-sm text-primary"><Loader2 className="h-3.5 w-3.5 animate-spin" />摘要已生成，正在保存到数据库…</p>
                    {digest.text && <div className="prose prose-sm dark:prose-invert max-w-none text-foreground opacity-80"><ReactMarkdown remarkPlugins={[remarkGfm]}>{digest.text}</ReactMarkdown></div>}
                  </div>
                ) : digest?.text ? (
                  <>
                    {digest.err && <div className="mb-2 flex items-center gap-1.5 rounded bg-destructive/10 p-2 text-xs text-destructive"><AlertCircle className="h-3.5 w-3.5 shrink-0" />{digest.err}</div>}
                    <div className="prose prose-sm dark:prose-invert max-w-none text-foreground"><ReactMarkdown remarkPlugins={[remarkGfm]}>{digest.text}</ReactMarkdown></div>
                    <div className="mt-2"><SaveNoteButton kind="今日要点" title={`${currentIndustry.name} 今日要点`} content={digest.text} /></div>
                  </>
                ) : digest?.needKey ? (
                  <p className="text-sm text-muted-foreground">还没接入 AI。<Link to="/settings" className="text-primary">先接入你的 AI</Link>，即可一键提炼本赛道今日要点。</p>
                ) : digest?.err ? (
                  <p className="text-sm text-destructive">{digest.err}</p>
                ) : (
                  <button type="button" onClick={() => void generateDigest(currentIndustry)} className="inline-flex items-center gap-1.5 rounded-lg bg-primary/15 px-3 py-1.5 text-sm font-medium text-primary hover:bg-primary/25"><Sparkles className="h-4 w-4" />让 AI 提炼今日要点</button>
                )}
              </div>
            )}
          </>
        )}
      </section>

      <section className="rounded-xl border border-border/60 bg-card/50 p-4">
        <h3 className="text-sm font-semibold text-foreground">最新重要资讯</h3>
        {loading && visibleItems.length === 0 ? (
          <p className="mt-3 text-xs text-muted-foreground"><Loader2 className="mr-1 inline h-3.5 w-3.5 animate-spin" />读取本地资讯历史…</p>
        ) : visibleItems.length === 0 ? (
          <p className="mt-3 rounded border border-dashed border-border/60 p-4 text-center text-xs text-muted-foreground">当前没有已保存资讯；若来源失败，请查看上方来源状态。</p>
        ) : (
          <ul className="mt-2 divide-y divide-border/40">
            {visibleItems.map((item) => (
              <li key={item.item_id} className="grid gap-1 py-2 text-sm md:grid-cols-[minmax(0,1fr)_8rem_10rem] md:items-center md:gap-3">
                <a href={item.url} target="_blank" rel="noreferrer noopener" className="group flex min-w-0 items-center gap-1.5 hover:text-primary hover:underline">
                  <span className="truncate">{item.title}</span><ExternalLink className="h-3 w-3 shrink-0 opacity-0 transition-opacity group-hover:opacity-60" />
                </a>
                <span className="truncate text-xs text-muted-foreground">{item.source_name || item.hint}</span>
                <span className="font-mono text-xs text-muted-foreground">{formatShanghaiTime(item.published_at || item.last_seen_at)}</span>
                <ArticleAssociation entities={item.entities} className="md:col-span-3" />
              </li>
            ))}
          </ul>
        )}
      </section>
      </>}
    </section>
  );
}
