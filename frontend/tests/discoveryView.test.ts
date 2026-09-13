import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { candidateWorkspaceHref } from "../src/lib/candidateCampaign.ts";
import {
  DISCOVERY_CANDIDATE_ENTRY_LABEL,
  discoveryFunnelLabel,
  discoverySectors,
  discoveryTimeSummary,
  filterDiscoveryItems,
  restrictedStatusLabel,
  type DiscoveryFilters,
} from "../src/lib/discoveryView.ts";
import type {
  DiscoveryOpportunityItem,
  DiscoverySnapshot,
  DiscoveryStrategy,
} from "../src/lib/recoveredMarketTypes.ts";

function opportunity(
  code: string,
  strategy: DiscoveryStrategy,
  overrides: Partial<DiscoveryOpportunityItem> = {},
): DiscoveryOpportunityItem {
  return {
    security_code: code,
    name: `证券${code}`,
    strategy,
    sector: "半导体",
    themes: ["AI"],
    discovery_state: "QUEUED",
    research_priority: "MEDIUM",
    reason_codes: ["MARKET_RELATIVE_STRENGTH"],
    supporting_observations: [],
    uncertainties: [],
    data_health: "normal",
    catalyst_status: "AVAILABLE",
    fundamental_status: "AVAILABLE",
    evidence_gate: "SUFFICIENT_FOR_RESEARCH",
    restricted_universe: {
      status: "CLEAR",
      reason_codes: [],
      listing_age_status: "KNOWN",
    },
    discovered_at: "2026-08-30T03:00:00Z",
    as_of: "2026-08-28",
    provenance_refs: ["eastmoney:spot"],
    ...overrides,
  };
}

const short = opportunity("600001", "SHORT", { research_priority: "HIGH" });
const swingA = opportunity("600003", "SWING", { sector: "银行", themes: ["红利"] });
const swingB = opportunity("600002", "SWING", {
  data_health: "unknown",
  catalyst_status: "UNKNOWN",
  fundamental_status: "UNKNOWN",
  evidence_gate: "UNKNOWN",
  restricted_universe: {
    status: "UNKNOWN",
    reason_codes: ["LISTING_AGE_UNKNOWN"],
    listing_age_status: "UNKNOWN",
  },
});
const medium = opportunity("600004", "MEDIUM", { sector: "医药", themes: ["创新药"] });

const snapshot: DiscoverySnapshot = {
  schema_version: "full-market-discovery.v0.1",
  status: "partial",
  as_of: "2026-08-28",
  fetched_at: "2026-08-30T03:00:00Z",
  last_successful_at: null,
  refresh_attempted_at: "2026-08-30T03:00:00Z",
  market_context: { status: "partial", core_universe_count: 4, sector_count: 3 },
  funnel: {
    core_universe: 4,
    cheap_scan_passed: 4,
    qualification_candidates: 4,
    queue_items: { SHORT: 1, SWING: 2, MEDIUM: 1 },
    excluded: 0,
  },
  datasets: [],
  queues: { SHORT: [short], SWING: [swingA, swingB], MEDIUM: [medium] },
  excluded: [],
  limitations: [],
  cache: { hit: false, age_seconds: null },
};

const filters = (strategy: DiscoveryStrategy, overrides: Partial<DiscoveryFilters> = {}): DiscoveryFilters => ({
  strategy,
  sector: "ALL",
  priority: "ALL",
  restricted: "ALL",
  health: "ALL",
  ...overrides,
});

test("Discovery keeps SHORT, SWING, and MEDIUM queues separate and preserves backend order", () => {
  assert.deepEqual(filterDiscoveryItems(snapshot, filters("SHORT")).map((row) => row.security_code), ["600001"]);
  assert.deepEqual(filterDiscoveryItems(snapshot, filters("SWING")).map((row) => row.security_code), ["600003", "600002"]);
  assert.deepEqual(filterDiscoveryItems(snapshot, filters("MEDIUM")).map((row) => row.security_code), ["600004"]);
});

