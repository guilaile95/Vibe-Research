import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";

import { GlassCard } from "@/components/ui/GlassCard";
import { api, type SectorMarketContextItem } from "@/lib/api";
import { formatActivity, formatSectorPercent } from "@/lib/sectorMarketView";
import { cn } from "@/lib/utils";


function valueClass(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "text-muted-foreground";
  if (value > 0) return "text-rose-600 dark:text-rose-400";
  if (value < 0) return "text-emerald-600 dark:text-emerald-400";
  return "text-foreground";
}


export function SectorMarketContext({ sectorKey }: { sectorKey: string }) {
  const [item, setItem] = useState<SectorMarketContextItem | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError(false);
    setItem(null);
    api.getSectorMarketContext(sectorKey)
      .then((result) => {
        if (alive) setItem(result.items[0] ?? null);
      })
      .catch(() => {
        if (alive) setError(true);
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => { alive = false; };
  }, [sectorKey]);

  return (
    <GlassCard className="mb-5 p-4 sm:p-5" data-sector-market-context={sectorKey}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 className="text-sm font-semibold">市场上下文</h2>
          <p className="mt-0.5 text-xs text-muted-foreground">指数趋势与当前成分截面 · observation only</p>
        </div>
        {item?.index && (
          <span className="rounded-full border border-border/60 bg-muted/20 px-2 py-0.5 text-[11px] text-muted-foreground">
            {item.index.name} · {item.index.thscode}
          </span>
        )}
      </div>

      {loading && (
        <div className="mt-4 flex items-center gap-2 text-xs text-muted-foreground">
          <Loader2 className="h-3.5 w-3.5 animate-spin" /> 加载市场事实…
        </div>
      )}
      {!loading && (error || !item) && (
        <p className="mt-4 text-xs text-muted-foreground">市场上下文暂不可用，产业研究内容不受影响。</p>
      )}
      {!loading && item?.mapping_status === "unavailable" && (
        <p className="mt-4 text-xs text-muted-foreground">未配置可核验的 Vibe Sector → THS Index 映射；不按名称猜测。</p>
      )}
      {!loading && item?.metrics && (
        <div className="mt-4 space-y-4">
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
            {[
              ["5日", item.metrics.return_5d_pct, formatSectorPercent(item.metrics.return_5d_pct)],
              ["20日", item.metrics.return_20d_pct, formatSectorPercent(item.metrics.return_20d_pct)],
              ["60日", item.metrics.return_60d_pct, formatSectorPercent(item.metrics.return_60d_pct)],
              ["5日动能变化", item.metrics.return_5d_delta_vs_previous_5d_pct, formatSectorPercent(item.metrics.return_5d_delta_vs_previous_5d_pct)],
              ["成交活跃度", null, formatActivity(item.metrics.turnover_vs_prior_20d)],
              ["指数日期", null, item.metrics.trade_date ?? "—"],
            ].map(([label, numeric, display]) => (
              <div key={String(label)} className="rounded-lg border border-border/50 bg-muted/15 px-2.5 py-2">
                <p className="text-[10px] text-muted-foreground">{label}</p>
                <p className={cn("mt-1 text-sm font-semibold", valueClass(numeric as number | null))}>{display}</p>
              </div>
            ))}
          </div>

          {item.breadth ? (
            <div>
              <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs">
                <span>当前成分 <strong>{item.breadth.constituents_total}</strong></span>
                <span className="text-rose-600 dark:text-rose-400">上涨 {item.breadth.up_count}</span>
                <span className="text-emerald-600 dark:text-emerald-400">下跌 {item.breadth.down_count}</span>
                <span>平盘 {item.breadth.flat_count}</span>
                <span>上涨占比 {item.breadth.up_ratio == null ? "—" : `${(item.breadth.up_ratio * 100).toFixed(1)}%`}</span>
                <span>当前成分等权代理 <strong className={valueClass(item.breadth.equal_weight_change_pct)}>{formatSectorPercent(item.breadth.equal_weight_change_pct)}</strong></span>
              </div>
              <div className="mt-2 flex flex-wrap gap-1.5">
                {item.breadth.constituents_sample.map((member) => (
                  <span key={member.code} className="rounded-full border border-border/50 px-2 py-0.5 text-[10px] text-muted-foreground">
                    {member.name} {formatSectorPercent(member.change_pct)}
                  </span>
                ))}
              </div>
            </div>
          ) : (
            <p className="text-xs text-muted-foreground">当前成分股宽度暂不可用。</p>
          )}

          <p className="text-[11px] leading-relaxed text-muted-foreground">
            5日动能变化 = 当前5日收益 − 前一段5日收益；成交活跃度 = 最新交易日成交额 / 此前20日均值，未做盘中时段归一。当前成分仅代表最新截面，不用于历史回填，也不代表指数权重或真实个股贡献。
          </p>
          {item.warnings.length > 0 && (
            <p className="text-[10px] text-muted-foreground">{item.warnings.join(" · ")}</p>
          )}
        </div>
      )}
    </GlassCard>
  );
}
