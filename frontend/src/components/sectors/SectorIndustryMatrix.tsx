import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowDownUp, Loader2 } from "lucide-react";
import type { SectorIndustryContextData } from "@/lib/api";
import {
  formatMatrixAmount,
  formatMatrixCount,
  formatMatrixPercent,
  sectorIndustryMatrixState,
  sortSectorIndustryRows,
  type SectorIndustrySortKey,
} from "@/lib/sectorIndustryMatrix";
import { cn } from "@/lib/utils";

const SORT_OPTIONS: Array<{ value: SectorIndustrySortKey; label: string }> = [
  { value: "member_aggregate_return_5d_pct", label: "5日成员聚合" },
  { value: "member_aggregate_return_20d_pct", label: "20日成员聚合" },
  { value: "up_ratio", label: "上涨比例" },
  { value: "above_ma20_ratio", label: "Above MA20" },
  { value: "turnover_pct_avg", label: "换手 participation" },
];

type Props = {
  data: SectorIndustryContextData | null;
  loading: boolean;
  error: boolean;
};

function valueClass(value: number | null | undefined): string {
  if (value == null) return "text-muted-foreground";
  if (value > 0) return "text-rose-600 dark:text-rose-400";
  if (value < 0) return "text-emerald-600 dark:text-emerald-400";
  return "text-foreground";
}

function statusLabel(status: "normal" | "partial" | "unavailable"): string {
  if (status === "normal") return "正常";
  if (status === "partial") return "部分可用";
  return "不可用";
}

