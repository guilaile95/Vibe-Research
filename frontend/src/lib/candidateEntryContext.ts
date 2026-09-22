import type { DiscoveryStrategy } from "./recoveredMarketTypes.ts";
import { safeInternalReturnTo } from "./internalReturnTo.ts";

/** Validated navigation context only; URL parameters never establish research evidence. */
export function candidateEntryContext(search: URLSearchParams): {
  returnTo: string;
  discoveryStrategy: DiscoveryStrategy | null;
} {
  const returnTo = safeInternalReturnTo(search.get("return_to"), "");
  const generic = { returnTo, discoveryStrategy: null };
  const strategy = search.get("strategy");
  if (
    search.get("source") !== "discovery"
    || !returnTo
    || (strategy !== "SHORT" && strategy !== "SWING" && strategy !== "MEDIUM")
    || ["source", "strategy", "return_to"].some((key) => search.getAll(key).length !== 1)
  ) return generic;

  const target = new URL(returnTo, "http://localhost");
  const mode = target.searchParams.get("mode");
  const queue = target.searchParams.get("strategy") ?? "SWING";
  if (
    target.pathname !== "/screener"
    || (mode !== null && mode !== "discovery")
    || queue !== strategy
    || ["mode", "strategy"].some((key) => target.searchParams.getAll(key).length > 1)
  ) return generic;

  return { returnTo, discoveryStrategy: strategy };
}
