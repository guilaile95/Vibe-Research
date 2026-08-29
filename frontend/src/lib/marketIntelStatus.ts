export type MarketIntelOverallStatus = "loading" | "normal" | "partial" | "stale" | "unavailable";
export type MarketIntelNativeStatus = "normal" | "partial" | "stale" | "unavailable";

export function deriveMarketIntelStatus({
  loading,
  hasNativeData,
  hasRadarData,
  nativeStatus,
  nativeError,
  radarError,
  radarFailedSources,
}: {
  loading: boolean;
  hasNativeData: boolean;
  hasRadarData: boolean;
  nativeStatus?: MarketIntelNativeStatus;
  nativeError: string | null;
  radarError: string | null;
  radarFailedSources: number;
}): MarketIntelOverallStatus {
  if (loading && !hasNativeData && !hasRadarData) return "loading";
  if (!hasNativeData && !hasRadarData) return "unavailable";
  if (
    nativeError
    || radarError
    || radarFailedSources > 0
    || nativeStatus === "partial"
    || nativeStatus === "unavailable"
    || !hasNativeData
    || !hasRadarData
  ) return "partial";
  return nativeStatus === "stale" ? "stale" : "normal";
}
