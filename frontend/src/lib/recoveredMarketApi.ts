import { get, request } from "./api.ts";
import type {
  NorthboundHistoryEnvelope,
  ScreenerEvaluateIn,
  ScreenerEvaluateResult,
  ScreenerSectorRepresentativesResult,
  FullMarketQuery,
  FullMarketResult,
  PatternQuery,
  PatternResult,
  DiscoverySnapshot,
  DragonTigerDiscovery,
} from "./recoveredMarketTypes.ts";

export const recoveredMarketApi = {
  marketNorthboundHistory: (days: 10 | 20 | 30 = 20) =>
    get<NorthboundHistoryEnvelope>(`/market/northbound/history?days=${days}`),

  evaluateScreener: (payload: ScreenerEvaluateIn, signal?: AbortSignal) =>
    request<ScreenerEvaluateResult>("/screener/evaluate", "POST", payload, {
      signal,
      unwrapData: false,
    }),

  getScreenerSectorRepresentatives: (signal?: AbortSignal) =>
    get<ScreenerSectorRepresentativesResult>("/screener/sources/sector-representatives", {
      signal,
      unwrapData: false,
    }),

  getFullMarket: (query: FullMarketQuery = {}, signal?: AbortSignal) => {
    const params = new URLSearchParams();
    if (query.as_of) params.set("as_of", query.as_of);
    if (query.latest != null) params.set("latest", String(query.latest));
    if (query.filters != null) params.set("filters", JSON.stringify(query.filters));
    if (query.filter_metric) params.set("filter_metric", query.filter_metric);
    if (query.filter_operator) params.set("filter_operator", query.filter_operator);
    if (query.filter_value != null) params.set("filter_value", String(query.filter_value));
    if (query.sort_by) params.set("sort_by", query.sort_by);
    if (query.sort_order) params.set("sort_order", query.sort_order);
    if (query.limit != null) params.set("limit", String(query.limit));
    if (query.offset != null) params.set("offset", String(query.offset));
    const qs = params.toString();
    return get<FullMarketResult>(`/screener/full-market${qs ? `?${qs}` : ""}`, {
      signal,
      unwrapData: false,
    });
  },

  getPatterns: (query: PatternQuery = {}, signal?: AbortSignal) => {
    const params = new URLSearchParams();
    if (query.as_of) params.set("as_of", query.as_of);
    if (query.latest != null) params.set("latest", String(query.latest));
    if (query.event_type) params.set("event_type", query.event_type);
    if (query.limit != null) params.set("limit", String(query.limit));
    if (query.offset != null) params.set("offset", String(query.offset));
    const qs = params.toString();
    return get<PatternResult>(`/research-data/patterns${qs ? `?${qs}` : ""}`, {
      signal,
      unwrapData: false,
    });
  },

  getDiscovery: (refresh = false, signal?: AbortSignal) =>
    get<DiscoverySnapshot>(`/screener/discovery?refresh=${refresh ? "true" : "false"}`, {
      signal,
      unwrapData: false,
    }),

  getDragonTigerDiscovery: (tradeDate?: string, signal?: AbortSignal) => {
    const qs = tradeDate ? `?trade_date=${encodeURIComponent(tradeDate)}` : "";
    return get<DragonTigerDiscovery>(`/market/dragon-tiger${qs}`, { signal });
  },
};
