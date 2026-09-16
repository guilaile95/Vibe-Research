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

function finiteNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

/**
 * 计数展示：权威未读取（null / undefined / 非有限数）时返回「未知」。
 * 未知绝不允许渲染成 0 —— 0 是一个已核实的断言，不是默认值。
 */
export function knownCountText(value: unknown): string {
  const known = finiteNumber(value);
  return known === null ? "未知" : String(known);
}

/** 来源健康比例；任一侧未知时整项未知，不宣称「正常」。 */
export function sourceHealthText(
  sources: { healthy?: unknown; total?: unknown } | null | undefined,
): string {
  const healthy = finiteNumber(sources?.healthy);
  const total = finiteNumber(sources?.total);
  if (healthy === null || total === null) return "未知";
  return `${healthy}/${total} 正常`;
}
