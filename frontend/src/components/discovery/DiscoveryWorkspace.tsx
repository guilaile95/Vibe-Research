import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AlertCircle, ChevronRight, Database, Loader2, RefreshCw } from "lucide-react";
import { Link } from "react-router-dom";

import { GlassCard } from "@/components/ui/GlassCard";
import { candidateWorkspaceHref } from "@/lib/candidateCampaign";
import {
  discoverySectors,
  displayDiscoveryTime,
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

const badgeClass = (status: string) => {
  if (["normal", "AVAILABLE", "SUFFICIENT_FOR_RESEARCH", "CLEAR"].includes(status)) return "border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300";
  if (["partial", "PARTIAL", "stale", "UNKNOWN"].includes(status)) return "border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300";
  if (["ERROR", "error", "unavailable", "RESTRICTED", "INSUFFICIENT"].includes(status)) return "border-destructive/30 bg-destructive/10 text-destructive";
  return "border-border bg-muted/40 text-muted-foreground";
};

function Badge({ children, tone }: { children: React.ReactNode; tone: string }) {
  return <span className={`rounded-full border px-2 py-0.5 text-[10px] font-medium ${badgeClass(tone)}`}>{children}</span>;
}

function ObservationValue({ value }: { value: unknown }) {
  if (value == null) return <span>未知</span>;
  if (typeof value === "number") return <span>{Number.isInteger(value) ? value.toLocaleString("zh-CN") : value.toFixed(3)}</span>;
  if (typeof value === "string") return <span>{value}</span>;
  return <span>{JSON.stringify(value)}</span>;
}

function OpportunityCard({ item }: { item: DiscoveryOpportunityItem }) {
  return (
    <GlassCard className="space-y-3 p-4" data-testid={`discovery-item-${item.strategy}-${item.security_code}`}>
      <div className="flex flex-wrap items-start gap-2">
        <div>
          <div className="flex items-center gap-2">
            <span className="font-medium">{item.name}</span>
            <span className="font-mono text-xs text-muted-foreground">{item.security_code}</span>
          </div>
          <p className="mt-1 text-xs text-muted-foreground">
            {item.sector || "行业未知"}{item.themes.length ? ` · ${item.themes.join(" / ")}` : " · 主题未知"}
          </p>
        </div>
        <div className="ml-auto flex flex-wrap justify-end gap-1.5">
          <Badge tone={item.research_priority}>{item.research_priority} 优先</Badge>
          <Badge tone={item.evidence_gate}>{item.evidence_gate}</Badge>
          {item.restricted_universe.status === "RESTRICTED" ? <Badge tone="RESTRICTED">Restricted</Badge> : null}
          {item.restricted_universe.status === "UNKNOWN" ? <Badge tone="UNKNOWN">资格未知</Badge> : null}
        </div>
      </div>

      <div className="grid gap-2 text-xs sm:grid-cols-3">
        <div className="rounded-lg border border-border/60 bg-muted/20 p-2">
          <span className="text-muted-foreground">基本面</span>
          <p className="mt-1 font-medium">{item.fundamental_status}</p>
        </div>
        <div className="rounded-lg border border-border/60 bg-muted/20 p-2">
          <span className="text-muted-foreground">催化线索</span>
          <p className="mt-1 font-medium">{item.catalyst_status}</p>
        </div>
        <div className="rounded-lg border border-border/60 bg-muted/20 p-2">
          <span className="text-muted-foreground">数据状态</span>
          <p className="mt-1 font-medium">{statusLabel(item.data_health)}</p>
        </div>
      </div>

      <details className="rounded-lg border border-border/50 bg-background/50 px-3 py-2" open>
        <summary className="cursor-pointer text-xs font-medium">为什么进入 {item.strategy} 研究队列</summary>
        <div className="mt-2 space-y-2">
          {item.supporting_observations.map((observation) => (
            <div key={`${observation.code}-${observation.source_ref}`} className="flex items-start justify-between gap-3 text-xs">
              <span>{observation.label}</span>
              <span className="max-w-[45%] break-words text-right text-muted-foreground"><ObservationValue value={observation.value} /></span>
            </div>
          ))}
          <div className="flex flex-wrap gap-1.5 pt-1">
            {item.reason_codes.map((reason) => <span key={reason} className="rounded bg-muted px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground">{reason}</span>)}
          </div>
        </div>
      </details>

      {item.uncertainties.length ? (
        <div className="rounded-lg border border-amber-500/25 bg-amber-500/5 px-3 py-2 text-xs">
          <p className="font-medium text-amber-700 dark:text-amber-300">仍需确认</p>
          <p className="mt-1 text-muted-foreground">{item.uncertainties.join(" · ")}</p>
        </div>
      ) : null}

      <div className="flex items-center justify-between border-t border-border/50 pt-3 text-xs text-muted-foreground">
        <span>As of {item.as_of}</span>
        <Link
          to={candidateWorkspaceHref(item.security_code)}
          className="inline-flex items-center gap-1 font-medium text-primary hover:underline"
          data-testid={`discovery-candidate-${item.security_code}`}
        >
          进入 Candidate Research <ChevronRight className="h-3.5 w-3.5" />
        </Link>
      </div>
    </GlassCard>
  );
}

export function DiscoveryWorkspace() {
  const [snapshot, setSnapshot] = useState<DiscoverySnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [filters, setFilters] = useState<DiscoveryFilters>({
    strategy: "SWING",
    sector: "ALL",
    priority: "ALL",
    restricted: "ALL",
    health: "ALL",
  });
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

  if (loading && !snapshot) {
    return <GlassCard className="flex min-h-52 items-center justify-center gap-2 p-6 text-sm text-muted-foreground" data-testid="discovery-loading"><Loader2 className="h-4 w-4 animate-spin" />正在扫描 Core A 股市场…</GlassCard>;
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
      <GlassCard className="space-y-4 p-4" data-testid="discovery-summary">
        <div className="flex flex-wrap items-start gap-3">
          <div>
            <div className="flex items-center gap-2">
              <h2 className="font-medium">全市场发现漏斗</h2>
              <Badge tone={snapshot.status}>{statusLabel(snapshot.status)}</Badge>
            </div>
            <p className="mt-1 text-xs text-muted-foreground">As of {snapshot.as_of} · 更新于 {displayDiscoveryTime(snapshot.fetched_at)}</p>
          </div>
          <button type="button" onClick={() => void load(true)} disabled={refreshing} className="ml-auto inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-xs hover:bg-muted disabled:opacity-50" data-testid="refresh-discovery">
            {refreshing ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
            {refreshing ? "刷新中…" : "刷新"}
          </button>
        </div>

        {error ? <div className="flex items-center gap-2 rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs text-destructive"><AlertCircle className="h-3.5 w-3.5" />刷新失败，继续显示当前结果：{error}</div> : null}

        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
          {[
            ["Core Universe", snapshot.funnel.core_universe],
            ["Stage 1 通过", snapshot.funnel.cheap_scan_passed],
            ["Stage 3 资格检查", snapshot.funnel.qualification_candidates],
            ["行业覆盖", snapshot.market_context.sector_count],
            ["Excluded / Blocked", snapshot.funnel.excluded],
          ].map(([label, value]) => (
            <div key={String(label)} className="rounded-lg border border-border/60 bg-muted/20 p-3">
              <p className="text-[11px] text-muted-foreground">{label}</p>
              <p className="mt-1 text-lg font-semibold">{String(value)}</p>
            </div>
          ))}
        </div>

        <div className="flex flex-wrap gap-2 text-[11px] text-muted-foreground">
          {snapshot.datasets.map((dataset) => (
            <span key={dataset.dataset_id} className="inline-flex items-center gap-1 rounded border border-border/50 px-2 py-1">
              <Database className="h-3 w-3" />{dataset.dataset_id}<Badge tone={dataset.status}>{statusLabel(dataset.status)}</Badge>
            </span>
          ))}
        </div>
      </GlassCard>

      <GlassCard className="space-y-3 p-4" data-testid="discovery-filters">
        <div className="flex flex-wrap gap-1 rounded-lg border border-border/60 bg-muted/20 p-1" role="tablist" aria-label="Discovery strategy">
          {STRATEGIES.map((strategy) => (
            <button key={strategy} type="button" role="tab" aria-selected={filters.strategy === strategy} onClick={() => setFilters((current) => ({ ...current, strategy }))} className={`rounded-md px-3 py-1.5 text-sm ${filters.strategy === strategy ? "bg-background font-medium shadow-sm" : "text-muted-foreground hover:text-foreground"}`} data-testid={`strategy-${strategy}`}>
              {strategy} <span className="ml-1 text-[10px] text-muted-foreground">{snapshot.queues[strategy].length}</span>
            </button>
          ))}
        </div>
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
          <select aria-label="Discovery sector" value={filters.sector} onChange={(event) => setFilters((current) => ({ ...current, sector: event.target.value }))} className="rounded-lg border border-border bg-background px-2 py-1.5 text-xs">
            <option value="ALL">全部行业 / 主题</option>
            {sectors.map((sector) => <option key={sector} value={sector}>{sector}</option>)}
          </select>
          <select aria-label="Discovery priority" value={filters.priority} onChange={(event) => setFilters((current) => ({ ...current, priority: event.target.value as DiscoveryFilters["priority"] }))} className="rounded-lg border border-border bg-background px-2 py-1.5 text-xs">
            {PRIORITIES.map((priority) => <option key={priority} value={priority}>{priority === "ALL" ? "全部优先级" : `${priority} 优先`}</option>)}
          </select>
          <select aria-label="Discovery restricted" value={filters.restricted} onChange={(event) => setFilters((current) => ({ ...current, restricted: event.target.value as DiscoveryFilters["restricted"] }))} className="rounded-lg border border-border bg-background px-2 py-1.5 text-xs">
            <option value="ALL">全部资格</option><option value="CLEAR">普通</option><option value="RESTRICTED">Restricted</option><option value="UNKNOWN">资格未知</option>
          </select>
          <select aria-label="Discovery health" value={filters.health} onChange={(event) => setFilters((current) => ({ ...current, health: event.target.value as DiscoveryFilters["health"] }))} className="rounded-lg border border-border bg-background px-2 py-1.5 text-xs">
            <option value="ALL">全部数据状态</option><option value="normal">可用</option><option value="partial">部分可用</option><option value="unknown">未知</option><option value="error">错误</option>
          </select>
        </div>
      </GlassCard>

      <div className="grid gap-3 xl:grid-cols-2" data-testid={`discovery-queue-${filters.strategy}`}>
        {items.length ? items.map((item) => <OpportunityCard key={`${item.strategy}-${item.security_code}`} item={item} />) : (
          <GlassCard className="p-8 text-center text-sm text-muted-foreground xl:col-span-2">当前筛选下没有研究候选；UNKNOWN 不会被补成假机会。</GlassCard>
        )}
      </div>

      <details className="rounded-xl border border-border/60 bg-card/50 p-4" data-testid="discovery-excluded">
        <summary className="cursor-pointer text-sm font-medium">为什么被挡在队列外（{snapshot.excluded.length}）</summary>
        <div className="mt-3 max-h-80 divide-y divide-border/40 overflow-y-auto">
          {snapshot.excluded.map((item, index) => (
            <div key={`${item.security_code}-${item.strategy || "all"}-${index}`} className="flex flex-wrap items-center gap-2 py-2 text-xs">
              <span className="font-medium">{item.name}</span><span className="font-mono text-muted-foreground">{item.security_code}</span>
              {item.strategy ? <span>{item.strategy}</span> : null}
              <span className="ml-auto text-muted-foreground">{item.reason_codes.join(" · ")}</span>
            </div>
          ))}
        </div>
      </details>

      <div className="space-y-1 text-[11px] text-muted-foreground">
        {snapshot.limitations.map((line) => <p key={line}>{line}</p>)}
        <p>Discovery 只回答“先研究谁、为什么”，不会生成交易决定或自动创建 Campaign。</p>
      </div>
    </section>
  );
}
