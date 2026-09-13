import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { candidateWorkspaceHref } from "../src/lib/candidateCampaign.ts";
import {
  DISCOVERY_CANDIDATE_ENTRY_LABEL,
  DISCOVERY_HEALTH_FILTER_LABEL,
  DISCOVERY_PRIORITY_FILTER_LABEL,
  DISCOVERY_QUEUE_SCOPE_NOTE,
  DISCOVERY_SECTOR_FILTER_LABEL,
  DISCOVERY_STRATEGY_FILTER_LABEL,
  coverageStatusLabel,
  discoveryFunnelLabel,
  discoverySectors,
  discoveryStrategyLabel,
  discoveryTimeSummary,
  evidenceGateLabel,
  filterDiscoveryItems,
  researchPriorityBadgeLabel,
  researchPriorityLabel,
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

test("Discovery opportunity card labels stay Chinese display-only with unknown enum passthrough", () => {
  assert.equal(researchPriorityLabel("HIGH"), "高");
  assert.equal(researchPriorityLabel("MEDIUM"), "中");
  assert.equal(researchPriorityLabel("LOW"), "低");
  assert.equal(researchPriorityLabel("ALL"), "全部优先级");
  assert.equal(researchPriorityLabel("URGENT"), "URGENT");
  assert.equal(researchPriorityBadgeLabel("HIGH"), "高优先");
  assert.equal(researchPriorityBadgeLabel("MEDIUM"), "中优先");
  assert.equal(researchPriorityBadgeLabel("LOW"), "低优先");
  assert.equal(researchPriorityBadgeLabel("UNKNOWN"), "UNKNOWN");
  assert.doesNotMatch(researchPriorityBadgeLabel("HIGH"), /\bHIGH\b/);
  assert.equal(evidenceGateLabel("SUFFICIENT_FOR_RESEARCH"), "研究证据足够");
  assert.equal(evidenceGateLabel("PARTIAL"), "部分");
  assert.equal(evidenceGateLabel("INSUFFICIENT"), "不足");
  assert.equal(evidenceGateLabel("UNKNOWN"), "未知");
  assert.equal(evidenceGateLabel("ERROR"), "错误");
  assert.equal(evidenceGateLabel("CUSTOM_GATE"), "CUSTOM_GATE");
  assert.equal(coverageStatusLabel("AVAILABLE"), "已有");
  assert.equal(coverageStatusLabel("PARTIAL"), "部分");
  assert.equal(coverageStatusLabel("UNKNOWN"), "未知");
  assert.equal(coverageStatusLabel("ERROR"), "错误");
  assert.equal(coverageStatusLabel("MISSING"), "MISSING");
  assert.equal(discoveryStrategyLabel("SHORT"), "短线");
  assert.equal(discoveryStrategyLabel("MEDIUM"), "中线");
  assert.equal(discoveryStrategyLabel("SWING"), "波段");
  assert.equal(discoveryStrategyLabel("INTRADAY"), "INTRADAY");
  assert.equal(DISCOVERY_STRATEGY_FILTER_LABEL, "发现策略");
  assert.equal(DISCOVERY_SECTOR_FILTER_LABEL, "发现行业");
  assert.equal(DISCOVERY_PRIORITY_FILTER_LABEL, "发现优先级");
  assert.equal(DISCOVERY_HEALTH_FILTER_LABEL, "发现数据状态");
  assert.equal(DISCOVERY_QUEUE_SCOPE_NOTE, "发现队列只回答“先研究谁、为什么”，不会生成交易决定或自动创建 Campaign。");
  for (const label of [
    researchPriorityBadgeLabel("HIGH"),
    evidenceGateLabel("SUFFICIENT_FOR_RESEARCH"),
    coverageStatusLabel("AVAILABLE"),
    discoveryStrategyLabel("SHORT"),
    DISCOVERY_QUEUE_SCOPE_NOTE,
  ]) {
    assert.doesNotMatch(label, /\bBUY\b|\bSELL\b|Opportunity Score|\bHIGH\b/);
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
  assert.match(source, /researchPriorityBadgeLabel/);
  assert.match(source, /evidenceGateLabel/);
  assert.match(source, /coverageStatusLabel/);
  assert.match(source, /data-research-priority=\{item\.research_priority\}/);
  assert.match(source, /data-evidence-gate=\{item\.evidence_gate\}/);
  assert.match(source, /data-fundamental-status=\{item\.fundamental_status\}/);
  assert.match(source, /data-catalyst-status=\{item\.catalyst_status\}/);
  assert.match(source, /DISCOVERY_QUEUE_SCOPE_NOTE/);
  assert.match(source, /DISCOVERY_STRATEGY_FILTER_LABEL/);
  assert.doesNotMatch(source, /\{item\.research_priority\} 优先/);
  assert.doesNotMatch(source, /aria-label="Discovery (?:strategy|sector|priority|health)"/);
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
