import assert from "node:assert/strict";
import test from "node:test";

import type {
  CampaignCurrentThesis,
  CampaignRecord,
  EvidenceLink,
  ResearchContinuity,
} from "../src/lib/api/types.ts";
import { buildResearchBrief } from "../src/lib/researchBrief.ts";
import type { DecisionContextHydrationResult } from "../src/lib/decisionContextHydration.ts";

const campaign: CampaignRecord = {
  campaign_id: "campaign_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  security_code: "600519",
  strategy: "SWING",
  status: "PRE-ENTRY",
  created_at: "2026-08-01T00:00:00.000Z",
};

function evidence(partial: Partial<EvidenceLink> & Pick<EvidenceLink, "evidence_id" | "stance" | "claim">): EvidenceLink {
  return {
    evidence_type: "news",
    classification: "fact",
    confidence: "high",
    source_title: "来源",
    source_url: "https://example.com/e",
    source_date: "2026-08-01",
    accessed_at: "2026-08-01T00:00:00.000Z",
    ...partial,
  };
}

function readyThesis(links: EvidenceLink[], invalidation: string[] = ["渠道崩塌"]): CampaignCurrentThesis {
  return {
    campaign_id: campaign.campaign_id,
    thesis_id: "thesis_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
    binding: {
      thesis_revision_at_bind: 3,
      campaign_strategy_at_bind: "SWING",
      bound_at: "2026-08-20T00:00:00.000Z",
    },
    frozen_revision: 3,
    original_snapshot: {
      thesis: {
        id: "thesis_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        subject_type: "stock",
        subject_id: "600519",
        market: "CN",
        title: "茅台波段研究",
        summary: "需求仍在，等待更好价格。",
        status: "active",
        core_claims: ["高端需求稳定", "库存可控", "估值回到可接受区间"],
        catalysts: [],
        risks: [],
        invalidation_conditions: invalidation,
        created_at: "2026-08-01T00:00:00.000Z",
        updated_at: "2026-08-20T00:00:00.000Z",
        current_revision: 3,
        formal_state: "frozen",
        formalization_started_at: "2026-08-10T00:00:00.000Z",
        confirmed_at: "2026-08-15T00:00:00.000Z",
        frozen_at: "2026-08-20T00:00:00.000Z",
        frozen_revision: 3,
        archived_at: null,
        strategy: "SWING",
        expected_horizon: { unit: "TRADING_DAY", min: 10, max: 30, anchor: "FREEZE_AT" },
        free_notes: null,
      },
      evidence_links: links,
      formal_state: "frozen",
      formalization_started_at: "2026-08-10T00:00:00.000Z",
      confirmed_at: "2026-08-15T00:00:00.000Z",
      frozen_at: "2026-08-20T00:00:00.000Z",
      frozen_revision: 3,
      archived_at: null,
      status: "active",
      current_revision: 3,
      updated_at: "2026-08-20T00:00:00.000Z",
    },
    deltas: [],
    effective_state: "FROZEN_ORIGINAL",
    ready: true,
    formal_status: "READY",
  };
}

const hydrationReady: DecisionContextHydrationResult = {
  status: "READY",
  source: "CURRENT_THESIS",
  reason: null,
  expectedHorizon: { unit: "TRADING_DAY", min: 10, max: 30, anchor: "FREEZE_AT" },
  horizonText: "10–30 个交易日",
  frozenRevision: 3,
};

function continuity(status: ResearchContinuity["changes"]["status"], items: ResearchContinuity["changes"]["items"] = []): ResearchContinuity {
  return {
    schema_version: "research_continuity.v0.1",
    status: "NORMAL",
    campaign_id: campaign.campaign_id,
    security_code: "600519",
    strategy: "SWING",
    fetched_at: "2026-08-22T00:00:00.000Z",
    baseline: {
      status: status === "NO_BASELINE" ? "NO_BASELINE" : "READY",
      authority_type: status === "NO_BASELINE" ? null : "CANDIDATE_RESEARCH_FORMAL_ORIGINAL",
    },
    changes: { status, items, observation_count: items.length },
    decision_calendar: {
      state: "NO_RECORD",
      next: null,
      latest_actual: null,
      fetched_at: "2026-08-22T00:00:00.000Z",
      source: "cninfo",
    },
    authority_refs: [],
    writes: { thesis: 0, decision: 0, campaign: 0, trade: 0 },
  };
}

