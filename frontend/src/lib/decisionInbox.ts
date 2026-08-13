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
  ACTIVE: "已激活",
  REDUCING: "减仓中",
  CLOSED: "已关闭",
  REJECTED: "已拒绝",
  EXPIRED: "已过期",
};

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

/** 提取用户可读错误文案（409 等 backend detail 如实显示，绝不伪装成功）。 */
export function errorMessage(err: unknown): string {
  if (err instanceof Error && err.message) return err.message;
  return "操作失败，请重试";
}
