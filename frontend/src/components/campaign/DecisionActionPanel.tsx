import { Link } from "react-router-dom";
import type { DecisionInboxCampaignItem } from "@/lib/api/types";
import { presentFrozenDecision, presentSellEngine } from "@/lib/decisionActionView";

function evaluationLabel(value: string | null | undefined): string {
  if (value === "EVALUATED") return "已评估";
  if (value === "UNKNOWN") return "信息不足";
  if (value === "ERROR") return "读取失败";
  return "尚未评估";
}

export function DecisionActionPanel({ item }: { item: DecisionInboxCampaignItem }) {
  const frozen = presentFrozenDecision(item);
  const sell = presentSellEngine(item);
  const proposalHref = `/campaigns/${encodeURIComponent(item.campaign_id)}/decision-proposal`;

  return (
    <section
      className="grid gap-3 rounded-lg border border-border/60 bg-background/35 p-3 text-xs lg:grid-cols-2"
      data-decision-action-panel={item.campaign_id}
    >
      <div
        className="space-y-2 rounded-md border border-border/50 bg-background/40 p-3"
        data-frozen-decision-state={frozen.state}
      >
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="font-medium">{frozen.title}</h3>
          <span className="rounded bg-muted px-1.5 py-0.5 text-[10px]" title={item.formal_decision_evaluation ?? "NOT_EVALUATED"}>
            {evaluationLabel(item.formal_decision_evaluation)}
          </span>
        </div>
        <p className="text-base font-semibold" data-frozen-decision-action={frozen.action ?? ""}>
          {frozen.actionLabel}
        </p>
        {frozen.decisionId ? (
          <div className="space-y-1 text-muted-foreground">
            <p className="font-mono text-[10px]" title={frozen.decisionId}>
              {frozen.decisionId}
            </p>
            <p>冻结于：{frozen.committedAt}</p>
            <p>
              复核边界：{frozen.reviewBy}
              {frozen.reviewState === "DUE"
                ? " · 已到复核时点"
                : frozen.reviewState === "UPCOMING" ? " · 尚未到期" : " · 状态未知"}
            </p>
          </div>
        ) : null}
        <p className="leading-5 text-muted-foreground">
          这是你已确认并冻结的记录，不是 AI 动态生成的行动建议；只有当前数据证明它仍适用时，才会开放后续操作。
        </p>
        <div className="flex flex-wrap gap-x-4 gap-y-2">
          {frozen.tradeHref ? (
            <Link
              to={frozen.tradeHref}
              className="font-medium text-primary hover:underline"
              data-testid="frozen-decision-trade-continuation"
            >
              如已实际执行，记录交易 →
            </Link>
          ) : null}
          <Link to="/decision-performance" className="text-primary hover:underline">
            打开决策复盘 →
          </Link>
        </div>
      </div>

      <div
        className="space-y-2 rounded-md border border-border/50 bg-background/40 p-3"
        data-sell-engine-state={sell.state}
        data-sell-engine-evaluation={sell.evaluation}
      >
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="font-medium">当前卖出复核（只读）</h3>
          <span className="rounded bg-muted px-1.5 py-0.5 text-[10px]" title={sell.evaluation}>
            {evaluationLabel(sell.evaluation)}
          </span>
        </div>
        <p className="text-base font-semibold">{sell.sellLabel}</p>
        {sell.reviewPressure ? (
          <p className="font-medium text-amber-700 dark:text-amber-400">存在卖出侧复核压力</p>
        ) : null}
        <div className="space-y-1 text-muted-foreground">
          <p>主要原因：{sell.primaryReasonLabel}</p>
          {sell.asOf ? <p>评估时间：{sell.asOf}</p> : null}
          {sell.uncertainties.length > 0 ? (
            <details>
              <summary className="cursor-pointer select-none hover:text-foreground">
                尚未闭合的评估项（{sell.uncertainties.length}）
              </summary>
              <ul className="mt-1 list-disc space-y-0.5 pl-4 font-mono text-[10px]">
                {sell.uncertainties.map((entry) => <li key={entry}>{entry}</li>)}
              </ul>
            </details>
          ) : null}
        </div>
        <p className="leading-5 text-muted-foreground">
          卖出复核只解释当前卖出侧压力，不会修改已确认决策，也不会自动创建交易。
        </p>
        <Link to={proposalHref} className="font-medium text-primary hover:underline">
          重新形成正式决策 →
        </Link>
      </div>
    </section>
  );
}
