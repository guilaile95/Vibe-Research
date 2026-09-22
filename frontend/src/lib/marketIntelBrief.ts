import type { NativeIntelItem } from "./api/types.ts";

// Exact source hints declared in news_sources.json. `macro` also contains
// general/social hotlists, so it is not evidence of research relevance.
const INDUSTRY_SOURCE_HINTS = new Set([
  "ai", "semi", "robot", "auto", "energy", "bio", "space",
  "security", "tech", "consumer", "science",
]);

/** Keep the API's order; source classification is not article-level relevance. */
export function selectResearchSourceItems(items: readonly NativeIntelItem[]): NativeIntelItem[] {
  return items.filter((item) => INDUSTRY_SOURCE_HINTS.has(item.hint)).slice(0, 4);
}
