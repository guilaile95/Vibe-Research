import { useEffect, useRef, useState } from "react";
import { AlertCircle, ExternalLink, Loader2, Trophy } from "lucide-react";
import { Link } from "react-router-dom";

import { GlassCard } from "@/components/ui/GlassCard";
import { ApiError } from "@/lib/api";
import { candidateWorkspaceHref } from "@/lib/candidateCampaign";
import { recoveredMarketApi } from "@/lib/recoveredMarketApi";
import type { DragonTigerDiscovery } from "@/lib/recoveredMarketTypes";

const STATUS_LABELS: Record<DragonTigerDiscovery["status"], string> = {
  NORMAL: "源记录已返回",
  PARTIAL: "部分返回",
  EMPTY: "该交易日无记录",
  UNAVAILABLE: "源暂不可用",
};

const COMPLETENESS_LABELS: Record<string, string> = {
  COMPLETE: "已覆盖源报告记录",
  PARTIAL: "存在格式异常行",
  TRUNCATED: "已到达有界读取上限",
  NO_RECORD: "源报告无记录",
  UNAVAILABLE: "未完成读取",
};

function formatAmount(value: number | null): string {
  if (value == null) return "未知";
  return `${new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 2 }).format(value)} 元`;
}

function formatPercent(value: number | null): string {
  return value == null ? "未知" : `${value.toLocaleString("zh-CN", { maximumFractionDigits: 4 })}%`;
}

function statusClass(status: DragonTigerDiscovery["status"]): string {
  if (status === "UNAVAILABLE") return "text-destructive";
  if (status === "PARTIAL") return "text-warning";
  return "text-muted-foreground";
}

