import type { AccountFundingQuoteCoverage } from "@/lib/api/types";

export function AccountCoverageNote({ coverage }: { coverage?: AccountFundingQuoteCoverage }) {
  return <div className="mt-2 text-[11px] text-muted-foreground" data-testid="account-coverage-basis">
    <p className={coverage && !coverage.complete ? "text-amber-700 dark:text-amber-400" : undefined}>{coverage ? `价格与数量可用覆盖：${coverage.valid_holdings} / ${coverage.total_holdings}${coverage.complete ? "（条目齐全）" : "（部分不可用）"}` : "价格与数量覆盖：未提供"}</p>
    <p>覆盖齐全只表示数值可用，不代表报价同日、最新或与账户金额时间一致；本结果未提供报价时间，无法确认时间兼容性。</p>
    <p>账户更新时间不是报价时间。金额参考不等于收益归因或已完成账户对账。</p>
  </div>;
}
