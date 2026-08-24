import { ClipboardList } from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import type { FinancialPeriod, Financials } from "@/lib/api";
import {
  formatFinancialAmount,
  formatFinancialRatio,
  fundamentalHealthState,
} from "@/lib/fundamentalHealthView";

interface Props {
  fin: Financials | null;
  error: string | null;
}

function Fact({ label, value, sub }: { label: string; value: string | null | undefined; sub?: string }) {
  return (
    <div className="rounded-lg bg-muted/30 p-3">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-0.5 font-mono text-base font-bold">{value || "未知"}</p>
      {sub && <p className="mt-0.5 text-[11px] text-muted-foreground">{sub}</p>}
    </div>
  );
}

function HistoryRow({ row }: { row: FinancialPeriod }) {
  return (
    <tr className="border-t border-border/40">
      <td className="whitespace-nowrap px-2 py-2 font-mono">{row.period_end ?? "未知"}</td>
      <td className="whitespace-nowrap px-2 py-2 text-right">{formatFinancialAmount(row.net_profit_amount)}</td>
      <td className="whitespace-nowrap px-2 py-2 text-right">{formatFinancialAmount(row.operating_cash_flow)}</td>
      <td className="whitespace-nowrap px-2 py-2 text-right">{formatFinancialRatio(row.cash_conversion_ratio)}</td>
      <td className="whitespace-nowrap px-2 py-2 text-right">{formatFinancialAmount(row.free_cash_flow)}</td>
    </tr>
  );
}

export function EarningsSnapshot({ fin, error }: Props) {
  const state = fundamentalHealthState(fin, error);
  const latest = fin;
  const missing = fin?.data_quality?.missing_fields ?? [];

  return (
    <GlassCard glow className="mb-4" data-testid="fundamental-health">
      <h3 className="mb-1 flex items-center gap-1.5 text-sm font-semibold">
        <ClipboardList className="h-4 w-4 text-primary" /> 单股财务体检
        {latest?.period_end && <span className="text-xs font-normal text-muted-foreground/60">· 报告期末 {latest.period_end}</span>}
      </h3>
      <p className="mb-3 text-[11px] text-muted-foreground/70">同花顺当前快照 · 报告期累计口径 · 事实观察，不构成评分或买卖建议。</p>

      {state === "error" && <p className="rounded-lg bg-destructive/5 p-3 text-sm text-destructive">财务数据暂不可用</p>}
      {state === "empty" && <p className="rounded-lg bg-muted/30 p-3 text-sm text-muted-foreground">当前数据源未返回财务记录</p>}

      {latest && state !== "error" && state !== "empty" && (
        <div className="space-y-4">
          <section>
            <h4 className="mb-2 text-xs font-semibold">Growth · 增长</h4>
            <div className="grid grid-cols-2 gap-2 lg:grid-cols-3">
              <Fact label="营业总收入" value={latest.revenue} sub={`同比 ${latest.revenue_yoy ?? "未知"}`} />
              <Fact label="净利润" value={latest.net_profit} sub={`同比 ${latest.net_profit_yoy ?? "未知"}`} />
              <Fact label="扣非净利润" value={latest.deduct_net_profit} sub={`同比 ${latest.deduct_net_profit_yoy ?? "未知"}`} />
            </div>
          </section>

          <section>
            <h4 className="mb-2 text-xs font-semibold">Profitability · 盈利能力</h4>
            <div className="grid grid-cols-2 gap-2 lg:grid-cols-4">
              <Fact label="ROE" value={latest.roe} />
              <Fact label="销售毛利率" value={latest.gross_margin} />
              <Fact label="销售净利率" value={latest.net_margin} />
              <Fact label="基本每股收益" value={latest.eps} />
            </div>
          </section>

          <section>
            <h4 className="mb-2 text-xs font-semibold">Cash Flow Quality · 现金流质量</h4>
            <div className="grid grid-cols-2 gap-2 lg:grid-cols-4">
              <Fact label="经营现金流" value={formatFinancialAmount(latest.operating_cash_flow)} sub="与净利润同一报告期" />
              <Fact label="现金转化率" value={formatFinancialRatio(latest.cash_conversion_ratio)} sub="经营现金流 / 净利润" />
              <Fact label="自由现金流" value={formatFinancialAmount(latest.free_cash_flow)} sub="经营现金流 - 资本开支" />
              <Fact label="自由现金流率" value={formatFinancialRatio(latest.free_cash_flow_margin)} sub="自由现金流 / 营业收入" />
              <Fact label="应计利润率" value={formatFinancialRatio(latest.accrual_ratio)} sub="(净利润 - 经营现金流) / 总资产" />
              <Fact label="资本开支" value={formatFinancialAmount(latest.capital_expenditure)} />
            </div>
          </section>

          <section>
            <h4 className="mb-2 text-xs font-semibold">Balance Sheet Quality · 资产负债表</h4>
            <div className="grid grid-cols-2 gap-2 lg:grid-cols-4">
              <Fact label="资产负债率" value={latest.debt_ratio} />
              <Fact label="流动比率" value={latest.current_ratio} />
              <Fact label="速动比率" value={latest.quick_ratio} />
              <Fact label="应收压力" value={formatFinancialRatio(latest.receivables_pressure)} sub="应收账款 / 营业收入" />
              <Fact label="净现金比例" value={formatFinancialRatio(latest.net_cash_ratio)} sub="(现金 - 总负债) / 总资产" />
              <Fact label="总负债" value={formatFinancialAmount(latest.total_debt)} />
            </div>
          </section>

          <section className="rounded-lg border border-border/60 p-3 text-xs text-muted-foreground">
            <h4 className="mb-2 font-semibold text-foreground">Data Quality · 数据质量</h4>
            <div className="grid gap-1 sm:grid-cols-2">
              <span>报告期末：{latest.period_end ?? "未知"}</span>
              <span>披露日期：未知（数据源未提供）</span>
              <span>来源：同花顺，经 AKShare 读取</span>
              <span>历史 PIT：不支持</span>
              <span>字段状态：{state === "partial" ? `部分缺失（${missing.length}）` : "本期字段完整"}</span>
              <span>口径：报告期累计值，不按相邻期推算单季变化</span>
            </div>
          </section>

          {fin.history?.length > 1 && (
            <details className="rounded-lg border border-border/60 p-3">
              <summary className="cursor-pointer text-xs font-semibold">查看最近 {fin.history.length} 个报告期现金利润匹配</summary>
              <p className="mt-2 text-[11px] text-muted-foreground">仅按完全相同的报告期末合并三表；未知值不补零。</p>
              <div className="mt-2 overflow-x-auto">
                <table className="w-full text-xs">
                  <thead className="text-muted-foreground"><tr><th className="px-2 py-2 text-left">报告期末</th><th className="px-2 py-2 text-right">净利润</th><th className="px-2 py-2 text-right">经营现金流</th><th className="px-2 py-2 text-right">现金转化</th><th className="px-2 py-2 text-right">自由现金流</th></tr></thead>
                  <tbody>{fin.history.map((row, index) => <HistoryRow key={`${row.period_end ?? "unknown"}-${index}`} row={row} />)}</tbody>
                </table>
              </div>
            </details>
          )}
        </div>
      )}
    </GlassCard>
  );
}
