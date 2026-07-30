import { type TechnicalIndicators } from "@/lib/api";
import {
  formatIndicator,
  formatPrice,
  formatVolumeRatio,
  indicatorStatusLabel,
  limitationLines,
  rsiZoneLabel,
  triggerLines,
} from "@/lib/technicalIndicatorsView";
import { cn } from "@/lib/utils";

interface Props {
  env: TechnicalIndicators | null;
  loading: boolean;
  error: string | null;
}

/** 纯 SVG SMA20 / SMA60 叠加折线（无图表库）。复用 K 线坐标系风格。 */
function SmaOverlay({ series }: { series: TechnicalIndicators["series"] }) {
  const W = 720;
  const H = 160;
  const PAD_X = 36;
  const PAD_Y = 14;
  const plotW = W - PAD_X * 2;
  const plotH = H - PAD_Y * 2;

  const pts = series.filter(
    (p) => (typeof p.sma20 === "number" && Number.isFinite(p.sma20)) ||
      (typeof p.sma60 === "number" && Number.isFinite(p.sma60)),
  );
  if (pts.length === 0) {
    return <p className="py-4 text-center text-xs text-muted-foreground">暂无均线数据。</p>;
  }

  let hi = -Infinity;
  let lo = Infinity;
  for (const p of pts) {
    if (typeof p.sma20 === "number" && p.sma20 > hi) hi = p.sma20;
    if (typeof p.sma20 === "number" && p.sma20 < lo) lo = p.sma20;
    if (typeof p.sma60 === "number" && p.sma60 > hi) hi = p.sma60;
    if (typeof p.sma60 === "number" && p.sma60 < lo) lo = p.sma60;
  }
  if (!Number.isFinite(hi) || !Number.isFinite(lo) || hi === lo) {
    hi += 1;
    lo -= 1;
  }

  const n = pts.length;
  const step = plotW / Math.max(n, 1);
  const xOf = (i: number) => PAD_X + i * step + step / 2;
  const yOf = (v: number) => PAD_Y + ((hi - v) / (hi - lo)) * plotH;

  const lineOf = (key: "sma20" | "sma60") =>
    pts
      .map((p, i) => {
        const v = p[key];
        return typeof v === "number" && Number.isFinite(v) ? `${xOf(i).toFixed(1)},${yOf(v).toFixed(1)}` : null;
      })
      .filter((s): s is string => s !== null)
      .join(" ");

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full" preserveAspectRatio="xMidYMid meet" role="img" aria-label="SMA20 与 SMA60 均线">
      {[0, 0.25, 0.5, 0.75, 1].map((t) => {
        const y = PAD_Y + plotH * t;
        return (
          <line key={t} x1={PAD_X} y1={y} x2={W - PAD_X} y2={y} stroke="hsl(var(--border) / 0.5)" strokeWidth={1} />
        );
      })}
      <polyline points={lineOf("sma20")} fill="none" stroke="hsl(var(--accent))" strokeWidth={1.2} />
      <polyline points={lineOf("sma60")} fill="none" stroke="hsl(var(--primary))" strokeWidth={1.2} />
      <text x={PAD_X} y={H - 3} fontSize={9} fill="hsl(var(--muted-foreground) / 0.6)">
        <tspan fill="hsl(var(--accent))">● SMA20</tspan>
        <tspan dx={12} fill="hsl(var(--primary))">● SMA60</tspan>
      </text>
    </svg>
  );
}

/** 紧凑数值条（用于 MACD / RSI 面板）：条形长度表示相对位置，不做复杂副图。 */
function MiniBar({ value, min = 0, max = 100 }: { value: number | null; min?: number; max?: number }) {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return <span className="font-mono text-xs text-muted-foreground">—</span>;
  }
  const span = Math.max(max - min, 1e-6);
  const pct = Math.min(100, Math.max(0, ((value - min) / span) * 100));
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className="relative inline-block h-1.5 w-16 overflow-hidden rounded-full bg-muted/50">
        <span className="absolute inset-y-0 left-0 rounded-full bg-primary" style={{ width: `${pct}%` }} />
      </span>
      <span className="font-mono text-xs text-foreground">{value.toFixed(2)}</span>
    </span>
  );
}

