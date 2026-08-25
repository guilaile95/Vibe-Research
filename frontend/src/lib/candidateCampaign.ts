import type { CampaignRecord, CampaignStatus } from "./api/types";

/** StockData 只呈现仍处于候选研究链路的 Campaign，不重新定义 transition graph。 */
export const CANDIDATE_CAMPAIGN_STATUSES: readonly CampaignStatus[] = [
  "DRAFT",
  "RESEARCHING",
  "PRE-ENTRY",
] as const;

/**
 * 选择当前证券的候选 Campaign。
 *
 * Campaign 的身份和 lifecycle 仍由 backend 负责；这里仅做 StockData 的
 * read-model 投影，确保不会把其他证券或 ACTIVE/terminal 历史带入候选继续路径。
 */
export function selectCandidateCampaigns(
  campaigns: readonly CampaignRecord[],
  securityCode: string,
): CampaignRecord[] {
  return campaigns
    .filter(
      (campaign) =>
        campaign.security_code === securityCode &&
        CANDIDATE_CAMPAIGN_STATUSES.includes(campaign.status),
    )
    .slice()
    .sort(
      (a, b) =>
        a.created_at.localeCompare(b.created_at) ||
        a.campaign_id.localeCompare(b.campaign_id),
    );
}
