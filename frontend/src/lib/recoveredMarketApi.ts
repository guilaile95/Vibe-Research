import { get, request } from "@/lib/api";
import type {
  NorthboundHistoryEnvelope,
  ScreenerEvaluateIn,
  ScreenerEvaluateResult,
  ScreenerSectorRepresentativesResult,
} from "@/lib/recoveredMarketTypes";

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
};
