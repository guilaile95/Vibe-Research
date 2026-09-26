import type { DailyReviewComparison } from "./api/types.ts";
import { formatFinancialAmount } from "./fundamentalHealthView.ts";

/** Only server-verified metrics become change summaries; raw snapshot deltas stay separate. */
export function marketComparisonCards(comparison: DailyReviewComparison) {
  return (["up_ratio", "total_amount"] as const).map((key) => {
    const evidence = comparison.market_comparability?.metrics?.[key];
    const values = comparison.market_breadth?.[key];
    const usable = values && [values.base, values.target, values.delta].every(
      (value) => typeof value === "number" && Number.isFinite(value),
    ) && (key !== "up_ratio" || Number.isFinite(values.delta! * 100));
    const comparable = evidence?.status === "comparable" && usable;
    const delta = comparable ? values!.delta! : null;
    const status = comparable ? "comparable" : evidence?.status === "incomparable" ? "incomparable" : "unverified";
    const issues = evidence?.issues?.length ? evidence.issues : [
      evidence?.status === "comparable" ? "差值所需数值不完整，暂不生成变化摘要。" : "该快照尚无行情时点和样本可比性核验结果。",
    ];
    return {
      key,
      label: key === "up_ratio" ? "上涨占比" : "全市场成交额",
      status,
      value: delta === null ? "暂不判断变化" : key === "up_ratio"
        ? `${delta > 0 ? "+" : ""}${(delta * 100).toFixed(2)} 个百分点`
        : `${delta > 0 ? "+" : ""}${formatFinancialAmount(delta)}`,
      issues: comparable ? [] : issues,
    };
  });
}
