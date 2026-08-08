import type {
  NorthboundHistoryEnvelope,
  NorthboundHistoryPoint,
} from "@/lib/recoveredMarketTypes";

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

function isValidCalendarDate(value: string): boolean {
  if (!DATE_RE.test(value)) return false;
  const [ys, ms, ds] = value.split("-");
  const y = Number(ys);
  const m = Number(ms);
  const d = Number(ds);
  const dt = new Date(Date.UTC(y, m - 1, d));
  return dt.getUTCFullYear() === y && dt.getUTCMonth() === m - 1 && dt.getUTCDate() === d;
}

function nonnegFinite(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) && value >= 0 ? value : null;
}

export function normalizeNorthboundHistorySeries(
  env: NorthboundHistoryEnvelope | null | undefined,
  maxPoints = 20,
): NorthboundHistoryPoint[] {
  if (!env || !Array.isArray(env.series) || maxPoints <= 0) return [];
  const out: NorthboundHistoryPoint[] = [];
  const seen = new Set<string>();
  for (const raw of env.series) {
    const tradeDate = typeof raw?.trade_date === "string" ? raw.trade_date.trim() : "";
    if (!isValidCalendarDate(tradeDate) || seen.has(tradeDate)) continue;
    const total = nonnegFinite(raw.total_turnover_mn);
    if (total === null) continue;
    const count = nonnegFinite(raw.trade_count);
    const etf = nonnegFinite(raw.etf_turnover_mn);
    seen.add(tradeDate);
    out.push({
      trade_date: tradeDate,
      total_turnover_mn: total,
      trade_count: count !== null && Number.isInteger(count) ? count : null,
      etf_turnover_mn: etf,
    });
  }
  out.sort((a, b) => a.trade_date.localeCompare(b.trade_date));
  return out.length > maxPoints ? out.slice(out.length - maxPoints) : out;
}

export type NorthboundTurnoverGeometryPoint = NorthboundHistoryPoint & { x: number; y: number };

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
  const rawMax = safePoints.length ? Math.max(...safePoints.map((point) => point.total_turnover_mn)) : 0;
  const scaleMax = rawMax > 0 ? rawMax : 1;
  const geoPoints = safePoints.map((point, index) => {
    const x = safePoints.length === 1
      ? padL + plotW / 2
      : padL + (plotW * index) / Math.max(1, safePoints.length - 1);
    const ratio = Math.min(1, Math.max(0, point.total_turnover_mn / scaleMax));
    return { ...point, x, y: padT + plotH * (1 - ratio) };
  });
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
    maxValue: rawMax,
    midValue: rawMax / 2,
    points: geoPoints,
    polyline: geoPoints.map((point) => `${point.x},${point.y}`).join(" "),
  };
}
