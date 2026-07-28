import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Activity, AlertTriangle, CheckCircle2, HelpCircle, Loader2, RefreshCw, XCircle } from "lucide-react";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import { cn } from "@/lib/utils";
import { api, ApiError } from "@/lib/api";
import type { DataHealthDetailResult, DataHealthOverviewResult, DataHealthRecordDto } from "@/lib/api/types";
import {
  cacheDetailText,
  cacheTag,
  coverageText,
  degradedDetailText,
  degradedTag,
  emptySystemGuide,
  filterItems,
  gateAdviceLabel,
  gateAdviceState,
  isProblemSource,
  parseHealthSearchParams,
  requestScopeCardHint,
  requestScopeDetailDisclaimer,
  staleTag,
  statusAriaLabel,
  statusLabel,
  summaryQualityTotal,
  type DataHealthRecord,
} from "@/lib/dataHealthView";

function StatusBadge({ status }: { status: string }) {
  const label = statusLabel(status);
  const cls =
    status === "normal"
      ? "bg-emerald-500/15 text-emerald-400"
      : status === "partial"
        ? "bg-amber-500/15 text-amber-400"
        : "bg-rose-500/15 text-rose-400";
  const Icon = status === "normal" ? CheckCircle2 : status === "partial" ? AlertTriangle : XCircle;
  return (
    <span
      className={cn("inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium", cls)}
      aria-label={statusAriaLabel(status)}
    >
      <Icon className="h-3 w-3" aria-hidden />
      {label}
    </span>
  );
}

function Tag({ children }: { children: string }) {
  return (
    <span className="rounded-full bg-slate-500/15 px-2 py-0.5 text-[10px] text-slate-300">
      {children}
    </span>
  );
}

function toViewRecord(r: DataHealthRecordDto): DataHealthRecord {
  return r as DataHealthRecord;
}

