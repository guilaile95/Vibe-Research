import type { DiscoveryOpportunityItem, DiscoverySnapshot, DiscoveryStrategy } from "./recoveredMarketTypes.ts";
import { discoveryConditionLabel, discoveryCoverageSummary } from "./discoveryView.ts";

/** A bounded browser navigation snapshot, never evidence or an authoritative ranking. */
export interface DiscoveryResearchOrigin {
  schemaVersion: "discovery-card.v1";
  scope: "NON_AUTHORITATIVE_CARD_CONTEXT";
  securityCode: string;
  securityName: string;
  strategy: DiscoveryStrategy;
  capturedAt: number;
  sourceFetchedAt: string | null;
  discoveredAt: string | null;
  asOf: string | null;
  conditionSummary: string;
  observations: { code: string; label: string; rawValue: string; sourceRef: string }[];
  reasonCodes: string[];
  sourceNames: string[];
  limitations: string[];
  truncated: boolean;
}
const MAX_BYTES = 16 * 1024;
const object = (value: unknown): value is Record<string, unknown> => Boolean(value) && typeof value === "object" && !Array.isArray(value);
const exactKeys = (value: Record<string, unknown>, keys: string[]) => Object.keys(value).length === keys.length && Object.keys(value).every(key => keys.includes(key));
const text = (value: unknown, max = 500): value is string => typeof value === "string" && value.length <= max && !/[\u0000-\u0008\u000b\u000c\u000e-\u001f]/.test(value);
const strings = (value: unknown, count: number, max = 500): value is string[] => Array.isArray(value) && value.length <= count && value.every(item => text(item, max));
const timestamp = (value: unknown): boolean => value === null || (text(value, 64) && /^\d{4}-\d{2}-\d{2}T/.test(value) && Number.isFinite(Date.parse(value)));
const day = (value: unknown): boolean => value === null || (text(value, 10) && /^\d{4}-\d{2}-\d{2}$/.test(value) && Number.isFinite(Date.parse(value)) && new Date(`${value}T00:00:00Z`).toISOString().slice(0, 10) === value);

export function parseDiscoveryResearchOrigin(value: unknown, expectedCode: string): DiscoveryResearchOrigin | null {
  if (!object(value) || !/^\d{6}$/.test(expectedCode) || !exactKeys(value, ["schemaVersion", "scope", "securityCode", "securityName", "strategy", "capturedAt", "sourceFetchedAt", "discoveredAt", "asOf", "conditionSummary", "observations", "reasonCodes", "sourceNames", "limitations", "truncated"])) return null;
  if (value.schemaVersion !== "discovery-card.v1" || value.scope !== "NON_AUTHORITATIVE_CARD_CONTEXT" || value.securityCode !== expectedCode
    || !text(value.securityName, 200) || typeof value.strategy !== "string" || !["SHORT", "SWING", "MEDIUM"].includes(value.strategy)
    || typeof value.capturedAt !== "number" || !Number.isSafeInteger(value.capturedAt) || value.capturedAt < 0
    || !timestamp(value.sourceFetchedAt) || !timestamp(value.discoveredAt) || !day(value.asOf) || !text(value.conditionSummary)
    || !strings(value.reasonCodes, 24, 200) || !strings(value.sourceNames, 24) || !strings(value.limitations, 24)
    || typeof value.truncated !== "boolean" || !Array.isArray(value.observations) || value.observations.length > 12
    || value.observations.some(item => !object(item) || !exactKeys(item, ["code", "label", "rawValue", "sourceRef"]) || !text(item.code, 200) || !text(item.label, 300) || !text(item.rawValue, 1000) || !text(item.sourceRef, 500))) return null;
  try {
    const serialized = JSON.stringify(value);
    if (new TextEncoder().encode(serialized).byteLength > MAX_BYTES) return null;
    // Detach from mutable router state; this is a snapshot, not a shared authority object.
    return JSON.parse(serialized) as DiscoveryResearchOrigin;
  } catch { return null; }
}

export function buildDiscoveryResearchOrigin(item: DiscoveryOpportunityItem, snapshot: DiscoverySnapshot, cardLimitations: string[], capturedAt = Date.now()): DiscoveryResearchOrigin | null {
  let truncated = false;
  const clipped = (value: unknown, max: number): string => { const raw = String(value ?? ""); if (raw.length > max) truncated = true; return raw.slice(0, max); };
  const list = (items: string[], count: number, max: number): string[] => { if (items.length > count) truncated = true; return items.slice(0, count).map(value => clipped(value, max)); };
  if (item.supporting_observations.length > 12) truncated = true;
  const result: DiscoveryResearchOrigin = {
    schemaVersion: "discovery-card.v1", scope: "NON_AUTHORITATIVE_CARD_CONTEXT", securityCode: item.security_code,
    securityName: clipped(item.name, 200), strategy: item.strategy, capturedAt,
    sourceFetchedAt: timestamp(snapshot.fetched_at) ? snapshot.fetched_at : null,
    discoveredAt: timestamp(item.discovered_at) ? item.discovered_at : null,
    asOf: day(item.as_of) ? item.as_of : null, conditionSummary: clipped(discoveryConditionLabel(item), 500),
    observations: item.supporting_observations.slice(0, 12).map(observation => ({ code: clipped(observation.code, 200), label: clipped(observation.label, 300), rawValue: clipped(JSON.stringify(observation.value) ?? "null", 1000), sourceRef: clipped(observation.source_ref, 500) })),
    reasonCodes: list(item.reason_codes, 24, 200), sourceNames: list(item.provenance_refs, 24, 500),
    limitations: list([...new Set(["仅为当时发现卡片的非权威浏览快照，不证明来源全文已读、研究价值或交易结论。", discoveryCoverageSummary(snapshot, item.strategy), "行业筛选只作用于已返回队列，不代表重新扫描全行业。", ...cardLimitations, ...snapshot.limitations])], 24, 500),
    truncated: false,
  };
  result.truncated = truncated;
  while (new TextEncoder().encode(JSON.stringify(result)).byteLength > MAX_BYTES) {
    result.truncated = true;
    if (result.observations.length) result.observations.pop();
    else if (result.sourceNames.length) result.sourceNames.pop();
    else if (result.reasonCodes.length) result.reasonCodes.pop();
    else if (result.limitations.length > 3) result.limitations.pop();
    else return null;
  }
  return parseDiscoveryResearchOrigin(result, item.security_code);
}
