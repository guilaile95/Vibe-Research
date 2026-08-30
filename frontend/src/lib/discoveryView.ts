import type {
  DiscoveryOpportunityItem,
  DiscoveryPriority,
  DiscoverySnapshot,
  DiscoveryStrategy,
} from "./recoveredMarketTypes.ts";

export type DiscoveryFilters = {
  strategy: DiscoveryStrategy;
  sector: string;
  priority: "ALL" | DiscoveryPriority;
  restricted: "ALL" | "CLEAR" | "RESTRICTED" | "UNKNOWN";
  health: "ALL" | DiscoveryOpportunityItem["data_health"];
};

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
