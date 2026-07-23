import { useCallback, useEffect, useRef, useState } from "react";
import { Loader2, RefreshCw } from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import {
  api,
  ApiError,
  type SectorDynamicData,
  type SectorDynamicPanel,
  type SectorPanelSummary,
} from "@/lib/api";
import { cn } from "@/lib/utils";

type Props = {
  sectorKey: string;
};

const PANEL_LABELS: Record<string, string> = {
  individual_info: "基本面",
  profit_forecast: "一致预期",
  announcements: "公告",
};

function statusBadgeClass(status: SectorDynamicData["status"]): string {
  if (status === "normal") return "border-emerald-500/40 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400";
  if (status === "partial") return "border-amber-500/40 bg-amber-500/10 text-amber-700 dark:text-amber-400";
  return "border-border/60 bg-muted/30 text-muted-foreground";
}

function panelOkCount(panels: Record<string, SectorDynamicPanel> | undefined): {
  ok: number;
  total: number;
  errors: string[];
} {
  if (!panels) return { ok: 0, total: 0, errors: [] };
  const keys = Object.keys(panels);
  let ok = 0;
  const errors: string[] = [];
  for (const k of keys) {
    const p = panels[k];
    if (p?.status === "ok") ok += 1;
    else if (p?.status === "error" && p.error) {
      errors.push(`${PANEL_LABELS[k] || k}: ${p.error}`);
    }
  }
  return { ok, total: keys.length, errors };
}

function s(summary: SectorPanelSummary | undefined, key: string): string | undefined {
  if (!summary) return undefined;
  const v = summary[key];
  if (v == null) return undefined;
  const t = String(v);
  return t || undefined;
}

