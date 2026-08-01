import { GlassCard } from "@/components/ui/GlassCard";
import type { NorthboundHistoryEnvelope } from "@/lib/api/types";
import {
  buildNorthboundTurnoverGeometry,
  normalizeNorthboundHistorySeries,
} from "@/lib/northboundHistoryView";
import {
  fetchedAtText,
  formatCount,
  formatTurnoverMn,
  limitationLines,
  northboundStatusLabel,
} from "@/lib/northboundView";
import { cn } from "@/lib/utils";
import { AlertTriangle, Info, LineChart } from "lucide-react";
import { useMemo } from "react";

export type NorthboundTurnoverHistoryChartProps = {
  env: NorthboundHistoryEnvelope | null;
  loading?: boolean;
  error?: string | null;
  className?: string;
};

function pointTitle(
  tradeDate: string,
  total: number,
  tradeCount: number | null,
  etf: number | null,
): string {
  return [
    tradeDate,
    `北向成交额 ${formatTurnoverMn(total)}`,
    `成交笔数 ${formatCount(tradeCount)}`,
    `ETF 成交额 ${formatTurnoverMn(etf)}`,
  ].join("\n");
}

export function NorthboundTurnoverHistoryChart({
  env,
  loading = false,
  error = null,
  className,
}: NorthboundTurnoverHistoryChartProps) {
  const points = useMemo(
    () => normalizeNorthboundHistorySeries(env, 20),
    [env],
  );
  const geometry = useMemo(
    () => buildNorthboundTurnoverGeometry(points, 640, 220),
    [points],
  );

  if (loading) {
    return (
      <GlassCard className={cn("mb-6", className)}>
        <div role="status" aria-live="polite" aria-busy="true" className="space-y-4">
          <span className="sr-only">北向成交历史加载中...</span>
          <div className="flex items-center justify-between">
            <div className="h-6 w-40 skeleton rounded" />
            <div className="h-5 w-16 skeleton rounded-full" />
          </div>
          <div className="h-4 w-72 skeleton rounded" />
          <div className="h-40 skeleton rounded-lg" />
        </div>
      </GlassCard>
    );
  }

  if (error) {
    return (
      <GlassCard className={cn("mb-6", className)}>
        <div role="alert" className="flex items-center gap-2 p-2 text-destructive">
          <AlertTriangle className="h-4 w-4 shrink-0" />
          <span className="text-sm font-medium">北向成交历史暂不可用</span>
        </div>
      </GlassCard>
    );
  }

  const badge = northboundStatusLabel(env?.status);
  const fetchedTime = fetchedAtText(env?.fetched_at);
  const limitations = limitationLines(env);
  const requested = env?.requested_days ?? 20;
  const returned = points.length;
  const unavailable = !env || env.status === "unavailable" || points.length === 0;

  return (
    <GlassCard className={cn("mb-6 space-y-4", className)} data-testid="northbound-turnover-history-chart">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border/40 pb-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="flex items-center gap-1.5 text-base font-semibold text-foreground">
              <LineChart className="h-4 w-4 text-primary" /> 北向成交额历史
            </h3>
            <span className={cn("rounded-full px-2 py-0.5 text-[10px] font-medium", badge.cls)}>
              {badge.text}
            </span>
          </div>
          <p className="mt-1 text-xs text-muted-foreground">
            近 20 个有效交易日 · HKEX 沪深股通成交额合计
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
          <span>来源: {env?.source || "HKEX Stock Connect Daily Statistics"}</span>
          <span>抓取: {fetchedTime}</span>
        </div>
      </div>

      <p className="text-[11px] text-muted-foreground">
        成交额不代表净买入或净流入。
      </p>

      {unavailable ? (
        <div className="flex items-center gap-2 rounded-lg border border-border/50 bg-muted/20 px-3 py-4 text-sm text-muted-foreground">
          <Info className="h-4 w-4 shrink-0" />
          暂无可用的北向成交历史数据
        </div>
      ) : (
        <>
          <div className="text-xs text-muted-foreground">
            {env?.status === "partial"
              ? `仅返回 ${returned}/${requested} 个有效交易日`
              : `已返回 ${returned}/${requested} 个有效交易日`}
          </div>

          {env?.status === "partial" && (
            <div className="space-y-1 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-800 dark:text-amber-300">
              {limitations.length > 0
                ? limitations.map((line) => <p key={line}>{line}</p>)
                : <p>部分交易日缺失或可选字段不完整。</p>}
            </div>
          )}

          <div className="overflow-x-auto">
            <svg
              role="img"
              aria-label="北向成交额历史折线图"
              viewBox={`0 0 ${geometry.width} ${geometry.height}`}
              className="h-auto w-full min-w-[320px] text-primary"
              data-testid="northbound-turnover-history-svg"
            >
              {/* horizontal guides: max / mid / zero */}
              {[
                { value: geometry.maxValue, y: geometry.padT },
                { value: geometry.midValue, y: geometry.padT + geometry.plotH / 2 },
                { value: 0, y: geometry.zeroY },
              ].map((g) => (
                <g key={`guide-${g.value}-${g.y}`}>
                  <line
                    x1={geometry.padL}
                    x2={geometry.padL + geometry.plotW}
                    y1={g.y}
                    y2={g.y}
                    stroke="currentColor"
                    strokeOpacity={0.15}
                    strokeWidth={1}
                  />
                  <text
                    x={geometry.padL - 6}
                    y={g.y + 3}
                    textAnchor="end"
                    className="fill-muted-foreground"
                    fontSize="10"
                  >
                    {formatTurnoverMn(g.value)}
                  </text>
                </g>
              ))}

              {geometry.polyline && (
                <polyline
                  fill="none"
                  stroke="currentColor"
                  strokeWidth={2}
                  strokeLinejoin="round"
                  strokeLinecap="round"
                  points={geometry.polyline}
                />
              )}

              {geometry.points.map((p) => (
                <circle
                  key={p.trade_date}
                  cx={p.x}
                  cy={p.y}
                  r={3.5}
                  fill="currentColor"
                  data-date={p.trade_date}
                  data-total-turnover={String(p.total_turnover_mn)}
                  data-testid="northbound-turnover-point"
                >
                  <title>
                    {pointTitle(
                      p.trade_date,
                      p.total_turnover_mn,
                      p.trade_count,
                      p.etf_turnover_mn,
                    )}
                  </title>
                </circle>
              ))}

              {geometry.points.length > 0 && (
                <>
                  <text
                    x={geometry.points[0].x}
                    y={geometry.height - 8}
                    textAnchor={geometry.points.length === 1 ? "middle" : "start"}
                    className="fill-muted-foreground"
                    fontSize="10"
                  >
                    {geometry.points[0].trade_date}
                  </text>
                  {geometry.points.length > 1 && (
                    <text
                      x={geometry.points[geometry.points.length - 1].x}
                      y={geometry.height - 8}
                      textAnchor="end"
                      className="fill-muted-foreground"
                      fontSize="10"
                    >
                      {geometry.points[geometry.points.length - 1].trade_date}
                    </text>
                  )}
                </>
              )}
            </svg>
          </div>
        </>
      )}

      {env?.status === "normal" && limitations.length > 0 && (
        <div className="space-y-1 text-[11px] text-muted-foreground">
          {limitations.map((line) => (
            <p key={line}>{line}</p>
          ))}
        </div>
      )}
    </GlassCard>
  );
}
