/** 北向成交额历史序列纯函数（可单测，无 React，永不抛异常）。 */
import type {
  NorthboundHistoryEnvelope,
  NorthboundHistoryPoint,
} from "@/lib/api/types";

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

function isValidCalendarDate(value: string): boolean {
  if (!DATE_RE.test(value)) return false;
  const [ys, ms, ds] = value.split("-");
  const y = Number(ys);
  const m = Number(ms);
  const d = Number(ds);
  if (!Number.isInteger(y) || !Number.isInteger(m) || !Number.isInteger(d)) return false;
  // Construct UTC date and require exact components (filters 2026-02-31 etc.).
  const dt = new Date(Date.UTC(y, m - 1, d));
  return (
    dt.getUTCFullYear() === y
    && dt.getUTCMonth() === m - 1
    && dt.getUTCDate() === d
  );
}

function nonnegFinite(value: unknown): number | null {
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0) return null;
  return value;
}

/**
 * Normalize northbound turnover history series for charting.
 * Does not mutate the input envelope/series.
 */
export function normalizeNorthboundHistorySeries(
  env: NorthboundHistoryEnvelope | null | undefined,
  maxPoints = 20,
): NorthboundHistoryPoint[] {
  if (!env || !Array.isArray(env.series) || maxPoints <= 0) return [];

  const out: NorthboundHistoryPoint[] = [];
  const seen = new Set<string>();

  for (const raw of env.series) {
    if (!raw || typeof raw !== "object") continue;
    const tradeDate = typeof raw.trade_date === "string" ? raw.trade_date.trim() : "";
    if (!isValidCalendarDate(tradeDate)) continue;
    if (seen.has(tradeDate)) continue; // first-wins

    const total = nonnegFinite(raw.total_turnover_mn);
    if (total === null) continue;

    const tradeCountRaw = nonnegFinite(raw.trade_count);
    const etfRaw = nonnegFinite(raw.etf_turnover_mn);
    // trade_count must be a finite non-negative integer-like value; otherwise null.
    const tradeCount =
      tradeCountRaw === null
        ? null
        : Number.isInteger(tradeCountRaw)
          ? tradeCountRaw
          : Math.round(tradeCountRaw) === tradeCountRaw
            ? tradeCountRaw
            : null;

    seen.add(tradeDate);
    out.push({
      trade_date: tradeDate,
      total_turnover_mn: total,
      trade_count: tradeCount,
      etf_turnover_mn: etfRaw,
    });
  }

  out.sort((a, b) => a.trade_date.localeCompare(b.trade_date));
  if (out.length > maxPoints) {
    return out.slice(out.length - maxPoints);
  }
  return out;
}

export type NorthboundTurnoverGeometryPoint = {
  trade_date: string;
  total_turnover_mn: number;
  trade_count: number | null;
  etf_turnover_mn: number | null;
  x: number;
  y: number;
};

export type NorthboundTurnoverGeometry = {
  width: number;
  height: number;
  padL: number;
  padR: number;
  padT: number;
  padB: number;
  plotW: number;
  plotH: number;
  zeroY: number;
  maxValue: number;
  midValue: number;
  points: NorthboundTurnoverGeometryPoint[];
  polyline: string;
};

/**
 * Pure geometry builder for the northbound turnover line chart.
 * Y-axis always starts at 0. All coordinates are finite.
 */
export function buildNorthboundTurnoverGeometry(
  points: NorthboundHistoryPoint[],
  width = 640,
  height = 220,
): NorthboundTurnoverGeometry {
  const w = Number.isFinite(width) && width > 0 ? width : 640;
  const h = Number.isFinite(height) && height > 0 ? height : 220;
  const padL = 44;
  const padR = 16;
  const padT = 16;
  const padB = 28;
  const plotW = Math.max(1, w - padL - padR);
  const plotH = Math.max(1, h - padT - padB);
  const zeroY = padT + plotH;

  const safePoints = Array.isArray(points) ? points : [];
  const values = safePoints.map((p) => p.total_turnover_mn).filter((v) => Number.isFinite(v) && v >= 0);
  const rawMax = values.length ? Math.max(...values) : 0;
  const maxValue = rawMax > 0 ? rawMax : 1; // prevent divide-by-zero; axis still starts at 0
  const midValue = maxValue / 2;

  const n = safePoints.length;
  const geoPoints: NorthboundTurnoverGeometryPoint[] = safePoints.map((p, i) => {
    const x =
      n === 1
        ? padL + plotW / 2
        : padL + (plotW * i) / Math.max(1, n - 1);
    const ratio = Math.min(1, Math.max(0, p.total_turnover_mn / maxValue));
    const y = padT + plotH * (1 - ratio);
    return {
      trade_date: p.trade_date,
      total_turnover_mn: p.total_turnover_mn,
      trade_count: p.trade_count,
      etf_turnover_mn: p.etf_turnover_mn,
      x: Number.isFinite(x) ? x : padL,
      y: Number.isFinite(y) ? y : zeroY,
    };
  });

  const polyline = geoPoints.map((p) => `${p.x},${p.y}`).join(" ");

  return {
    width: w,
    height: h,
    padL,
    padR,
    padT,
    padB,
    plotW,
    plotH,
    zeroY,
    maxValue: rawMax > 0 ? rawMax : 0,
    midValue: rawMax > 0 ? midValue : 0,
    points: geoPoints,
    polyline,
  };
}