export function DataHealth() {
  const [searchParams, setSearchParams] = useSearchParams();
  const filters = useMemo(() => parseHealthSearchParams(searchParams), [searchParams]);

  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [overview, setOverview] = useState<DataHealthOverviewResult | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<DataHealthDetailResult | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setErr(null);
    try {
      const data = await api.getDataHealth();
      setOverview(data);
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : "数据健康服务暂不可用";
      setErr(msg || "数据健康服务暂不可用");
      // 保留旧 overview
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!selectedId) {
      setDetail(null);
      return;
    }
    let cancelled = false;
    setDetailLoading(true);
    api.getDataHealthSource(selectedId)
      .then((d) => {
        if (!cancelled) setDetail(d);
      })
      .catch(() => {
        if (!cancelled) setDetail(null);
      })
      .finally(() => {
        if (!cancelled) setDetailLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedId]);

  const items = overview?.items ?? [];
  const viewItems = useMemo(
    () =>
      filterItems(items.map(toViewRecord), {
        module: filters.module,
        status: filters.status,
        is_stale: filters.is_stale,
        blocks_advice: filters.blocks_advice,
      }),
    [items, filters],
  );
  const problems = useMemo(
    () => items.map(toViewRecord).filter(isProblemSource),
    [items],
  );
  const gateRec = items.find((i) => i.source_id === "portfolio_advice_gate") ?? null;
  const gateState = gateAdviceState(gateRec ? toViewRecord(gateRec) : null);

  const setFilter = (key: string, value: string | null) => {
    const next = new URLSearchParams(searchParams);
    if (value == null || value === "") next.delete(key);
    else next.set(key, value);
    setSearchParams(next, { replace: true });
  };

  return (
    <div className="mx-auto max-w-6xl p-4 md:p-6">
      <PageHeader
        title="数据健康"
        subtitle="只读展示现有数据源质量与时效，不主动刷新业务数据。"
        actions={
          <button
            type="button"
            onClick={() => void load()}
            className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-xs text-muted-foreground hover:text-foreground"
          >
            <RefreshCw className={cn("h-3.5 w-3.5", loading && "animate-spin")} />
            重新读取
          </button>
        }
      />

      {loading && !overview && (
        <GlassCard className="mb-4 flex items-center gap-2 p-6 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" /> 加载数据健康状态…
        </GlassCard>
      )}

      {err && (
        <GlassCard className="mb-4 border-rose-500/30 p-4 text-sm text-rose-300">
          数据健康服务暂不可用
          <span className="mt-1 block text-xs text-muted-foreground">{err}</span>
        </GlassCard>
      )}

      {overview && (
        <>
          {/* 1. 全局概览 */}
          <GlassCard className="mb-4 p-4">
            <div className="mb-3 flex flex-wrap items-center gap-3">
              <Activity className="h-5 w-5 text-primary" />
              <h2 className="text-sm font-semibold">全局概览</h2>
              <StatusBadge status={overview.overall_status} />
            </div>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
              <Metric label="正常" value={overview.summary.normal} />
              <Metric label="部分可用" value={overview.summary.partial} />
              <Metric label="不可用" value={overview.summary.unavailable} />
              <Metric label="数据陈旧" value={overview.summary.stale} hint="可与质量状态重叠" />
              <Metric label="尚未初始化" value={overview.summary.not_initialized} hint="属于不可用子集" />
            </div>
            <p className="mt-2 text-[11px] text-muted-foreground">
              质量三态合计 {summaryQualityTotal(overview.summary)} / 11；
              「数据陈旧」「尚未初始化」不是互斥分区。
            </p>
            {emptySystemGuide(overview.summary) && (
              <p className="mt-2 rounded-lg bg-slate-500/10 px-3 py-2 text-xs text-muted-foreground">
                当前系统尚无业务数据观察记录。请先使用每日复盘、资讯雷达、持仓等业务入口产生数据后，再查看健康状态。
              </p>
            )}
          </GlassCard>

          {/* 2. 建议可用性 */}
          <GlassCard className="mb-4 p-4">
            <h2 className="mb-2 text-sm font-semibold">建议可用性</h2>
            <p className="text-sm">
              最近一次评估结果：
              <span className="ml-2 font-medium text-foreground">{gateAdviceLabel(gateState)}</span>
              {gateRec?.is_stale && (
                <span className="ml-2">
                  <Tag>评估已陈旧</Tag>
                </span>
              )}
            </p>
            {gateState === "blocked" && overview.block_reasons.length > 0 && (
              <ul className="mt-2 list-inside list-disc text-xs text-amber-300">
                {overview.block_reasons.map((b) => (
                  <li key={b.error_code}>{b.summary}</li>
                ))}
              </ul>
            )}
            <p className="mt-2 text-[11px] text-muted-foreground">
              下一次生成仍会重新执行实时 preflight。Gate 陈旧只标记评估时效，不改写最近允许/阻断结论。
            </p>
          </GlassCard>

          {/* 3. 异常和陈旧 */}
          <GlassCard className="mb-4 p-4">
            <h2 className="mb-2 text-sm font-semibold">异常和陈旧来源</h2>
            {problems.length === 0 ? (
              <p className="text-xs text-muted-foreground">当前无 partial / unavailable / 陈旧来源。</p>
            ) : (
              <ul className="space-y-1">
                {problems.map((p) => (
                  <li key={p.source_id} className="flex flex-wrap items-center gap-2 text-xs">
                    <button
                      type="button"
                      className="text-primary underline-offset-2 hover:underline"
                      onClick={() => setSelectedId(p.source_id)}
                    >
                      {p.display_name}
                    </button>
                    <StatusBadge status={p.status} />
                    {staleTag(p.is_stale) && <Tag>{staleTag(p.is_stale)!}</Tag>}
                  </li>
                ))}
              </ul>
            )}
          </GlassCard>

          {/* 筛选 */}
          <div className="mb-3 flex flex-wrap gap-2 text-xs">
            <select
              className="rounded-lg border border-border bg-black/20 px-2 py-1"
              value={filters.status ?? ""}
              onChange={(e) => setFilter("status", e.target.value || null)}
            >
              <option value="">全部状态</option>
              <option value="normal">正常</option>
              <option value="partial">部分可用</option>
              <option value="unavailable">不可用</option>
            </select>
            <select
              className="rounded-lg border border-border bg-black/20 px-2 py-1"
              value={filters.is_stale == null ? "" : String(filters.is_stale)}
              onChange={(e) => {
                const v = e.target.value;
                setFilter("is_stale", v === "" ? null : v);
              }}
            >
              <option value="">陈旧：全部</option>
              <option value="true">仅陈旧</option>
              <option value="false">仅非陈旧</option>
            </select>
            <select
              className="rounded-lg border border-border bg-black/20 px-2 py-1"
              value={filters.blocks_advice == null ? "" : String(filters.blocks_advice)}
              onChange={(e) => {
                const v = e.target.value;
                setFilter("blocks_advice", v === "" ? null : v);
              }}
            >
              <option value="">阻断：全部</option>
              <option value="true">阻断建议</option>
              <option value="false">不阻断</option>
            </select>
          </div>

          {/* 4. 全部 11 来源 */}
          <h2 className="mb-2 text-sm font-semibold">全部数据源（{viewItems.length}）</h2>
          <div className="mb-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {viewItems.map((it) => (
              <GlassCard
                key={it.source_id}
                className={cn(
                  "cursor-pointer p-3 transition hover:border-primary/40",
                  selectedId === it.source_id && "border-primary/50",
                )}
                onClick={() => setSelectedId(it.source_id)}
              >
                <div className="mb-1 flex flex-wrap items-center gap-2">
                  <span className="text-sm font-medium">{it.display_name}</span>
                  <StatusBadge status={it.status} />
                </div>
                <p className="mb-1 text-[11px] text-muted-foreground">{it.module}</p>
                <div className="mb-2 flex flex-wrap gap-1">
                  {staleTag(it.is_stale) && <Tag>{staleTag(it.is_stale)!}</Tag>}
                  {cacheTag(it.is_cached) && <Tag>{cacheTag(it.is_cached)!}</Tag>}
                  {degradedTag(it.is_degraded) && <Tag>{degradedTag(it.is_degraded)!}</Tag>}
                  {requestScopeCardHint(it.source_id) && (
                    <Tag>{requestScopeCardHint(it.source_id)!}</Tag>
                  )}
                  {it.last_error_code === "SOURCE_NOT_INITIALIZED" && <Tag>尚未初始化</Tag>}
                </div>
                <p className="text-[11px] text-muted-foreground">
                  交易日：{it.data_trade_date ?? "—"} · 最近成功：{it.last_success_at ?? "—"}
                </p>
                <p className="text-[11px] text-muted-foreground">
                  覆盖：{coverageText(it.coverage_current, it.coverage_expected)}
                </p>
                {it.last_error_summary && (
                  <p className="mt-1 text-[11px] text-amber-200/80">{it.last_error_summary}</p>
                )}
                {it.blocks_advice && (
                  <p className="mt-1 text-[11px] text-rose-300">阻止持仓建议</p>
                )}
                <button
                  type="button"
                  className="mt-2 text-[11px] text-primary hover:underline"
                  onClick={(e) => {
                    e.stopPropagation();
                    setSelectedId(it.source_id);
                  }}
                >
                  查看详情
                </button>
                {it.detail_path && (
                  <Link
                    to={it.detail_path}
                    className="ml-3 text-[11px] text-muted-foreground hover:text-foreground"
                    onClick={(e) => e.stopPropagation()}
                  >
                    业务页面
                  </Link>
                )}
              </GlassCard>
            ))}
          </div>

          {/* 5. 详情 */}
          <GlassCard className="p-4">
            <h2 className="mb-2 flex items-center gap-2 text-sm font-semibold">
              <HelpCircle className="h-4 w-4" />
              单来源详情
            </h2>
            {!selectedId && (
              <p className="text-xs text-muted-foreground">点击上方来源卡片查看计算依据。</p>
            )}
            {detailLoading && (
              <p className="flex items-center gap-2 text-xs text-muted-foreground">
                <Loader2 className="h-3 w-3 animate-spin" /> 加载详情…
              </p>
            )}
            {detail && !detailLoading && (
              <div className="space-y-2 text-xs">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-sm font-medium">{detail.record.display_name}</span>
                  <StatusBadge status={detail.record.status} />
                </div>
                <p>观察时间：{detail.record.observed_at ?? "—"}</p>
                <p>最近成功：{detail.record.last_success_at ?? "—"}</p>
                <p>错误码：{detail.record.last_error_code ?? "—"}</p>
                <p>错误摘要：{detail.record.last_error_summary ?? "—"}</p>
                <p>
                  缓存：
                  {cacheDetailText(detail.record.is_cached) ?? "（明确未使用缓存）"}
                </p>
                <p>
                  降级：
                  {degradedDetailText(detail.record.is_degraded) ?? "（明确未降级）"}
                </p>
                <p>
                  覆盖：{coverageText(detail.record.coverage_current, detail.record.coverage_expected)}
                </p>
                {detail.calculation.rule_summary && (
                  <p className="text-muted-foreground">{detail.calculation.rule_summary}</p>
                )}
                {requestScopeDetailDisclaimer(
                  detail.record.source_id,
                  detail.calculation.disclaimer,
                ) && (
                  <p className="rounded bg-slate-500/10 p-2 text-amber-100/90">
                    {requestScopeDetailDisclaimer(
                      detail.record.source_id,
                      detail.calculation.disclaimer,
                    )}
                  </p>
                )}
                {detail.related_pages?.length > 0 && (
                  <div className="flex flex-wrap gap-2 pt-1">
                    {detail.related_pages.map((p) => (
                      <Link
                        key={p.path}
                        to={p.path}
                        className="rounded-lg border border-border px-2 py-1 text-primary hover:bg-primary/10"
                      >
                        {p.label}
                      </Link>
                    ))}
                  </div>
                )}
              </div>
            )}
          </GlassCard>
        </>
      )}
    </div>
  );
}

function Metric({
  label,
  value,
  hint,
}: {
  label: string;
  value: number;
  hint?: string;
}) {
  return (
    <div className="rounded-lg bg-black/20 px-3 py-2" title={hint}>
      <p className="text-[11px] text-muted-foreground">{label}</p>
      <p className="text-lg font-semibold tabular-nums">{value}</p>
    </div>
  );
}
