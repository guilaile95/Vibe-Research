import type {
  FormalDecisionOutcome,
  FormalDecisionReviewWorklist,
  FormalReviewWorklistItem,
} from "@/lib/api/types";
import { decisionActionLabel } from "./decisionActionView.ts";
import { CAMPAIGN_STRATEGY_LABELS } from "./decisionInbox.ts";

export type FormalReviewWorklistFilter = "due" | "upcoming" | "unavailable";

const DUE_STATE_LABELS: Record<string, string> = {
  DUE: "已到复核时点",
  NOT_DUE: "尚未到期",
  ERROR: "无法判断",
};

const OUTCOME_STATUS_LABELS: Record<string, string> = {
  PENDING: "待评估",
  EVALUATED: "已评估",
  UNKNOWN: "信息不足",
  NOT_EVALUATED: "尚未评估",
  ERROR: "读取失败",
};

const ACTUAL_CAPITAL_STATE_LABELS: Record<string, string> = {
  PENDING: "待评估",
  NO_ACTUAL_TRADE: "无实际交易",
  EVALUATED: "已评估",
  ERROR: "读取失败",
  UNKNOWN: "信息不足",
  NOT_EVALUATED: "尚未评估",
  NOT_APPLICABLE: "不适用",
};

const ALLOCATION_STATE_LABELS: Record<string, string> = {
  ALLOCATED: "已归属",
  UNALLOCATED: "未归属",
  UNPLANNED: "非计划内",
  NOT_APPLICABLE: "不适用",
  UNKNOWN: "信息不足",
  NOT_EVALUATED: "尚未评估",
  ERROR: "读取失败",
};

const SCAN_STATE_LABELS: Record<string, string> = {
  COMPLETE: "扫描完成",
  COMPLETE_EMPTY: "扫描完成（无候选）",
  INVALID_WITNESS: "见证校验失败",
  NOT_APPLICABLE: "不适用",
};

export const PROCESS_REVIEW_DIMENSIONS = [
  "STRONGEST_SUPPORTING_EVIDENCE",
  "STRONGEST_OPPOSING_EVIDENCE",
  "PRE_MORTEM",
  "INVALIDATION_FACTS",
] as const;

const PROCESS_REVIEW_DIMENSION_LABELS: Record<string, string> = {
  STRONGEST_SUPPORTING_EVIDENCE: "最有力的支持证据",
  STRONGEST_OPPOSING_EVIDENCE: "最有力的反对证据",
  PRE_MORTEM: "如果判断失败，最可能的原因",
  INVALIDATION_FACTS: "哪些事实会推翻判断",
};

const PROCESS_REVIEW_STATUS_LABELS: Record<string, string> = {
  ANSWERED: "已回答",
  UNKNOWN: "未知",
  NOT_ANSWERED: "未回答",
};

const PROCESS_REVIEW_PACKET_STATE_LABELS: Record<string, string> = {
  COMPLETE: "完整",
  INCOMPLETE: "不完整",
};

const PROCESS_REVIEW_EVALUATION_LABELS: Record<string, string> = {
  EVALUATED: "已评估",
  UNKNOWN: "未知",
  NOT_EVALUATED: "尚未评估",
  ERROR: "读取失败",
};

const PROCESS_REVIEW_TWO_PASS_STATE_LABELS: Record<string, string> = {
  VALID: "有效",
  INCOMPLETE: "不完整",
};

const PROCESS_REVIEW_INDEPENDENCE_LABELS: Record<string, string> = {
  YES: "是",
  NO: "否",
};

const PROCESS_REVIEW_QUALITY_STATE_LABELS: Record<string, string> = {
  NOT_EVALUATED: "尚未评估",
};

export const PROCESS_REVIEW_NONE_COPY = "本次冻结决定没有绑定预冻结决策挑战。";
export const PROCESS_REVIEW_ERROR_COPY = "过程复核不可用；绑定的决策挑战权威损坏或无法读取。";
export const PROCESS_REVIEW_BOUND_HEADING = "已绑定决策挑战";
export const PROCESS_REVIEW_COVERAGE_COPY = "挑战覆盖不等于判断正确。";

export const COUNTERFACTUAL_COLUMN_HEADER = "反事实路径";
export const COUNTERFACTUAL_PATH_HEADING = "个股收盘到收盘路径";
export const COUNTERFACTUAL_DECISION_REFERENCE_LABEL = "决定参考价";
export const COUNTERFACTUAL_EVALUATION_LABEL = "评估时点价";
export const COUNTERFACTUAL_RETURN_LABEL = "收益";
export const COUNTERFACTUAL_SCOPE_COPY = "仅个股路径，不是组合盈亏，也不是判断质量";
export const COUNTERFACTUAL_SEPARATION_COPY = "该路径与实际资金结果相互独立。";

export interface FormalOutcomeIdentityInput {
  security_code?: unknown;
  strategy?: unknown;
  next_best_action?: unknown;
}

function displayText(value: unknown): string {
  return typeof value === "string" && value.trim() ? value : "—";
}

function mappedLabel(value: unknown, labels: Record<string, string>): string {
  if (typeof value !== "string" || !value) return "—";
  return Object.prototype.hasOwnProperty.call(labels, value) ? labels[value] : value;
}

export function worklistItems(
  worklist: FormalDecisionReviewWorklist,
  filter: FormalReviewWorklistFilter,
): readonly FormalReviewWorklistItem[] {
  return worklist[filter];
}

