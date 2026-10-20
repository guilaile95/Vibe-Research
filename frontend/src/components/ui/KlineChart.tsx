import { useId, useMemo } from "react";
import type { KlineBar, TechnicalIndicators } from "@/lib/api";
import {
  buildKlineIndicatorGeometry,
  formatOverlayPrice,
  hasAnyOverlayMetric,
  normalizeKlineIndicatorOverlay,
  type KlineIndicatorMetric,
  type KlineMetricSegment,
} from "@/lib/klineIndicatorOverlay";

import { formatInspectionVolume, moveInspectionDate } from "@/lib/klineInspection";

export type KlineChartProps = {
  bars: KlineBar[];
  selectedDate?: string | null;
  onSelectedDateChange?: (date: string | null) => void;
  indicators?: TechnicalIndicators | null;
  researchMarkers?: readonly { date: string; label: string; href: string; title: string }[];
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
export function KlineChart({ bars, indicators = null, researchMarkers = [], selectedDate = null, onSelectedDateChange }: KlineChartProps) {
  const inspectionId = useId();
  const points = useMemo(
    () => normalizeKlineIndicatorOverlay(bars, indicators?.series ?? null, 60),
    [bars, indicators],
  );
  const geometry = useMemo(
    () => buildKlineIndicatorGeometry(points, 720, 220),
    [points],
  );

  const selected = geometry.candles.find((c) => c.date === selectedDate);
  const selectedPoint = points.find((c) => c.date === selectedDate);
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
    <div className="min-w-0 space-y-2">
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

      {onSelectedDateChange && <>
        <p id={`${inspectionId}-help`} className="text-xs text-muted-foreground">聚焦下方检查按钮，用左右键逐日查看，Home / End 到首末日，Escape 清除选择；也可点击蜡烛或文字表。仅显示最近 60 条有效日 K 线。成交量为来源原值，单位未提供，不推断为股或手。</p>
        <button type="button" data-testid="kline-inspection-control" aria-describedby={`${inspectionId}-help ${inspectionId}-status`}
          className="rounded border border-border px-3 py-2 text-xs focus:outline focus:outline-2 focus:outline-primary"
          onClick={() => onSelectedDateChange(selectedDate ?? last.date)}
          onKeyDown={(event) => {
            if (event.key === "Escape") { onSelectedDateChange(null); return; }
            if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key) || event.altKey || event.ctrlKey || event.metaKey) return;
            event.preventDefault();
            onSelectedDateChange(moveInspectionDate(points.map((p) => p.date), selectedDate, event.key));
          }}>键盘检查 K 线</button>
        <p id={`${inspectionId}-status`} role="status" aria-live="polite" className="break-words text-xs" data-testid="kline-inspection-status">
          {selected ? `已选 ${selected.date} · 开 ${formatOverlayPrice(selected.open)} · 高 ${formatOverlayPrice(selected.high)} · 低 ${formatOverlayPrice(selected.low)} · 收 ${formatOverlayPrice(selected.close)} · 量 ${formatInspectionVolume(selectedPoint?.volume)}（单位未知）`
            : selectedDate ? `${selectedDate}：当前窗口没有此日期的有效日 K 线，未选择相邻日期。` : "尚未选择日期"}
        </p>
      </>}
      <svg
        viewBox={`0 ${researchMarkers.length ? -28 : 0} ${W} ${H + (researchMarkers.length ? 28 : 0)}`}
        className="w-full"
        preserveAspectRatio="xMidYMid meet"
        role={onSelectedDateChange ? "group" : "img"}
        aria-label={hasOverlay ? "K 线及技术指标图" : "K 线图"}
        data-testid="kline-chart-svg"
      >
        {researchMarkers.map((marker) => {
          const candle = geometry.candles.find((item) => item.date === marker.date);
          if (!candle) return null;
          return (
            <a key={marker.date} href={marker.href} onClick={() => onSelectedDateChange?.(marker.date)} aria-label={marker.title} data-testid="kline-research-marker">
              <title>{marker.title}</title>
              <line x1={candle.x} x2={candle.x} y1={-3} y2={H} stroke="hsl(var(--primary) / 0.25)" strokeDasharray="3 3" />
              <circle cx={candle.x} cy={-14} r={11} fill="hsl(var(--primary))" />
              <text x={candle.x} y={-10} textAnchor="middle" fontSize={10} fill="hsl(var(--primary-foreground))">{marker.label}</text>
            </a>
          );
        })}
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
            <g key={c.date} data-testid="kline-candle" data-date={c.date} onClick={() => onSelectedDateChange?.(c.date)} style={{ cursor: onSelectedDateChange ? "pointer" : undefined }}>
              {onSelectedDateChange && <rect x={c.x - geometry.plotW / geometry.candles.length / 2} y={0} width={geometry.plotW / geometry.candles.length} height={H} fill="transparent" />}
              <title>{candleTitle(c)}</title>
              <line x1={c.x} y1={c.yHigh} x2={c.x} y2={c.yLow} stroke={color} strokeWidth={1} />
              <rect x={c.x - cw / 2} y={c.bodyTop} width={cw} height={c.bodyH} fill={color} />
            </g>
          );
        })}
        {selected && onSelectedDateChange && <g data-testid="kline-inspection-crosshair" pointerEvents="none" aria-hidden="true">
          <line x1={selected.x} x2={selected.x} y1={padY} y2={H - padY} stroke="hsl(var(--primary))" strokeDasharray="4 3" />
          <line x1={padX} x2={W - padX} y1={selected.yClose} y2={selected.yClose} stroke="hsl(var(--primary))" strokeDasharray="4 3" />
          <circle cx={selected.x} cy={selected.yClose} r={4} fill="hsl(var(--primary))" />
        </g>}
      </svg>
      {onSelectedDateChange && <details className="min-w-0 text-xs">
        <summary className="cursor-pointer py-2">查看可访问的 OHLCV 数据表（{points.length} 条）</summary>
        <div className="max-w-full overflow-x-auto" tabIndex={0} role="region" aria-label="日 K 线数据表，可横向滚动">
          <table className="w-full text-right" data-testid="kline-inspection-table">
            <caption className="py-2 text-left">当前窗口原始 OHLCV；成交量单位未知</caption>
            <thead><tr>{["日期", "开盘", "最高", "最低", "收盘", "成交量（原值）"].map((label) => <th key={label} scope="col" className="whitespace-nowrap p-2">{label}</th>)}</tr></thead>
            <tbody>{points.map((p) => <tr key={p.date} aria-selected={p.date === selectedDate} className={p.date === selectedDate ? "bg-primary/10" : ""}>
              <th scope="row" className="whitespace-nowrap p-2"><button type="button" className="py-1 text-primary underline" onClick={() => onSelectedDateChange(p.date)}>{p.date}</button></th>
              {[p.open, p.high, p.low, p.close].map((value, index) => <td key={index} className="whitespace-nowrap p-2 font-mono">{formatOverlayPrice(value)}</td>)}
              <td className="whitespace-nowrap p-2 font-mono">{formatInspectionVolume(p.volume)}</td>
            </tr>)}</tbody>
          </table>
        </div>
      </details>}
    </div>
  );
}
