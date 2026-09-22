import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AlertCircle, ChevronRight, Database, Loader2, RefreshCw } from "lucide-react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router-dom";

import { GlassCard } from "@/components/ui/GlassCard";
import { formatDiscoveryObservationValue } from "@/lib/discoveryObservation";
import {
  discoveryCandidateHref,
  discoveryCardAnchor,
  discoveryFiltersFromSearch,
  discoverySearchWithFilters,
  discoverySectors,
  discoverySummaryObservations,
  discoveryTimeSummary,
  filterDiscoveryItems,
  statusLabel,
  type DiscoveryFilters,
} from "@/lib/discoveryView";
import { ApiError } from "@/lib/api";
import { recoveredMarketApi } from "@/lib/recoveredMarketApi";
import type {
  DiscoveryOpportunityItem,
  DiscoveryPriority,
  DiscoverySnapshot,
  DiscoveryStrategy,
} from "@/lib/recoveredMarketTypes";

const STRATEGIES: DiscoveryStrategy[] = ["SHORT", "SWING", "MEDIUM"];
const PRIORITIES: Array<"ALL" | DiscoveryPriority> = ["ALL", "HIGH", "MEDIUM", "LOW"];
const STRATEGY_LABELS: Record<DiscoveryStrategy, string> = { SHORT: "短线", SWING: "波段", MEDIUM: "中线" };
const PRIORITY_LABELS = { ALL: "全部研究优先级", HIGH: "高", MEDIUM: "中", LOW: "低" };
const COVERAGE_LABELS = { AVAILABLE: "已有", PARTIAL: "部分可用", UNKNOWN: "未知", ERROR: "错误" };
const EVIDENCE_LABELS = { SUFFICIENT_FOR_RESEARCH: "可继续研究", PARTIAL: "证据不完整", INSUFFICIENT: "证据不足", UNKNOWN: "证据未知", ERROR: "证据错误" };
const DATASET_LABELS: Record<string, string> = {
  "market-snapshot": "市场行情",
  "sector-context": "行业背景",
  "fundamental-qualification": "基本面数据",
  "catalyst-qualification": "催化线索",
  "research_data_plane.full_market": "历史行情",
  "market.a_share_snapshot": "市场行情",
  "native_intel.security_mentions": "资讯提及",
  "financials.snapshot": "基本面数据",
  "announcements.recent": "近期公告",
};
const GAP_LABELS: Record<string, string> = {
  SECTOR_CONTEXT_UNKNOWN: "行业背景未知",
  THEME_CONTEXT_UNKNOWN: "主题关联未知",
  LISTING_AGE_NOT_EVALUATED: "上市时长尚未评估",
  FUNDAMENTAL_FACTS_UNKNOWN: "基本面事实缺失",
  FUNDAMENTAL_FRESHNESS_UNKNOWN: "财务报告期与时效尚未确认",
  CATALYST_EVIDENCE_UNKNOWN: "催化依据尚未确认",
  NATIVE_INTEL_MAPPING_UNKNOWN: "资讯与公司之间的关联尚未确认",
  AMOUNT_UNKNOWN: "成交额未知",
  TURNOVER_UNKNOWN: "换手率未知",
  SESSION_RETURN_UNKNOWN: "当日涨跌幅未知",
  RETURN_20D_UNKNOWN: "20 日收益缺失",
  RETURN_60D_UNKNOWN: "60 日收益缺失",
  VALUATION_INPUT_UNKNOWN: "估值数据缺失",
  HISTORICAL_MARKET_CONTEXT_UNKNOWN: "历史行情背景未知",
  HISTORICAL_ROW_STALE: "历史行情已过期",
  MARKET_TRADE_DATE_UNKNOWN: "行情交易日未知",
  RDP_LATEST_DATE_UNKNOWN: "历史行情日期未知",
  RDP_LATEST_DATE_BEHIND_MARKET: "历史行情日期早于当前市场日期",
  RDP_LATEST_DATE_AFTER_MARKET: "历史行情日期晚于当前市场日期",
};
const FACT_LABELS: Record<string, string> = {
  pe_ttm: "市盈率（TTM）", pb: "市净率", period: "报告期", revenue_yoy: "营收同比",
  net_profit_yoy: "净利润同比", operating_cash_flow: "经营现金流", roe: "净资产收益率",
  announcement_count: "公告数量", intel_mentions: "资讯提及", intel_sources: "资讯来源", intel_mapping_status: "公司关联",
};