test("已确认快照映射标的、策略、周期与观点", () => {
  const brief = buildResearchBrief({
    campaignId: campaign.campaign_id,
    campaign,
    currentThesis: readyThesis([
      evidence({ evidence_id: "ev1", stance: "support", claim: "终端动销仍在", classification: "fact" }),
    ]),
    hydration: hydrationReady,
    continuity: continuity("NO_BASELINE"),
    continuityError: null,
    contextState: "ready",
    contextMessage: "",
  });
  assert.equal(brief.securityCode, "600519");
  assert.equal(brief.strategyLabel, "波段");
  assert.equal(brief.horizonText, "10–30 个交易日");
  assert.equal(brief.horizonSource, "CURRENT_THESIS");
  assert.equal(brief.confirmed.status, "CONFIRMED");
  assert.equal(brief.confirmed.title, "茅台波段研究");
  assert.ok(brief.confirmed.claims.includes("高端需求稳定"));
  assert.match(brief.confirmed.note, /冻结快照 v3/);
});

test("未确认 Thesis 不会把草稿当正式观点", () => {
  const brief = buildResearchBrief({
    campaignId: campaign.campaign_id,
    campaign,
    currentThesis: {
      campaign_id: campaign.campaign_id,
      thesis_id: "thesis_cccccccccccccccccccccccccccccccc",
      binding: {
        thesis_revision_at_bind: 1,
        campaign_strategy_at_bind: "SWING",
        bound_at: "2026-08-20T00:00:00.000Z",
      },
      formal_state: "confirmed",
      frozen_revision: null,
      ready: false,
      formal_status: "NOT_READY",
      reason: "NOT_FROZEN",
    },
    hydration: { status: "UNAVAILABLE", source: "NONE", reason: "NOT_FROZEN", expectedHorizon: null, horizonText: null, frozenRevision: null },
    continuity: null,
    continuityError: null,
    contextState: "unavailable",
    contextMessage: "Current Thesis 尚未就绪：NOT_FROZEN",
  });
  assert.equal(brief.confirmed.status, "UNAVAILABLE");
  assert.equal(brief.confirmed.claims.length, 0);
  assert.match(brief.confirmed.note, /未确认草稿/);
  assert.equal(brief.evidence.supporting.length, 0);
  assert.match(brief.invalidation.note, /不把表单里的失效条件当作正式记录/);
});

test("没有反对记录不等于没有反对证据；记录失效条件不等于已触发", () => {
  const brief = buildResearchBrief({
    campaignId: campaign.campaign_id,
    campaign,
    currentThesis: readyThesis([
      evidence({ evidence_id: "ev1", stance: "support", claim: "终端动销仍在", classification: "fact" }),
      evidence({ evidence_id: "ev2", stance: "support", claim: "可能补库存", classification: "inference" }),
    ], ["渠道崩塌"]),
    hydration: hydrationReady,
    continuity: continuity("NOT_EVALUATED"),
    continuityError: null,
    contextState: "ready",
    contextMessage: "",
  });
  assert.equal(brief.evidence.opposingRecorded, false);
  assert.match(brief.evidence.note, /不等于没有反对证据/);
  assert.deepEqual(brief.invalidation.conditions, ["渠道崩塌"]);
  assert.match(brief.invalidation.note, /不是这些条件已经触发/);
  assert.equal(brief.evidence.supporting[0].classificationKind, "fact");
  assert.equal(brief.evidence.supporting[1].classificationKind, "inference");
});

test("NO_BASELINE 与读取失败都不能写成没有变化", () => {
  const noBaseline = buildResearchBrief({
    campaignId: campaign.campaign_id,
    campaign,
    currentThesis: readyThesis([]),
    hydration: hydrationReady,
    continuity: continuity("NO_BASELINE"),
    continuityError: null,
    contextState: "ready",
    contextMessage: "",
  });
  assert.match(noBaseline.changes.note, /不能声称没有变化/);
  const failed = buildResearchBrief({
    campaignId: campaign.campaign_id,
    campaign,
    currentThesis: readyThesis([]),
    hydration: hydrationReady,
    continuity: null,
    continuityError: "UNAVAILABLE",
    contextState: "ready",
    contextMessage: "",
  });
  assert.equal(failed.changes.status, "UNAVAILABLE");
  assert.match(failed.changes.note, /不能声称没有变化/);
});
