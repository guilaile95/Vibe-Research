import { useMemo } from "react";
import type { KlineBar, TechnicalIndicators } from "@/lib/api";
import {
  buildKlineIndicatorGeometry,
  formatOverlayPrice,
  hasAnyOverlayMetric,
  normalizeKlineIndicatorOverlay,
  type KlineIndicatorMetric,
  type KlineMetricSegment,
} from "@/lib/klineIndicatorOverlay";

export type KlineChartProps = {
  bars: KlineBar[];
  indicators?: TechnicalIndicators | null;
};

const METRIC_META: Record<
  KlineIndicatorMetric,
  { label: string; testId: string; stroke: string; dash?: string }
> = {
  sma20: {
    label: "SMA20",
    testId: "kline-overlay-sma20",
    stroke: "hsl(var(--primary))",
  },
  sma60: {
    label: "SMA60",
    testId: "kline-overlay-sma60",
    stroke: "hsl(var(--warning))",
  },
  bollinger_upper: {
    label: "BOLL 上轨",
    testId: "kline-overlay-bollinger-upper",
    stroke: "hsl(var(--muted-foreground))",
    dash: "4 3",
  },
  bollinger_lower: {
    label: "BOLL 下轨",
    testId: "kline-overlay-bollinger-lower",
    stroke: "hsl(var(--muted-foreground))",
    dash: "4 3",
  },
};

function segmentPointsAttr(seg: KlineMetricSegment): string {
  return seg.points.map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(" ");
}

function candleTitle(c: {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  sma20: number | null;
  sma60: number | null;
  bollinger_upper: number | null;
  bollinger_lower: number | null;
}): string {
  const lines = [
    c.date,
    `开盘 ${formatOverlayPrice(c.open)}`,
    `最高 ${formatOverlayPrice(c.high)}`,
    `最低 ${formatOverlayPrice(c.low)}`,
    `收盘 ${formatOverlayPrice(c.close)}`,
  ];
  if (c.sma20 != null) lines.push(`SMA20 ${formatOverlayPrice(c.sma20)}`);
  if (c.sma60 != null) lines.push(`SMA60 ${formatOverlayPrice(c.sma60)}`);
  if (c.bollinger_upper != null) lines.push(`BOLL 上轨 ${formatOverlayPrice(c.bollinger_upper)}`);
  if (c.bollinger_lower != null) lines.push(`BOLL 下轨 ${formatOverlayPrice(c.bollinger_lower)}`);
  return lines.join("\n");
}

/**
 * 轻量 SVG K 线（蜡烛图）+ 可选价格指标叠加。
 * 无外部图表库依赖；指标失败不影响 K 线展示。
 */
export function KlineChart({ bars, indicators = null }: KlineChartProps) {
  const points = useMemo(
    () => normalizeKlineIndicatorOverlay(bars, indicators?.series ?? null, 60),
    [bars, indicators],
  );
  const geometry = useMemo(
    () => buildKlineIndicatorGeometry(points, 720, 220),
    [points],
  );

  const hasOverlay = hasAnyOverlayMetric(points);
  const partialNote =
    indicators?.status === "partial" && hasOverlay ? "技术指标部分缺失" : null;

  const activeMetrics = (Object.keys(METRIC_META) as KlineIndicatorMetric[]).filter(
    (m) => geometry.metricSegments[m].length > 0,
  );

  if (geometry.candles.length === 0) {
    return <p className="py-6 text-center text-xs text-muted-foreground">无有效 K 线数据。</p>;
  }

  const last = geometry.candles[geometry.candles.length - 1];
  const lastClose = last.close;
  const hi = geometry.priceHigh;
  const lo = geometry.priceLow;
  const { width: W, height: H, padX, padY, plotH, candleWidth: cw } = geometry;

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-baseline gap-3 text-xs text-muted-foreground">
        <span>
          最新收盘 <b className="font-mono text-foreground">{formatOverlayPrice(lastClose)}</b>
        </span>
        <span>
          区间{" "}
          <b className="font-mono text-foreground">
            {formatOverlayPrice(lo)} – {formatOverlayPrice(hi)}
          </b>
        </span>
        <span className="font-mono">
          {geometry.candles[0]?.date} → {last.date}
        </span>
        {partialNote && (
          <span className="rounded bg-warning/10 px-1.5 py-0.5 text-[11px] text-warning">
            {partialNote}
          </span>
        )}
      </div>

      {activeMetrics.length > 0 && (
        <div className="flex flex-wrap gap-3 text-[11px] text-muted-foreground" data-testid="kline-overlay-legend">
          {activeMetrics.map((m) => (
            <span key={m} className="inline-flex items-center gap-1.5">
              <span
                className="inline-block h-0.5 w-3 rounded"
                style={{
                  background: METRIC_META[m].stroke,
                  borderBottom: METRIC_META[m].dash ? `1px dashed ${METRIC_META[m].stroke}` : undefined,
                }}
              />
              {METRIC_META[m].label}
            </span>
          ))}
        </div>
      )}

      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="w-full"
        preserveAspectRatio="xMidYMid meet"
        role="img"
        aria-label={hasOverlay ? "K 线及技术指标图" : "K 线图"}
        data-testid="kline-chart-svg"
      >
        {/* 网格线 */}
        {[0, 0.25, 0.5, 0.75, 1].map((t) => {
          const y = padY + plotH * t;
          const v = hi - (hi - lo) * t;
          return (
            <g key={t}>
              <line
                x1={padX}
                y1={y}
                x2={W - padX}
                y2={y}
                stroke="hsl(var(--border) / 0.5)"
                strokeWidth={1}
              />
              <text x={4} y={y + 3} fontSize={9} fill="hsl(var(--muted-foreground) / 0.6)">
                {formatOverlayPrice(v)}
              </text>
            </g>
          );
        })}

        {/* 收盘折线 */}
        {geometry.closeLine && (
          <polyline
            points={geometry.closeLine}
            fill="none"
            stroke="hsl(var(--primary) / 0.5)"
            strokeWidth={1}
          />
        )}

        {/* 指标叠加（断点分段） */}
        {activeMetrics.map((metric) => {
          const meta = METRIC_META[metric];
          return geometry.metricSegments[metric].map((seg, idx) => {
            if (seg.points.length === 1) {
              const p = seg.points[0];
              return (
                <circle
                  key={`${metric}-pt-${idx}-${p.date}`}
                  cx={p.x}
                  cy={p.y}
                  r={2.2}
                  fill={meta.stroke}
                  data-testid={meta.testId}
                  data-indicator={metric}
                />
              );
            }
            const pts = segmentPointsAttr(seg);
            return (
              <polyline
                key={`${metric}-seg-${idx}`}
                points={pts}
                fill="none"
                stroke={meta.stroke}
                strokeWidth={1.5}
                strokeDasharray={meta.dash}
                strokeLinejoin="round"
                strokeLinecap="round"
                data-testid={meta.testId}
                data-indicator={metric}
              />
            );
          });
        })}

        {/* 蜡烛 */}
        {geometry.candles.map((c) => {
          const color = c.up ? "hsl(var(--danger))" : "hsl(var(--success))";
          return (
            <g key={c.date} data-testid="kline-candle" data-date={c.date}>
              <title>{candleTitle(c)}</title>
              <line x1={c.x} y1={c.yHigh} x2={c.x} y2={c.yLow} stroke={color} strokeWidth={1} />
              <rect x={c.x - cw / 2} y={c.bodyTop} width={cw} height={c.bodyH} fill={color} />
            </g>
          );
        })}
      </svg>
    </div>
  );
}
