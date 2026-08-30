import type {
  CampaignRecord,
  CampaignStatus,
  DerivedPositionsResult,
  EvidenceRecord,
  PortfolioCapitalAvailabilityState,
  PortfolioCapitalReplacementCandidate,
  PortfolioFitState,
  ReplacementReviewState,
} from "./api/types";

/** StockData 只呈现仍处于候选研究链路的 Campaign，不重新定义 transition graph。 */
export const CANDIDATE_CAMPAIGN_STATUSES: readonly CampaignStatus[] = [
  "DRAFT",
  "RESEARCHING",
  "PRE-ENTRY",
] as const;

export type CandidatePositionState = "HELD" | "NOT_HELD" | "UNKNOWN";

export interface CandidatePositionPresentation {
  state: CandidatePositionState;
  shares: number | null;
  reason: string;
}

export type CandidateEvidenceCoverageKey =
  | "FUNDAMENTALS"
  | "CATALYSTS"
  | "EXTERNAL_RESEARCH";

export interface CandidateEvidenceCoverage {
  key: CandidateEvidenceCoverageKey;
  label: string;
  count: number;
  gap: boolean;
}

export interface CandidateEvidenceGapSummary {
  coverage: CandidateEvidenceCoverage[];
  classificationCounts: { fact: number; inference: number; unknown: number };
  highConfidenceFactCount: number;
  latestSourceDate: string | null;
  freshness: "NOT_EVALUATED";
  sourceConflict: "UNKNOWN";
  nextResearchQuestions: string[];
  highestImpactQuestion: string | null;
}

export const CANDIDATE_CONFIDENCE_LEVELS = ["HIGH", "MEDIUM", "LOW", "UNKNOWN"] as const;
export type CandidateConfidence = (typeof CANDIDATE_CONFIDENCE_LEVELS)[number];

export interface CandidateValuationCaseDraft {
  assumptions: string;
  inputMetric: string;
  inputValue: string;
  inputPeriod: string;
  source: string;
  dataAt: string;
  priceLow: string;
  priceHigh: string;
  horizon: string;
  changeConditions: string;
}

export interface CandidateValuationCase {
  assumptions: string[];
  inputs: Array<{ metric: string; value: string | number; period: string }>;
  source: string;
  data_at: string;
  price_range: { low: number; high: number };
  horizon: string;
  change_conditions: string[];
}

export interface CandidateTradeTermsDraft {
  entryLow: string;
  entryHigh: string;
  invalidationPrice: string;
  executionStyle: "" | "SCALE_IN";
}

export interface CandidateTradeTerms {
  entry_range: { low: number; high: number };
  invalidation_price: number;
  execution_style?: "SCALE_IN";
}

export interface PortfolioCapitalContextPresentation {
  valid: boolean;
  schemaVersion: string | null;
  capitalAvailability: {
    state: PortfolioCapitalAvailabilityState;
    confirmedCash: number | null;
    reasonCodes: string[];
  };
  portfolioFit: {
    state: PortfolioFitState;
    existingPositionCount: number | null;
    reasonCodes: string[];
  };
  replacementReview: {
    state: ReplacementReviewState;
    reasonCodes: string[];
    candidates: PortfolioCapitalReplacementCandidate[];
  };
  positionSizingStatus: string;
  authorityRefs: string[];
  finalAllowedActions: string[] | null;
}

const CAPITAL_AVAILABILITY_STATES = new Set<PortfolioCapitalAvailabilityState>(["AVAILABLE", "CONSTRAINED", "UNKNOWN"]);
const PORTFOLIO_FIT_STATES = new Set<PortfolioFitState>(["SUPPORTIVE", "CONSTRAINED", "UNKNOWN"]);
const REPLACEMENT_REVIEW_STATES = new Set<ReplacementReviewState>(["NOT_REQUIRED", "WORTH_REVIEW", "NOT_PROVEN", "UNKNOWN"]);
const CAMPAIGN_STRATEGY_VALUES = new Set(["SHORT", "SWING", "MEDIUM"]);
const PORTFOLIO_CAPITAL_CONTEXT_SCHEMA_VERSION = "portfolio_capital_context.v0.1";

