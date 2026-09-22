import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { candidateWorkspaceHref } from "../src/lib/candidateCampaign.ts";
import {
  discoverySectors,
  discoveryCandidateHref,
  discoveryCardAnchor,
  discoveryFiltersFromSearch,
  discoverySearchWithFilters,
  discoverySummaryObservations,
  discoveryTimeSummary,
  filterDiscoveryItems,
  screenerModeFromSearch,
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

test("Discovery only links into Candidate Research and exposes no BUY or hidden score contract", () => {
  assert.equal(candidateWorkspaceHref(swingA.security_code), "/candidates/600003");

  const source = readFileSync(
    new URL("../src/components/discovery/DiscoveryWorkspace.tsx", import.meta.url),
    "utf8",
  );
  assert.match(source, /discoveryCandidateHref\(item, searchParams\)/);
  assert.doesNotMatch(source, /\/api\/campaigns|\b(?:score|ranking|BUY NOW|BUY SMALL|SCALE IN)\b/i);
});

test("Discovery query restores every filter and validates enum values without dropping an absent sector", () => {
  const search = new URLSearchParams({ strategy: "MEDIUM", sector: "消费 & 医药", priority: "LOW", restricted: "RESTRICTED", health: "unknown" });
  assert.deepEqual(discoveryFiltersFromSearch(search), filters("MEDIUM", {
    sector: "消费 & 医药", priority: "LOW", restricted: "RESTRICTED", health: "unknown",
  }));
  assert.deepEqual(discoveryFiltersFromSearch(new URLSearchParams("strategy=bad&priority=bad&restricted=bad&health=bad")), filters("SWING"));
  assert.deepEqual(discoveryFiltersFromSearch(new URLSearchParams()), filters("SWING"));
});

test("Discovery query updates keep all other conditions and Screener mode across URL round trips", () => {
  const initial = new URLSearchParams("mode=full-market&strategy=SHORT&sector=银行&priority=HIGH&restricted=CLEAR&health=normal&view=compact");
  const next = discoverySearchWithFilters(initial, { priority: "LOW" });
  assert.equal(initial.get("priority"), "HIGH", "do not mutate router state");
  assert.equal(next.get("mode"), "full-market");
  assert.equal(next.get("view"), "compact");
  assert.deepEqual(discoveryFiltersFromSearch(new URLSearchParams(next.toString())), filters("SHORT", {
    sector: "银行", priority: "LOW", restricted: "CLEAR", health: "normal",
  }));
  for (const mode of ["discovery", "candidate", "full-market", "patterns", "dragon-tiger"] as const) {
    next.set("mode", mode);
    assert.equal(screenerModeFromSearch(next), mode);
    assert.equal(discoveryFiltersFromSearch(next).priority, "LOW");
  }
  assert.equal(screenerModeFromSearch(new URLSearchParams("mode=https://example.org")), "discovery");
});

test("Discovery candidate context carries only source, strategy and a same-origin return to the exact card", () => {
  const search = new URLSearchParams("strategy=SWING&sector=红利&priority=MEDIUM&restricted=ALL&health=ALL");
  const candidate = new URL(discoveryCandidateHref(swingA, search), "http://localhost");
  assert.equal(candidate.pathname, "/candidates/600003");
  assert.deepEqual([...candidate.searchParams.keys()].sort(), ["return_to", "source", "strategy"]);
  assert.equal(candidate.searchParams.get("source"), "discovery");
  assert.equal(candidate.searchParams.get("strategy"), "SWING");
  const returnTo = new URL(candidate.searchParams.get("return_to")!, candidate.origin);
  assert.equal(returnTo.origin, candidate.origin);
  assert.equal(returnTo.pathname, "/screener");
  assert.equal(returnTo.hash, `#${discoveryCardAnchor(swingA)}`);
  assert.equal(returnTo.searchParams.get("mode"), "discovery");
  assert.deepEqual(discoveryFiltersFromSearch(returnTo.searchParams), discoveryFiltersFromSearch(search));
  const suspiciousSector = new URLSearchParams({ sector: "//outside.example/?x=1#fragment", return_to: "https://outside.example" });
  const bounded = new URL(discoveryCandidateHref(swingA, suspiciousSector), candidate.origin);
  assert.equal(new URL(bounded.searchParams.get("return_to")!, candidate.origin).pathname, "/screener");
});

test("Discovery summary selects actual observations without changing source values or queue order", () => {
  const observations = [
    { code: "LIQUIDITY_AT_OR_ABOVE_MARKET_MEDIAN", label: "成交额", value: 1e8, source_ref: "market" },
    { code: "POSITIVE_RETURN_20D", label: "20 日收益", value: 0.12, source_ref: "rdp" },
    { code: "SECTOR_SUPPORTIVE", label: "行业", value: 1.2, source_ref: "market" },
    { code: "CATALYST_CLUE_AVAILABLE", label: "公告", value: { announcement_count: 2 }, source_ref: "announcements" },
  ];
  const item = opportunity("600003", "SWING", { supporting_observations: observations });
  assert.deepEqual(discoverySummaryObservations(item), [observations[1], observations[0], observations[2]]);
  assert.equal(item.supporting_observations[0], observations[0]);
  assert.equal(discoverySummaryObservations(item)[0].value, 0.12);
  assert.deepEqual(discoverySummaryObservations(swingA), []);
  assert.deepEqual(discoverySummaryObservations({ ...item, supporting_observations: [observations[3]] }), [observations[3]]);
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
