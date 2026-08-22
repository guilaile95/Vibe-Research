// Campaign / Decision Inbox 纯展示逻辑（P0-CS1 + R1）。
//
// 铁律：
// - 前端绝不重新定义 transition graph —— 「下一合法动作」只来自
//   GET /api/campaigns/{id}/next-actions（backend frozen graph 单一权威）。
// - 前端绝不提交 status / campaign_id / created_at —— 创建 payload 只含
//   security_code + strategy（服务端决定 DRAFT 与 id）。
// - 前端绝不链式自动迁移 —— 每个 transition 都是一次显式用户点击。
// - 「正在建立的 Campaign」只是 frontend read-model 分类
//   （DRAFT / RESEARCHING / PRE-ENTRY 尚未进入 current Campaign composition，
//   不得宣称 current membership —— current 只由 backend inbox campaign_items 决定）。

import type {
  CampaignNextActions,
  CampaignRecord,
  CampaignStatus,
  CampaignStrategy,
  DecisionInboxCampaignItem,
  DecisionInboxHoldingSetupItem,
} from "./api/types";

export const CAMPAIGN_STRATEGIES: readonly CampaignStrategy[] = [
  "SHORT",
  "SWING",
  "MEDIUM",
] as const;

export const CAMPAIGN_STRATEGY_LABELS: Record<CampaignStrategy, string> = {
  SHORT: "短线",
  SWING: "波段",
  MEDIUM: "中线",
};

export const CAMPAIGN_STATUS_LABELS: Record<CampaignStatus, string> = {
  DRAFT: "草稿",
  RESEARCHING: "研究中",
  "PRE-ENTRY": "待入场",
  // 「进行中」= 已进入 current membership，不等于买卖建议已批准。
  ACTIVE: "进行中",
  REDUCING: "减仓中",
  CLOSED: "已关闭",
  REJECTED: "已拒绝",
  EXPIRED: "已过期",
};

/** Decision Inbox visible_state → 用户可读主解释（不改 semantic 值）。 */
export const VISIBLE_STATE_LABELS: Record<string, string> = {
  NO_ACTION_REQUIRED: "暂无待办",
  REVIEW_REQUIRED: "需要复核",
  BLOCKED_BY_DATA: "关键数据未就绪",
  SETUP_REQUIRED: "设置尚未完成",
};

/** reason_code → 用户可读主解释；未知码原样回退，绝不改写 semantic 值。 */
export const REASON_CODE_LABELS: Record<string, string> = {
  UNASSIGNED_HOLDING: "持仓尚未分配 Campaign",
  CAMPAIGN_NOT_IN_SCOPE: "该 Campaign 不在当前决策范围",
  THESIS_MISSING: "尚未绑定正式投资逻辑",
  THESIS_NOT_READY: "投资逻辑尚未就绪",
  THESIS_NOT_FROZEN: "投资逻辑尚未冻结",
  THESIS_WEAKENED: "投资逻辑已弱化",
  THESIS_STRENGTHENED: "投资逻辑已强化",
  THESIS_DISPROVEN: "投资逻辑已被证伪",
  THESIS_INVALIDATED: "投资逻辑已失效",
  THESIS_UNKNOWN: "投资逻辑状态未知",
  FORMAL_DECISION_MISSING: "尚未形成正式决策",
  REVIEW_BY_REACHED: "已到复核时点",
  HARD_RISK_CONFIRMED: "硬风险已确认",
  HARD_RISK_UNKNOWN: "硬风险状态未知",
  HARD_RISK_NOT_EVALUATED: "硬风险尚未评估",
  CRITICAL_DATA_BLOCKED: "关键数据被阻断",
  CRITICAL_DATA_UNKNOWN: "关键数据状态未知",
  CRITICAL_DATA_STALE: "关键数据已过期",
  CRITICAL_DATA_EVALUATION_UNKNOWN: "关键数据评估未知",
  CRITICAL_DATA_NOT_EVALUATED: "关键数据尚未评估",
  CRITICAL_DATA_ERROR: "关键数据评估出错",
  COVERAGE_INCOMPLETE: "评估覆盖不完整",
  MATERIAL_CHANGE_MATERIAL: "出现实质性变化",
  MATERIAL_CHANGE_CRITICAL: "出现关键变化",
  MATERIAL_CHANGE_UNKNOWN: "实质变化状态未知",
  MATERIAL_CHANGE_NOT_EVALUATED: "实质变化尚未评估",
  LOW_CONFIDENCE: "置信度偏低",
  CLEAN: "无额外原因",
};

export function visibleStateLabel(state: string): string {
  return VISIBLE_STATE_LABELS[state] ?? state;
}

export function reasonCodeLabel(code: string): string {
  return REASON_CODE_LABELS[code] ?? code;
}

export function presentReasonCodes(codes: readonly string[]): {
  primary: string[];
  extraCount: number;
  details: { code: string; label: string }[];
} {
  const details = codes.map((code) => ({ code, label: reasonCodeLabel(code) }));
  return {
    primary: details.slice(0, 2).map((item) => item.label),
    extraCount: Math.max(0, details.length - 2),
    details,
  };
}

/** 完整 campaign_id 仍保留在 data 属性 / title；主视觉只显示可辨认短码。 */
export function formatCampaignIdShort(campaignId: string): string {
  const prefix = "campaign_";
  if (campaignId.startsWith(prefix) && campaignId.length > prefix.length + 8) {
    return `${campaignId.slice(0, prefix.length + 8)}…`;
  }
  if (campaignId.length > 16) return `${campaignId.slice(0, 16)}…`;
  return campaignId;
}

