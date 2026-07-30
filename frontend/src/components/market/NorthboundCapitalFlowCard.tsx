import { GlassCard } from "@/components/ui/GlassCard";
import type { NorthboundCapitalFlow } from "@/lib/api/types";
import {
  fetchedAtText,
  formatCount,
  formatTurnoverMn,
  formatTurnoverYuan,
  limitationLines,
  northboundFreshnessText,
  northboundStatusLabel,
} from "@/lib/northboundView";
import { cn } from "@/lib/utils";
import { AlertTriangle, Info, Landmark } from "lucide-react";

export type NorthboundCapitalFlowCardProps = {
  env: NorthboundCapitalFlow | null;
  loading?: boolean;
  error?: string | null;
  className?: string;
};

export function NorthboundCapitalFlowCard({
  env,
  loading = false,
  error = null,
  className,
}: NorthboundCapitalFlowCardProps) {
  if (loading) {
    return (
      <GlassCard className={cn("mb-6", className)}>
        <div
          role="status"
          aria-live="polite"
          aria-busy="true"
          className="space-y-4"
        >
          <span className="sr-only">北向资金数据加载中...</span>
          <div className="flex items-center justify-between">
            <div className="h-6 w-32 skeleton rounded" />
            <div className="h-5 w-16 skeleton rounded-full" />
          </div>
          <div className="h-4 w-64 skeleton rounded" />
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <div className="h-16 skeleton rounded-lg" />
            <div className="h-16 skeleton rounded-lg" />
            <div className="h-16 skeleton rounded-lg" />
          </div>
          <div className="h-28 skeleton rounded-lg" />
        </div>
      </GlassCard>
    );
  }

  if (error) {
    return (
      <GlassCard className={cn("mb-6", className)}>
        <div role="alert" className="flex items-center gap-2 text-destructive p-2">
          <AlertTriangle className="h-4 w-4 shrink-0" />
          <span className="text-sm font-medium">{error}</span>
        </div>
      </GlassCard>
    );
  }

  if (!env) {
    return (
      <GlassCard className={cn("mb-6", className)}>
        <div role="alert" className="flex items-center gap-2 text-muted-foreground p-2">
          <Info className="h-4 w-4 shrink-0" />
          <span className="text-sm">北向资金暂无数据</span>
        </div>
      </GlassCard>
    );
  }

  const badge = northboundStatusLabel(env.status);
  const freshness = northboundFreshnessText(env);
  const fetchedTime = fetchedAtText(env.fetched_at);
  const limitations = limitationLines(env);

  const nb = env.data?.northbound;
  const sse = env.data?.shanghai_connect;
  const szse = env.data?.shenzhen_connect;
  const activeStocks = env.data?.active_stocks ?? [];

  return (
    <GlassCard className={cn("mb-6 space-y-4", className)}>
      {/* 头部：标题、状态徽标、元信息 */}
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border/40 pb-3">
        <div className="flex items-center gap-2">
          <h3 className="flex items-center gap-1.5 text-base font-semibold text-foreground">
            <Landmark className="h-4 w-4 text-primary" /> 北向资金
          </h3>
          <span className={cn("rounded-full px-2 py-0.5 text-[10px] font-medium", badge.cls)}>
            {badge.text}
          </span>
        </div>

        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
          <span>来源: {env.source || "HKEX"}</span>
          <span>•</span>
          <span className={cn(env.is_stale && "text-amber-600 dark:text-amber-400 font-medium")}>
            {freshness}
          </span>
          <span>•</span>
          <span>抓取: {fetchedTime}</span>
        </div>
      </div>

      {/* 关键真实性限制提示 */}
      <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-xs text-amber-900 dark:text-amber-200">
        <div className="flex items-center gap-1.5 font-medium mb-1">
          <Info className="h-4 w-4 shrink-0 text-amber-600 dark:text-amber-400" />
          <span>数据限制说明：本数据源不提供北向净买入（权威源仅发布成交额与相关指标）</span>
        </div>
        {limitations.length > 0 && (
          <ul className="ml-5 list-disc space-y-0.5 text-muted-foreground">
            {limitations.map((line, idx) => (
              <li key={idx}>{line}</li>
            ))}
          </ul>
        )}
      </div>

      {/* 主指标网格（北向合计） */}
      <div>
        <h4 className="mb-2 text-xs font-semibold text-muted-foreground uppercase tracking-wider">
          北向合计
        </h4>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <div className="rounded-lg border border-border/50 bg-muted/20 p-3">
            <p className="text-xs text-muted-foreground">北向成交额</p>
            <p className="mt-1 font-mono text-lg font-bold text-foreground">
              {formatTurnoverMn(nb?.total_turnover_mn)}
            </p>
          </div>
          <div className="rounded-lg border border-border/50 bg-muted/20 p-3">
            <p className="text-xs text-muted-foreground">成交笔数</p>
            <p className="mt-1 font-mono text-lg font-bold text-foreground">
              {formatCount(nb?.trade_count)}
            </p>
          </div>
          <div className="rounded-lg border border-border/50 bg-muted/20 p-3">
            <p className="text-xs text-muted-foreground">ETF 成交额</p>
            <p className="mt-1 font-mono text-lg font-bold text-foreground">
              {formatTurnoverMn(nb?.etf_turnover_mn)}
            </p>
          </div>
        </div>
      </div>

      {/* 沪股通 / 深股通 两列 */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        {/* 沪股通 */}
        <div className="rounded-lg border border-border/40 bg-muted/10 p-3 space-y-2">
          <h4 className="text-xs font-semibold text-foreground flex items-center justify-between">
            <span>沪股通 (SSE)</span>
          </h4>
          <div className="grid grid-cols-2 gap-2 text-xs">
            <div>
              <span className="text-muted-foreground block">北向成交额</span>
              <span className="font-mono font-medium text-foreground">
                {formatTurnoverMn(sse?.total_turnover_mn)}
              </span>
            </div>
            <div>
              <span className="text-muted-foreground block">成交笔数</span>
              <span className="font-mono font-medium text-foreground">
                {formatCount(sse?.trade_count)}
              </span>
            </div>
            <div>
              <span className="text-muted-foreground block">ETF 成交额</span>
              <span className="font-mono font-medium text-foreground">
                {formatTurnoverMn(sse?.etf_turnover_mn)}
              </span>
            </div>
            <div>
              <span className="text-muted-foreground block">每日额度余额</span>
              <span className="font-mono font-medium text-foreground">
                {formatTurnoverMn(sse?.daily_quota_balance_mn)}
              </span>
            </div>
          </div>
        </div>

        {/* 深股通 */}
        <div className="rounded-lg border border-border/40 bg-muted/10 p-3 space-y-2">
          <h4 className="text-xs font-semibold text-foreground flex items-center justify-between">
            <span>深股通 (SZSE)</span>
          </h4>
          <div className="grid grid-cols-2 gap-2 text-xs">
            <div>
              <span className="text-muted-foreground block">北向成交额</span>
              <span className="font-mono font-medium text-foreground">
                {formatTurnoverMn(szse?.total_turnover_mn)}
              </span>
            </div>
            <div>
              <span className="text-muted-foreground block">成交笔数</span>
              <span className="font-mono font-medium text-foreground">
                {formatCount(szse?.trade_count)}
              </span>
            </div>
            <div>
              <span className="text-muted-foreground block">ETF 成交额</span>
              <span className="font-mono font-medium text-foreground">
                {formatTurnoverMn(szse?.etf_turnover_mn)}
              </span>
            </div>
            <div>
              <span className="text-muted-foreground block">每日额度余额</span>
              <span className="font-mono font-medium text-foreground">
                {formatTurnoverMn(szse?.daily_quota_balance_mn)}
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* 活跃股表（按成交额） */}
      <div>
        <h4 className="mb-2 text-xs font-semibold text-muted-foreground uppercase tracking-wider">
          活跃股（按成交额）
        </h4>
        {activeStocks.length === 0 ? (
          <p className="text-xs text-muted-foreground italic">暂无活跃股数据</p>
        ) : (
          <div className="overflow-x-auto rounded-lg border border-border/40">
            <table className="w-full text-left text-xs">
              <caption className="sr-only">北向资金活跃股列表</caption>
              <thead>
                <tr className="border-b border-border/40 bg-muted/30 text-muted-foreground">
                  <th scope="col" className="px-3 py-2 font-medium">#</th>
                  <th scope="col" className="px-3 py-2 font-medium">市场</th>
                  <th scope="col" className="px-3 py-2 font-medium">代码</th>
                  <th scope="col" className="px-3 py-2 font-medium">名称</th>
                  <th scope="col" className="px-3 py-2 font-medium text-right">北向成交额</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border/30">
                {activeStocks.map((stock) => (
                  <tr key={`${stock.market}-${stock.code}-${stock.rank}`}>
                    <td className="px-3 py-2 font-mono text-muted-foreground">{stock.rank}</td>
                    <td className="px-3 py-2 text-muted-foreground">
                      {stock.market === "SSE" ? "沪股通" : "深股通"}
                    </td>
                    <td className="px-3 py-2 font-mono text-muted-foreground">{stock.code}</td>
                    <td className="px-3 py-2 font-medium text-foreground">{stock.name}</td>
                    <td className="px-3 py-2 font-mono text-right text-foreground">
                      {formatTurnoverYuan(stock.total_turnover_yuan)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Warnings 列表 */}
      {env.warnings && env.warnings.length > 0 && (
        <div className="rounded-lg border border-amber-500/20 bg-amber-500/5 p-3 text-xs text-amber-800 dark:text-amber-300">
          <p className="font-medium mb-1">提示信息：</p>
          <ul className="ml-5 list-disc space-y-0.5">
            {env.warnings.map((w, idx) => (
              <li key={idx}>{w}</li>
            ))}
          </ul>
        </div>
      )}
    </GlassCard>
  );
}