const badgeClass = (status: string) => {
  if (["normal", "AVAILABLE", "SUFFICIENT_FOR_RESEARCH", "CLEAR"].includes(status)) return "border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300";
  if (["partial", "PARTIAL", "stale", "unknown", "UNKNOWN"].includes(status)) return "border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300";
  if (["ERROR", "error", "unavailable", "RESTRICTED", "INSUFFICIENT"].includes(status)) return "border-destructive/30 bg-destructive/10 text-destructive";
  return "border-border bg-muted/40 text-muted-foreground";
};

function Badge({ children, tone }: { children: React.ReactNode; tone: string }) {
  return <span className={`rounded-full border px-2 py-0.5 text-[10px] font-medium ${badgeClass(tone)}`}>{children}</span>;
}

function ObservationValue({ value }: { value: unknown }) {
  if (value == null) return <span>未知</span>;
  if (typeof value === "number") return <span>{String(value)}</span>;
  if (typeof value === "string") return <span>{value === "MAPPED" ? "已关联" : COVERAGE_LABELS[value as keyof typeof COVERAGE_LABELS] ?? value}</span>;
  if (typeof value === "object" && !Array.isArray(value)) return (
    <span className="inline-flex flex-wrap justify-end gap-x-3 gap-y-1">
      {Object.entries(value).map(([key, fact]) => <span key={key}>{FACT_LABELS[key] ?? key}：<ObservationValue value={fact} /></span>)}
    </span>
  );
  return <span>{JSON.stringify(value)}</span>;
}

