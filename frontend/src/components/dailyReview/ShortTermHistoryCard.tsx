import { GlassCard } from "@/components/ui/GlassCard";
import type { Bk11HistoryEnvelope } from "@/lib/api/types";
import {
  dataTimeText,
  deltaValue,
  digestText,
  factValue,
  formatDeltaNumber,
  formatNullableNumber,
  gapValue,
  hasComparableDelta,
  ladderRows,
  ladderValue,
  latestEnvelope,
  latestSectionStatus,
  limitationLines,
  previousTradeDate,
  statusBadgeCls,
  statusLabel,
} from "@/lib/bk11HistoryView";
import { cn } from "@/lib/utils";
import {
  AlertTriangle,
  BarChart3,
  GitCompare,
  History,
  Info,
  Layers,
  TrendingUp,
} from "lucide-react";

export type ShortTermHistoryCardProps = {
  env: Bk11HistoryEnvelope | null;
  loading?: boolean;
  error?: string | null;
  className?: string;
};

function FactCell({ label, value }: { label: string; value: unknown }) {
  return (
    <div className="rounded-lg bg-muted/25 p-2.5">
      <p className="text-[11px] text-muted-foreground">{label}</p>
      <p className="mt-0.5 font-mono text-base font-semibold text-foreground">
        {formatNullableNumber(value)}
      </p>
    </div>
  );
}

function DeltaCell({ label, value }: { label: string; value: unknown }) {
  const text = formatDeltaNumber(value);
  const isDelta = text !== "—";
  const num = typeof value === "number" ? value : null;
  return (
    <div className="rounded-lg bg-muted/25 p-2.5">
      <p className="text-[11px] text-muted-foreground">{label}</p>
      <p
        className={cn(
          "mt-0.5 font-mono text-sm font-semibold",
          isDelta && num !== null && num > 0
            ? "text-emerald-500"
            : isDelta && num !== null && num < 0
              ? "text-destructive"
              : "text-foreground",
        )}
      >
        {text}
      </p>
    </div>
  );
}

