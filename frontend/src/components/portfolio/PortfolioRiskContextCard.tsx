import { AlertCircle } from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import type { PortfolioRiskContext } from "@/lib/api";
import { buildRiskContextCapabilities, formatRiskMoney, formatRiskPercent, hasCompleteConcentration, isLegacyPositionAuthority, positionAuthorityLabel, riskContextStatusLabel } from "@/lib/portfolioRiskContext";
import { cn } from "@/lib/utils";

function StateBadge({ status }: { status: string }) {
  const positive = ["NORMAL", "COMPLETE", "AVAILABLE"].includes(status);
  return (
    <span className={cn("rounded px-1.5 py-0.5 text-[10px] font-mono", positive ? "bg-success/15 text-success" : "bg-amber-500/15 text-amber-700 dark:text-amber-300")}>
      {riskContextStatusLabel(status)}
    </span>
  );
}

function CapabilityRow({ label, value, testId, muted = false }: { label: string; value: string; testId: string; muted?: boolean }) {
  return (
    <div className="flex min-w-0 flex-wrap items-baseline justify-between gap-x-3 gap-y-1 border-b border-border/30 py-2 last:border-b-0" data-testid={testId}>
      <span className="text-muted-foreground">{label}</span>
      <span className={cn("text-right font-medium", muted && "text-muted-foreground")}>{value}</span>
    </div>
  );
}