/**
 * 按钮视觉层级用已有 terminal 分类，不复制 transition graph。
 * 终态目标降权；推进目标保持主操作。
 */
export function isDestructiveTransition(toStatus: CampaignStatus): boolean {
  return isTerminalCampaignStatus(toStatus);
}

/** transition 目标状态 → 用户动作按钮文案（只做文案，不做合法性判定）。 */
export const TRANSITION_ACTION_LABELS: Record<CampaignStatus, string> = {
  DRAFT: "回到草稿",
  RESEARCHING: "开始研究",
  "PRE-ENTRY": "标记待入场",
  ACTIVE: "激活 Campaign",
  REDUCING: "开始减仓",
  CLOSED: "关闭 Campaign",
  REJECTED: "拒绝 Campaign",
  EXPIRED: "标记过期",
};

/** frontend read-model 分类：「正在建立的 Campaign」状态集（工作单 §4/§5）。 */
export const SETUP_CAMPAIGN_STATUSES: readonly CampaignStatus[] = [
  "DRAFT",
  "RESEARCHING",
  "PRE-ENTRY",
] as const;

/** terminal 状态：不属于 setup flow（工作单 §9，不做历史 Campaign UI）。 */
export const TERMINAL_CAMPAIGN_STATUSES: readonly CampaignStatus[] = [
  "CLOSED",
  "REJECTED",
  "EXPIRED",
] as const;

export function isSetupCampaignStatus(status: CampaignStatus): boolean {
  return (SETUP_CAMPAIGN_STATUSES as readonly string[]).includes(status);
}

export function isTerminalCampaignStatus(status: CampaignStatus): boolean {
  return (TERMINAL_CAMPAIGN_STATUSES as readonly string[]).includes(status);
}

/**
 * 从 Decision Inbox snapshot 收集当前持仓 security universe：
 * holding_setup_items（未分配持仓）+ campaign_items（current Campaign 持仓）。
 * 必须两者并集 —— 否则 ACTIVE sibling 会隐藏同 Security 的 DRAFT sibling
 * （工作单 §6：600519 SWING ACTIVE 时 600519 已不在 holding_setup_items，
 * 但 MEDIUM DRAFT 仍需可达）。
 */
export function collectHoldingUniverseSecurityCodes(snapshot: {
  holding_setup_items: DecisionInboxHoldingSetupItem[];
  campaign_items: DecisionInboxCampaignItem[];
}): string[] {
  const codes = new Set<string>();
  for (const item of snapshot.holding_setup_items) {
    codes.add(item.security_code);
  }
  for (const item of snapshot.campaign_items) {
    codes.add(item.security_code);
  }
  return [...codes].sort();
}

/**
 * 选择「正在建立的 Campaign」：
 * security ∈ holding universe 且 status ∈ {DRAFT, RESEARCHING, PRE-ENTRY}。
 * ACTIVE/REDUCING（current，由 inbox campaign_items 呈现）与 terminal
 * 一律排除。确定性排序：security_code → created_at → campaign_id。
 */
export function selectSetupCampaigns(
  campaigns: CampaignRecord[],
  universeCodes: readonly string[],
): CampaignRecord[] {
  const universe = new Set(universeCodes);
  return campaigns
    .filter(
      (c) =>
        universe.has(c.security_code) &&
        isSetupCampaignStatus(c.status),
    )
    .sort((a, b) =>
      a.security_code.localeCompare(b.security_code)
      || a.created_at.localeCompare(b.created_at)
      || a.campaign_id.localeCompare(b.campaign_id),
    );
}

/** 可渲染的 transition 目标：next-actions 缺失/失败 → 空（绝不猜测 graph）。 */
export function renderableTransitionTargets(
  nextActions: CampaignNextActions | null,
): CampaignStatus[] {
  if (!nextActions || nextActions.next_actions.length === 0) return [];
  return nextActions.next_actions;
}

/** 创建 Campaign 的精确 payload：只含 security_code + strategy。 */
export function createCampaignPayload(
  securityCode: string,
  strategy: CampaignStrategy,
): { security_code: string; strategy: CampaignStrategy } {
  return { security_code: securityCode, strategy };
}

/** 显式 transition 的精确 payload：expected_status（CAS）+ to_status。 */
export function transitionPayload(
  currentStatus: CampaignStatus,
  toStatus: CampaignStatus,
): { expected_status: CampaignStatus; to_status: CampaignStatus } {
  return { expected_status: currentStatus, to_status: toStatus };
}

export type FormalDecisionNextStep = {
  kind: "review" | "new-decision" | "proposal";
  label: string;
  href: string;
};

/** Formal Decision 状态只映射到显式入口，不推断用户是否应创建新决策。 */
export function formalDecisionNextSteps(
  evaluation: string | null | undefined,
  campaignId: string,
): FormalDecisionNextStep[] {
  if (!evaluation) return [];
  const proposalHref = `/campaigns/${encodeURIComponent(campaignId)}/decision-proposal`;
  if (evaluation === "EVALUATED") {
    return [
      { kind: "review", label: "打开决策复盘", href: "/decision-performance" },
      { kind: "new-decision", label: "形成新的 Formal Decision", href: proposalHref },
    ];
  }
  return [{ kind: "proposal", label: "打开 Formal Decision Review", href: proposalHref }];
}

/** 提取用户可读错误文案（409 等 backend detail 如实显示，绝不伪装成功）。 */
export function errorMessage(err: unknown): string {
  if (err instanceof Error && err.message) return err.message;
  return "操作失败，请重试";
}
