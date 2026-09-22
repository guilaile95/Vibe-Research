import type { NativeIntelItem } from "./api/types.ts";

// Exact source hints declared in news_sources.json. `macro` also contains
// general/social hotlists, so it is not evidence of research relevance.
const INDUSTRY_SOURCE_HINTS = new Set([
  "ai", "semi", "robot", "auto", "energy", "bio", "space",
  "security", "tech", "consumer", "science",
]);

/** Keep the API's order. Deduplicate known article URLs, never infer a shared event from titles. */
export function selectResearchSourceItems(items: readonly NativeIntelItem[]): NativeIntelItem[] {
  const seen = new Set<string>();
  return items.filter((item) => {
    if (!INDUSTRY_SOURCE_HINTS.has(item.hint)) return false;
    let key = "";
    try {
      const url = new URL(item.canonical_url || item.url);
      if (url.protocol === "https:" || url.protocol === "http:") {
        url.hash = "";
        key = url.href;
      }
    } catch { /* An unknown URL is not proof of duplication. */ }
    if (key && seen.has(key)) return false;
    if (key) seen.add(key);
    return true;
  }).slice(0, 4);
}
