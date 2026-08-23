import type { TradeAttributionCandidate } from "./api/types";
import type { TradeDraft } from "./tradeLedgerView";

const CAMPAIGN_ID_RE = /^campaign_[0-9a-f]{32}$/;
const DECISION_ID_RE = /^decision_[0-9a-f]{32}$/;
const SECURITY_CODE_RE = /^[0-9]{6}$/;

export const EXECUTION_NEXT_BEST_ACTIONS = [
  "BUY NOW",
  "BUY SMALL",
  "SCALE IN",
  "REDUCE",
  "EXIT",
] as const;

export interface TradeContinuationContext {
  securityCode: string;
  campaignId: string;
  decisionId: string;
  nextBestAction: string | null;
}

export interface TradeAttributionHint {
  tradeId: string;
  campaignId: string;
  decisionId: string;
}

export function isExecutionNextBestAction(value: unknown): value is string {
  return (
    typeof value === "string"
    && (EXECUTION_NEXT_BEST_ACTIONS as readonly string[]).includes(value)
  );
}

export function buildTradeContinuationHref(input: {
  securityCode: unknown;
  campaignId: unknown;
  decisionId: unknown;
  nextBestAction: unknown;
}): string | null {
  if (
    typeof input.securityCode !== "string"
    || !SECURITY_CODE_RE.test(input.securityCode)
    || typeof input.campaignId !== "string"
    || !CAMPAIGN_ID_RE.test(input.campaignId)
    || typeof input.decisionId !== "string"
    || !DECISION_ID_RE.test(input.decisionId)
    || !isExecutionNextBestAction(input.nextBestAction)
  ) {
    return null;
  }
  const query = new URLSearchParams({
    create: "1",
    code: input.securityCode,
    campaign_id: input.campaignId,
    decision_id: input.decisionId,
    next_best_action: input.nextBestAction,
  });
  return `/trades?${query.toString()}`;
}

export function buildEvaluatedTradeContinuationHref(input: {
  securityCode: unknown;
  campaignId: unknown;
  decisionId: unknown;
  nextBestAction: unknown;
  formalDecisionEvaluation: unknown;
}): string | null {
  if (input.formalDecisionEvaluation !== "EVALUATED") return null;
  return buildTradeContinuationHref(input);
}

export function parseTradeContinuation(
  params: URLSearchParams,
): TradeContinuationContext | null {
  if (params.get("create") !== "1") return null;
  const securityCode = params.get("code") ?? "";
  const campaignId = params.get("campaign_id") ?? "";
  const decisionId = params.get("decision_id") ?? "";
  const nextBestAction = params.get("next_best_action");
  if (
    !SECURITY_CODE_RE.test(securityCode)
    || !CAMPAIGN_ID_RE.test(campaignId)
    || !DECISION_ID_RE.test(decisionId)
    || !isExecutionNextBestAction(nextBestAction)
  ) {
    return null;
  }
  return { securityCode, campaignId, decisionId, nextBestAction };
}

export function emptyTradeDraft(code = ""): TradeDraft {
  return {
    code,
    name: "",
    operation: "",
    execution_status: "",
    planned_price: "",
    planned_quantity: "",
    actual_price: "",
    actual_quantity: "",
    executed_at: "",
    fee: "",
    other_cost: "",
    unexecuted_reason: "",
    note: "",
    advice_ref: null,
    thesis_ref: null,
  };
}

export function continuationTradeDraft(
  context: TradeContinuationContext,
): TradeDraft {
  // Only the immutable security identity is carried into the draft. Operation,
  // execution status, time, price, quantity, costs and attribution stay empty.
  return emptyTradeDraft(context.securityCode);
}

export function isPreferredAttributionCandidate(
  hint: TradeAttributionHint | null,
  selectedTradeId: string | null,
  candidate: TradeAttributionCandidate,
): boolean {
  return Boolean(
    hint
    && selectedTradeId === hint.tradeId
    && candidate.decision_id === hint.decisionId
    && candidate.campaign_id === hint.campaignId,
  );
}
