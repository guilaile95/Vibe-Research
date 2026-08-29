import assert from "node:assert/strict";
import test from "node:test";
import type { CampaignRecord, DerivedPositionsResult, EvidenceRecord } from "../src/lib/api/types.ts";
import {
  CANDIDATE_CAMPAIGN_STATUSES,
  CANDIDATE_CONFIDENCE_LEVELS,
  buildCandidateEvidenceGap,
  buildCandidateTradeTerms,
  buildCandidateValuationCase,
  candidateWorkspaceHref,
  deriveCandidatePosition,
  selectCandidateCampaigns,
  summarizeCandidateEvidence,
} from "../src/lib/candidateCampaign.ts";

function campaign(overrides: Partial<CampaignRecord> = {}): CampaignRecord {
  return {
    campaign_id: "campaign_a",
    security_code: "600519",
    strategy: "SWING",
    status: "DRAFT",
    created_at: "2026-08-26T00:00:00.000Z",
    ...overrides,
  };
}

test("StockData candidate projection only keeps the active security setup statuses", () => {
  const rows = selectCandidateCampaigns([
    campaign({ campaign_id: "campaign-other", security_code: "000001" }),
    campaign({ campaign_id: "campaign-active", status: "ACTIVE" }),
    campaign({ campaign_id: "campaign-researching", status: "RESEARCHING" }),
    campaign({ campaign_id: "campaign-pre-entry", status: "PRE-ENTRY" }),
    campaign({ campaign_id: "campaign-draft", status: "DRAFT" }),
    campaign({ campaign_id: "campaign-closed", status: "CLOSED" }),
  ], "600519");

  assert.deepEqual(rows.map((row) => row.campaign_id), [
    "campaign-draft",
    "campaign-pre-entry",
    "campaign-researching",
  ]);
  assert.deepEqual(CANDIDATE_CAMPAIGN_STATUSES, ["DRAFT", "RESEARCHING", "PRE-ENTRY"]);
});

test("StockData candidate projection has deterministic created_at then id ordering", () => {
  const rows = [
    campaign({ campaign_id: "campaign-z", created_at: "2026-08-26T00:00:01.000Z" }),
    campaign({ campaign_id: "campaign-b", created_at: "2026-08-26T00:00:00.000Z" }),
    campaign({ campaign_id: "campaign-a", created_at: "2026-08-26T00:00:00.000Z" }),
  ];
  assert.deepEqual(selectCandidateCampaigns(rows, "600519").map((row) => row.campaign_id), [
    "campaign-a",
    "campaign-b",
    "campaign-z",
  ]);
  assert.equal(rows[0].campaign_id, "campaign-z", "projection must not mutate input order");
});

test("StockData candidate projection returns no rows for another security", () => {
  assert.deepEqual(selectCandidateCampaigns([campaign()], "000001"), []);
});

function derived(overrides: Partial<DerivedPositionsResult> = {}): DerivedPositionsResult {
  return {
    derivation_status: "OK",
    bootstrap_status: "BOOTSTRAPPED",
    canonical: true,
    ledger_start: null,
    positions: [],
    data_limitations: [],
    ...overrides,
  };
}

test("Candidate Workspace route preserves the six-digit code", () => {
  assert.equal(candidateWorkspaceHref(" 600519 "), "/candidates/600519");
});

test("candidate position is HELD/NOT_HELD only from canonical bootstrapped ledger", () => {
  assert.equal(deriveCandidatePosition(derived({
    positions: [{ code: "600519", name: "贵州茅台", shares: 100, cost_basis: 1, avg_cost: 1, status: "OPEN", origin: "ledger", cost_known: true }],
  }), "600519").state, "HELD");
  assert.equal(deriveCandidatePosition(derived(), "600519").state, "NOT_HELD");
  assert.equal(deriveCandidatePosition(derived({ bootstrap_status: "NOT_BOOTSTRAPPED" }), "600519").state, "UNKNOWN");
  assert.equal(deriveCandidatePosition(derived({ canonical: false }), "600519").state, "UNKNOWN");
});

test("Evidence gap is an inventory projection and keeps uncovered categories visible", () => {
  const record = (evidence_type: EvidenceRecord["evidence_type"]): EvidenceRecord => ({
    id: evidence_type,
    subject_type: "stock",
    subject_id: "600519",
    evidence_type,
    claim: evidence_type,
    source_title: "fixture",
    source_url: null,
    source_date: "2026-08-01",
    accessed_at: "2026-08-01T00:00:00Z",
    classification: "fact",
    confidence: "medium",
    created_at: "2026-08-01T00:00:00Z",
    updated_at: "2026-08-01T00:00:00Z",
    deleted: 0,
    deleted_at: null,
  });
  const records = [record("financial_filing"), record("news")];
  assert.deepEqual(summarizeCandidateEvidence(records).map(({ key, count, gap }) => ({ key, count, gap })), [
    { key: "FUNDAMENTALS", count: 1, gap: false },
    { key: "CATALYSTS", count: 1, gap: false },
    { key: "EXTERNAL_RESEARCH", count: 0, gap: true },
  ]);
  const gap = buildCandidateEvidenceGap(records);
  assert.deepEqual(gap.classificationCounts, { fact: 2, inference: 0, unknown: 0 });
  assert.equal(gap.highConfidenceFactCount, 0);
  assert.equal(gap.freshness, "NOT_EVALUATED");
  assert.equal(gap.sourceConflict, "UNKNOWN");
  assert.equal(gap.highestImpactQuestion, "哪个核心估值输入仍缺少 high-confidence fact 作为可追溯依据？");
  assert.ok(gap.nextResearchQuestions.some((question) => question.includes("独立研究")));
});

test("PRE-ENTRY builders require complete scenarios and invalidation below entry", () => {
  assert.deepEqual(CANDIDATE_CONFIDENCE_LEVELS, ["HIGH", "MEDIUM", "LOW", "UNKNOWN"]);
  const scenario = buildCandidateValuationCase({
    assumptions: "销量增长, 毛利稳定",
    inputMetric: "EPS",
    inputValue: "8.5",
    inputPeriod: "2026E",
    source: "公司公告",
    dataAt: "2026-08-01",
    priceLow: "1200",
    priceHigh: "1400",
    horizon: "12 个月",
    changeConditions: "EPS 下修",
  });
  assert.deepEqual(scenario, {
    assumptions: ["销量增长", "毛利稳定"],
    inputs: [{ metric: "EPS", value: 8.5, period: "2026E" }],
    source: "公司公告",
    data_at: "2026-08-01",
    price_range: { low: 1200, high: 1400 },
    horizon: "12 个月",
    change_conditions: ["EPS 下修"],
  });
  assert.deepEqual(buildCandidateTradeTerms({ entryLow: "1250", entryHigh: "1300", invalidationPrice: "1180", executionStyle: "SCALE_IN" }), {
    entry_range: { low: 1250, high: 1300 },
    invalidation_price: 1180,
    execution_style: "SCALE_IN",
  });
  assert.equal(buildCandidateTradeTerms({ entryLow: "1250", entryHigh: "1300", invalidationPrice: "1260", executionStyle: "" }), null);
});
