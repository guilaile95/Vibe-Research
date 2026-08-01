/** K 线技术指标叠加纯函数（无 React / DOM / 网络）。 */
import type { KlineBar, TechnicalIndicatorSeriesPoint } from "@/lib/api/types";

export type KlineIndicatorOverlayPoint = {
  date: string;
  open: number;
  close: number;
  high: number;
  low: number;
  sma20: number | null;
  sma60: number | null;
  bollinger_upper: number | null;
  bollinger_lower: number | null;
};

export type KlineIndicatorMetric =
  | "sma20"
  | "sma60"
  | "bollinger_upper"
  | "bollinger_lower";

const METRICS: KlineIndicatorMetric[] = [
  "sma20",
  "sma60",
  "bollinger_upper",
  "bollinger_lower",
];

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

function isValidCalendarDate(value: string): boolean {
  if (!DATE_RE.test(value)) return false;
  const [ys, ms, ds] = value.split("-");
  const y = Number(ys);
  const m = Number(ms);
  const d = Number(ds);
  if (!Number.isInteger(y) || !Number.isInteger(m) || !Number.isInteger(d)) return false;
  const dt = new Date(Date.UTC(y, m - 1, d));
  return (
    dt.getUTCFullYear() === y
    && dt.getUTCMonth() === m - 1
    && dt.getUTCDate() === d
  );
}

function extractDate(raw: unknown): string | null {
  if (typeof raw !== "string") return null;
  const head = raw.trim().slice(0, 10);
  return isValidCalendarDate(head) ? head : null;
}

function positiveFinite(value: unknown): number | null {
  if (typeof value === "boolean" || value == null) return null;
  const n = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(n) || n <= 0) return null;
  return n;
}

function parseOhlc(bar: KlineBar): {
  date: string;
  open: number;
  close: number;
  high: number;
  low: number;
} | null {
  const date = extractDate(bar?.date ?? bar?.datetime);
  if (!date) return null;
  const open = positiveFinite(bar?.open);
  const close = positiveFinite(bar?.close);
  const high = positiveFinite(bar?.high);
  const low = positiveFinite(bar?.low);
  if (open == null || close == null || high == null || low == null) return null;
  if (high < low) return null;
  if (high < open || high < close) return null;
  if (low > open || low > close) return null;
  return { date, open, close, high, low };
}

function priceMetric(value: unknown): number | null {
  // Price overlays must be finite and > 0.
  return positiveFinite(value);
}

/**
 * Align K-line bars with technical-indicator series for price overlays.
 * Does not mutate inputs.
 */
export function normalizeKlineIndicatorOverlay(
  bars: KlineBar[] | null | undefined,
  indicatorSeries: TechnicalIndicatorSeriesPoint[] | null | undefined,
  maxPoints = 60,
): KlineIndicatorOverlayPoint[] {
  if (!Array.isArray(bars) || maxPoints <= 0) return [];

  // First valid K-line per date (skip invalids; later valid can fill if earlier invalid).
  const candleByDate = new Map<string, { open: number; close: number; high: number; low: number }>();
  for (const bar of bars) {
    const parsed = parseOhlc(bar);
    if (!parsed) continue;
    if (candleByDate.has(parsed.date)) continue;
    candleByDate.set(parsed.date, {
      open: parsed.open,
      close: parsed.close,
      high: parsed.high,
      low: parsed.low,
    });
  }

  // Indicator map: first valid date record wins.
  const indByDate = new Map<
    string,
    {
      sma20: number | null;
      sma60: number | null;
      bollinger_upper: number | null;
      bollinger_lower: number | null;
    }
  >();
  if (Array.isArray(indicatorSeries)) {
    for (const row of indicatorSeries) {
      if (!row || typeof row !== "object") continue;
      const date = extractDate(row.date);
      if (!date || indByDate.has(date)) continue;
      indByDate.set(date, {
        sma20: priceMetric(row.sma20),
        sma60: priceMetric(row.sma60),
        bollinger_upper: priceMetric(row.bollinger_upper),
        bollinger_lower: priceMetric(row.bollinger_lower),
      });
    }
  }

  const dates = Array.from(candleByDate.keys()).sort((a, b) => a.localeCompare(b));
  const kept = dates.length > maxPoints ? dates.slice(dates.length - maxPoints) : dates;

  return kept.map((date) => {
    const c = candleByDate.get(date)!;
    const ind = indByDate.get(date);
    return {
      date,
      open: c.open,
      close: c.close,
      high: c.high,
      low: c.low,
      sma20: ind?.sma20 ?? null,
      sma60: ind?.sma60 ?? null,
      bollinger_upper: ind?.bollinger_upper ?? null,
      bollinger_lower: ind?.bollinger_lower ?? null,
    };
  });
}

export type KlineGeometryCandle = {
  date: string;
  open: number;
  close: number;
  high: number;
  low: number;
  x: number;
  yOpen: number;
  yClose: number;
  yHigh: number;
  yLow: number;
  bodyTop: number;
  bodyH: number;
  up: boolean;
  sma20: number | null;
  sma60: number | null;
  bollinger_upper: number | null;
  bollinger_lower: number | null;
};

export type KlineMetricSegmentPoint = {
  date: string;
  value: number;
  x: number;
  y: number;
};

export type KlineMetricSegment = {
  points: KlineMetricSegmentPoint[];
};

