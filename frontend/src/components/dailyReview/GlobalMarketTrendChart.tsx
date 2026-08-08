import { useMemo } from "react";
import type { GlobalIndexTrends } from "@/lib/api";

const COLORS = ["#60a5fa", "#3b82f6", "#22d3ee", "#f59e0b", "#a78bfa", "#fb7185", "#34d399", "#f97316"];
const WIDTH = 760;
const HEIGHT = 300;
const PLOT = { left: 48, right: 14, top: 16, bottom: 36 };
const PLOT_WIDTH = WIDTH - PLOT.left - PLOT.right;
const PLOT_HEIGHT = HEIGHT - PLOT.top - PLOT.bottom;

const toTimestamp = (value: string) => Date.parse(`${value.replace(" ", "T")}:00+08:00`);
const timeFormatter = new Intl.DateTimeFormat("zh-CN", {
  timeZone: "Asia/Shanghai",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});
const dateTimeFormatter = new Intl.DateTimeFormat("zh-CN", {
  timeZone: "Asia/Shanghai",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

const createTicks = (min: number, max: number, count: number) =>
  Array.from({ length: count }, (_, index) => min + ((max - min) * index) / (count - 1));

interface GlobalMarketTrendChartProps {
  trends: GlobalIndexTrends;
}

export function GlobalMarketTrendChart({ trends }: GlobalMarketTrendChartProps) {
  const chart = useMemo(() => {
    const normalized = trends.series.map((series, seriesIndex) => ({
      ...series,
      color: COLORS[seriesIndex % COLORS.length],
      points: series.points
        .map((point) => ({ timestamp: toTimestamp(point.time), value: point.change_pct }))
        .filter((point) => Number.isFinite(point.timestamp) && Number.isFinite(point.value)),
    }));
    const allPoints = normalized.flatMap((series) => series.points);
    if (allPoints.length < 2) {
      return { series: [], xTicks: [], yTicks: [], xScale: () => PLOT.left, yScale: () => PLOT.top, spansMultipleDates: false };
    }
    const minTime = Math.min(...allPoints.map((point) => point.timestamp));
    const maxTime = Math.max(...allPoints.map((point) => point.timestamp));
    const rawMin = Math.min(...allPoints.map((point) => point.value), 0);
    const rawMax = Math.max(...allPoints.map((point) => point.value), 0);
    const yStep = 0.5;
    const minY = Math.floor(rawMin / yStep) * yStep;
    const maxY = Math.max(minY + yStep, Math.ceil(rawMax / yStep) * yStep);
    const xScale = (value: number) => PLOT.left + ((value - minTime) / Math.max(1, maxTime - minTime)) * PLOT_WIDTH;
    const yScale = (value: number) => PLOT.top + ((maxY - value) / Math.max(yStep, maxY - minY)) * PLOT_HEIGHT;

    return {
      series: normalized.map((series) => ({
        ...series,
        path: series.points.map((point, index) => `${index ? "L" : "M"}${xScale(point.timestamp).toFixed(2)},${yScale(point.value).toFixed(2)}`).join(" "),
      })),
      xTicks: createTicks(minTime, maxTime, 6),
      yTicks: createTicks(minY, maxY, 5),
      xScale,
      yScale,
      spansMultipleDates: maxTime - minTime >= 24 * 60 * 60 * 1000,
    };
  }, [trends]);

  if (!chart.series.length) {
    return <div className="flex h-[260px] items-center justify-center text-sm text-muted-foreground">有效走势点不足</div>;
  }

  return (
    <div className="min-w-0" data-testid="global-market-trend-chart">
      <svg
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        className="h-auto min-h-[260px] w-full"
        role="img"
        aria-labelledby="global-market-trend-title global-market-trend-description"
      >
        <title id="global-market-trend-title">全球市场分时涨跌幅对比</title>
        <desc id="global-market-trend-description">{chart.series.map((item) => item.name).join("、")}，按北京时间对齐并相对各自昨收归一化。</desc>

        {chart.yTicks.map((value, index) => {
          const y = chart.yScale(value);
          return (
            <g key={`y-${index}`}>
              <line x1={PLOT.left} x2={WIDTH - PLOT.right} y1={y} y2={y} stroke="rgba(255,255,255,0.09)" strokeDasharray="3 3" />
              <text x={PLOT.left - 8} y={y + 3} textAnchor="end" fill="#a1a1aa" fontSize="10">{value.toFixed(1)}%</text>
            </g>
          );
        })}
        {chart.xTicks.map((value, index) => {
          const x = chart.xScale(value);
          return (
            <g key={`x-${index}`}>
              <line x1={x} x2={x} y1={PLOT.top} y2={HEIGHT - PLOT.bottom} stroke="rgba(255,255,255,0.06)" strokeDasharray="3 3" />
              <text x={x} y={HEIGHT - 12} textAnchor="middle" fill="#a1a1aa" fontSize="10">{chart.spansMultipleDates ? dateTimeFormatter.format(new Date(value)) : timeFormatter.format(new Date(value))}</text>
            </g>
          );
        })}
        <line x1={PLOT.left} x2={WIDTH - PLOT.right} y1={chart.yScale(0)} y2={chart.yScale(0)} stroke="rgba(255,255,255,0.3)" />
        {chart.series.map((series) => (
          <path key={series.key} d={series.path} fill="none" stroke={series.color} strokeWidth="1.6" strokeLinejoin="round" vectorEffect="non-scaling-stroke">
            <title>{`${series.name} ${series.change_pct > 0 ? "+" : ""}${series.change_pct.toFixed(2)}%`}</title>
          </path>
        ))}
      </svg>
      <div className="flex flex-wrap justify-center gap-x-4 gap-y-1 px-2 pb-1 text-[10px] text-muted-foreground sm:text-[11px]">
        {chart.series.map((series) => (
          <span key={series.key} className="inline-flex items-center gap-1.5">
            <span className="h-0.5 w-4 rounded-full" style={{ backgroundColor: series.color }} aria-hidden="true" />
            {series.name}
          </span>
        ))}
      </div>
    </div>
  );
}

export default GlobalMarketTrendChart;