export function SectorIndustryMatrix({ data, loading, error }: Props) {
  const [sortKey, setSortKey] = useState<SectorIndustrySortKey>("member_aggregate_return_5d_pct");
  const [descending, setDescending] = useState(true);
  const state = sectorIndustryMatrixState(data, loading, error);
  const rows = useMemo(
    () => sortSectorIndustryRows(data?.items ?? [], sortKey, descending),
    [data?.items, descending, sortKey],
  );

  return (
    <section data-sector-industry-matrix aria-labelledby="sector-industry-matrix-title" className="space-y-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h3 id="sector-industry-matrix-title" className="text-sm font-semibold">行业环境 / 横向比较</h3>
          <p className="mt-0.5 text-xs text-muted-foreground">当前行业成员与 RDP 个股历史行情的透明聚合，不是行业指数。</p>
        </div>
        {data && <span className="rounded-md bg-muted/40 px-2 py-1 text-[10px] text-muted-foreground">{statusLabel(data.status)}</span>}
      </div>

      <div className="rounded-lg border border-primary/20 bg-primary/5 px-3 py-2 text-[11px] leading-relaxed text-muted-foreground" data-testid="sector-industry-disclaimer">
        <p>分类：Eastmoney 当前行业 · 成员口径：当前快照成员</p>
        <p>历史强弱：基于当前成员回看个股历史行情的聚合，不代表历史行业指数 · 历史成员有效性：未证明</p>
        <p>板块估值：不可用 · CROWDING：仅透明 participation proxy，不生成综合分数</p>
      </div>

      {state === "loading" && (
        <div className="flex items-center gap-2 py-6 text-xs text-muted-foreground"><Loader2 className="h-3.5 w-3.5 animate-spin" /> 加载行业环境…</div>
      )}
      {state === "error" && (
        <p className="rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-4 text-xs text-destructive">行业环境读取失败（不等于空行业）。</p>
      )}
      {state === "unavailable" && (
        <div className="rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-4 text-xs text-destructive">
          <p>当前行业环境暂不可用。</p>
          {data?.warnings?.[0] && <p className="mt-1 text-muted-foreground">{data.warnings[0]}</p>}
        </div>
      )}
      {state === "empty" && (
        <p className="rounded-lg border border-border/50 bg-muted/15 px-3 py-4 text-xs text-muted-foreground">当前行业快照为空（空结果不等于数据源不可用）。</p>
      )}

      {(state === "normal" || state === "partial") && data && (
        <>
          <div className="flex flex-wrap items-center justify-between gap-2 text-[10px] text-muted-foreground">
            <span>{data.universe.current_member_count} 个当前成员 · {data.universe.industry_count} 个行业 · RDP as_of {data.rdp_as_of ?? "—"}</span>
            <label className="flex items-center gap-1.5">
              <span>排序</span>
              <select
                aria-label="行业矩阵排序"
                value={sortKey}
                onChange={(event) => setSortKey(event.target.value as SectorIndustrySortKey)}
                className="rounded border border-border/70 bg-background px-2 py-1 text-[10px] text-foreground"
              >
                {SORT_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
              </select>
              <button
                type="button"
                aria-label={descending ? "改为升序" : "改为降序"}
                onClick={() => setDescending((value) => !value)}
                className="rounded border border-border/70 p-1 hover:bg-muted"
              >
                <ArrowDownUp className="h-3 w-3" />
              </button>
            </label>
          </div>
          <div className="overflow-x-auto rounded-lg border border-border/50">
            <table className="w-full min-w-[1080px] text-left text-xs" data-testid="sector-industry-table">
              <thead className="bg-muted/25 text-[10px] text-muted-foreground">
                <tr>
                  <th className="px-3 py-2">Eastmoney 行业</th>
                  <th className="px-3 py-2">成员 / RDP</th>
                  <th className="px-3 py-2">覆盖率</th>
                  <th className="px-3 py-2">5日成员聚合</th>
                  <th className="px-3 py-2">20日成员聚合</th>
                  <th className="px-3 py-2">上涨 / 下跌 / 平盘</th>
                  <th className="px-3 py-2">Above MA20</th>
                  <th className="px-3 py-2">Participation</th>
                  <th className="px-3 py-2">估值</th>
                  <th className="px-3 py-2">入口</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border/40">
                {rows.map((row) => {
                  const five = row.metrics.member_aggregate_return_5d_pct;
                  const twenty = row.metrics.member_aggregate_return_20d_pct;
                  return (
                    <tr key={row.industry_key} className="hover:bg-muted/15" data-testid={`sector-industry-row-${row.industry_key}`}>
                      <td className="px-3 py-2">
                        <span className="font-medium">{row.industry_name}</span>
                        <span className={cn("ml-1.5 rounded px-1 py-0.5 text-[9px]", row.status === "normal" ? "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300" : "bg-amber-500/10 text-amber-700 dark:text-amber-300")}>{statusLabel(row.status)}</span>
                      </td>
                      <td className="px-3 py-2">{formatMatrixCount(row.current_member_count)} / {formatMatrixCount(row.rdp_usable_member_count)}</td>
                      <td className="px-3 py-2">{formatMatrixPercent(row.coverage_ratio, true)}</td>
                      <td className={cn("px-3 py-2 font-medium", valueClass(five))}>{formatMatrixPercent(five)}<span className="ml-1 text-[10px] text-muted-foreground">n={row.metrics.return_5d_usable_count}</span></td>
                      <td className={cn("px-3 py-2 font-medium", valueClass(twenty))}>{formatMatrixPercent(twenty)}<span className="ml-1 text-[10px] text-muted-foreground">n={row.metrics.return_20d_usable_count}</span></td>
                      <td className="px-3 py-2">{formatMatrixPercent(row.breadth.up_ratio, true)} / {formatMatrixPercent(row.breadth.down_ratio, true)} / {formatMatrixPercent(row.breadth.flat_ratio, true)}</td>
                      <td className="px-3 py-2">{formatMatrixPercent(row.breadth.above_ma20_ratio, true)}<span className="ml-1 text-[10px] text-muted-foreground">{row.breadth.above_ma20_count}/{row.breadth.ma20_usable_count}</span></td>
                      <td className="px-3 py-2">换手 {formatMatrixPercent(row.participation.turnover_pct_avg)}<br /><span className="text-[10px] text-muted-foreground">量比 {row.participation.volume_ratio_20d_avg == null ? "—" : `${row.participation.volume_ratio_20d_avg.toFixed(2)}×`} · 额 {formatMatrixAmount(row.participation.amount_total)}</span></td>
                      <td className="px-3 py-2 text-muted-foreground" title={row.valuation.message}>不可用</td>
                      <td className="px-3 py-2"><Link to="/market-cloud" className="text-primary hover:underline" title="仅进入现有当前市场环境，不创建行业研究工作台">市场云图</Link></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  );
}
