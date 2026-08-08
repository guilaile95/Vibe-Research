import { useMemo } from "react";
import { AlertTriangle, Info, LineChart } from "lucide-react";

import { GlassCard } from "@/components/ui/GlassCard";
import { cn } from "@/lib/utils";
import type { NorthboundHistoryEnvelope } from "@/lib/recoveredMarketTypes";
import {
  buildNorthboundTurnoverGeometry,
  normalizeNorthboundHistorySeries,
} from "@/lib/northboundHistoryView";

type Props = {
  env: NorthboundHistoryEnvelope | null;
  loading?: boolean;
  error?: string | null;
  className?: string;
};

function formatTurnover(value: number | null | undefined): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  return `${(value / 100).toFixed(2)} 亿`;
}

function formatCount(value: number | null | undefined): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  return Math.round(value).toLocaleString("zh-CN");
}

export function NorthboundTurnoverHistoryChart({ env, loading = false, error = null, className }: Props) {
  const points = useMemo(() => normalizeNorthboundHistorySeries(env, 20), [env]);
  const geometry = useMemo(() => buildNorthboundTurnoverGeometry(points), [points]);

  if (loading) {
    return <GlassCard className={cn("space-y-4", className)}><div role="status" className="skeleton h-48 rounded-lg" /></GlassCard>;
  }
  if (error) {
    return (
      <GlassCard className={className}>
        <div role="alert" className="flex items-center gap-2 text-sm text-destructive">
          <AlertTriangle className="h-4 w-4" />北向成交历史暂不可用
        </div>
      </GlassCard>
    );
  }

  const unavailable = !env || env.status === "unavailable" || points.length === 0;
  const limitationLines = (env?.limitations || []).map((item) => item.detail).filter(Boolean) as string[];

  return (
    <GlassCard className={cn("space-y-4", className)} data-testid="northbound-turnover-history-chart">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-border/50 pb-3">
        <div>
          <h3 className="flex items-center gap-2 text-base font-semibold"><LineChart className="h-4 w-4" />北向成交额历史</h3>
          <p className="mt-1 text-xs text-muted-foreground">近 20 个有效交易日 · HKEX 沪深股通成交额合计</p>
        </div>
        <span className="rounded-full border border-border px-2 py-0.5 text-[11px] text-muted-foreground">{env?.status || "unavailable"}</span>
      </div>
      <p className="text-[11px] text-muted-foreground">成交额不代表净买入或净流入。</p>

      {unavailable ? (
        <div className="flex items-center gap-2 rounded-lg border border-border/50 px-3 py-5 text-sm text-muted-foreground"><Info className="h-4 w-4" />暂无可用历史数据</div>
      ) : (
        <div className="overflow-x-auto">
          <svg role="img" aria-label="北向成交额历史折线图" viewBox={`0 0 ${geometry.width} ${geometry.height}`} className="h-auto w-full min-w-[320px] text-foreground">
            {[geometry.padT, geometry.padT + geometry.plotH / 2, geometry.zeroY].map((y) => (
              <line key={y} x1={geometry.padL} x2={geometry.padL + geometry.plotW} y1={y} y2={y} stroke="currentColor" strokeOpacity="0.12" />
            ))}
            {geometry.polyline ? <polyline fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" points={geometry.polyline} /> : null}
            {geometry.points.map((point) => (
              <circle key={point.trade_date} cx={point.x} cy={point.y} r="3.5" fill="currentColor" data-testid="northbound-turnover-point" data-date={point.trade_date}>
                <title>{`${point.trade_date}\n北向成交额 ${formatTurnover(point.total_turnover_mn)}\n成交笔数 ${formatCount(point.trade_count)}\nETF 成交额 ${formatTurnover(point.etf_turnover_mn)}`}</title>
              </circle>
            ))}
          </svg>
        </div>
      )}

      <div className="flex flex-wrap justify-between gap-2 text-[11px] text-muted-foreground">
        <span>来源：{env?.source || "HKEX Stock Connect Daily Statistics"}</span>
        <span>{env ? `${points.length}/${env.requested_days} 个有效交易日` : ""}</span>
      </div>
      {limitationLines.length ? <div className="space-y-1 text-[11px] text-muted-foreground">{limitationLines.map((line) => <p key={line}>{line}</p>)}</div> : null}
    </GlassCard>
  );
}
