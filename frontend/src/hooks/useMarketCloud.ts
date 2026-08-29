import { useEffect, useState } from "react";
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
    let cancelled = false;
    setLoading(true);
    setError(null);

    const url = `/api/market/cloud?scope=${encodeURIComponent(scope)}&period=${encodeURIComponent(period)}`;

    fetch(url)
      .then(async (res) => {
        if (!res.ok) {
          throw new Error(`HTTP ${res.status}`);
        }
        const json = await res.json();
        if (cancelled) return;
        setData(json.data as MarketCloudEnvelope);
        setLoading(false);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : String(err));
        setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [scope, period, reloadKey]);

  return {
    data,
    loading,
    error,
    reload: () => setReloadKey((k) => k + 1),
  };
}