function OpportunityCard({ item }: { item: DiscoveryOpportunityItem }) {
  const [searchParams] = useSearchParams();
  const location = useLocation();
  const navigate = useNavigate();
  const anchor = discoveryCardAnchor(item);
  const selected = location.hash === `#${anchor}`;
  const observations = discoverySummaryObservations(item);
  const gaps = [...new Set([
    ...(item.restricted_universe.status === "RESTRICTED" ? ["受限研究：需要进一步核对资格"] : []),
    ...(item.restricted_universe.status === "UNKNOWN" ? ["研究资格未知"] : []),
    ...(["error", "unknown"].includes(item.data_health) ? [`数据状态：${statusLabel(item.data_health)}`] : []),
    ...(["ERROR", "INSUFFICIENT"].includes(item.evidence_gate) ? [EVIDENCE_LABELS[item.evidence_gate]] : []),
    ...item.uncertainties.map((line) => GAP_LABELS[line] ?? line),
    ...(item.fundamental_status !== "AVAILABLE" ? [`基本面：${COVERAGE_LABELS[item.fundamental_status]}`] : []),
    ...(item.catalyst_status !== "AVAILABLE" ? [`催化线索：${COVERAGE_LABELS[item.catalyst_status]}`] : []),
    ...(item.data_health !== "normal" ? [`数据状态：${statusLabel(item.data_health)}`] : []),
    ...(item.evidence_gate !== "SUFFICIENT_FOR_RESEARCH" ? [EVIDENCE_LABELS[item.evidence_gate]] : []),
  ])];
  return (
    <GlassCard id={anchor} tabIndex={-1} data-return-selected={selected || undefined} className={`scroll-mt-4 space-y-4 p-4 sm:p-5 ${selected ? "ring-2 ring-primary/50" : ""}`} data-testid={anchor}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-base font-semibold">{item.name}</h3>
            <span className="font-mono text-xs text-muted-foreground">{item.security_code}</span>
          </div>
          <p className="mt-1 text-xs text-muted-foreground">
            {item.sector || "行业未知"}{item.themes.length ? ` · ${item.themes.join(" / ")}` : " · 主题未知"}
          </p>
        </div>
        <Link
          to={discoveryCandidateHref(item, searchParams)}
          onClick={(event) => {
            if (event.button === 0 && !event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey) {
              navigate({ pathname: location.pathname, search: location.search, hash: `#${anchor}` }, { replace: true });
            }
          }}
          className="inline-flex shrink-0 items-center gap-1 py-1 text-sm font-medium text-primary hover:underline"
          data-testid={`discovery-candidate-${item.security_code}`}
        >
          进入候选研究 <ChevronRight className="h-3.5 w-3.5" />
        </Link>
      </div>

      <div className={`grid gap-4 border-t border-border/50 pt-4 ${gaps.length ? "lg:grid-cols-2" : ""}`}>
        <div className="min-w-0">
          <p className="text-xs font-medium">进入{STRATEGY_LABELS[item.strategy]}研究队列的依据</p>
          <dl className="mt-2 max-w-xl space-y-2 text-xs" data-testid={`discovery-summary-observations-${item.security_code}`}>
            {observations.map((observation) => (
              <div key={`${observation.code}-${observation.source_ref}`} className="flex items-start justify-between gap-3">
                <dt className="min-w-0 break-words">{observation.label}</dt>
                <dd className="max-w-[50%] break-words text-right font-medium tabular-nums"><ObservationValue value={formatDiscoveryObservationValue(observation.code, observation.value)} /></dd>
              </div>
            ))}
          </dl>
          {!item.supporting_observations.length ? <p className="mt-2 text-xs text-muted-foreground">暂未提供观察明细，需进一步核对依据。</p> : null}
          <div className="mt-3 flex flex-wrap gap-1.5">
            <Badge tone={item.research_priority}>研究优先级：{PRIORITY_LABELS[item.research_priority]}</Badge>
            <Badge tone={item.evidence_gate}>{EVIDENCE_LABELS[item.evidence_gate] ?? item.evidence_gate}</Badge>
          </div>
        </div>

        {gaps.length ? (
          <div className="min-w-0 border-l-2 border-amber-500/30 pl-3 text-xs" data-testid={`discovery-gaps-${item.security_code}`}>
            <p className="flex items-center gap-1.5 font-medium text-amber-700 dark:text-amber-300"><AlertCircle className="h-3.5 w-3.5 shrink-0" />仍需确认</p>
            <p className="mt-2 break-words text-muted-foreground">{gaps[0]}</p>
            {gaps.length > 1 ? <p className="mt-2 text-muted-foreground">另有 {gaps.length - 1} 项，见完整依据与来源。</p> : null}
          </div>
        ) : null}
      </div>

      <div className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-muted-foreground">
        <span>基本面：{COVERAGE_LABELS[item.fundamental_status]}</span>
        <span>催化线索：{COVERAGE_LABELS[item.catalyst_status]}</span>
        <span>数据状态：{statusLabel(item.data_health)}</span>
        <span>行情归属 {item.as_of ?? "未知"}</span>
      </div>
      <details className="border-t border-border/50 pt-3 text-xs text-muted-foreground" data-testid={`discovery-evidence-${item.security_code}`}>
        <summary className="cursor-pointer hover:text-foreground">完整依据与来源</summary>
        <div className="mt-3 space-y-2 break-words">
          <div className="flex flex-wrap gap-1.5">
            {item.reason_codes.map((reason) => <span key={reason} className="rounded bg-muted px-1.5 py-0.5 font-mono text-[10px]">{reason}</span>)}
          </div>
          <p>证据状态：{item.evidence_gate} · 研究资格：{item.restricted_universe.status}</p>
          {gaps.length ? <ul className="space-y-1" aria-label="全部待确认项">{gaps.map((gap) => <li key={gap}>{gap}</li>)}</ul> : null}
          {item.restricted_universe.reason_codes.length ? <p>资格依据：{item.restricted_universe.reason_codes.join(" · ")}</p> : null}
          {item.uncertainties.length ? <p>待确认项原文：{item.uncertainties.join(" · ")}</p> : null}
          <dl className="space-y-2" aria-label="全部观察依据">
            {item.supporting_observations.map((observation) => (
              <div key={`${observation.code}-${observation.source_ref}`}>
                <dt>{observation.label}</dt>
                <dd><ObservationValue value={formatDiscoveryObservationValue(observation.code, observation.value)} /></dd>
                <dd className="mt-1 text-[10px]">{observation.code} · 原始值 {JSON.stringify(observation.value)} · {observation.source_ref}</dd>
              </div>
            ))}
          </dl>
          <p>来源：{item.provenance_refs.join(" · ") || "未提供"}</p>
        </div>
      </details>
    </GlassCard>
  );
}

