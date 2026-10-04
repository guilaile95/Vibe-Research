import type { AttributionResult } from "@/lib/api/types";

const bound = (value: string | null | undefined, open: string) =>
  value === undefined ? "未记录" : value === null ? open : value;

/** Explain only existing PA1 fields; no recomputation or inferred quote dates. */
export function AttributionScopeNote({ result, historical }: { result: AttributionResult; historical: boolean }) {
  const count = result.selected_trade_count;
  const limitations = (result.positions ?? []).flatMap(position =>
    (position.data_limitations ?? []).map(text => `${position.code}：${text}`));
  return <section aria-label="归因口径与限制" className="rounded-xl border border-border/60 bg-card p-4 text-sm" data-testid="attribution-scope">
    <h2 className="font-medium">本次数字如何理解</h2>
    <dl className="mt-2 grid gap-2 text-xs sm:grid-cols-2">
      <div><dt className="text-muted-foreground">交易筛选范围</dt><dd>{bound(result.date_from, "不设起始")} 至 {bound(result.date_to, "不设结束")}</dd></div>
      <div><dt className="text-muted-foreground">实际参与的交易行</dt><dd>{Number.isInteger(count) && count! >= 0 ? `${count} 笔` : "未记录（旧结果不推算）"}</dd></div>
      <div><dt className="text-muted-foreground">{historical ? "原结果计算日期" : "计算日期"}</dt><dd>{result.as_of_date || "未记录"}（不是报价日期）</dd></div>
      <div><dt className="text-muted-foreground">单位</dt><dd>金额沿用交易录入单位，币种未提供；数量沿用流水数量，不折算成手。均价成本为金额 / 数量。</dd></div>
    </dl>
    <ul className="mt-3 list-disc space-y-1 pl-4 text-xs text-muted-foreground">
      <li>仅按所选交易从零累计成本，不自动补入筛选起点之前的持仓。缺少买入成本的卖出不计入实现盈亏，不能据此把零当作没有损失。</li>
      <li>费用合计包含手续费和其他成本。买入费用进入成本，卖出费用从收入扣除；展示费用合计不是再扣一次。</li>
      <li>未实现盈亏仅使用本次已提供的价格；缺价保留未知，部分合计不代表全部持仓。结果没有报价时间，无法确认报价同日或新鲜。</li>
      {historical && <li>当前是历史快照原结果，未重新获取行情或计算。</li>}
    </ul>
    {limitations.length > 0 && <div className="mt-3 rounded-md bg-amber-500/10 p-2 text-xs text-amber-700 dark:text-amber-400" role="note">
      <p className="font-medium">逐股限制（先于汇总阅读）</p>
      <ul className="mt-1 space-y-1">{limitations.map((text, index) => <li key={`${index}:${text}`}>{text}</li>)}</ul>
    </div>}
  </section>;
}
