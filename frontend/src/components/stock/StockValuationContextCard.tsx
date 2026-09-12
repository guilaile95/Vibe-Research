import { Scale, Loader2 } from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import type { StockValuationContext, StockValuationMetric } from "@/lib/api";
import {
  formatPositiveRank,
  formatValuationDelta,
  formatValuationNumber,
} from "@/lib/stockValuationContextView";

interface Props {
  data: StockValuationContext | null;
  loading: boolean;
  error: string | null;
}

function statusLabel(status: StockValuationContext["status"]): string {
  if (status === "normal") return "当前数据可比";
  if (status === "partial") return "部分数据可比";
  return "数据不可用";
}

function metricRow(label: string, testId: string, metric: StockValuationMetric) {
  return (
    <tr className="border-t border-border/40" data-testid={testId}>
      <td className="py-2 pr-3">{label}</td>
      <td className="px-2 py-2 text-right font-mono">{formatValuationNumber(metric.stock_value)}</td>
      <td className="px-2 py-2 text-right font-mono">{formatValuationNumber(metric.industry_positive_median)}</td>
      <td className="px-2 py-2 text-right font-mono">{formatValuationDelta(metric.vs_industry_positive_median)}</td>
      <td className="pl-2 py-2 text-right font-mono">{formatPositiveRank(metric.rank_among_positive, metric.positive_sample_count)}</td>
    </tr>
  );
}

export function StockValuationContextCard({ data, loading, error }: Props) {
  if (!data && !loading && !error) return null;

  return (
    <GlassCard className="mb-4" data-testid="stock-valuation-context">
      <div className="mb-3 flex items-center justify-between gap-3">
        <h3 className="flex items-center gap-1.5 text-sm font-semibold">
          <Scale className="h-4 w-4 text-primary" /> 相对行业估值
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
          加载相对行业估值…
        </div>
      )}

      {error && !data && !loading && (
        <div className="space-y-1 text-sm text-muted-foreground">
          <p>相对行业估值暂不可用。</p>
          <p className="text-xs">{error}；未将缺失估值显示为 0。</p>
        </div>
      )}

      {data && data.pe_ttm && data.pb && (
        <>
          <div className="mb-3 grid gap-2 text-xs text-muted-foreground sm:grid-cols-2">
            <p>当前行业：<span className="text-foreground">{data.industry_name ?? "不可用"}</span></p>
            <p>
              成员口径：<span className="text-foreground">当前行业成员快照</span>
              <span className="ml-1 font-mono text-[10px]">{data.industry_membership_semantics}</span>
            </p>
            <p>PE-TTM 来源：<span className="font-mono text-foreground">Eastmoney f115</span></p>
            <p>PB 来源：<span className="font-mono text-foreground">Eastmoney f23</span></p>
          </div>

          {data.industry_status !== "normal" && (
            <p
              className="mb-3 rounded border border-warning/30 bg-warning/5 p-2 text-xs text-warning"
              data-testid="stock-valuation-industry-notice"
            >
              {data.industry_status === "unknown"
                ? "当前行业为 UNKNOWN，行业正值中位数不计算；个股估值仍可独立显示。"
                : "当前行业快照不可用，行业正值中位数不计算；个股估值仍独立显示。"}
            </p>
          )}

          <p className="mb-3 text-[11px] text-muted-foreground/70">
            这里只比较当前行业成员的正值 PE/PB 中位数，不是行业指数估值，也不是近 5 年历史分位；差值不是便宜或贵，也不构成买卖建议。
          </p>

          <div className="overflow-x-auto">
            <table className="w-full min-w-[560px] text-sm">
              <thead>
                <tr className="text-xs text-muted-foreground">
                  <th className="py-1.5 pr-3 text-left font-normal">指标</th>
                  <th className="px-2 py-1.5 text-right font-normal">个股</th>
                  <th className="px-2 py-1.5 text-right font-normal">行业正值中位数</th>
                  <th className="px-2 py-1.5 text-right font-normal">相对行业（差值）</th>
                  <th className="pl-2 py-1.5 text-right font-normal">正值样本位次</th>
                </tr>
              </thead>
              <tbody>
                {metricRow("PE-TTM", "stock-valuation-pe", data.pe_ttm)}
                {metricRow("市净率 PB", "stock-valuation-pb", data.pb)}
              </tbody>
            </table>
          </div>

          <div className="mt-3 grid gap-2 border-t border-border/40 pt-3 text-[11px] text-muted-foreground sm:grid-cols-2">
            <div className="rounded bg-muted/25 p-2">
              <p className="mb-1 font-mono text-foreground">PE-TTM</p>
              <p>行业成员：{data.industry_member_count}</p>
              <p>正值 / 零 / 负 / 缺：{data.pe_ttm.industry_positive_count} / {data.pe_ttm.industry_zero_count} / {data.pe_ttm.industry_negative_count} / {data.pe_ttm.industry_missing_count}</p>
            </div>
            <div className="rounded bg-muted/25 p-2">
              <p className="mb-1 font-mono text-foreground">市净率 PB</p>
              <p>行业成员：{data.industry_member_count}</p>
              <p>正值 / 零 / 负 / 缺：{data.pb.industry_positive_count} / {data.pb.industry_zero_count} / {data.pb.industry_negative_count} / {data.pb.industry_missing_count}</p>
            </div>
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
