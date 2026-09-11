import { LineChart, Loader2 } from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import type { StockRelativeContext, StockRelativeHorizon } from "@/lib/api";
import { formatSampleCoverage, formatStockRelativePercent } from "@/lib/stockRelativeContextView";

interface Props {
  data: StockRelativeContext | null;
  loading: boolean;
  error: string | null;
}

const HORIZONS: StockRelativeHorizon[] = ["5D", "20D", "60D"];

function statusLabel(status: StockRelativeContext["status"]): string {
  if (status === "normal") return "当前数据可比";
  if (status === "partial") return "部分数据可比";
  return "数据不可用";
}

export function StockRelativeContextCard({ data, loading, error }: Props) {
  if (!data && !loading && !error) return null;

  return (
    <GlassCard className="mb-4" data-testid="stock-relative-context">
      <div className="mb-3 flex items-center justify-between gap-3">
        <h3 className="flex items-center gap-1.5 text-sm font-semibold">
          <LineChart className="h-4 w-4 text-primary" /> 市场 / 行业相对表现
        </h3>
        {data && (
          <span className="rounded bg-muted/50 px-1.5 py-0.5 text-[10px] text-muted-foreground">
            {statusLabel(data.status)}
          </span>
        )}
      </div>

      {loading && !data && (
        <div className="flex items-center py-5 text-sm text-muted-foreground">
          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          加载相对表现…
        </div>
      )}

      {error && !data && !loading && (
        <div className="space-y-1 text-sm text-muted-foreground">
          <p>相对表现数据暂不可用。</p>
          <p className="text-xs">{error}；未将缺失数据显示为 0。</p>
        </div>
      )}

      {data && (
        <>
          <div className="mb-3 grid gap-2 text-xs text-muted-foreground sm:grid-cols-2">
            <p>比较日期：<span className="font-mono text-foreground">{data.comparison_date ?? "不可用"}</span></p>
            <p>当前行业：<span className="text-foreground">{data.industry_name ?? "不可用"}</span></p>
            <p>
              成员口径：<span className="text-foreground">当前行业成员快照</span>
              <span className="ml-1 font-mono text-[10px]">{data.industry_membership_semantics}</span>
            </p>
            <p>数据口径：<span className="font-mono text-foreground">UNADJUSTED / 未复权</span></p>
          </div>

          {data.industry_status !== "normal" && (
            <p className="mb-3 rounded border border-warning/30 bg-warning/5 p-2 text-xs text-warning">
              {data.industry_status === "unknown"
                ? "当前行业为 UNKNOWN，行业中位数不计算；市场比较仍可独立显示。"
                : "当前行业快照不可用，行业中位数不计算；市场比较仍独立显示。"}
            </p>
          )}

          <p className="mb-3 text-[11px] text-muted-foreground/70">
            下表为原始价格变化，不是复权收益或总回报；行业仅按当前成员快照观察。
          </p>

          <div className="overflow-x-auto">
            <table className="w-full min-w-[640px] text-sm">
              <thead>
                <tr className="text-xs text-muted-foreground">
                  <th className="py-1.5 pr-3 text-left font-normal">周期</th>
                  <th className="px-2 py-1.5 text-right font-normal">个股</th>
                  <th className="px-2 py-1.5 text-right font-normal">行业中位数</th>
                  <th className="px-2 py-1.5 text-right font-normal">相对行业</th>
                  <th className="px-2 py-1.5 text-right font-normal">市场中位数</th>
                  <th className="pl-2 py-1.5 text-right font-normal">相对市场</th>
                </tr>
              </thead>
              <tbody>
                {HORIZONS.map((horizon) => {
                  const period = data.periods[horizon];
                  return (
                    <tr key={horizon} className="border-t border-border/40">
                      <td className="py-2 pr-3 font-mono">
                        <span>{horizon}</span>
                        <span className="ml-1 text-[10px] text-muted-foreground">原始价格变化</span>
                      </td>
                      <td className="px-2 py-2 text-right font-mono">{formatStockRelativePercent(period.stock_return_pct)}</td>
                      <td className="px-2 py-2 text-right font-mono">{formatStockRelativePercent(period.industry_median_pct)}</td>
                      <td className="px-2 py-2 text-right font-mono">{formatStockRelativePercent(period.vs_industry_pct_points)}</td>
                      <td className="px-2 py-2 text-right font-mono">{formatStockRelativePercent(period.market_median_pct)}</td>
                      <td className="pl-2 py-2 text-right font-mono">{formatStockRelativePercent(period.vs_market_pct_points)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          <div className="mt-3 grid gap-2 border-t border-border/40 pt-3 text-[11px] text-muted-foreground sm:grid-cols-3">
            {HORIZONS.map((horizon) => {
              const period = data.periods[horizon];
              return (
                <div key={horizon} className="rounded bg-muted/25 p-2">
                  <p className="mb-1 font-mono text-foreground">{horizon}</p>
                  <p>行业有效样本：{formatSampleCoverage(period.industry_valid_count, period.industry_member_count, period.industry_coverage)}</p>
                  <p>市场有效样本：{formatSampleCoverage(period.market_valid_count, period.market_total_count, period.market_coverage)}</p>
                </div>
              );
            })}
          </div>

          {data.warnings.length > 0 && (
            <div className="mt-3 space-y-1 text-[11px] text-muted-foreground/80">
              {data.warnings.map((warning) => <p key={warning}>· {warning}</p>)}
            </div>
          )}
        </>
      )}
    </GlassCard>
  );
}
