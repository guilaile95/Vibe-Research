import React, { useState, useEffect, useCallback } from "react";
import { BarChart3, Loader2, AlertCircle, TrendingUp, Target } from "lucide-react";
import { api } from "@/lib/api";
import type { AdoptionSummary, OutcomeSummary, StockAnalyticsItem } from "@/lib/api/types";
import { FormalOutcomeSection } from "@/components/outcome/FormalOutcomeSection";

const DecisionPerformance: React.FC = () => {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [adoptionSummary, setAdoptionSummary] = useState<AdoptionSummary | null>(null);
  const [outcomeSummary, setOutcomeSummary] = useState<OutcomeSummary | null>(null);
  const [stocks, setStocks] = useState<StockAnalyticsItem[]>([]);
  const [dateFrom, setDateFrom] = useState<string>("");
  const [dateTo, setDateTo] = useState<string>("");

  const fetchAll = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [adop, outc, stk] = await Promise.all([
        api.getAdoptionSummary({ date_from: dateFrom, date_to: dateTo }),
        api.getOutcomeSummary({ adoption_status: undefined, date_from: dateFrom, date_to: dateTo }),
        api.getStockAnalytics({ date_from: dateFrom, date_to: dateTo, limit: 20 }),
      ]);
      setAdoptionSummary(adop);
      setOutcomeSummary(outc);
      setStocks(stk);
    } catch (err: any) {
      setError(err?.message || "加载数据失败");
    } finally {
      setLoading(false);
    }
  }, [dateFrom, dateTo]);

  useEffect(() => {
    fetchAll();
  }, [fetchAll]);

  const handleRefresh = () => {
    fetchAll();
  };

  const formatRate = (rate: number | null | undefined) => {
    if (rate === null || rate === undefined) return "—";
    return `${(rate * 100).toFixed(1)}%`;
  };

  const barWidth = (count: number, total: number) =>
    total > 0 ? `${(count / total) * 100}%` : "0%";

  const adoptionRate = adoptionSummary?.adoption_rate;
  const outcomePositiveRate = outcomeSummary?.positive_rate;

  return (
    <div className="space-y-8">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">决策绩效</h1>
          <p className="text-muted-foreground">基于历史决策反馈的采纳率与结果分布</p>
        </div>
        <div className="flex gap-3">
          <input
            type="date"
            value={dateFrom}
            onChange={(e) => setDateFrom(e.target.value)}
            className="bg-background border border-input rounded-md px-3 py-2 text-sm"
          />
          <input
            type="date"
            value={dateTo}
            onChange={(e) => setDateTo(e.target.value)}
            className="bg-background border border-input rounded-md px-3 py-2 text-sm"
          />
          <button
            onClick={handleRefresh}
            disabled={loading}
            className="px-4 py-2 bg-primary text-primary-foreground rounded-md hover:bg-primary/90 disabled:opacity-50 flex items-center gap-2"
          >
            {loading ? <Loader2 className="animate-spin" /> : <TrendingUp className="h-4 w-4" />}
            刷新
          </button>
        </div>
      </div>

      {error && (
        <div className="flex items-center gap-2 text-red-500 bg-red-500/10 p-3 rounded-md">
          <AlertCircle className="h-5 w-5" />
          <span>{error}</span>
        </div>
      )}

      <FormalOutcomeSection />

      {loading ? (
        <div className="flex h-40 items-center justify-center">
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {/* 采纳率 */}
          <div className="rounded-xl border border-border/60 bg-card p-6 shadow-sm">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 bg-blue-500/10 rounded-xl flex items-center justify-center">
                  <Target className="h-5 w-5 text-blue-500" />
                </div>
                <div>
                  <h3 className="font-medium">采纳率</h3>
                  <p className="text-sm text-muted-foreground">整体反馈采纳比例</p>
                </div>
              </div>
              {adoptionRate != null && (
                <div className="text-3xl font-mono font-semibold">{formatRate(adoptionRate)}</div>
              )}
            </div>

            {adoptionSummary && (
              <div className="space-y-3">
                {Object.entries(adoptionSummary.counts).map(([status, count]) => (
                  <div key={status} className="flex items-center justify-between">
                    <span className="text-sm capitalize">{status}</span>
                    <div className="flex-1 mx-4 h-1.5 bg-muted rounded">
                      <div
                        className="h-full bg-blue-500 rounded"
                        style={{ width: barWidth(count, adoptionSummary.total) }}
                      />
                    </div>
                    <span className="text-sm font-mono">{count}</span>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* 结果分布 */}
          <div className="rounded-xl border border-border/60 bg-card p-6 shadow-sm">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 bg-emerald-500/10 rounded-xl flex items-center justify-center">
                  <TrendingUp className="h-5 w-5 text-emerald-500" />
                </div>
                <div>
                  <h3 className="font-medium">结果分布</h3>
                  <p className="text-sm text-muted-foreground">决策结果质量</p>
                </div>
              </div>
              {outcomePositiveRate != null && (
                <div className="text-3xl font-mono font-semibold">{formatRate(outcomePositiveRate)}</div>
              )}
            </div>

            {outcomeSummary && (
              <div className="space-y-3">
                {Object.entries(outcomeSummary.counts).map(([status, count]) => (
                  <div key={status} className="flex items-center justify-between">
                    <span className="text-sm capitalize">{status}</span>
                    <div className="flex-1 mx-4 h-1.5 bg-muted rounded">
                      <div
                        className="h-full bg-emerald-500 rounded"
                        style={{ width: barWidth(count, outcomeSummary.total) }}
                      />
                    </div>
                    <span className="text-sm font-mono">{count}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      <div className="rounded-xl border border-border/60 bg-card p-6 shadow-sm">
        <h3 className="font-medium mb-4 flex items-center gap-2">
          <BarChart3 className="h-5 w-5" />
          个股绩效汇总
        </h3>

        <div className="overflow-auto max-h-[420px]">
          <table className="w-full">
            <thead>
              <tr className="text-left border-b border-border">
                <th className="pb-3 font-mono text-xs uppercase tracking-widest text-muted-foreground">股票</th>
                <th className="pb-3 font-mono text-xs uppercase tracking-widest text-muted-foreground">总反馈</th>
                <th className="pb-3 font-mono text-xs uppercase tracking-widest text-muted-foreground">采纳率</th>
                <th className="pb-3 font-mono text-xs uppercase tracking-widest text-muted-foreground">正向结果</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {stocks.map((stock) => (
                <tr key={stock.code} className="hover:bg-accent/50">
                  <td className="py-4 font-mono font-medium">{stock.code}</td>
                  <td className="py-4 text-center">{stock.total}</td>
                  <td className="py-4 text-center">{formatRate(stock.adoption_rate)}</td>
                  <td className="py-4 text-center">{formatRate(stock.outcome_positive_rate)}</td>
                </tr>
              ))}
            </tbody>
          </table>

          {stocks.length === 0 && !error && (
            <div className="py-12 text-center text-muted-foreground">暂无反馈数据</div>
          )}
        </div>
      </div>
    </div>
  );
};

export default DecisionPerformance;