export function DragonTigerDiscoveryPanel() {
  const [tradeDate, setTradeDate] = useState("");
  const [result, setResult] = useState<DragonTigerDiscovery | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const controllerRef = useRef<AbortController | null>(null);

  useEffect(() => () => controllerRef.current?.abort(), []);

  const load = async () => {
    if (loading) return;
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const next = await recoveredMarketApi.getDragonTigerDiscovery(tradeDate || undefined, controller.signal);
      if (!controller.signal.aborted && controllerRef.current === controller) setResult(next);
    } catch (cause) {
      if (controller.signal.aborted) return;
      setError(cause instanceof ApiError ? cause.message : "龙虎榜市场查询失败");
    } finally {
      if (controllerRef.current === controller) {
        controllerRef.current = null;
        setLoading(false);
      }
    }
  };

  return (
    <div className="space-y-3" data-testid="dragon-tiger-discovery-panel">
      <GlassCard className="space-y-4 p-4">
        <div className="flex flex-wrap items-start gap-3">
          <div className="min-w-0 flex-1">
            <h2 className="flex items-center gap-1.5 text-sm font-semibold">
              <Trophy className="h-4 w-4 text-primary" />龙虎榜市场发现
            </h2>
            <p className="mt-1 text-xs leading-5 text-muted-foreground">
              读取现有 Eastmoney 龙虎榜报告的市场级公开上榜记录；这是事实发现入口，不是全 A 股票清单，也不产生买卖建议。
            </p>
          </div>
          <div className="flex w-full flex-wrap items-end gap-2 sm:w-auto">
            <label className="space-y-1 text-xs text-muted-foreground">
              指定交易日（可选）
              <input
                aria-label="龙虎榜交易日"
                data-testid="dragon-tiger-trade-date"
                type="date"
                value={tradeDate}
                disabled={loading}
                onChange={(event) => setTradeDate(event.target.value)}
                className="block rounded-lg border border-border bg-background px-2 py-1.5 text-xs text-foreground"
              />
            </label>
            <button
              type="button"
              data-testid="load-dragon-tiger-discovery"
              onClick={load}
              disabled={loading}
              className="inline-flex items-center gap-1.5 rounded-lg bg-foreground px-3 py-1.5 text-sm font-medium text-background disabled:opacity-40"
            >
              {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
              {loading ? "读取中…" : "读取龙虎榜"}
            </button>
          </div>
        </div>
        {error ? (
          <div className="flex items-center gap-2 text-xs text-destructive" role="alert">
            <AlertCircle className="h-4 w-4" />{error}
          </div>
        ) : null}
      </GlassCard>

      {result ? (
        <GlassCard className="space-y-3 p-4" data-testid="dragon-tiger-discovery-result">
          <div className="flex flex-wrap items-center gap-2 text-sm font-medium">
            <span data-testid="dragon-tiger-discovery-status" className={statusClass(result.status)}>
              数据状态：{STATUS_LABELS[result.status]}
            </span>
            <span className="text-xs text-muted-foreground">
              源交易日：{result.trade_date || result.requested_trade_date || "未知"}
            </span>
          </div>
          <div className="grid gap-1 text-xs text-muted-foreground sm:grid-cols-2 lg:grid-cols-4">
            <span>来源：{result.provider}</span>
            <span>报告：{result.report_name}</span>
            <span>返回记录：{result.pagination.returned_rows} / {result.pagination.source_count ?? "未知"}</span>
            <span>完整性：{COMPLETENESS_LABELS[result.completeness.status] || result.completeness.status}</span>
          </div>
          <p className="text-xs text-muted-foreground">
            分页边界：每页 {result.pagination.page_size} 行 · 最多 {result.pagination.max_pages} 页 / {result.pagination.max_rows} 行 · 已读取 {result.pagination.fetched_pages} 页
            {result.pagination.truncated ? " · 已明确截断" : ""}
          </p>
          {result.status === "UNAVAILABLE" ? (
            <p className="text-xs text-destructive">现有源读取未完成；没有回退到逐票龙虎榜或席位请求。</p>
          ) : null}
          {result.status === "PARTIAL" ? (
            <p className="text-xs text-warning">当前结果仅代表边界内可见的源记录，不应解读为完整报告。</p>
          ) : null}
          {result.status === "EMPTY" ? (
            <p className="text-xs text-muted-foreground">该日期的源报告没有返回上榜记录。</p>
          ) : null}
          {result.limitations.map((limitation) => (
            <p key={limitation} className="text-xs text-muted-foreground">限制：{limitation}</p>
          ))}

          {result.rows.length > 0 ? (
            <div className="overflow-x-auto rounded-lg border border-border/50" data-testid="dragon-tiger-discovery-table">
              <table className="w-full min-w-[780px] text-xs">
                <thead className="border-b border-border/50 text-left text-muted-foreground">
                  <tr>
                    <th className="px-3 py-2">证券</th>
                    <th className="px-3 py-2">上榜原因</th>
                    <th className="px-3 py-2">龙虎榜买卖净额（元）</th>
                    <th className="px-3 py-2">换手率（%）</th>
                    <th className="px-3 py-2">继续研究</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border/40">
                  {result.rows.map((row, index) => (
                    <tr key={`${row.source_record_identity}-${index}`} className="align-top hover:bg-muted/30" data-testid="dragon-tiger-discovery-row">
                      <td className="px-3 py-2">
                        <Link className="font-mono font-medium hover:text-primary hover:underline" to={`/stock-data?code=${encodeURIComponent(row.security_code)}`}>
                          {row.security_code}
                        </Link>
                        <span className="mt-0.5 block max-w-[140px] truncate text-muted-foreground">{row.security_name || "名称未知"}</span>
                      </td>
                      <td className="max-w-[320px] whitespace-normal break-words px-3 py-2 text-muted-foreground">{row.reason || "未提供"}</td>
                      <td className="whitespace-nowrap px-3 py-2 font-mono">{formatAmount(row.billboard_net_amount)}</td>
                      <td className="whitespace-nowrap px-3 py-2 font-mono">{formatPercent(row.turnover_rate_pct)}</td>
                      <td className="whitespace-nowrap px-3 py-2">
                        <Link className="inline-flex items-center gap-1 text-primary hover:underline" to={candidateWorkspaceHref(row.security_code)}>
                          候选研究 <ExternalLink className="h-3 w-3" />
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
        </GlassCard>
      ) : null}
    </div>
  );
}