export type KlineIndicatorGeometry = {
  width: number;
  height: number;
  padX: number;
  padY: number;
  plotW: number;
  plotH: number;
  priceHigh: number;
  priceLow: number;
  candles: KlineGeometryCandle[];
  closeLine: string;
  metricSegments: Record<KlineIndicatorMetric, KlineMetricSegment[]>;
  candleWidth: number;
};

function safeSize(value: unknown, fallback: number): number {
  if (typeof value !== "number" || !Number.isFinite(value) || value <= 0) return fallback;
  return value;
}

/**
 * Pure geometry for candles + price indicator overlays.
 * Y range includes all candle highs/lows and non-null overlay metrics.
 */
export function buildKlineIndicatorGeometry(
  points: KlineIndicatorOverlayPoint[],
  width?: number,
  height?: number,
): KlineIndicatorGeometry {
  const W = safeSize(width, 720);
  const H = safeSize(height, 220);
  const padX = 36;
  const padY = 16;
  const plotW = Math.max(1, W - padX * 2);
  const plotH = Math.max(1, H - padY * 2);

  const list = Array.isArray(points) ? points : [];
  let priceHigh = -Infinity;
  let priceLow = Infinity;
  for (const p of list) {
    if (Number.isFinite(p.high) && p.high > priceHigh) priceHigh = p.high;
    if (Number.isFinite(p.low) && p.low < priceLow) priceLow = p.low;
    for (const m of METRICS) {
      const v = p[m];
      if (typeof v === "number" && Number.isFinite(v)) {
        if (v > priceHigh) priceHigh = v;
        if (v < priceLow) priceLow = v;
      }
    }
  }
  if (!Number.isFinite(priceHigh) || !Number.isFinite(priceLow)) {
    priceHigh = 1;
    priceLow = 0;
  }
  if (priceHigh === priceLow) {
    // Expand safe band when all prices identical.
    const base = Math.abs(priceHigh) > 0 ? Math.abs(priceHigh) * 0.01 : 1;
    priceHigh += base;
    priceLow -= base;
  }

  const n = list.length;
  const step = plotW / Math.max(n, 1);
  const candleWidth = Math.max(2, Math.min(10, step * 0.7));
  const yOf = (v: number) => padY + ((priceHigh - v) / (priceHigh - priceLow)) * plotH;
  const xOf = (i: number) => padX + i * step + step / 2;

  const candles: KlineGeometryCandle[] = list.map((p, i) => {
    const x = xOf(i);
    const yOpen = yOf(p.open);
    const yClose = yOf(p.close);
    const yHigh = yOf(p.high);
    const yLow = yOf(p.low);
    const bodyTop = Math.min(yOpen, yClose);
    const bodyH = Math.max(1, Math.abs(yClose - yOpen));
    return {
      date: p.date,
      open: p.open,
      close: p.close,
      high: p.high,
      low: p.low,
      x: Number.isFinite(x) ? x : padX,
      yOpen: Number.isFinite(yOpen) ? yOpen : padY,
      yClose: Number.isFinite(yClose) ? yClose : padY,
      yHigh: Number.isFinite(yHigh) ? yHigh : padY,
      yLow: Number.isFinite(yLow) ? yLow : padY,
      bodyTop: Number.isFinite(bodyTop) ? bodyTop : padY,
      bodyH: Number.isFinite(bodyH) ? bodyH : 1,
      up: p.close >= p.open,
      sma20: p.sma20,
      sma60: p.sma60,
      bollinger_upper: p.bollinger_upper,
      bollinger_lower: p.bollinger_lower,
    };
  });

  const closeLine = candles
    .map((c) => `${c.x.toFixed(1)},${c.yClose.toFixed(1)}`)
    .join(" ");

  const metricSegments = {
    sma20: [] as KlineMetricSegment[],
    sma60: [] as KlineMetricSegment[],
    bollinger_upper: [] as KlineMetricSegment[],
    bollinger_lower: [] as KlineMetricSegment[],
  };

  for (const metric of METRICS) {
    let current: KlineMetricSegmentPoint[] = [];
    for (let i = 0; i < candles.length; i++) {
      const c = candles[i];
      const value = c[metric];
      if (typeof value === "number" && Number.isFinite(value) && value > 0) {
        const y = yOf(value);
        current.push({
          date: c.date,
          value,
          x: c.x,
          y: Number.isFinite(y) ? y : padY,
        });
      } else if (current.length) {
        metricSegments[metric].push({ points: current });
        current = [];
      }
    }
    if (current.length) {
      metricSegments[metric].push({ points: current });
    }
  }

  return {
    width: W,
    height: H,
    padX,
    padY,
    plotW,
    plotH,
    priceHigh,
    priceLow,
    candles,
    closeLine,
    metricSegments,
    candleWidth,
  };
}

export function formatOverlayPrice(v: number): string {
  if (!Number.isFinite(v)) return "—";
  return v.toFixed(2);
}

export function hasAnyOverlayMetric(points: KlineIndicatorOverlayPoint[]): boolean {
  for (const p of points) {
    for (const m of METRICS) {
      if (typeof p[m] === "number" && Number.isFinite(p[m]!)) return true;
    }
  }
  return false;
}

export { METRICS as KLINE_OVERLAY_METRICS };