export function ShortTermHistoryCard({
  env,
  loading = false,
  error = null,
  className,
}: ShortTermHistoryCardProps) {
  if (loading) {
    return (
      <GlassCard className={cn("mb-6", className)}>
        <div role="status" aria-live="polite" aria-busy="true" className="space-y-4">
          <span className="sr-only">短线市场历史数据加载中...</span>
          <div className="flex items-center justify-between">
            <div className="h-6 w-40 skeleton rounded" />
            <div className="h-5 w-16 skeleton rounded-full" />
          </div>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <div className="h-16 skeleton rounded-lg" />
            <div className="h-16 skeleton rounded-lg" />
            <div className="h-16 skeleton rounded-lg" />
            <div className="h-16 skeleton rounded-lg" />
          </div>
          <div className="h-24 skeleton rounded-lg" />
        </div>
      </GlassCard>
    );
  }

  if (error) {
    return (
      <GlassCard className={cn("mb-6", className)}>
        <div role="alert" className="flex items-center gap-2 p-2 text-destructive">
          <AlertTriangle className="h-4 w-4 shrink-0" />
          <span className="text-sm font-medium">{error}</span>
        </div>
      </GlassCard>
    );
  }

  if (!env) {
    return (
      <GlassCard className={cn("mb-6", className)}>
        <div
          role="status"
          className="flex items-center gap-2 p-2 text-muted-foreground"
        >
          <Info className="h-4 w-4 shrink-0" />
          <span className="text-sm">短线市场历史暂无数据</span>
        </div>
      </GlassCard>
    );
  }

  const status = env.status;
  const latest = latestEnvelope(env);
  const badgeText = statusLabel(status);
  const badgeCls = statusBadgeCls(status);
  const digest = digestText(env);
  const limitations = limitationLines(env);
  const hasDelta = hasComparableDelta(env);
  const prevDate = previousTradeDate(env);
  const factsStatus = latestSectionStatus(env, "facts");
  const ladderStatus = latestSectionStatus(env, "ladder");
  const gapStatus = latestSectionStatus(env, "gap");

  return (
    <GlassCard className={cn("mb-6 space-y-4", className)}>
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border/40 pb-3">
        <div className="flex items-center gap-2">
          <h3 className="flex items-center gap-1.5 text-base font-semibold text-foreground">
            <History className="h-4 w-4 text-primary" /> 短线市场历史
          </h3>
          <span className={cn("rounded-full px-2 py-0.5 text-[10px] font-medium", badgeCls)}>
            {badgeText}
          </span>
        </div>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
          {env.trade_date && <span>交易日: {env.trade_date}</span>}
          <span>数据时间: {dataTimeText(env.data_time)}</span>
        </div>
      </div>

      {status === "empty" && (
        <div
          role="status"
          className="flex items-center gap-2 text-sm text-muted-foreground"
        >
          <Info className="h-4 w-4 shrink-0" />
          <span>暂无已保存的 BK-11 短线历史快照（生产快照写入仍受上游输入缺失阻塞）。</span>
        </div>
      )}

      {status === "error" && (
        <div
          role="alert"
          className="flex items-center gap-2 text-sm text-destructive"
        >
          <AlertTriangle className="h-4 w-4 shrink-0" />
          <span>短线市场历史存储当前无法安全读取。</span>
        </div>
      )}

      {status === "unavailable" && (
        <div
          role="status"
          className="flex items-center gap-2 text-sm text-destructive"
        >
          <AlertTriangle className="h-4 w-4 shrink-0" />
          <span>最新快照当前不可用，不展示任何历史指标。</span>
        </div>
      )}

      {(status === "normal" || status === "partial") && latest && (
        <>
          <div>
            <h4 className="mb-2 flex items-center gap-1.5 text-sm font-semibold text-muted-foreground">
              <BarChart3 className="h-4 w-4 text-primary" /> 核心市场事实
              {factsStatus && (
                <span className={cn("rounded-full px-2 py-0.5 text-[10px]", statusBadgeCls(factsStatus))}>
                  {statusLabel(factsStatus)}
                </span>
              )}
            </h4>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4">
              <FactCell label="上涨家数" value={factValue(env, "advance_count")} />
              <FactCell label="下跌家数" value={factValue(env, "decline_count")} />
              <FactCell label="涨停家数" value={factValue(env, "limit_up_count")} />
              <FactCell label="跌停家数" value={factValue(env, "limit_down_count")} />
              <FactCell label="炸板家数" value={factValue(env, "failed_limit_up_count")} />
              <FactCell label="触板家数" value={factValue(env, "touched_limit_up_count")} />
              <FactCell label="上涨占比" value={factValue(env, "up_ratio")} />
              <FactCell label="封板率" value={factValue(env, "seal_rate")} />
            </div>
          </div>

          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            <div>
              <h4 className="mb-2 flex items-center gap-1.5 text-sm font-semibold text-muted-foreground">
                <Layers className="h-4 w-4 text-primary" /> 连板梯队
                {ladderStatus && (
                  <span className={cn("rounded-full px-2 py-0.5 text-[10px]", statusBadgeCls(ladderStatus))}>
                    {statusLabel(ladderStatus)}
                  </span>
                )}
              </h4>
              <div className="overflow-x-auto rounded-lg bg-muted/25 p-3">
                <div className="flex flex-wrap gap-x-4 gap-y-1 text-sm">
                  <span className="text-muted-foreground">
                    最高板: <b className="font-mono text-foreground">{formatNullableNumber(ladderValue(env, "max_boards"))}</b>
                  </span>
                  <span className="text-muted-foreground">
                    连板家数: <b className="font-mono text-foreground">{formatNullableNumber(ladderValue(env, "lianban_count"))}</b>
                  </span>
                </div>
                {(() => {
                  const rows = ladderRows(env);
                  if (rows.length === 0) {
                    return (
                      <p className="mt-2 text-xs text-muted-foreground/60">
                        暂无连板梯队明细
                      </p>
                    );
                  }
                  return (
                    <table className="mt-2 w-full text-sm">
                      <thead>
                        <tr className="border-b border-border/40 text-left text-xs text-muted-foreground">
                          <th className="py-1 pr-4 font-medium">板数</th>
                          <th className="py-1 font-medium">股票数量</th>
                        </tr>
                      </thead>
                      <tbody>
                        {rows.map((row) => (
                          <tr key={row.boards} className="border-b border-border/20 last:border-0">
                            <td className="py-1 pr-4 font-mono text-foreground">
                              {formatNullableNumber(row.boards)}
                            </td>
                            <td className="py-1 font-mono text-foreground">
                              {formatNullableNumber(row.count)}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  );
                })()}
              </div>
            </div>

            <div>
              <h4 className="mb-2 flex items-center gap-1.5 text-sm font-semibold text-muted-foreground">
                <TrendingUp className="h-4 w-4 text-primary" /> 梯队断层
                {gapStatus && (
                  <span className={cn("rounded-full px-2 py-0.5 text-[10px]", statusBadgeCls(gapStatus))}>
                    {statusLabel(gapStatus)}
                  </span>
                )}
              </h4>
              <div className="overflow-x-auto rounded-lg bg-muted/25 p-3">
                <div className="flex flex-wrap gap-x-4 gap-y-1 text-sm">
                  <span className="text-muted-foreground">
                    缺口层级: <b className="font-mono text-foreground">{formatNullableNumber(gapValue(env, "gap_level_count"))}</b>
                  </span>
                  <span className="text-muted-foreground">
                    缺口段数: <b className="font-mono text-foreground">{formatNullableNumber(gapValue(env, "gap_segment_count"))}</b>
                  </span>
                  <span className="text-muted-foreground">
                    最大宽度: <b className="font-mono text-foreground">{formatNullableNumber(gapValue(env, "largest_gap_width"))}</b>
                  </span>
                </div>
              </div>
            </div>
          </div>

          <div>
            <h4 className="mb-2 flex items-center gap-1.5 text-sm font-semibold text-muted-foreground">
              <GitCompare className="h-4 w-4 text-primary" /> 与前序快照变化
              {prevDate && <span className="text-[11px] font-normal text-muted-foreground/60">对比 {prevDate}</span>}
            </h4>
            {hasDelta ? (
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                <DeltaCell label="涨停变化" value={deltaValue(env, "limit_up_count")} />
                <DeltaCell label="上涨变化" value={deltaValue(env, "advance_count")} />
                <DeltaCell label="下跌变化" value={deltaValue(env, "decline_count")} />
                <DeltaCell label="炸板变化" value={deltaValue(env, "failed_limit_up_count")} />
              </div>
            ) : (
              <p className="text-sm text-muted-foreground/60">
                暂无前序快照，不生成比较。
              </p>
            )}
          </div>

          {env.summary && (
            <div className="rounded-lg border border-border/40 bg-muted/10 p-3">
              <h4 className="mb-1 flex items-center gap-1.5 text-sm font-semibold text-muted-foreground">
                窗口摘要（
                {(() => {
                  const summary = env.summary as Record<string, unknown>;
                  const windowObj =
                    summary.window && typeof summary.window === "object"
                      ? (summary.window as Record<string, unknown>)
                      : null;
                  const count =
                    typeof windowObj?.count === "number"
                      ? windowObj.count
                      : env.window.snapshot_count;
                  return String(count);
                })()}
                {" "}天）
              </h4>
              <p className="whitespace-pre-wrap break-words text-xs leading-relaxed text-muted-foreground">
                {digest || "暂无摘要"}
              </p>
            </div>
          )}

          {!env.summary && digest && (
            <div className="rounded-lg border border-border/40 bg-muted/10 p-3">
              <p className="whitespace-pre-wrap break-words text-xs leading-relaxed text-muted-foreground">
                {digest}
              </p>
            </div>
          )}
        </>
      )}

      {(status === "partial" || status === "unavailable") && (
        <p className="text-xs text-muted-foreground/70">
          {status === "partial"
            ? "最新快照仅部分可用，以下内容按可用部分展示。"
            : "最新快照不可用，历史指标不展示。"}
        </p>
      )}

      {(limitations.length > 0 || env.warnings.length > 0) && (
        <details className="rounded-lg border border-border/40 bg-muted/10 p-3">
          <summary className="cursor-pointer text-xs font-medium text-muted-foreground">
            技术详情与限制
          </summary>
          <ul className="mt-2 space-y-1 text-xs text-muted-foreground/80">
            {env.warnings.map((w, i) => (
              <li key={`w-${i}`}>⚠ {w}</li>
            ))}
            {limitations.map((l, i) => (
              <li key={`l-${i}`}>· {l}</li>
            ))}
          </ul>
        </details>
      )}
    </GlassCard>
  );
}
