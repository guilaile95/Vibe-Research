import type {
  CampaignStatus,
  FormalDecisionOutcome,
  FormalDecisionReviewWorklist,
  FormalReviewWorklistItem,
} from "@/lib/api/types";
import { decisionActionLabel } from "./decisionActionView.ts";
import {
  CAMPAIGN_STATUS_LABELS,
  CAMPAIGN_STRATEGY_LABELS,
  isTerminalCampaignStatus,
} from "./decisionInbox.ts";

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
  if (actual.state === "ERROR") {
    return {
      label: actualCapitalStateLabel("ERROR"),
      canonical: "ERROR",
    };
  }
  const hasState = typeof actual.state === "string" && actual.state.length > 0;
  if (!hasState) return { label: "—", canonical: "" };
  const count = actual.trade_count;
  const hasKnownCount = typeof count === "number"
    && Number.isSafeInteger(count)
    && count >= 0;
  if (!hasKnownCount) {
    return {
      label: actualCapitalStateLabel(actual.state),
      canonical: displayText(actual.state),
    };
  }
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

export type OutcomeResearchEntryKind = "current-proposal" | "new-research" | "unavailable";

export interface OutcomeResearchEntry {
  kind: OutcomeResearchEntryKind;
  label: string;
  /** null 表示没有可安全导航的目标；调用方必须只渲染文本。 */
  href: string | null;
  detail: string;
}

const A_SHARE_CODE = /^\d{6}$/;

/**
 * 历史 Decision 的下一步入口。三个概念严格分开：
 * - 历史 Decision 本身是只读事实，不是入口；
 * - Campaign 尚未结束 → 继续这轮研究（它自己的 Proposal）；
 * - Campaign 已终态 → 新判断必须新建一轮研究，不重开、不改写原来这轮。
 *
 * Campaign 身份或状态读不到时返回 unavailable，绝不猜测目标。
 */
export function outcomeResearchEntry(
  campaignId: unknown,
  campaignStatus: unknown,
  securityCode: unknown,
): OutcomeResearchEntry {
  if (typeof campaignId !== "string" || !campaignId.trim()) {
    return {
      kind: "unavailable",
      label: "Campaign 身份缺失",
      href: null,
      detail: "这条历史 Decision 没有可核对的 Campaign，已停止导航。",
    };
  }
  if (
    typeof campaignStatus !== "string"
    || !Object.prototype.hasOwnProperty.call(CAMPAIGN_STATUS_LABELS, campaignStatus)
  ) {
    return {
      kind: "unavailable",
      label: "Campaign 状态未知",
      href: null,
      detail: "无法确认这一轮研究是否仍然有效，已停止导航。",
    };
  }
  if (isTerminalCampaignStatus(campaignStatus as CampaignStatus)) {
    if (typeof securityCode !== "string" || !A_SHARE_CODE.test(securityCode)) {
      return {
        kind: "unavailable",
        label: "缺少可用的证券代码",
        href: null,
        detail: "这一轮研究已结束，但没有可用的 6 位证券代码，已停止导航。",
      };
    }
    return {
      kind: "new-research",
      label: "需要新判断：新建一轮研究",
      href: `/candidates/${securityCode}`,
      detail: "这一轮研究已结束。新判断需要在候选研究中显式选择策略后新建，原来这轮不会被重新打开或改写。",
    };
  }
  return {
    kind: "current-proposal",
    label: "继续这轮研究（Proposal）",
    href: `/campaigns/${encodeURIComponent(campaignId.trim())}/decision-proposal`,
    detail: "这一轮研究尚未结束，进入它的 Proposal 与生命周期；不会新建或改写正式决策。",
  };
}