export function DiscoveryWorkspace() {
  const [snapshot, setSnapshot] = useState<DiscoverySnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [searchParams, setSearchParams] = useSearchParams();
  const location = useLocation();
  const filters = useMemo(() => discoveryFiltersFromSearch(searchParams), [searchParams]);
  const setFilters = (patch: Partial<DiscoveryFilters>) => setSearchParams(discoverySearchWithFilters(searchParams, patch));
  const controllerRef = useRef<AbortController | null>(null);

  const load = useCallback(async (refresh: boolean, background = false) => {
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    if (!background) setLoading(!snapshot);
    setRefreshing(refresh || background);
    setError(null);
    try {
      const next = await recoveredMarketApi.getDiscovery(refresh, controller.signal);
      if (controller.signal.aborted || controllerRef.current !== controller) return;
      setSnapshot(next);
      setLoading(false);
      setRefreshing(false);
      if (!refresh && next.cache.hit && !next.cache.refresh_failed) void load(true, true);
    } catch (cause) {
      if (controller.signal.aborted || controllerRef.current !== controller) return;
      setError(cause instanceof ApiError ? cause.message : cause instanceof Error ? cause.message : "市场发现暂时不可用");
      setLoading(false);
      setRefreshing(false);
    }
  }, [snapshot]);

  useEffect(() => {
    void load(false);
    return () => controllerRef.current?.abort();
  // Initial snapshot load only. Refreshes are explicit or cache-triggered.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const sectors = useMemo(() => snapshot ? discoverySectors(snapshot) : [], [snapshot]);
  const items = useMemo(() => snapshot ? filterDiscoveryItems(snapshot, filters) : [], [snapshot, filters]);
  const selectedAnchor = items.map(discoveryCardAnchor).find((anchor) => location.hash === `#${anchor}`);
  useEffect(() => {
    if (!selectedAnchor) return;
    const frame = requestAnimationFrame(() => {
      const card = document.getElementById(selectedAnchor);
      card?.scrollIntoView({ block: "center" });
      card?.focus({ preventScroll: true });
    });
    return () => cancelAnimationFrame(frame);
  }, [selectedAnchor, location.key]);
  const fullMarketSearch = new URLSearchParams(searchParams);
  fullMarketSearch.set("mode", "full-market");

  if (loading && !snapshot) {
    return <GlassCard className="flex min-h-52 items-center justify-center gap-2 p-6 text-sm text-muted-foreground" data-testid="discovery-loading"><Loader2 className="h-4 w-4 animate-spin" />正在寻找 A 股研究线索…</GlassCard>;
  }

  if (!snapshot) {
    return (
      <GlassCard className="space-y-3 p-5" data-testid="discovery-unavailable">
        <div className="flex items-center gap-2 text-destructive"><AlertCircle className="h-4 w-4" />{error || "市场发现不可用"}</div>
        <button type="button" onClick={() => void load(true)} className="rounded-lg border border-border px-3 py-1.5 text-xs hover:bg-muted">重试</button>
      </GlassCard>
    );
  }

  return (
    <section className="space-y-4" data-testid="discovery-workspace">
      <div className="space-y-2" data-testid="discovery-summary">
        <div className="flex flex-wrap items-start gap-3">
          <div>
            <div className="flex items-center gap-2">
              <h2 className="font-medium">研究候选</h2>
              <Badge tone={snapshot.status}>{statusLabel(snapshot.status)}</Badge>
            </div>
            <p className="mt-1 text-xs text-muted-foreground">{discoveryTimeSummary(snapshot)}</p>
          </div>
          <button type="button" onClick={() => void load(true)} disabled={refreshing} className="ml-auto inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-xs hover:bg-muted disabled:opacity-50" data-testid="refresh-discovery">
            {refreshing ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
            {refreshing ? "刷新中…" : "刷新"}
          </button>
        </div>

        {error ? <div className="flex items-center gap-2 rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs text-destructive"><AlertCircle className="h-3.5 w-3.5" />刷新失败，继续显示当前结果：{error}</div> : null}

        {snapshot.datasets.some((dataset) => dataset.status !== "normal") ? (
          <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-amber-700 dark:text-amber-300" data-testid="discovery-source-warning">
            {snapshot.datasets.filter((dataset) => dataset.status !== "normal").map((dataset) => (
              <span key={dataset.dataset_id} className="break-words">{DATASET_LABELS[dataset.dataset_id] ?? dataset.dataset_id}：{statusLabel(dataset.status)}</span>
            ))}
          </div>
        ) : null}
      </div>

      <div className="space-y-3 border-y border-border/50 py-3" data-testid="discovery-filters">
        <div className="flex flex-wrap items-center gap-1" role="tablist" aria-label="发现策略">
          {STRATEGIES.map((strategy) => (
            <button key={strategy} type="button" role="tab" aria-selected={filters.strategy === strategy} onClick={() => setFilters({ strategy })} className={`rounded-md px-3 py-1.5 text-sm ${filters.strategy === strategy ? "bg-background font-medium shadow-sm" : "text-muted-foreground hover:text-foreground"}`} data-testid={`strategy-${strategy}`}>
              {STRATEGY_LABELS[strategy]} <span className="ml-1 text-[10px] text-muted-foreground">{snapshot.queues[strategy].length}</span>
            </button>
          ))}
        </div>
        <div className="grid grid-cols-2 gap-2 lg:grid-cols-4 [&>select]:min-w-0">
          <select aria-label="发现行业或主题" value={filters.sector} onChange={(event) => setFilters({ sector: event.target.value })} className="rounded-lg border border-border bg-background px-2 py-1.5 text-xs">
            <option value="ALL">全部行业 / 主题</option>
            {filters.sector !== "ALL" && !sectors.includes(filters.sector) ? <option value={filters.sector}>{filters.sector}（本次队列暂无）</option> : null}
            {sectors.map((sector) => <option key={sector} value={sector}>{sector}</option>)}
          </select>
          <select aria-label="研究优先级" value={filters.priority} onChange={(event) => setFilters({ priority: event.target.value as DiscoveryFilters["priority"] })} className="rounded-lg border border-border bg-background px-2 py-1.5 text-xs">
            {PRIORITIES.map((priority) => <option key={priority} value={priority}>{priority === "ALL" ? PRIORITY_LABELS[priority] : `${PRIORITY_LABELS[priority]}优先级`}</option>)}
          </select>
          <select aria-label="研究资格" value={filters.restricted} onChange={(event) => setFilters({ restricted: event.target.value as DiscoveryFilters["restricted"] })} className="rounded-lg border border-border bg-background px-2 py-1.5 text-xs">
            <option value="ALL">全部资格</option><option value="CLEAR">普通</option><option value="RESTRICTED">受限研究</option><option value="UNKNOWN">资格未知</option>
          </select>
          <select aria-label="发现数据状态" value={filters.health} onChange={(event) => setFilters({ health: event.target.value as DiscoveryFilters["health"] })} className="rounded-lg border border-border bg-background px-2 py-1.5 text-xs">
            <option value="ALL">全部数据状态</option><option value="normal">可用</option><option value="partial">部分可用</option><option value="unknown">未知</option><option value="error">错误</option>
          </select>
        </div>
      </div>

      <p className="text-sm text-muted-foreground">当前显示 <span className="font-medium text-foreground">{items.length}</span> 个{STRATEGY_LABELS[filters.strategy]}研究候选</p>
      <p className="text-xs text-muted-foreground" data-testid="discovery-queue-boundary">仅筛选本次候选队列，每策略最多12条，同优先级顺序非价值排名。</p>
      <div className="space-y-3" data-testid={`discovery-queue-${filters.strategy}`}>
        {items.length ? items.map((item) => <OpportunityCard key={`${item.strategy}-${item.security_code}`} item={item} />) : (
          <GlassCard className="space-y-3 p-8 text-center text-sm text-muted-foreground">
            <p>{["unavailable", "error"].includes(snapshot.status) ? "当前发现数据不可用，暂时无法提供研究候选。" : "当前筛选下没有研究候选；信息缺失的对象不会被补成机会。"}</p>
            <Link to={{ pathname: location.pathname, search: `?${fullMarketSearch}` }} className="inline-block text-primary hover:underline" data-testid="discovery-open-full-market">进入全市场筛选</Link>
          </GlassCard>
        )}
      </div>

      {snapshot.limitations.length ? (
        <div className="space-y-1 text-xs text-muted-foreground">
          <p className="font-medium text-foreground">数据使用限制</p>
          {snapshot.limitations.map((line) => <p key={line}>{line}</p>)}
        </div>
      ) : null}

      <details className="rounded-xl border border-border/60 bg-card/50 p-4" data-testid="discovery-diagnostics">
        <summary className="cursor-pointer text-sm font-medium"><Database className="mr-2 inline h-4 w-4" />扫描范围与数据来源</summary>
        <div className="mt-4 space-y-4">
          <dl className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
            {[
              ["扫描股票池", snapshot.funnel.core_universe],
              ["初筛通过", snapshot.funnel.cheap_scan_passed],
              ["进入资格检查", snapshot.funnel.qualification_candidates],
              ["行业覆盖", snapshot.market_context.sector_count],
              ["排除或拦截", snapshot.funnel.excluded],
            ].map(([label, value]) => <div key={String(label)}><dt className="text-xs text-muted-foreground">{label}</dt><dd className="mt-1 font-medium">{String(value)}</dd></div>)}
          </dl>
          <div className="divide-y divide-border/50 text-xs text-muted-foreground">
            {snapshot.datasets.map((dataset) => (
              <div key={dataset.dataset_id} className="space-y-1.5 break-words py-3">
                <div className="flex flex-wrap items-center gap-2"><span className="font-medium text-foreground">{DATASET_LABELS[dataset.dataset_id] ?? dataset.dataset_id}</span><Badge tone={dataset.status}>{statusLabel(dataset.status)}</Badge></div>
                <p className="font-mono text-[11px]">{dataset.dataset_id}</p>
                <p>数据归属 {dataset.as_of ?? "未知"} · 获取于 {dataset.fetched_at}</p>
                {dataset.reason_code ? <p>状态说明：{dataset.reason_code}</p> : null}
                <p>来源：{dataset.provenance_refs.join(" · ") || "未提供"}</p>
              </div>
            ))}
          </div>
        </div>
      </details>

      <details className="rounded-xl border border-border/60 bg-card/50 p-4" data-testid="discovery-excluded">
        <summary className="cursor-pointer text-sm font-medium">为什么被挡在队列外（{snapshot.excluded.length}）</summary>
        <div className="mt-3 max-h-80 divide-y divide-border/40 overflow-y-auto">
          {snapshot.excluded.map((item, index) => (
            <div key={`${item.security_code}-${item.strategy || "all"}-${index}`} className="flex flex-wrap items-center gap-2 py-2 text-xs">
              <span className="font-medium">{item.name}</span><span className="font-mono text-muted-foreground">{item.security_code}</span>
              {item.strategy ? <span>{STRATEGY_LABELS[item.strategy]}</span> : null}
              <span className="ml-auto text-muted-foreground">{item.reason_codes.join(" · ")}</span>
            </div>
          ))}
        </div>
      </details>

      <div className="space-y-1 text-[11px] text-muted-foreground">
        <p>发现线索用于进一步研究，不会生成交易决定或自动创建投资计划。</p>
      </div>
    </section>
  );
}
