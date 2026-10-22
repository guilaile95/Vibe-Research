import assert from "node:assert/strict";
import test from "node:test";
import { buildDiscoveryResearchOrigin, parseDiscoveryResearchOrigin } from "../src/lib/discoveryResearchOrigin.ts";
import type { DiscoveryOpportunityItem, DiscoverySnapshot } from "../src/lib/recoveredMarketTypes.ts";

const item: DiscoveryOpportunityItem = { security_code: "600519", name: "合成公司", strategy: "SWING", sector: "合成行业", themes: [], discovery_state: "QUEUED", condition_match: "FULL_CONDITIONS", research_priority: "MEDIUM", reason_codes: ["POSITIVE_RETURN_20D"], supporting_observations: [{ code: "RETURN_20D", label: "20日收益", value: 0.12, source_ref: "synthetic:history" }], uncertainties: ["FUNDAMENTAL_FRESHNESS_UNKNOWN"], data_health: "partial", catalyst_status: "PARTIAL", fundamental_status: "PARTIAL", evidence_gate: "PARTIAL", restricted_universe: { status: "UNKNOWN", reason_codes: [], listing_age_status: "UNKNOWN" }, discovered_at: "2026-10-22T02:00:00Z", as_of: "2026-10-21", provenance_refs: ["synthetic:market", "synthetic:announcements"] };
const snapshot: DiscoverySnapshot = { schema_version: "full-market-discovery.v0.1", status: "partial", as_of: "2026-10-21", fetched_at: "2026-10-22T02:01:00Z", last_successful_at: null, refresh_attempted_at: null, market_context: { status: "partial", core_universe_count: 100, sector_count: 1 }, funnel: { core_universe: 100, cheap_scan_passed: 30, qualification_candidates: 24, queue_items: { SHORT: 0, SWING: 1, MEDIUM: 0 }, excluded: 0 }, datasets: [], queues: { SHORT: [], SWING: [item], MEDIUM: [] }, excluded: [], limitations: ["合成目录不包含原文；公告窗口未证明查全"], cache: { hit: false, age_seconds: null } };

test("original discovery basis is a detached bounded non-authoritative snapshot, not URL facts", () => {
  const origin = buildDiscoveryResearchOrigin(item, snapshot, ["财务时效待核"], 123)!;
  assert.equal(origin.scope, "NON_AUTHORITATIVE_CARD_CONTEXT"); assert.equal(origin.securityCode, "600519"); assert.equal(origin.strategy, "SWING");
  assert.deepEqual(origin.observations, [{ code: "RETURN_20D", label: "20日收益", rawValue: "0.12", sourceRef: "synthetic:history" }]);
  assert.deepEqual(origin.sourceNames, item.provenance_refs); assert.deepEqual(origin.reasonCodes, item.reason_codes);
  assert.equal(origin.sourceFetchedAt, snapshot.fetched_at); assert.equal(origin.discoveredAt, item.discovered_at); assert.equal(origin.asOf, item.as_of);
  assert.ok(origin.limitations.includes("财务时效待核")); assert.ok(origin.limitations.includes(snapshot.limitations[0])); assert.equal(origin.truncated, false);
  const parsed = parseDiscoveryResearchOrigin(origin, "600519")!; origin.observations[0].rawValue = "changed";
  assert.equal(parsed.observations[0].rawValue, "0.12");
});
test("missing, cross-stock, unknown shape, oversized fields and invalid dates are rejected rather than fabricated", () => {
  const origin = buildDiscoveryResearchOrigin(item, snapshot, [], 123)!;
  for (const value of [null, {}, { ...origin, securityCode: "000001" }, { ...origin, scope: "VERIFIED_EVIDENCE" }, { ...origin, strategy: "UNKNOWN" }, { ...origin, buy: true }, { ...origin, asOf: "2026-02-30" }, { ...origin, capturedAt: -1 }, { ...origin, sourceFetchedAt: "unknown" }, { ...origin, conditionSummary: "x".repeat(501) }, { ...origin, observations: [{ ...origin.observations[0], rawValue: "x".repeat(1001) }] }]) assert.equal(parseDiscoveryResearchOrigin(value, "600519"), null);
  assert.equal(parseDiscoveryResearchOrigin(origin, "000001"), null);
});
test("bounded snapshots disclose truncation and remain under16KiB without unbounded card objects", () => {
  const large = { ...item, reason_codes: Array(50).fill("中".repeat(200)), supporting_observations: Array(20).fill({ code: "RAW", label: "中".repeat(300), value: "中".repeat(1000), source_ref: "中".repeat(500) }), provenance_refs: Array(50).fill("中".repeat(500)) };
  const origin = buildDiscoveryResearchOrigin(large, snapshot, Array(50).fill("中".repeat(500)), 123)!;
  assert.ok(origin); assert.equal(origin.truncated, true); assert.ok(new TextEncoder().encode(JSON.stringify(origin)).byteLength <= 16 * 1024);
  assert.ok(origin.limitations.some(line => line.includes("非权威")));
  assert.equal(parseDiscoveryResearchOrigin({ ...origin, observations: Array(13).fill({ code: "", label: "", rawValue: "", sourceRef: "" }) }, "600519"), null);
});
