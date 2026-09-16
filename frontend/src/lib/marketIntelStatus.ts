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

/**
 * 历史资讯计数。store 自报的 item_count 是直接计数，优先采用；
 * 只有在它有信号表明不可信时才丢弃 items 的 total ——
 * 后端在 store 读取失败时用它自己的错误分支返回 HTTP 200 + 硬编码 total=0
 * （native_intel_router 的 NativeIntelStoreError 分支），那个 0 不是已核实的计数。
 */
export function knownHistoryItemCount(input: {
  store?: { readable?: unknown; item_count?: unknown } | null | undefined;
  items?: { status?: unknown; total?: unknown } | null | undefined;
}): number | null {
  const storeCount = finiteNumber(input.store?.item_count);
  if (storeCount !== null) return storeCount;
  if (input.store?.readable === false) return null;
  if (input.items?.status === "unavailable") return null;
  return finiteNumber(input.items?.total);
}
