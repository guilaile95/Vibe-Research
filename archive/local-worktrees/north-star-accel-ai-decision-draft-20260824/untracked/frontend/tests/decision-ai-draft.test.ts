import assert from "node:assert/strict";
import test from "node:test";

import { appliedDecisionDraftFields, proposalViewOrigin } from "../src/lib/decisionAiDraft.ts";
import type { CampaignDecisionDraft } from "../src/lib/api/types.ts";


function draft(): CampaignDecisionDraft {
  return {
    schema_version: "campaign-decision-draft.v0.1",
    draft_id: `decision_draft_${"a".repeat(32)}`,
    campaign_id: `campaign_${"b".repeat(32)}`,
    security_code: "600519",
    strategy: "SWING",
    thesis_id: "c".repeat(32),
    thesis_revision: 2,
    holding_fingerprint: "d".repeat(64),
    context_fingerprint: "e".repeat(64),
    context_as_of: "2026-08-24T00:00:00.000000Z",
    generated_at: "2026-08-24T00:00:01.000000Z",
    model_provider: "test-provider",
    model_name: "test-model",
    prompt_version: "campaign-decision-draft.prompt.v0.1",
    analysis_policy_version: "campaign-decision-draft.analysis-policy.v0.1",
    payload: {
      asset_view: { view: "ASSET", stance: "SUPPORT", note: "asset note" },
      trade_view: { view: "TRADE", stance: "WAIT", note: "trade note" },
      portfolio_view: { view: "PORTFOLIO", constraint: "portfolio constraint" },
      key_assumptions: ["assumption one", "assumption two"],
      event_invalidation_conditions: ["invalidation one"],
      limitations: ["unknown remains unknown"],
    },
    record_hash: "f".repeat(64),
  };
}


test("AI draft projects only into editable proposal fields", () => {
  assert.deepEqual(appliedDecisionDraftFields(draft()), {
    assetStance: "SUPPORT",
    assetNote: "asset note",
    tradeStance: "WAIT",
    tradeNote: "trade note",
    portfolioConstraint: "portfolio constraint",
    assumptions: "assumption one\nassumption two",
    invalidations: "invalidation one",
  });
});


test("view origin display trusts only the server preview value", () => {
  const provenance = {
    asset_view: { view_origin: "MODEL_PROPOSAL", provenance_refs: ["decision_ai_draft:test"] },
    trade_view: { view_origin: "USER_DRAFT", provenance_refs: [] },
  };
  assert.equal(proposalViewOrigin(provenance, "asset_view"), "MODEL_PROPOSAL");
  assert.equal(proposalViewOrigin(provenance, "trade_view"), "USER_DRAFT");
  assert.equal(proposalViewOrigin(provenance, "portfolio_view"), "USER_DRAFT");
  assert.equal(
    proposalViewOrigin({ asset_view: { view_origin: "MODEL_PROPOSAL_FAKE" } }, "asset_view"),
    "USER_DRAFT",
  );
});
