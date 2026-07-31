import { useMemo } from "react";
import { Loader2 } from "lucide-react";
import {
  formatCapitalFlowAmount,
  type SectorCapitalFlowSeries,
} from "@/lib/sectorCapitalFlow";
import { cn } from "@/lib/utils";

type Props = {
  series: SectorCapitalFlowSeries | null;
  loading: boolean;
};

function statusBadgeClass(status: SectorCapitalFlowSeries["status"]): string {
  if (status === "normal") {
    return "border-emerald-500/40 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400";
  }
  if (status === "partial") {
    return "border-amber-500/40 bg-amber-500/10 text-amber-700 dark:text-amber-400";
  }
  return "border-border/60 bg-muted/30 text-muted-foreground";
}

export function SectorCapitalFlowChart({ series, loading }: Props) {
  const chart = useMemo(() => {
    if (!series || series.points.length === 0) return null;
    const points = series.points;
    const maxAbs = Math.max(...points.map((p) => Math.abs(p.mainNet)), 1);
    const width = 640;
    const height = 180;
    const padL = 8;
    const padR = 8;
    const padT = 12;
    const padB = 20;
    const plotW = width - padL - padR;
    const plotH = height - padT - padB;
    const zeroY = padT + plotH / 2;
    const n = points.length;
    const gap = 1;
    const barW = Math.max(2, (plotW - gap * Math.max(0, n - 1)) / n);

    const bars = points.map((p, i) => {
      const x = padL + i * (barW + gap);
      const hRaw = (Math.abs(p.mainNet) / maxAbs) * (plotH / 2 - 2);
      const h = p.mainNet === 0 ? 1 : Math.max(hRaw, 1);
      const y = p.mainNet >= 0 ? zeroY - h : zeroY;
      const fill =
        p.mainNet > 0
          ? "rgb(244 63 94)" // rose — 正值
          : p.mainNet < 0
            ? "rgb(16 185 129)" // emerald — 负值
            : "rgb(148 163 184)";
      const title = [
        p.date,
        `主力净流入合计 ${formatCapitalFlowAmount(p.mainNet)}`,
        `当日覆盖 ${p.contributingCompanies}/${p.expectedCompanies} 家`,
      ].join("\n");
      return { x, y, w: barW, h, fill, title, date: p.date, mainNet: p.mainNet };
    });

    return { width, height, zeroY, padL, plotW, bars };
  }, [series]);

  return (
    <div
      data-testid="sector-capital-flow-chart"
      className="rounded-xl border border-border/50 bg-muted/10 px-3 py-3"
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <h4 className="text-sm font-semibold text-foreground">代表公司主力资金时序</h4>
          <p className="mt-0.5 text-[11px] text-muted-foreground">
            近 60 个有数据交易日 · 按代表公司 main_net 逐日合计
          </p>
          <p className="mt-1 text-[11px] text-muted-foreground/90">
            仅为代表公司合计，不代表完整行业资金流。
          </p>
        </div>
        {series && series.points.length > 0 && (
          <div className="flex flex-wrap items-center gap-1.5 text-[11px]">
            <span
              className={cn(
                "rounded-full border px-2 py-0.5 font-medium",
                statusBadgeClass(series.status),
              )}
            >
              {series.status}
            </span>
            <span className="rounded-full border border-border/60 bg-muted/20 px-2 py-0.5 text-muted-foreground">
              公司覆盖 {series.availableCompanies}/{series.expectedCompanies}
            </span>
            {series.latestDate && (
              <span className="text-muted-foreground">截至 {series.latestDate}</span>
            )}
          </div>
        )}
      </div>

      {series?.limitations?.length ? (
        <ul className="mt-2 space-y-0.5 text-[11px] text-amber-700 dark:text-amber-400">
          {series.limitations.map((lim, i) => (
            <li key={i}>· {lim}</li>
          ))}
        </ul>
      ) : null}

      {loading && !series?.points?.length ? (
        <div className="mt-3 flex items-center gap-2 text-xs text-muted-foreground">
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
          加载代表公司资金时序…
        </div>
      ) : !series || series.points.length === 0 ? (
        <p className="mt-3 text-xs text-muted-foreground">代表公司资金流暂不可用</p>
      ) : chart ? (
        <div className="mt-3 w-full overflow-x-auto">
          <svg
            viewBox={`0 0 ${chart.width} ${chart.height}`}
            className="h-[180px] w-full min-w-[280px]"
            role="img"
            aria-label="代表公司主力资金时序柱状图"
          >
            <line
              x1={chart.padL}
              x2={chart.padL + chart.plotW}
              y1={chart.zeroY}
              y2={chart.zeroY}
              stroke="currentColor"
              strokeOpacity={0.25}
              strokeWidth={1}
            />
            {chart.bars.map((b) => (
              <rect
                key={b.date}
                data-testid="sector-capital-flow-bar"
                data-date={b.date}
                data-sign={b.mainNet > 0 ? "pos" : b.mainNet < 0 ? "neg" : "zero"}
                x={b.x}
                y={b.y}
                width={b.w}
                height={b.h}
                fill={b.fill}
                opacity={0.9}
              >
                <title>{b.title}</title>
              </rect>
            ))}
          </svg>
        </div>
      ) : null}
    </div>
  );
}