test("Discovery filters sector/theme, priority, restricted status, and health without inventing UNKNOWN facts", () => {
  assert.deepEqual(filterDiscoveryItems(snapshot, filters("SWING", { sector: "红利" })).map((row) => row.security_code), ["600003"]);
  assert.deepEqual(filterDiscoveryItems(snapshot, filters("SHORT", { priority: "HIGH" })).map((row) => row.security_code), ["600001"]);
  assert.deepEqual(filterDiscoveryItems(snapshot, filters("SHORT", { restricted: "CLEAR" })).map((row) => row.security_code), ["600001"]);
  assert.deepEqual(filterDiscoveryItems(snapshot, filters("SWING", { restricted: "UNKNOWN" })).map((row) => row.security_code), ["600002"]);

  const unknown = filterDiscoveryItems(snapshot, filters("SWING", { health: "unknown" }));
  assert.equal(unknown.length, 1);
  assert.equal(unknown[0].security_code, "600002");
  assert.equal(unknown[0].evidence_gate, "UNKNOWN");
  assert.equal(unknown[0].fundamental_status, "UNKNOWN");
  assert.equal(unknown[0].restricted_universe.status, "UNKNOWN");
  const sectors = discoverySectors(snapshot);
  assert.deepEqual(new Set(sectors), new Set(["AI", "创新药", "医药", "半导体", "红利", "银行"]));
  assert.deepEqual(sectors, [...sectors].sort((left, right) => left.localeCompare(right, "zh-CN")));
});

test("Discovery restricted and funnel labels stay Chinese display-only with unknown enum passthrough", () => {
  assert.equal(restrictedStatusLabel("RESTRICTED"), "受限研究");
  assert.equal(restrictedStatusLabel("CLEAR"), "普通");
  assert.equal(restrictedStatusLabel("UNKNOWN"), "资格未知");
  assert.equal(restrictedStatusLabel("ALL"), "全部资格");
  assert.equal(restrictedStatusLabel("RESTRICTED_RESEARCH_ONLY"), "RESTRICTED_RESEARCH_ONLY");
  assert.equal(restrictedStatusLabel("CUSTOM_STATUS"), "CUSTOM_STATUS");
  assert.equal(discoveryFunnelLabel("core_universe"), "核心池");
  assert.equal(discoveryFunnelLabel("cheap_scan_passed"), "Stage 1 通过");
  assert.equal(discoveryFunnelLabel("qualification_candidates"), "Stage 3 资格检查");
  assert.equal(discoveryFunnelLabel("sector_coverage"), "行业覆盖");
  assert.equal(discoveryFunnelLabel("excluded"), "排除 / 拦截");
  assert.equal(discoveryFunnelLabel("UNEXPECTED_BUCKET"), "UNEXPECTED_BUCKET");
  assert.equal(DISCOVERY_CANDIDATE_ENTRY_LABEL, "进入候选研究");
  for (const label of [
    restrictedStatusLabel("RESTRICTED"),
    discoveryFunnelLabel("core_universe"),
    DISCOVERY_CANDIDATE_ENTRY_LABEL,
  ]) {
    assert.doesNotMatch(label, /\bBUY\b|\bSELL\b|Opportunity Score/);
  }
});

test("Discovery only links into Candidate Research and exposes no BUY or hidden score contract", () => {
  assert.equal(candidateWorkspaceHref(swingA.security_code), "/candidates/600003");

  const source = readFileSync(
    new URL("../src/components/discovery/DiscoveryWorkspace.tsx", import.meta.url),
    "utf8",
  );
  assert.match(source, /candidateWorkspaceHref\(item\.security_code\)/);
  assert.match(source, /restrictedStatusLabel/);
  assert.match(source, /discoveryFunnelLabel/);
  assert.match(source, /DISCOVERY_CANDIDATE_ENTRY_LABEL/);
  assert.doesNotMatch(source, /\/api\/campaigns|\b(?:score|ranking|BUY NOW|BUY SMALL|SCALE IN)\b/i);
});

test("Discovery stale summary preserves the last successful timestamp", () => {
  assert.equal(
    discoveryTimeSummary({
      ...snapshot,
      status: "stale",
      fetched_at: "2026-08-30T02:00:00Z",
      last_successful_at: "2026-08-30T02:00:00Z",
      refresh_attempted_at: "2026-08-30T04:00:00Z",
      cache: { hit: true, age_seconds: null, refresh_failed: true },
    }),
    "行情归属 2026-08-28 · 最后成功更新于 2026-08-30 10:00 · 刷新失败于 2026-08-30 12:00",
  );
});
