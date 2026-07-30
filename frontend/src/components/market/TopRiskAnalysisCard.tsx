import { GlassCard } from "@/components/ui/GlassCard";
import type { TopRiskAnalysis } from "@/lib/api/types";
import {
  confidenceText,
  coverageText,
  fetchedAtText,
  limitationLines,
  riskLevel,
  riskScoreText,
  topRiskDirectionLabel,
  topRiskFreshnessText,
  topRiskStatusLabel,
  traceArchiveStatusText,
} from "@/lib/topRiskView";
import { cn } from "@/lib/utils";
import { AlertTriangle, Info, ShieldAlert } from "lucide-react";

export type TopRiskAnalysisCardProps = {
  env: TopRiskAnalysis | null;
  loading?: boolean;
  error?: string | null;
  className?: string;
};

export function TopRiskAnalysisCard({
  env,
  loading = false,
  error = null,
  className,
}: TopRiskAnalysisCardProps) {
  if (loading) {
    return (
      <GlassCard className={cn("mb-6", className)}>
        <div
          role="status"
          aria-live="polite"
          aria-busy="true"
          className="space-y-4"
        >
          <span className="sr-only">顶部风险分析加载中...</span>
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
          <div className="h-20 skeleton rounded-lg" />
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
          <span className="text-sm">顶部风险分析暂无数据</span>
        </div>
      </GlassCard>
    );
  }

  const badge = topRiskStatusLabel(env.status);
  const freshness = topRiskFreshnessText(env);
  const fetchedTime = fetchedAtText(env.fetched_at);
  const limitations = limitationLines(env);
  const level = riskLevel(env.risk_score);
  const archive = traceArchiveStatusText(env.trace_archive_status);
  const data = env.data;
  const trace = env.trace ?? [];
  const decisionRunId = env.decision_run_id ?? null;

  return (
    <GlassCard className={cn("mb-6 space-y-4", className)}>
      {/* 头部：标题、影子模式标识、状态徽标、元信息 */}
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border/40 pb-3">
        <div className="flex items-center gap-2">
          <h3 className="flex items-center gap-1.5 text-base font-semibold text-foreground">
            <ShieldAlert className="h-4 w-4 text-primary" /> 顶部风险分析
            <span className="rounded bg-muted/40 px-1.5 py-0.5 text-[10px] font-normal text-muted-foreground">
              影子模式
            </span>
          </h3>
          <span className={cn("rounded-full px-2 py-0.5 text-[10px] font-medium", badge.cls)}>
            {badge.text}
          </span>
        </div>

        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
          <span>{freshness}</span>
          <span>•</span>
          <span className={cn(env.is_stale && "text-amber-600 dark:text-amber-400 font-medium")}>
            抓取: {fetchedTime}
          </span>
        </div>
      </div>

      {/* 核心指标网格 */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <div className="rounded-lg border border-border/50 bg-muted/20 p-3">
          <p className="text-xs text-muted-foreground">风险分数</p>
          <p className={cn("mt-1 font-mono text-2xl font-bold", level.cls)}>
            {riskScoreText(env.risk_score)}
          </p>
          <p className={cn("text-[11px] font-medium", level.cls)}>{level.text}</p>
        </div>
        <div className="rounded-lg border border-border/50 bg-muted/20 p-3">
          <p className="text-xs text-muted-foreground">置信度</p>
          <p className="mt-1 font-mono text-lg font-bold text-foreground">
            {confidenceText(env.confidence)}
          </p>
        </div>
        <div className="rounded-lg border border-border/50 bg-muted/20 p-3">
          <p className="text-xs text-muted-foreground">覆盖</p>
          <p className="mt-1 font-mono text-sm font-bold text-foreground">
            {coverageText(env.coverage)}
          </p>
        </div>
        <div className="rounded-lg border border-border/50 bg-muted/20 p-3">
          <p className="text-xs text-muted-foreground">信号资格</p>
          <p className="mt-1 font-mono text-sm font-bold text-muted-foreground">
            {env.signal_eligible ? "可参与" : "不参与"}
          </p>
          <p className="text-[10px] text-muted-foreground/70">signal: {env.signal}</p>
        </div>
      </div>

      {/* 一句话结论 */}
      {data?.narrative && (
        <p className="rounded-lg border border-border/40 bg-muted/10 p-3 text-sm text-foreground">
          {data.narrative}
        </p>
      )}

      {/* 风险证据 / 安全证据 */}
      {(data?.risk_drivers?.length ?? 0) > 0 || (data?.safety_signals?.length ?? 0) > 0 ? (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {data && data.risk_drivers.length > 0 && (
            <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-3">
              <p className="mb-1 text-xs font-semibold text-destructive">风险证据</p>
              <ul className="ml-5 list-disc space-y-0.5 text-xs text-foreground">
                {data.risk_drivers.map((d, i) => (
                  <li key={i}>{d}</li>
                ))}
              </ul>
            </div>
          )}
          {data && data.safety_signals.length > 0 && (
            <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/5 p-3">
              <p className="mb-1 text-xs font-semibold text-emerald-600 dark:text-emerald-400">
                安全证据
              </p>
              <ul className="ml-5 list-disc space-y-0.5 text-xs text-foreground">
                {data.safety_signals.map((d, i) => (
                  <li key={i}>{d}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      ) : null}

      {/* 限制说明（影子模式定位） */}
      <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-xs text-amber-900 dark:text-amber-200">
        <div className="flex items-center gap-1.5 font-medium mb-1">
          <Info className="h-4 w-4 shrink-0 text-amber-600 dark:text-amber-400" />
          <span>数据限制说明：影子模式仅做顶部风险参考，不参与最终交易结论 / 仓位。</span>
        </div>
        {limitations.length > 0 && (
          <ul className="ml-5 list-disc space-y-0.5 text-muted-foreground">
            {limitations.map((line, idx) => (
              <li key={idx}>{line}</li>
            ))}
          </ul>
        )}
      </div>

      {/* 步骤级 trace（默认折叠，原生 details 可访问） */}
      {trace.length > 0 && (
        <details className="rounded-lg border border-border/40 bg-muted/5 p-3 text-xs">
          <summary className="cursor-pointer font-medium text-muted-foreground">
            步骤级分析明细（{trace.length} 步）
          </summary>
          <div className="mt-2 space-y-2">
            {trace.map((t) => (
              <div key={t.step_id} className="rounded border border-border/30 p-2">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="font-medium text-foreground">{t.label}</span>
                  <span className="text-muted-foreground">
                    {t.skipped
                      ? "已跳过"
                      : `${topRiskDirectionLabel(t.direction)} · risk ${t.step_risk} · 置信 ${t.confidence}`}
                  </span>
                </div>
                {t.skipped && t.skip_reason && (
                  <p className="text-[11px] text-muted-foreground">跳过原因：{t.skip_reason}</p>
                )}
                {!t.skipped && t.reasons?.length > 0 && (
                  <ul className="ml-4 list-disc text-[11px] text-muted-foreground">
                    {t.reasons.map((r, i) => (
                      <li key={i}>{r}</li>
                    ))}
                  </ul>
                )}
              </div>
            ))}
          </div>
        </details>
      )}

      {/* 追踪身份 + 决策依据入口 */}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-border/40 pt-2 text-[11px] text-muted-foreground">
        <span>
          追踪状态: <span className={cn("font-medium", archive.cls)}>{archive.text}</span>
        </span>
        {decisionRunId && env.trace_archive_status === "archived" ? (
          <>
            <span>•</span>
            <a
              href={`/decision-evidence?run_id=${encodeURIComponent(decisionRunId)}`}
              className="font-mono text-primary hover:underline"
            >
              决策依据 #{decisionRunId}
            </a>
          </>
        ) : (
          <>
            <span>•</span>
            <span>decision_run_id: {decisionRunId ?? "—"}</span>
          </>
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