export function PortfolioRiskContextCard({ context, error }: { context: PortfolioRiskContext | null; error?: string | null }) {
  if (!context) {
    return (
      <GlassCard className="mb-4" data-testid="portfolio-risk-context-card">
        <div className="flex items-center gap-2 text-sm text-muted-foreground" data-testid="portfolio-risk-context-loading">
          <AlertCircle className="h-4 w-4" />
          {error || "组合风险概览加载中…"}
        </div>
      </GlassCard>
    );
  }

  const concentration = context.security_concentration;
  const industry = context.industry_exposure;
  const coverage = context.industry_coverage;
  const capabilities = buildRiskContextCapabilities(context);
  const completeConcentration = hasCompleteConcentration(context);
  const legacyPositionAuthority = isLegacyPositionAuthority(context);

  return (
    <GlassCard className="mb-4" data-testid="portfolio-risk-context-card">
      <div className="mb-3 flex min-w-0 flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <h3 className="text-sm font-semibold">组合风险概览</h3>
          <p className="mt-1 text-[11px] leading-4 text-muted-foreground">只读当前组合事实：先显示现在知道什么，再显示当前没有足够 authority 计算什么。</p>
        </div>
        <span data-testid="portfolio-risk-context-status"><StateBadge status={context.status} /></span>
      </div>

      <div
        className={cn(
          "mb-3 rounded-md border p-3 text-xs",
          legacyPositionAuthority ? "border-amber-500/40 bg-amber-500/10" : "border-border/40",
        )}
        data-testid="portfolio-risk-context-position-authority"
      >
        <div className="flex min-w-0 flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
          <span className="text-muted-foreground">持仓事实</span>
          <span className={cn("font-medium", legacyPositionAuthority ? "text-amber-700 dark:text-amber-300" : "text-muted-foreground")}>
            {positionAuthorityLabel(context)}
          </span>
        </div>
        {legacyPositionAuthority && (
          <p className="mt-1 break-words leading-4 text-amber-800 dark:text-amber-200" data-testid="portfolio-risk-context-legacy-authority">
            尚未完成 canonical Position Reality；当前持仓来自 legacy fallback，仅用于可见性，不应视为完整当前组合风险事实。
          </p>
        )}
      </div>

      <div className="grid gap-2 text-xs sm:grid-cols-2 lg:grid-cols-4">
        <div className="min-w-0 rounded-md border border-border/40 p-2" data-testid="portfolio-risk-context-concentration">
          <p className="text-muted-foreground">组合集中度</p>
          {completeConcentration ? (
            <div className="mt-1 space-y-0.5 font-mono font-semibold">
              <div data-testid="portfolio-risk-context-top1">Top 1 {formatRiskPercent(concentration.top1_pct)}</div>
              <div data-testid="portfolio-risk-context-top3">Top 3 {formatRiskPercent(concentration.top3_pct)}</div>
              <div>Top 5 {formatRiskPercent(concentration.top5_pct)}</div>
            </div>
          ) : (
            <div className="mt-1 font-medium text-amber-700 dark:text-amber-300" data-testid="portfolio-risk-context-concentration-gap">
              {riskContextStatusLabel(concentration.status)}
            </div>
          )}
          <p className="mt-1 break-words text-[11px] text-muted-foreground">{context.quote_coverage.usable_holdings} / {context.quote_coverage.total_holdings} 只行情可用；不对已知子集重新归一化。</p>
        </div>

        <div className="min-w-0 rounded-md border border-border/40 p-2" data-testid="portfolio-risk-context-cash">
          <p className="text-muted-foreground">现金缓冲</p>
          <p className="mt-1 font-mono font-semibold" data-testid="portfolio-risk-context-cash-buffer">
            {context.cash_buffer.status === "AVAILABLE" ? formatRiskPercent(context.cash_buffer.ratio_pct) : "不可用"}
          </p>
          <p className="mt-1 break-words text-[11px] text-muted-foreground">仅同 confirmation_id 的 canonical current facts；不输出安全阈值或建议。</p>
        </div>

        <div className="min-w-0 rounded-md border border-border/40 p-2" data-testid="portfolio-risk-context-account">
          <p className="text-muted-foreground">账户分母</p>
          <p className="mt-1 font-mono font-semibold">{formatRiskMoney(context.account_exposure.denominator.value)}</p>
          <p className="mt-1 break-words text-[11px] text-muted-foreground">{context.account_exposure.status === "AVAILABLE" ? formatRiskPercent(context.account_exposure.tracked_stock_account_pct) : "当前不可用"}；mixed-time visibility，不是 Official Settled NAV exposure。</p>
        </div>

        <div className="min-w-0 rounded-md border border-border/40 p-2" data-testid="portfolio-risk-context-coverage">
          <p className="text-muted-foreground">数据覆盖</p>
          <p className="mt-1 font-medium">行情 {context.quote_coverage.usable_holdings}/{context.quote_coverage.total_holdings}</p>
          <p className="break-words text-[11px] text-muted-foreground">行业 {coverage.industry_classified_holdings}/{coverage.quote_usable_holdings} 可分类（覆盖 {formatRiskPercent(coverage.coverage_ratio == null ? null : coverage.coverage_ratio * 100)}）；未知 {coverage.unknown_industry_holdings}</p>
        </div>
      </div>

      <div className="mt-3 grid gap-3 lg:grid-cols-[1.2fr_1fr]">
        <div className="min-w-0 rounded-md border border-border/40 p-3" data-testid="portfolio-risk-context-industries">
          <div className="mb-2 flex min-w-0 flex-wrap items-center justify-between gap-2">
            <h4 className="font-medium">当前行业暴露</h4>
            <StateBadge status={industry.status} />
          </div>
          <p className="mb-2 break-words text-[11px] leading-4 text-muted-foreground">{industry.provider} · {industry.membership_semantics}</p>
          {industry.items.length ? (
            <div className="space-y-2">
              {industry.items.map((item) => (
                <div key={item.industry} className="min-w-0 rounded border border-border/30 p-2" data-testid={`portfolio-risk-context-industry-${item.industry}`}>
                  <div className="flex min-w-0 flex-wrap justify-between gap-2">
                    <span className="min-w-0 break-words font-medium">{item.industry}</span>
                    <span className="shrink-0 font-mono">{formatRiskPercent(item.weight_in_tracked_stock_pct)}</span>
                  </div>
                  <div className="mt-1 break-words text-[11px] text-muted-foreground">{formatRiskMoney(item.market_value)} · {item.member_count} 只 · {item.securities.join("、")}</div>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-xs text-muted-foreground" data-testid="portfolio-risk-context-industry-empty">{industry.status === "UNAVAILABLE" ? "行业分类暂不可用；集中度、账户事实仍独立保留。" : "当前没有可聚合的行业暴露。"}</p>
          )}
        </div>

        <div className="min-w-0 rounded-md border border-border/40 p-3" data-testid="portfolio-risk-context-capabilities">
          <h4 className="mb-1 font-medium">风险能力状态</h4>
          <CapabilityRow label="单笔风险预算" value={capabilities.singleTrade ? "已有（Candidate PRE-ENTRY）" : "不可用"} testId="portfolio-risk-context-single-trade" />
          <CapabilityRow label="组合风险预算" value={capabilities.portfolioAggregated} testId="portfolio-risk-context-portfolio-budget" muted />
          <CapabilityRow label="正式账户回撤" value="不可用：没有正式 NAV 历史" testId="portfolio-risk-context-drawdown" muted />
          <CapabilityRow label="压力测试" value="延期：尚无确认的组合压力情景" testId="portfolio-risk-context-stress" muted />
          <div className="mt-2 space-y-1 text-[11px] text-muted-foreground" data-testid="portfolio-risk-context-no-score">
            <div>不生成黑箱组合风险评分。</div>
            <div data-testid="portfolio-risk-context-no-recommendation">不生成加仓、减仓、卖出或调仓建议。</div>
          </div>
        </div>
      </div>

      <details className="mt-3 text-[11px] text-muted-foreground" data-testid="portfolio-risk-context-limitations">
        <summary className="cursor-pointer select-none">查看数据限制与只读边界</summary>
        <ul className="mt-2 list-disc space-y-1 pl-4">
          {context.limitations.map((limitation) => <li key={limitation} className="break-words">{limitation}</li>)}
        </ul>
      </details>
    </GlassCard>
  );
}
