import { useMemo } from "react";
import type { KlineBar } from "@/lib/api";

/**
 * 轻量 SVG K 线（蜡烛图）：自包含、无外部图表库依赖。
 * 输入 mootdx OHLC bars；自动适配高/低区间，红涨绿跌（A 股配色）。
 */
export function KlineChart({ bars }: { bars: KlineBar[] }) {
  const W = 720;
  const H = 220;
  const PAD_X = 36;
  const PAD_Y = 16;
  const plotW = W - PAD_X * 2;
  const plotH = H - PAD_Y * 2;

  const { candles, hi, lo, lastClose } = useMemo(() => {
    const norm = bars
      .map((b) => {
        const date = b.date ?? b.datetime ?? "";
        const open = Number(b.open);
        const close = Number(b.close);
        const high = Number(b.high);
        const low = Number(b.low);
        if (![open, close, high, low].every(Number.isFinite)) return null;
        return { date, open, close, high, low };
      })
      .filter((c): c is NonNullable<typeof c> => c !== null);

    let hi = -Infinity;
    let lo = Infinity;
    for (const c of norm) {
      if (c.high > hi) hi = c.high;
      if (c.low < lo) lo = c.low;
    }
    if (!Number.isFinite(hi) || !Number.isFinite(lo)) {
      hi = 1;
      lo = 0;
    }
    if (hi === lo) {
      hi += 1;
      lo -= 1;
    }
    const lastClose = norm.length ? norm[norm.length - 1].close : null;
    return { candles: norm, hi, lo, lastClose };
  }, [bars]);

  if (candles.length === 0) {
    return <p className="py-6 text-center text-xs text-muted-foreground">无有效 K 线数据。</p>;
  }

  const n = candles.length;
  const step = plotW / Math.max(n, 1);
  const cw = Math.max(2, Math.min(10, step * 0.7));
  const yOf = (v: number) => PAD_Y + ((hi - v) / (hi - lo)) * plotH;
  const xOf = (i: number) => PAD_X + i * step + step / 2;
  // 收盘价格折线（叠加）
  const linePts = candles
    .map((c, i) => `${xOf(i).toFixed(1)},${yOf(c.close).toFixed(1)}`)
    .join(" ");
  const last = candles[candles.length - 1];

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-baseline gap-3 text-xs text-muted-foreground">
        <span>最新收盘 <b className="font-mono text-foreground">{lastClose?.toFixed(2) ?? "—"}</b></span>
        <span>区间 <b className="font-mono text-foreground">{lo.toFixed(2)} – {hi.toFixed(2)}</b></span>
        <span className="font-mono">{candles[0]?.date} → {last.date}</span>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" preserveAspectRatio="xMidYMid meet" role="img" aria-label="K 线图">
        {/* 网格线 */}
        {[0, 0.25, 0.5, 0.75, 1].map((t) => {
          const y = PAD_Y + plotH * t;
          const v = hi - (hi - lo) * t;
          return (
            <g key={t}>
              <line x1={PAD_X} y1={y} x2={W - PAD_X} y2={y} stroke="hsl(var(--border) / 0.5)" strokeWidth={1} />
              <text x={4} y={y + 3} fontSize={9} fill="hsl(var(--muted-foreground) / 0.6)">{v.toFixed(2)}</text>
            </g>
          );
        })}
        {/* 收盘折线 */}
        <polyline points={linePts} fill="none" stroke="hsl(var(--primary) / 0.5)" strokeWidth={1} />
        {/* 蜡烛 */}
        {candles.map((c, i) => {
          const up = c.close >= c.open;
          const color = up ? "hsl(var(--danger))" : "hsl(var(--success))";
          const x = xOf(i);
          const yOpen = yOf(c.open);
          const yClose = yOf(c.close);
          const bodyTop = Math.min(yOpen, yClose);
          const bodyH = Math.max(1, Math.abs(yClose - yOpen));
          return (
            <g key={i}>
              <line x1={x} y1={yOf(c.high)} x2={x} y2={yOf(c.low)} stroke={color} strokeWidth={1} />
              <rect x={x - cw / 2} y={bodyTop} width={cw} height={bodyH} fill={color} />
            </g>
          );
        })}
      </svg>
    </div>
  );
}