function recordOf(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function nonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.trim() !== "";
}

function stringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every(nonEmptyString);
}

function nullableFiniteNumber(value: unknown): value is number | null {
  return value === null || (typeof value === "number" && Number.isFinite(value));
}

function nullableCount(value: unknown): value is number | null {
  return value === null || (typeof value === "number" && Number.isInteger(value) && value >= 0);
}

function finalAllowedActions(actionEnvelope: unknown): string[] | null {
  const envelope = recordOf(actionEnvelope);
  const actions = envelope?.allowed_actions;
  return stringArray(actions) ? actions.slice() : null;
}

function unknownPortfolioCapital(finalActions: string[] | null): PortfolioCapitalContextPresentation {
  return {
    valid: false,
    schemaVersion: null,
    capitalAvailability: { state: "UNKNOWN", confirmedCash: null, reasonCodes: [] },
    portfolioFit: { state: "UNKNOWN", existingPositionCount: null, reasonCodes: [] },
    replacementReview: { state: "UNKNOWN", reasonCodes: [], candidates: [] },
    positionSizingStatus: "UNKNOWN",
    authorityRefs: [],
    finalAllowedActions: finalActions,
  };
}

/** Read-only CAP1 projection. Missing or malformed authority data fails closed. */
export function presentPortfolioCapitalContext(
  portfolioView: unknown,
  actionEnvelope: unknown,
): PortfolioCapitalContextPresentation {
  const finalActions = finalAllowedActions(actionEnvelope);
  const view = recordOf(portfolioView);
  const context = recordOf(view?.portfolio_capital_context);
  const availability = recordOf(context?.capital_availability);
  const fit = recordOf(context?.portfolio_fit);
  const replacement = recordOf(context?.replacement_review);
  const candidates = replacement?.candidates;

  if (
    !context
    || context.schema_version !== PORTFOLIO_CAPITAL_CONTEXT_SCHEMA_VERSION
    || !availability
    || !CAPITAL_AVAILABILITY_STATES.has(availability.state as PortfolioCapitalAvailabilityState)
    || !nullableFiniteNumber(availability.confirmed_cash)
    || (availability.state !== "UNKNOWN" && availability.confirmed_cash === null)
    || !stringArray(availability.reason_codes)
    || !fit
    || !PORTFOLIO_FIT_STATES.has(fit.state as PortfolioFitState)
    || !nullableCount(fit.existing_position_count)
    || (fit.state !== "UNKNOWN" && fit.existing_position_count === null)
    || !stringArray(fit.reason_codes)
    || !replacement
    || !REPLACEMENT_REVIEW_STATES.has(replacement.state as ReplacementReviewState)
    || !stringArray(replacement.reason_codes)
    || !Array.isArray(candidates)
    || !nonEmptyString(context.position_sizing_status)
    || !stringArray(context.authority_refs)
  ) return unknownPortfolioCapital(finalActions);

  const normalizedCandidates: PortfolioCapitalReplacementCandidate[] = [];
  for (const candidateValue of candidates) {
    const candidate = recordOf(candidateValue);
    if (
      !candidate
      || !nonEmptyString(candidate.security_code)
      || !/^\d{6}$/.test(candidate.security_code)
      || !nonEmptyString(candidate.campaign_id)
      || !nonEmptyString(candidate.strategy)
      || !CAMPAIGN_STRATEGY_VALUES.has(candidate.strategy)
      || !stringArray(candidate.reason_codes)
    ) return unknownPortfolioCapital(finalActions);
    normalizedCandidates.push({
      security_code: candidate.security_code,
      campaign_id: candidate.campaign_id,
      strategy: candidate.strategy as PortfolioCapitalReplacementCandidate["strategy"],
      reason_codes: candidate.reason_codes.slice(),
    });
  }

  const availabilityState = availability.state as PortfolioCapitalAvailabilityState;
  const fitState = fit.state as PortfolioFitState;
  const replacementState = replacement.state as ReplacementReviewState;
  return {
    valid: true,
    schemaVersion: context.schema_version,
    capitalAvailability: {
      state: availabilityState,
      confirmedCash: availabilityState === "UNKNOWN" ? null : availability.confirmed_cash,
      reasonCodes: availability.reason_codes.slice(),
    },
    portfolioFit: {
      state: fitState,
      existingPositionCount: fitState === "UNKNOWN" ? null : fit.existing_position_count,
      reasonCodes: fit.reason_codes.slice(),
    },
    replacementReview: {
      state: replacementState,
      reasonCodes: replacement.reason_codes.slice(),
      candidates: replacementState === "UNKNOWN" ? [] : normalizedCandidates,
    },
    positionSizingStatus: context.position_sizing_status,
    authorityRefs: context.authority_refs.slice(),
    finalAllowedActions: finalActions,
  };
}

