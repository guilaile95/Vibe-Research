import type { DailyReviewComparison } from "@/lib/api";
import { marketComparisonCards } from "@/lib/marketComparisonView";

export function MarketComparisonSummary({ comparison }: { comparison: DailyReviewComparison }) {
  const cards = marketComparisonCards(comparison);
  return (
    <section className="mb-4 rounded-xl border border-border/60 p-3 sm:p-4" data-testid="market-comparison-summary" aria-label="市场变化核对">
      <h5 className="text-sm font-semibold">市场变化核对</h5>
      <p className="mt-1 text-xs leading-5 text-muted-foreground">先核对来源、行情时点和统计样本，再判断变化。页面生成时间不能代替行情时间。</p>
      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        {cards.map((card) => (
          <div key={card.key} className="min-w-0 rounded-lg bg-muted/30 p-3" data-testid={`comparison-${card.key}`}>
            <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
              <span>{card.label}</span>
              <span className="text-muted-foreground">{card.status === "comparable" ? "已记录维度可比" : card.status === "incomparable" ? "比较条件不一致" : "比较依据不足"}</span>
            </div>
            <p className="mt-2 break-words text-base font-semibold">{card.value}</p>
            {card.issues.length > 0 ? (
              <div className="mt-2 break-words text-xs leading-5 text-muted-foreground">
                <ul className="list-inside list-disc space-y-1">
                  {card.issues.slice(0, 2).map((issue, index) => <li key={index}>{issue}</li>)}
                </ul>
                {card.issues.length > 2 && (
                  <details className="mt-1">
                    <summary className="cursor-pointer">另有 {card.issues.length - 2} 项核对缺口</summary>
                    <ul className="mt-1 list-inside list-disc space-y-1">
                      {card.issues.slice(2).map((issue, index) => <li key={index}>{issue}</li>)}
                    </ul>
                  </details>
                )}
              </div>
            ) : <p className="mt-2 text-xs text-muted-foreground">相对基础快照；仅说明记录值的变化，不推断市场原因。</p>}
          </div>
        ))}
      </div>
      <p className="mt-3 text-xs leading-5 text-muted-foreground">下方表格保留存档数值和排名差异。未通过上述核对的差值不代表可比市场变化；本次未核验其他指标的时点与样本。</p>
    </section>
  );
}