export function SectorResearchLiveData({ sectorKey }: Props) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [data, setData] = useState<SectorDynamicData | null>(null);
  const [expanded, setExpanded] = useState(false);
  const inflight = useRef(false);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  // sectorKey 变化时清空旧数据
  useEffect(() => {
    setData(null);
    setError(null);
    setExpanded(false);
    inflight.current = false;
  }, [sectorKey]);

  const load = useCallback(async () => {
    if (inflight.current) return;
    inflight.current = true;
    setLoading(true);
    setError(null);
    try {
      const res = await api.getSectorResearchData(sectorKey);
      if (!mounted.current) return;
      setData(res);
    } catch (e) {
      if (!mounted.current) return;
      const msg = e instanceof ApiError ? e.message : e instanceof Error ? e.message : String(e);
      setError(msg);
    } finally {
      inflight.current = false;
      if (mounted.current) setLoading(false);
    }
  }, [sectorKey]);

  const onToggle = useCallback(() => {
    const next = !expanded;
    setExpanded(next);
    if (next && !data && !loading) {
      void load();
    }
  }, [expanded, data, loading, load]);

  const onRefresh = useCallback(() => {
    setExpanded(true);
    void load();
  }, [load]);

  return (
    <GlassCard className="p-4 sm:p-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h3 className="text-sm font-semibold text-foreground">动态数据</h3>
          <p className="mt-0.5 text-xs text-muted-foreground">
            代表公司 · 一致预期 / 公告 · 单家失败不空白整板
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={onRefresh}
            disabled={loading}
            className={cn(
              "inline-flex h-8 items-center gap-1 rounded-lg border border-border/60 px-2.5 text-xs text-muted-foreground",
              "hover:text-foreground disabled:opacity-60",
            )}
          >
            {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
            刷新
          </button>
          <button
            type="button"
            onClick={onToggle}
            className="inline-flex h-8 items-center rounded-lg border border-primary/40 bg-primary/10 px-2.5 text-xs font-medium text-primary hover:bg-primary/20"
          >
            {expanded ? "收起" : "展开加载"}
          </button>
        </div>
      </div>

      {error && (
        <div className="mt-3 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-foreground/90">
          {error}
        </div>
      )}

      {expanded && data && (
        <div className="mt-3 space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <span
              className={cn(
                "rounded-full border px-2 py-0.5 text-[11px] font-medium",
                statusBadgeClass(data.status),
              )}
            >
              {data.status}
            </span>
            {data.fetched_at && (
              <span className="text-[11px] text-muted-foreground">
                更新 {data.fetched_at.slice(0, 19).replace("T", " ")}
              </span>
            )}
            {data.source && (
              <span className="text-[11px] text-muted-foreground">源 {data.source}</span>
            )}
          </div>

          {data.warnings?.length > 0 && (
            <ul className="space-y-1 rounded-lg border border-border/50 bg-muted/20 px-3 py-2 text-[11px] text-muted-foreground">
              {data.warnings.map((w, i) => (
                <li key={i}>· {w}</li>
              ))}
            </ul>
          )}

          {data.error && (
            <p className="text-xs text-amber-600 dark:text-amber-400">{data.error}</p>
          )}

          {data.companies?.length > 0 ? (
            <div className="grid grid-cols-1 gap-2 min-[390px]:grid-cols-1 sm:grid-cols-2">
              {data.companies.map((c) => {
                const { ok, total, errors } = panelOkCount(c.panels);
                const panelKeys = Object.keys(c.panels || {});
                return (
                  <div
                    key={c.code}
                    className="rounded-xl border border-border/50 bg-muted/15 px-3 py-2.5"
                  >
                    <div className="flex items-baseline justify-between gap-2">
                      <p className="min-w-0 truncate text-sm font-medium">
                        {c.name || c.code}
                        <span className="ml-1.5 text-[11px] font-normal text-muted-foreground">
                          {c.code}
                        </span>
                      </p>
                      <span className="shrink-0 text-[11px] text-muted-foreground">
                        面板 {ok}/{total}
                      </span>
                    </div>
                    <div className="mt-1.5 flex flex-wrap gap-1">
                      {panelKeys.map((pk) => {
                        const p = c.panels?.[pk];
                        const st = p?.status;
                        return (
                          <span
                            key={pk}
                            className={cn(
                              "rounded-full border px-1.5 py-0.5 text-[10px]",
                              st === "ok" && "border-emerald-500/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-400",
                              st === "error" && "border-amber-500/40 bg-amber-500/10 text-amber-700 dark:text-amber-400",
                              !st && "border-border/50 text-muted-foreground",
                            )}
                            title={p?.error || undefined}
                          >
                            {PANEL_LABELS[pk] || pk}
                            {st === "ok" ? " ✓" : st === "error" ? " !" : ""}
                          </span>
                        );
                      })}
                    </div>

                    {c.panels.individual_info?.status === "ok" && (
                      <div className="mt-2 space-y-0.5 text-[11px] text-muted-foreground">
                        {s(c.panels.individual_info.summary, "industry") && (
                          <p>
                            <span className="font-medium text-foreground/80">行业：</span>
                            {s(c.panels.individual_info.summary, "industry")}
                          </p>
                        )}
                        {s(c.panels.individual_info.summary, "market_cap") && (
                          <p>
                            <span className="font-medium text-foreground/80">市值：</span>
                            {s(c.panels.individual_info.summary, "market_cap")}
                          </p>
                        )}
                        {s(c.panels.individual_info.summary, "business") && (
                          <p className="line-clamp-2">
                            <span className="font-medium text-foreground/80">主营：</span>
                            {s(c.panels.individual_info.summary, "business")}
                          </p>
                        )}
                      </div>
                    )}

                    {c.panels.profit_forecast?.status === "ok" && (
                      <div className="mt-2 space-y-0.5 text-[11px] text-muted-foreground">
                        {s(c.panels.profit_forecast.summary, "note") ? (
                          <p className="italic">{s(c.panels.profit_forecast.summary, "note")}</p>
                        ) : (
                          <>
                            {s(c.panels.profit_forecast.summary, "coverage") && (
                              <p>
                                <span className="font-medium text-foreground/80">机构数：</span>
                                {s(c.panels.profit_forecast.summary, "coverage")}
                              </p>
                            )}
                            {s(c.panels.profit_forecast.summary, "year") && (
                              <p>
                                <span className="font-medium text-foreground/80">预测年度：</span>
                                {s(c.panels.profit_forecast.summary, "year")}
                              </p>
                            )}
                            {(s(c.panels.profit_forecast.summary, "eps")
                              || s(c.panels.profit_forecast.summary, "forecast")) && (
                              <p>
                                <span className="font-medium text-foreground/80">预测：</span>
                                {s(c.panels.profit_forecast.summary, "eps")
                                  || s(c.panels.profit_forecast.summary, "forecast")}
                              </p>
                            )}
                          </>
                        )}
                      </div>
                    )}

                    {c.panels.announcements?.status === "ok" && (
                      <div className="mt-2 space-y-0.5 text-[11px] text-muted-foreground">
                        {s(c.panels.announcements.summary, "count") != null && (
                          <p>
                            <span className="font-medium text-foreground/80">公告数：</span>
                            {s(c.panels.announcements.summary, "count")}
                          </p>
                        )}
                        {s(c.panels.announcements.summary, "latest_date") && (
                          <p>
                            <span className="font-medium text-foreground/80">最新日期：</span>
                            {s(c.panels.announcements.summary, "latest_date")}
                          </p>
                        )}
                        {s(c.panels.announcements.summary, "latest_title") && (
                          <p className="line-clamp-2">
                            <span className="font-medium text-foreground/80">标题：</span>
                            {s(c.panels.announcements.summary, "latest_title")}
                          </p>
                        )}
                      </div>
                    )}

                    {errors.length > 0 && (
                      <p className="mt-1 line-clamp-2 text-[10px] text-muted-foreground">
                        {errors.join(" · ")}
                      </p>
                    )}
                  </div>
                );
              })}
            </div>
          ) : (
            !loading && (
              <p className="text-xs text-muted-foreground">暂无代表公司数据。</p>
            )
          )}
        </div>
      )}

      {expanded && loading && !data && (
        <div className="mt-3 flex items-center gap-2 text-xs text-muted-foreground">
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
          加载中…
        </div>
      )}
    </GlassCard>
  );
}