export function worklistLabel(filter: FormalReviewWorklistFilter): string {
  if (filter === "due") return "待复核";
  if (filter === "upcoming") return "尚未到期";
  return "权威不可用";
}

export function campaignStrategyLabel(value: unknown): string {
  if (typeof value !== "string" || !value.trim()) return "—";
  return Object.prototype.hasOwnProperty.call(CAMPAIGN_STRATEGY_LABELS, value)
    ? CAMPAIGN_STRATEGY_LABELS[value as keyof typeof CAMPAIGN_STRATEGY_LABELS]
    : value;
}

export function frozenDecisionNbaLabel(value: unknown): string {
  if (typeof value !== "string" || !value.trim()) return "未知";
  return decisionActionLabel(value);
}

export function formalOutcomeIdentityTitle(input: FormalOutcomeIdentityInput): string {
  return [
    displayText(input.security_code),
    campaignStrategyLabel(input.strategy),
    frozenDecisionNbaLabel(input.next_best_action),
  ].join(" · ");
}

export function dueStateLabel(value: unknown): string {
  return mappedLabel(value, DUE_STATE_LABELS);
}

export function outcomeStatusLabel(value: unknown): string {
  return mappedLabel(value, OUTCOME_STATUS_LABELS);
}

export function actualCapitalStateLabel(value: unknown): string {
  return mappedLabel(value, ACTUAL_CAPITAL_STATE_LABELS);
}

export function counterfactualStateLabel(value: unknown): string {
  return mappedLabel(value, OUTCOME_STATUS_LABELS);
}

export function allocationStateLabel(value: unknown): string {
  return mappedLabel(value, ALLOCATION_STATE_LABELS);
}

export function scanStateLabel(value: unknown): string {
  return mappedLabel(value, SCAN_STATE_LABELS);
}

export function processReviewDimensionLabel(value: unknown): string {
  return mappedLabel(value, PROCESS_REVIEW_DIMENSION_LABELS);
}

export function processReviewDimensionStatusLabel(value: unknown): string {
  return mappedLabel(value, PROCESS_REVIEW_STATUS_LABELS);
}

export function processReviewQualityLabel(value: unknown): string {
  const state = typeof value === "string" && value ? value : "NOT_EVALUATED";
  return `过程质量：${mappedLabel(state, PROCESS_REVIEW_QUALITY_STATE_LABELS)}`;
}

export function processReviewPacketSummary(review: {
  packet_state?: string | null;
  challenge_evaluation?: string | null;
}): { label: string; canonical: string } {
  return {
    label: `数据包：${mappedLabel(review.packet_state, PROCESS_REVIEW_PACKET_STATE_LABELS)} · 评估：${mappedLabel(review.challenge_evaluation, PROCESS_REVIEW_EVALUATION_LABELS)}`,
    canonical: `packet: ${displayText(review.packet_state)} · evaluation: ${displayText(review.challenge_evaluation)}`,
  };
}

export function processReviewTwoPassSummary(review: {
  two_pass_state?: string | null;
  two_pass_semantic_independence_verified?: string | null;
}): { label: string; canonical: string } {
  return {
    label: `两轮：${mappedLabel(review.two_pass_state, PROCESS_REVIEW_TWO_PASS_STATE_LABELS)} · 语义独立性已验证：${mappedLabel(review.two_pass_semantic_independence_verified, PROCESS_REVIEW_INDEPENDENCE_LABELS)}`,
    canonical: `two-pass: ${displayText(review.two_pass_state)} · semantic independence verified: ${displayText(review.two_pass_semantic_independence_verified)}`,
  };
}

export function actualCapitalSummary(item: FormalDecisionOutcome): {
  label: string;
  canonical: string;
} {
  const actual = item.actual_capital_outcome;
  if (!actual) return { label: "—", canonical: "" };
  if (actual.state === "NO_ACTUAL_TRADE") {
    return {
      label: `${actualCapitalStateLabel("NO_ACTUAL_TRADE")} · ${actualCapitalStateLabel("NOT_APPLICABLE")}`,
      canonical: "NO_ACTUAL_TRADE / NOT_APPLICABLE",
    };
  }
  if (actual.state === "PENDING") {
    return {
      label: `${actualCapitalStateLabel("PENDING")} · ${dueStateLabel("NOT_DUE")}`,
      canonical: "PENDING / NOT_DUE",
    };
  }
  const count = actual.trade_count ?? 0;
  return {
    label: `${actualCapitalStateLabel(actual.state)} · ${count} 笔已归属成交`,
    canonical: `${displayText(actual.state)} · ${count} exact attributed executed trade(s)`,
  };
}

export function counterfactualSummary(item: FormalDecisionOutcome): {
  label: string;
  canonical: string;
} {
  const value = item.counterfactual_outcome;
  if (!value) return { label: "—", canonical: "" };
  return {
    label: counterfactualStateLabel(value.state),
    canonical: displayText(value.state),
  };
}

export function mergeOutcomeItem(
  items: readonly FormalDecisionOutcome[],
  outcome: FormalDecisionOutcome,
): FormalDecisionOutcome[] {
  const index = items.findIndex((item) => item.decision_id === outcome.decision_id);
  if (index < 0) return [...items, outcome];
  return items.map((item, currentIndex) => currentIndex === index ? outcome : item);
}
