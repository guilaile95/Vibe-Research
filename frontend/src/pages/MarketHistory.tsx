import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { NorthboundTurnoverHistoryChart } from "@/components/market/NorthboundTurnoverHistoryChart";
import { PageHeader } from "@/components/ui/PageHeader";
import { recoveredMarketApi } from "@/lib/recoveredMarketApi";
import type { NorthboundHistoryEnvelope } from "@/lib/recoveredMarketTypes";

export function MarketHistory() {
  const [env, setEnv] = useState<NorthboundHistoryEnvelope | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setLoading(true);
    recoveredMarketApi.marketNorthboundHistory(20)
      .then((value) => {
        if (!active) return;
        setEnv(value);
        setError(null);
      })
      .catch(() => {
        if (!active) return;
        setError("北向成交历史暂不可用");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  return (
    <div className="space-y-5">
      <PageHeader title="市场历史" subtitle="恢复的北向成交额历史研究视图。" />
      <div className="text-xs text-muted-foreground">
        <Link to="/daily-review" className="hover:text-foreground">返回今天</Link>
        <span className="mx-2">·</span>
        <Link to="/screener" className="hover:text-foreground">信号筛选</Link>
      </div>
      <NorthboundTurnoverHistoryChart env={env} loading={loading} error={error} />
    </div>
  );
}
