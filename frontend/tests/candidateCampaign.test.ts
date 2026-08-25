import assert from "node:assert/strict";
import test from "node:test";
import type { CampaignRecord } from "../src/lib/api/types.ts";
import {
  CANDIDATE_CAMPAIGN_STATUSES,
  selectCandidateCampaigns,
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
