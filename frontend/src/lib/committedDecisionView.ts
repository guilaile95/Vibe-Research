// Inbox 已提交决定卡片的展示标签。证券代码/策略来自 Campaign 上下文，
// 不另请求接口；缺失 NBA 不得推断为买入/卖出。

import { decisionActionLabel } from "./decisionActionView.ts";
import { CAMPAIGN_STRATEGY_LABELS } from "./decisionInbox.ts";

export interface CommittedDecisionIdentityInput {
  securityCode?: unknown;
  strategy?: unknown;
  nextBestAction?: unknown;
}

const VALIDITY_STATUS_AT_COMMIT_LABELS: Record<string, string> = {
  CURRENT: "当前",
};

function displayText(value: unknown): string {
  return typeof value === "string" && value.trim() ? value : "—";
}

export function campaignStrategyLabel(value: unknown): string {
  if (typeof value !== "string" || !value.trim()) return "—";
  return Object.prototype.hasOwnProperty.call(CAMPAIGN_STRATEGY_LABELS, value)
    ? CAMPAIGN_STRATEGY_LABELS[value as keyof typeof CAMPAIGN_STRATEGY_LABELS]
    : value;
}

export function committedDecisionNbaLabel(value: unknown): string {
  if (typeof value !== "string" || !value.trim()) return "信息不足";
  return decisionActionLabel(value);
}

export function committedDecisionIdentityTitle(input: CommittedDecisionIdentityInput): string {
  return [
    displayText(input.securityCode),
    campaignStrategyLabel(input.strategy),
    committedDecisionNbaLabel(input.nextBestAction),
  ].join(" · ");
}

export function validityStatusAtCommitLabel(value: unknown): string | null {
  if (typeof value !== "string" || !value.trim()) return null;
  return Object.prototype.hasOwnProperty.call(VALIDITY_STATUS_AT_COMMIT_LABELS, value)
    ? VALIDITY_STATUS_AT_COMMIT_LABELS[value]
    : value;
}
