import type { CampaignDecisionDraft } from "./api";
import type { ViewStance } from "./decisionProposalForm";

export interface AppliedDecisionDraftFields {
  assetStance: ViewStance;
  assetNote: string;
  tradeStance: ViewStance;
  tradeNote: string;
  portfolioConstraint: string;
  assumptions: string;
  invalidations: string;
}

/** Project a server-validated advisory draft into the existing editable form. */
export function appliedDecisionDraftFields(
  draft: CampaignDecisionDraft,
): AppliedDecisionDraftFields {
  return {
    assetStance: draft.payload.asset_view.stance,
    assetNote: draft.payload.asset_view.note,
    tradeStance: draft.payload.trade_view.stance,
    tradeNote: draft.payload.trade_view.note,
    portfolioConstraint: draft.payload.portfolio_view.constraint,
    assumptions: draft.payload.key_assumptions.join("\n"),
    invalidations: draft.payload.event_invalidation_conditions.join("\n"),
  };
}

export function proposalViewOrigin(
  viewProvenance: Record<string, unknown> | undefined,
  viewName: "asset_view" | "trade_view" | "portfolio_view",
): "MODEL_PROPOSAL" | "USER_DRAFT" {
  const value = viewProvenance?.[viewName];
  if (!value || typeof value !== "object") return "USER_DRAFT";
  return (value as { view_origin?: unknown }).view_origin === "MODEL_PROPOSAL"
    ? "MODEL_PROPOSAL"
    : "USER_DRAFT";
}
