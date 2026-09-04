import type { NativeIntelHotlistItem } from "@/lib/api/types";

export type HotlistFilter = "all" | "rising" | "new" | `source:${string}`;

export interface FormattedRankDelta {
  text: string;
  type: "up" | "down" | "flat" | "new" | "none";
}

export function formatRankDelta(
  rankDelta?: number | null,
  previousRank?: number | null,
  currentState?: NativeIntelHotlistItem["current_state"],
  rank?: number | null,
): FormattedRankDelta {
  // 严格定义“新上榜”：只有当前在榜，且此前没有观测过排名，且当前 rank 存在
  if (currentState === "ON_LIST" && previousRank == null && rank != null) {
    return { text: "新上榜", type: "new" };
  }
  if (rankDelta == null || rankDelta === 0) {
    return { text: "-", type: "flat" };
  }
  if (rankDelta > 0) {
    return { text: `+${rankDelta}`, type: "up" };
  }
  return { text: `${rankDelta}`, type: "down" };
}

export function filterHotlistItems(
  items: NativeIntelHotlistItem[],
  filter: HotlistFilter,
): NativeIntelHotlistItem[] {
  if (filter === "all") return items;
  if (filter === "rising") {
    return items.filter((item) => (item.rank_delta ?? 0) > 0);
  }
  if (filter === "new") {
    return items.filter(
      (item) => item.current_state === "ON_LIST" && item.previous_rank == null && item.rank != null,
    );
  }
  if (filter.startsWith("source:")) {
    const targetSourceId = filter.slice("source:".length);
    return items.filter((item) => item.source_id === targetSourceId);
  }
  return items;
}

export function formatStateBadge(state: NativeIntelHotlistItem["current_state"]): {
  label: string;
  className: string;
} {
  switch (state) {
    case "ON_LIST":
      return { label: "在榜", className: "bg-emerald-500/15 text-emerald-500 border-emerald-500/30" };
    case "OFF_LIST":
      return { label: "已掉榜", className: "bg-muted text-muted-foreground border-border" };
    case "DISABLED":
      return { label: "已停用", className: "bg-muted text-muted-foreground border-border" };
    case "STALE":
      return { label: "已过期", className: "bg-amber-500/15 text-amber-500 border-amber-500/30" };
    case "UNKNOWN":
      return { label: "源失败/未知", className: "bg-amber-500/15 text-amber-500 border-amber-500/30" };
    case "NO_RANK_SEMANTICS":
    default:
      return { label: "无排名", className: "bg-muted text-muted-foreground border-border" };
  }
}

export interface FormattedFilterBadge {
  type: "keyword" | "ai";
  labels: string[];
  className: string;
}

export function formatFilterBadge(
  match?: NativeIntelHotlistItem["filter_match"],
): FormattedFilterBadge | null {
  if (!match) return null;
  if (match.method === "keyword") {
    if (!match.matched_groups || match.matched_groups.length === 0) return null;
    return {
      type: "keyword",
      labels: match.matched_groups,
      className: "bg-cyan-500/15 text-cyan-400 border-cyan-500/30",
    };
  }
  if (match.method === "ai") {
    const pct = Math.round((match.relevance_score ?? 0) * 100);
    return {
      type: "ai",
      labels: [`${match.primary_tag} (${pct}%)`],
      className: "bg-purple-500/15 text-purple-400 border-purple-500/30",
    };
  }
  return null;
}
