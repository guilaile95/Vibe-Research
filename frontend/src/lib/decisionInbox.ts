// Campaign / Decision Inbox 纯展示逻辑（P0-CS1）。
//
// 铁律：
// - 前端绝不重新定义 transition graph —— 「下一合法动作」只来自
//   GET /api/campaigns/{id}/next-actions（backend frozen graph 单一权威）。
// - 前端绝不提交 status / campaign_id / created_at —— 创建 payload 只含
//   security_code + strategy（服务端决定 DRAFT 与 id）。
// - 前端绝不链式自动迁移 —— 每个 transition 都是一次显式用户点击。

import type {
  CampaignStatus,
  CampaignStrategy,
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