export function candidateWorkspaceHref(code: string): string {
  return `/candidates/${encodeURIComponent(code.trim())}`;
}

/** Position Reality 不完整时保持 UNKNOWN；没有 OPEN 行只在 canonical ledger 上等于 NOT_HELD。 */
export function deriveCandidatePosition(
  result: DerivedPositionsResult,
  securityCode: string,
): CandidatePositionPresentation {
  if (
    result.derivation_status !== "OK"
    || result.bootstrap_status !== "BOOTSTRAPPED"
    || result.canonical !== true
  ) {
    return {
      state: "UNKNOWN",
      shares: null,
      reason: `Position Reality 未形成 canonical 结论（${result.derivation_status} / ${result.bootstrap_status}）。`,
    };
  }
  const holding = result.positions.find(
    (position) => position.code === securityCode && position.status === "OPEN" && position.shares > 0,
  );
  return holding
    ? { state: "HELD", shares: holding.shares, reason: "canonical ledger 存在 OPEN position。" }
    : { state: "NOT_HELD", shares: 0, reason: "canonical ledger 未发现 OPEN position。" };
}

/** 这里只做 Evidence Ledger 库存盘点；gap 不等于 Evidence Gate 或充分性结论。 */
export function summarizeCandidateEvidence(
  records: readonly EvidenceRecord[],
): CandidateEvidenceCoverage[] {
  const specs: Array<{
    key: CandidateEvidenceCoverageKey;
    label: string;
    types: readonly EvidenceRecord["evidence_type"][];
  }> = [
    { key: "FUNDAMENTALS", label: "基本面披露", types: ["financial_filing"] },
    { key: "CATALYSTS", label: "催化与事件", types: ["announcement", "news"] },
    { key: "EXTERNAL_RESEARCH", label: "外部研究", types: ["report", "research_note"] },
  ];
  return specs.map(({ key, label, types }) => {
    const count = records.filter((record) => types.includes(record.evidence_type)).length;
    return { key, label, count, gap: count === 0 };
  });
}

/**
 * Evidence gap 的透明 read-model：只根据现有 Ledger 字段盘点。
 * 没有 freshness/conflict policy 的证据，因此两者绝不乐观推断。
 */
