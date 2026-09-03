import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import type {
  CampaignCurrentThesis,
  CampaignRecord,
  CampaignThesisBinding,
  ThesisAggregate,
} from "../src/lib/api/types.ts";
import {
  formatExpectedHorizon,
  hydratedHorizonValue,
  isValidExpectedHorizon,
  resolveDecisionContext,
} from "../src/lib/decisionContextHydration.ts";

const campaign: CampaignRecord = {
  campaign_id: "campaign_0123456789abcdef0123456789abcdef",
  security_code: "600519",
  strategy: "SWING",
  status: "ACTIVE",
  created_at: "2026-08-22T00:00:00.000Z",
};

const binding: CampaignThesisBinding = {
  campaign_id: campaign.campaign_id,
  thesis_id: "0123456789abcdef0123456789abcdef",
  thesis_revision_at_bind: 2,
  campaign_strategy_at_bind: "SWING",
  bound_at: "2026-08-22T00:00:00.000Z",
};

const aggregate: ThesisAggregate = {
  thesis: {
    id: binding.thesis_id,
    subject_type: "stock",
    subject_id: "600519",
    market: "CN",
    title: "Frozen thesis",
    summary: "summary",
    status: "active",
    core_claims: ["a", "b", "c"],
    catalysts: [],
    risks: [],
    invalidation_conditions: [],
    created_at: "2026-08-22T00:00:00.000Z",
    updated_at: "2026-08-22T00:00:00.000Z",
    current_revision: 2,
    formal_state: "frozen",
    formalization_started_at: "2026-08-22T00:00:00.000Z",
    confirmed_at: "2026-08-22T00:00:00.000Z",
    frozen_at: "2026-08-22T00:00:00.000Z",
    frozen_revision: 2,
    archived_at: null,
    strategy: "SWING",
    expected_horizon: { unit: "TRADING_DAY", min: 10, max: 30, anchor: "FREEZE_AT" },
    free_notes: null,
  },
  evidence_links: [],
};

const ready: CampaignCurrentThesis = {
  campaign_id: campaign.campaign_id,
  thesis_id: binding.thesis_id,
  binding: {
    thesis_revision_at_bind: 2,
    campaign_strategy_at_bind: "SWING",
    bound_at: binding.bound_at,
  },
  frozen_revision: 2,
  original_snapshot: {} as never,
  deltas: [],
  effective_state: "STABLE",
  ready: true,
  formal_status: "READY",
};

function notReady(reason = "NOT_FROZEN"): CampaignCurrentThesis {
  return {
    campaign_id: campaign.campaign_id,
    thesis_id: binding.thesis_id,
    binding: ready.binding,
    formal_state: "confirmed",
    frozen_revision: null,
    ready: false,
    formal_status: "NOT_READY",
    reason,
  };
}

test("expected horizon 校验复用策略范围并格式化", () => {
  assert.equal(isValidExpectedHorizon({ unit: "TRADING_DAY", min: 5, max: 45, anchor: "FREEZE_AT" }, "SWING"), true);
  assert.equal(isValidExpectedHorizon({ unit: "TRADING_DAY", min: 1, max: 10, anchor: "FREEZE_AT" }, "SHORT"), true);
  assert.equal(isValidExpectedHorizon({ unit: "TRADING_DAY", min: 40, max: 252, anchor: "FREEZE_AT" }, "MEDIUM"), true);
  assert.equal(isValidExpectedHorizon({ unit: "TRADING_DAY", min: 4, max: 30, anchor: "FREEZE_AT" }, "SWING"), false);
  assert.equal(isValidExpectedHorizon({ unit: "TRADING_DAY", min: 10, max: 46, anchor: "FREEZE_AT" }, "SWING"), false);
  assert.equal(isValidExpectedHorizon({ unit: "TRADING_DAY", min: true, max: 30, anchor: "FREEZE_AT" }, "SWING"), false);
  assert.equal(isValidExpectedHorizon({ unit: "CALENDAR_DAY", min: 10, max: 30, anchor: "FREEZE_AT" }, "SWING"), false);
  assert.equal(formatExpectedHorizon({ unit: "TRADING_DAY", min: 10, max: 30, anchor: "FREEZE_AT" }), "10–30 个交易日");
});

test("READY Current Thesis + aggregate 合法时只从 Current Thesis hydration", () => {
  const result = resolveDecisionContext(campaign, binding, ready, aggregate);
  assert.equal(result.status, "READY");
  if (result.status !== "READY") return;
  assert.equal(result.source, "CURRENT_THESIS");
  assert.equal(result.frozenRevision, 2);
  assert.equal(result.horizonText, "10–30 个交易日");
});

test("NOT_READY、缺失/非法 horizon 与 identity mismatch 都 fail closed", () => {
  assert.equal(resolveDecisionContext(campaign, binding, notReady(), aggregate).status, "UNAVAILABLE");
  assert.equal(resolveDecisionContext(campaign, binding, ready, {
    ...aggregate,
    thesis: { ...aggregate.thesis, expected_horizon: null },
  }).status, "UNAVAILABLE");
  assert.equal(resolveDecisionContext(campaign, binding, ready, {
    ...aggregate,
    thesis: { ...aggregate.thesis, expected_horizon: { unit: "TRADING_DAY", min: 1, max: 2, anchor: "FREEZE_AT" } },
  }).status, "UNAVAILABLE");
  assert.equal(resolveDecisionContext(campaign, { ...binding, thesis_id: "fedcba9876543210fedcba9876543210" }, ready, aggregate).status, "UNAVAILABLE");
  assert.equal(resolveDecisionContext(campaign, binding, ready, {
    ...aggregate,
    thesis: { ...aggregate.thesis, frozen_revision: 3 },
  }).status, "UNAVAILABLE");
});

test("hydration 不覆盖用户已经填写或触碰的 horizon", () => {
  const result = resolveDecisionContext(campaign, binding, ready, aggregate);
  assert.equal(hydratedHorizonValue("", false, result), "10–30 个交易日");
  assert.equal(hydratedHorizonValue("用户自己的 horizon", false, result), "用户自己的 horizon");
  assert.equal(hydratedHorizonValue("", true, result), "");
});

test("页面通过 backend authority hydration，不从 URL query 推导 horizon/review_by", () => {
  const source = readFileSync(new URL("../src/pages/DecisionProposalReview.tsx", import.meta.url), "utf8");
  assert.match(source, /api\.getCampaign\(campaignId\)/);
  assert.match(source, /api\.getCampaignThesisBinding\(campaignId\)/);
  assert.match(source, /api\.getCampaignCurrentThesis\(campaignId\)/);
  assert.match(source, /api\.thesisGet\(nextBinding\.thesis_id\)/);
  assert.match(source, /关注时间范围已从当前投资逻辑预填/);
  assert.doesNotMatch(source, /searchParams.*strategy_horizon/);
  assert.doesNotMatch(source, /expected_horizon.*reviewBy/);
});
