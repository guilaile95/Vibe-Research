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

export function allocationStateLabel(value: unknown): string {
  return mappedLabel(value, ALLOCATION_STATE_LABELS);
}

export function scanStateLabel(value: unknown): string {
  return mappedLabel(value, SCAN_STATE_LABELS);
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

export function mergeOutcomeItem(
  items: readonly FormalDecisionOutcome[],
  outcome: FormalDecisionOutcome,
): FormalDecisionOutcome[] {
  const index = items.findIndex((item) => item.decision_id === outcome.decision_id);
  if (index < 0) return [...items, outcome];
  return items.map((item, currentIndex) => currentIndex === index ? outcome : item);
}