export function buildCandidateEvidenceGap(
  records: readonly EvidenceRecord[],
): CandidateEvidenceGapSummary {
  const coverage = summarizeCandidateEvidence(records);
  const classificationCounts = {
    fact: records.filter((record) => record.classification === "fact").length,
    inference: records.filter((record) => record.classification === "inference").length,
    unknown: records.filter((record) => record.classification === "unknown").length,
  };
  const highConfidenceFactCount = records.filter(
    (record) => record.classification === "fact" && record.confidence === "high",
  ).length;
  const sourceDates = records
    .map((record) => record.source_date)
    .filter((date): date is string => Boolean(date))
    .sort((a, b) => b.localeCompare(a));
  const gapKeys = new Set(coverage.filter((item) => item.gap).map((item) => item.key));
  const nextResearchQuestions: string[] = [];
  if (gapKeys.has("FUNDAMENTALS")) {
    nextResearchQuestions.push("最新财报或正式财务披露是否支持关键盈利与现金流假设？");
  }
  if (highConfidenceFactCount === 0) {
    nextResearchQuestions.push("哪个核心估值输入仍缺少 high-confidence fact 作为可追溯依据？");
  }
  if (gapKeys.has("CATALYSTS")) {
    nextResearchQuestions.push("近期公告或公开事件中，什么事实最可能改变催化与失效条件？");
  }
  if (gapKeys.has("EXTERNAL_RESEARCH")) {
    nextResearchQuestions.push("哪份独立研究最能挑战 Base case，而不是重复公司叙事？");
  }
  if (classificationCounts.unknown > 0) {
    nextResearchQuestions.push("哪些 UNKNOWN 记录需要补来源，才能区分事实与推断？");
  }
  return {
    coverage,
    classificationCounts,
    highConfidenceFactCount,
    latestSourceDate: sourceDates[0] ?? null,
    freshness: "NOT_EVALUATED",
    sourceConflict: "UNKNOWN",
    nextResearchQuestions,
    highestImpactQuestion: nextResearchQuestions[0] ?? null,
  };
}

function splitRequiredLines(value: string): string[] {
  return value.split(/[,\n]/).map((item) => item.trim()).filter(Boolean);
}

function positiveNumber(value: string): number | null {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
}

function inputValue(value: string): string | number {
  const trimmed = value.trim();
  const parsed = Number(trimmed);
  return trimmed !== "" && Number.isFinite(parsed) ? parsed : trimmed;
}

/** 构造 backend 校验的单个 Bear/Base/Bull case；任何缺项都 fail closed。 */
export function buildCandidateValuationCase(
  draft: CandidateValuationCaseDraft,
): CandidateValuationCase | null {
  const assumptions = splitRequiredLines(draft.assumptions);
  const changeConditions = splitRequiredLines(draft.changeConditions);
  const low = positiveNumber(draft.priceLow);
  const high = positiveNumber(draft.priceHigh);
  const metric = draft.inputMetric.trim();
  const value = draft.inputValue.trim();
  const period = draft.inputPeriod.trim();
  const dataAt = draft.dataAt.trim();
  if (
    assumptions.length === 0
    || changeConditions.length === 0
    || low === null
    || high === null
    || high < low
    || !metric
    || !value
    || !period
    || !draft.source.trim()
    || !/^\d{4}-\d{2}-\d{2}$/.test(dataAt)
    || !draft.horizon.trim()
  ) return null;
  return {
    assumptions,
    inputs: [{ metric, value: inputValue(value), period }],
    source: draft.source.trim(),
    data_at: dataAt,
    price_range: { low, high },
    horizon: draft.horizon.trim(),
    change_conditions: changeConditions,
  };
}

/** 入场区间必须有效，且失效价必须严格低于 entry low。 */
export function buildCandidateTradeTerms(
  draft: CandidateTradeTermsDraft,
): CandidateTradeTerms | null {
  const low = positiveNumber(draft.entryLow);
  const high = positiveNumber(draft.entryHigh);
  const invalidation = positiveNumber(draft.invalidationPrice);
  if (low === null || high === null || invalidation === null || high < low || invalidation >= low) {
    return null;
  }
  return {
    entry_range: { low, high },
    invalidation_price: invalidation,
    ...(draft.executionStyle ? { execution_style: draft.executionStyle } : {}),
  };
}

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