export function TechnicalIndicatorsCard({ env, loading, error }: Props) {
  if (loading) {
    return (
      <section
        role="status"
        aria-live="polite"
        aria-busy="true"
        className="card-surface mb-4 p-5"
      >
        <span className="sr-only">技术指标加载中…</span>
        <div className="space-y-3">
          <div className="skeleton h-5 w-32" />
          <div className="skeleton h-4 w-48" />
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {Array.from({ length: 8 }).map((_, i) => (
              <div key={i} className="skeleton h-14 rounded-lg bg-muted/30" />
            ))}
          </div>
          <div className="skeleton h-24 w-full" />
        </div>
      </section>
    );
  }

  if (error) {
    return (
      <section role="alert" className="card-surface mb-4 border-warning/30 p-5">
        <div className="flex items-center gap-2 text-sm text-warning">
          <span className="font-semibold">技术指标</span>
          <span className="rounded border border-warning/40 bg-warning/10 px-1.5 py-0.5 text-[10px]">不可用</span>
        </div>
        <p className="mt-2 text-sm text-warning">{error}</p>
      </section>
    );
  }

  if (!env) {
    return (
      <section className="card-surface mb-4 p-5">
        <div className="py-6 text-center text-sm text-muted-foreground">暂无技术指标数据。</div>
      </section>
    );
  }

  const status = indicatorStatusLabel(env.status);
  const rsi = rsiZoneLabel(env.latest.rsi14);
  const triggers = triggerLines(env.triggers);
  const limitations = limitationLines(env);

  const latest = env.latest;
  const maGrid: Array<{ k: string; v: string; sub?: string; subCls?: string }> = [
    { k: "SMA5", v: formatPrice(latest.sma5) },
    { k: "SMA10", v: formatPrice(latest.sma10) },
    { k: "SMA20", v: formatPrice(latest.sma20) },
    { k: "SMA60", v: formatPrice(latest.sma60) },
    { k: "EMA12", v: formatPrice(latest.ema12) },
    { k: "EMA26", v: formatPrice(latest.ema26) },
    { k: "RSI14", v: formatIndicator(latest.rsi14), sub: rsi.text, subCls: rsi.cls },
    { k: "量比", v: formatVolumeRatio(latest.volume_ratio_5_20) },
  ];

  return (
    <section className="card-surface mb-4 p-5">
      <div className="mb-3 flex flex-wrap items-baseline gap-2">
        <h3 className="flex items-center gap-1.5 text-sm font-semibold">
          <span className="block h-4 w-[3px] rounded-full bg-primary" /> 技术指标
        </h3>
        <span className={cn("rounded px-1.5 py-0.5 text-[10px]", status.cls)}>{status.text}</span>
        {env.trade_date && (
          <span className="font-mono text-xs text-muted-foreground">交易日 {env.trade_date}</span>
        )}
      </div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {maGrid.map((m) => (
          <div key={m.k} className="rounded-lg bg-muted/30 p-3">
            <p className="text-xs text-muted-foreground">{m.k}</p>
            <p className="mt-0.5 font-mono text-base font-bold">{m.v}</p>
            {m.sub && (
              <p className={cn("text-[11px]", m.subCls ?? "text-muted-foreground")}>{m.sub}</p>
            )}
          </div>
        ))}
      </div>

      {env.series.length > 0 && (
        <div className="mt-4">
          <p className="mb-1.5 text-xs text-muted-foreground">SMA20 / SMA60 均线</p>
          <SmaOverlay series={env.series} />
        </div>
      )}

      <div className="mt-4 grid grid-cols-3 gap-3 rounded-lg bg-muted/30 p-3">
        <div>
          <p className="text-xs text-muted-foreground">MACD DIF</p>
          <p className="mt-0.5 font-mono text-sm font-bold">{formatIndicator(latest.macd_dif)}</p>
        </div>
        <div>
          <p className="text-xs text-muted-foreground">DEA</p>
          <p className="mt-0.5 font-mono text-sm font-bold">{formatIndicator(latest.macd_dea)}</p>
        </div>
        <div>
          <p className="text-xs text-muted-foreground">MACD 柱</p>
          <p className={cn("mt-0.5 font-mono text-sm font-bold", (latest.macd_histogram ?? 0) >= 0 ? "text-danger" : "text-success")}>
            {formatIndicator(latest.macd_histogram)}
          </p>
        </div>
      </div>

      <div className="mt-4 grid grid-cols-3 gap-3 rounded-lg bg-muted/30 p-3">
        <div>
          <p className="text-xs text-muted-foreground">布林上轨</p>
          <p className="mt-0.5 font-mono text-sm font-bold">{formatPrice(latest.bollinger_upper)}</p>
        </div>
        <div>
          <p className="text-xs text-muted-foreground">中轨</p>
          <p className="mt-0.5 font-mono text-sm font-bold">{formatPrice(latest.bollinger_middle)}</p>
        </div>
        <div>
          <p className="text-xs text-muted-foreground">下轨</p>
          <p className="mt-0.5 font-mono text-sm font-bold">{formatPrice(latest.bollinger_lower)}</p>
        </div>
      </div>

      <div className="mt-4 flex items-center gap-3 rounded-lg bg-muted/30 p-3">
        <span className="text-xs text-muted-foreground">RSI14</span>
        <MiniBar value={latest.rsi14} min={0} max={100} />
        <span className={cn("text-[10px]", rsi.cls)}>{rsi.text}</span>
      </div>

      {triggers.length > 0 && (
        <div className="mt-4">
          <p className="mb-1.5 text-xs font-medium text-muted-foreground">触发事实</p>
          <ul className="space-y-1">
            {triggers.map((line, i) => (
              <li key={i} className="flex items-start gap-2 text-sm">
                <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-primary/60" />
                <span className="text-foreground">{line}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {limitations.length > 0 && (
        <div className="mt-4 rounded-lg border border-warning/30 bg-warning/5 p-3">
          <p className="mb-1 text-xs font-medium text-warning">数据局限</p>
          <ul className="space-y-1">
            {limitations.map((line, i) => (
              <li key={i} className="text-xs text-muted-foreground">{line}</li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
