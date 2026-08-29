import { useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import type { MarketCloudEnvelope } from "@/lib/marketCloud";

export type MarketCloudScope = "all" | "cyb" | "star" | "sh" | "sz";
export type MarketCloudPeriod = "today";

interface UseMarketCloudOptions {
  scope: MarketCloudScope;
  period: MarketCloudPeriod;
}

interface UseMarketCloudResult {
  data: MarketCloudEnvelope | null;
  loading: boolean;
  error: string | null;
  reload: () => void;
}

export function useMarketCloud({ scope, period }: UseMarketCloudOptions): UseMarketCloudResult {
  const [data, setData] = useState<MarketCloudEnvelope | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);

    api.marketCloud(scope, period, controller.signal)
      .then((nextData) => {
        if (controller.signal.aborted) return;
        setData(nextData);
        setLoading(false);
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        setError(err instanceof ApiError ? err.message : err instanceof Error ? err.message : String(err));
        setLoading(false);
      });

    return () => controller.abort();
  }, [scope, period, reloadKey]);

  return {
    data,
    loading,
    error,
    reload: () => setReloadKey((k) => k + 1),
  };
}
