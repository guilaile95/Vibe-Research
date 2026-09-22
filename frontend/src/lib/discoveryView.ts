import type {
  DiscoveryOpportunityItem,
  DiscoveryPriority,
  DiscoverySnapshot,
  DiscoveryStrategy,
} from "./recoveredMarketTypes.ts";
import { candidateWorkspaceHref } from "./candidateCampaign.ts";
import { safeInternalReturnTo } from "./internalReturnTo.ts";

export type DiscoveryFilters = {
  strategy: DiscoveryStrategy;
  sector: string;
  priority: "ALL" | DiscoveryPriority;
  restricted: "ALL" | "CLEAR" | "RESTRICTED" | "UNKNOWN";
  health: "ALL" | DiscoveryOpportunityItem["data_health"];
};

export type ScreenerMode = "discovery" | "candidate" | "full-market" | "patterns" | "dragon-tiger";

export function screenerModeFromSearch(search: URLSearchParams): ScreenerMode {
  const mode = search.get("mode");
  return mode === "candidate" || mode === "full-market" || mode === "patterns" || mode === "dragon-tiger"
    ? mode : "discovery";
}

export function discoveryFiltersFromSearch(search: URLSearchParams): DiscoveryFilters {
  const strategy = search.get("strategy");
  const priority = search.get("priority");
  const restricted = search.get("restricted");
  const health = search.get("health");
  return {
    strategy: strategy === "SHORT" || strategy === "MEDIUM" ? strategy : "SWING",
    sector: search.get("sector") || "ALL",
    priority: priority === "HIGH" || priority === "MEDIUM" || priority === "LOW" ? priority : "ALL",
    restricted: restricted === "CLEAR" || restricted === "RESTRICTED" || restricted === "UNKNOWN" ? restricted : "ALL",
    health: health === "normal" || health === "partial" || health === "unknown" || health === "error" ? health : "ALL",
  };
}

export function discoverySearchWithFilters(search: URLSearchParams, patch: Partial<DiscoveryFilters>): URLSearchParams {
  const next = new URLSearchParams(search);
  const filters = { ...discoveryFiltersFromSearch(search), ...patch };
  for (const [key, value] of Object.entries(filters)) next.set(key, value);
  return next;
}

export function discoveryCardAnchor(item: Pick<DiscoveryOpportunityItem, "security_code" | "strategy">): string {
  return `discovery-item-${item.strategy}-${item.security_code}`;
}

/** Navigation context only: observations and authority-bearing facts stay out of the URL. */
export function discoveryCandidateHref(
  item: Pick<DiscoveryOpportunityItem, "security_code" | "strategy">,
  search: URLSearchParams,
): string {
  const returnSearch = discoverySearchWithFilters(search, { strategy: item.strategy });
  returnSearch.set("mode", "discovery");
  const returnTo = safeInternalReturnTo(`/screener?${returnSearch}#${discoveryCardAnchor(item)}`, "/screener");
  return `${candidateWorkspaceHref(item.security_code)}?${new URLSearchParams({
    source: "discovery", strategy: item.strategy, return_to: returnTo,
  })}`;
}

/** Surface the supplied strategy observation, then at most two more; never invent an explanation. */
export function discoverySummaryObservations(item: DiscoveryOpportunityItem) {
  const primaryCodes = item.strategy === "SHORT" ? ["POSITIVE_SESSION_MOMENTUM", "CHANGE_PCT"]
    : item.strategy === "SWING" ? ["POSITIVE_RETURN_20D", "RETURN_20D"]
      : ["POSITIVE_RETURN_60D", "RETURN_60D"];
  const primary = item.supporting_observations.find((observation) => primaryCodes.includes(observation.code.toUpperCase()));
  return (primary
    ? [primary, ...item.supporting_observations.filter((observation) => observation !== primary)]
    : item.supporting_observations).slice(0, 3);
}

export function filterDiscoveryItems(snapshot: DiscoverySnapshot, filters: DiscoveryFilters) {
  return (snapshot.queues[filters.strategy] || []).filter((item) => (
    (filters.sector === "ALL" || item.sector === filters.sector || item.themes.includes(filters.sector))
    && (filters.priority === "ALL" || item.research_priority === filters.priority)
    && (filters.restricted === "ALL" || item.restricted_universe.status === filters.restricted)
    && (filters.health === "ALL" || item.data_health === filters.health)
  ));
}

export function discoverySectors(snapshot: DiscoverySnapshot): string[] {
  return Array.from(new Set(
    Object.values(snapshot.queues)
      .flat()
      .flatMap((item) => [item.sector, ...item.themes])
      .filter((value): value is string => Boolean(value)),
  )).sort((left, right) => left.localeCompare(right, "zh-CN"));
}

export function statusLabel(status: string): string {
  return ({
    normal: "可用",
    partial: "部分可用",
    stale: "历史结果",
    unavailable: "不可用",
    error: "错误",
    unknown: "未知",
  } as Record<string, string>)[status] || status;
}

export function displayDiscoveryTime(value: string | null | undefined): string {
  if (!value) return "未知";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date).replace(/\//g, "-");
}

export function discoveryTimeSummary(
  snapshot: Pick<DiscoverySnapshot, "as_of" | "status" | "fetched_at" | "last_successful_at" | "refresh_attempted_at" | "cache">,
): string {
  const marketDate = snapshot.as_of ?? "未知";
  if (snapshot.status === "stale" || snapshot.cache.refresh_failed) {
    const lastSuccessful = snapshot.last_successful_at
      ? displayDiscoveryTime(snapshot.last_successful_at)
      : "未知";
    const failedAttempt = snapshot.refresh_attempted_at
      ? ` · 刷新失败于 ${displayDiscoveryTime(snapshot.refresh_attempted_at)}`
      : "";
    return `行情归属 ${marketDate} · 最后成功更新于 ${lastSuccessful}${failedAttempt}`;
  }
  return `行情归属 ${marketDate} · 抓取于 ${displayDiscoveryTime(snapshot.fetched_at)}`;
}
