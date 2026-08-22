import type {
  CampaignCurrentThesis,
  CampaignRecord,
  CampaignThesisBinding,
  ExpectedHorizon,
  ThesisAggregate,
} from "./api/types.ts";
import { STRATEGY_HORIZON_RANGES } from "./campaignThesis.ts";

export type DecisionContextHydrationResult =
  | {
      status: "READY";
      source: "CURRENT_THESIS";
      reason: null;
      expectedHorizon: ExpectedHorizon;
      horizonText: string;
      frozenRevision: number;
    }
  | {
      status: "UNAVAILABLE";
      source: "NONE";
      reason: string;
      expectedHorizon: null;
      horizonText: null;
      frozenRevision: number | null;
    };

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

export function isValidExpectedHorizon(
  value: unknown,
  strategy: CampaignRecord["strategy"],
): value is ExpectedHorizon {
  if (!isRecord(value)) return false;
  const min = value.min;
  const max = value.max;
  if (
    value.unit !== "TRADING_DAY"
    || value.anchor !== "FREEZE_AT"
    || typeof min !== "number"
    || typeof max !== "number"
    || !Number.isInteger(min)
    || !Number.isInteger(max)
    || min <= 0
    || max < min
  ) {
    return false;
  }
  const range = STRATEGY_HORIZON_RANGES[strategy];
  return Boolean(range) && min >= range[0] && max <= range[1];
}

export function formatExpectedHorizon(value: ExpectedHorizon): string {
  return `${value.min}–${value.max} 个交易日`;
}

export function hydratedHorizonValue(
  currentValue: string,
  userTouched: boolean,
  result: DecisionContextHydrationResult,
): string {
  if (userTouched || currentValue.trim() || result.status !== "READY") return currentValue;
  return result.horizonText;
}

function unavailable(
  reason: string,
  frozenRevision: number | null = null,
): DecisionContextHydrationResult {
  return {
    status: "UNAVAILABLE",
    source: "NONE",
    reason,
    expectedHorizon: null,
    horizonText: null,
    frozenRevision,
  };
}

export function resolveDecisionContext(
  campaign: CampaignRecord,
  binding: CampaignThesisBinding,
  current: CampaignCurrentThesis,
  aggregate: ThesisAggregate,
): DecisionContextHydrationResult {
  if (binding.campaign_id !== campaign.campaign_id) {
    return unavailable("Campaign binding identity 不一致");
  }
  if (binding.thesis_id !== aggregate.thesis.id) {
    return unavailable("绑定 Thesis identity 不一致");
  }
  if (binding.campaign_strategy_at_bind !== campaign.strategy) {
    return unavailable("Campaign strategy 与绑定策略不一致");
  }
  if (current.campaign_id !== campaign.campaign_id || current.thesis_id !== binding.thesis_id) {
    return unavailable("Current Thesis identity 不一致");
  }
  if (current.binding.campaign_strategy_at_bind !== campaign.strategy) {
    return unavailable("Current Thesis binding strategy 不一致");
  }
  if (!current.ready) {
    return unavailable(`Current Thesis 尚未就绪：${current.reason}`);
  }
  if (current.formal_status !== "READY") {
    return unavailable("Current Thesis readiness 不一致");
  }
  if (!Number.isInteger(current.frozen_revision) || current.frozen_revision <= 0) {
    return unavailable("Current Thesis frozen revision 不合法", current.frozen_revision ?? null);
  }
  if (aggregate.thesis.formal_state !== "frozen" || aggregate.thesis.status === "archived") {
    return unavailable("绑定 Thesis 不是可用的 frozen active Thesis", current.frozen_revision);
  }
  if (aggregate.thesis.frozen_revision !== current.frozen_revision) {
    return unavailable("Current Thesis 与 Thesis aggregate 的 frozen revision 不一致", current.frozen_revision);
  }
  if (aggregate.thesis.strategy !== campaign.strategy) {
    return unavailable("Thesis strategy 与 Campaign strategy 不一致", current.frozen_revision);
  }
  const expectedHorizon = aggregate.thesis.expected_horizon;
  if (!isValidExpectedHorizon(expectedHorizon, campaign.strategy)) {
    return unavailable("Current Thesis 未提供合法 expected horizon", current.frozen_revision);
  }
  return {
    status: "READY",
    source: "CURRENT_THESIS",
    reason: null,
    expectedHorizon,
    horizonText: formatExpectedHorizon(expectedHorizon),
    frozenRevision: current.frozen_revision,
  };
}
