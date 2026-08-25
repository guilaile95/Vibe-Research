import type { TradeAttributionCandidate, TradeContinuationRef } from "./api/types";
import type { TradeDraft } from "./tradeLedgerView";

const DECISION_ID_RE = /^decision_[0-9a-f]{32}$/;
const SNAPSHOT_HASH_RE = /^[0-9a-f]{64}$/;

export interface TradeContinuationContext {
  continuationRef: TradeContinuationRef;
  securityCode: string;
}

export interface TradeAttributionHint {
  tradeId: string;
  campaignId?: string;
  decisionId: string;
}

export function buildTradeContinuationHref(input: {
  securityCode: unknown;
  continuationRef: unknown;
}): string | null {
  if (
    typeof input.securityCode !== "string"
    || !/^\d{6}$/.test(input.securityCode)
    || !isValidContinuationRef(input.continuationRef)
  ) return null;
  const query = new URLSearchParams({
    create: "1",
    code: input.securityCode,
    decision_id: input.continuationRef.decision_id,
    snapshot_hash: input.continuationRef.snapshot_hash,
  });
  return `/trades?${query.toString()}`;
}

export function buildEvaluatedTradeContinuationHref(input: {
  securityCode: unknown;
  continuationRef: unknown;
  formalDecisionEvaluation: unknown;
}): string | null {
  if (input.formalDecisionEvaluation !== "EVALUATED") return null;
  return buildTradeContinuationHref(input);
}

function isValidContinuationRef(value: unknown): value is TradeContinuationRef {
  if (!value || typeof value !== "object") return false;
  const ref = value as Record<string, unknown>;
  return typeof ref.decision_id === "string"
    && DECISION_ID_RE.test(ref.decision_id)
    && typeof ref.snapshot_hash === "string"
    && SNAPSHOT_HASH_RE.test(ref.snapshot_hash);
}

export function parseTradeContinuation(
  params: URLSearchParams,
): TradeContinuationContext | null {
  if (params.get("create") !== "1") return null;
  const securityCode = params.get("code") ?? "";
  const decisionId = params.get("decision_id") ?? "";
  const snapshotHash = params.get("snapshot_hash") ?? "";
  if (!/^\d{6}$/.test(securityCode) || !isValidContinuationRef({
    decision_id: decisionId,
    snapshot_hash: snapshotHash,
  })) return null;
  return {
    securityCode,
    continuationRef: { decision_id: decisionId, snapshot_hash: snapshotHash },
  };
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
  return {
    ...emptyTradeDraft(context.securityCode),
    continuation_ref: context.continuationRef,
  };
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
    && (hint.campaignId === undefined || candidate.campaign_id === hint.campaignId),
  );
}
