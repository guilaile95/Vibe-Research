import { useState } from "react";
import { AlertCircle, Loader2 } from "lucide-react";
import { api } from "@/lib/api";
import type {
  CampaignNextActions,
  CampaignStatus,
  CampaignStrategy,
} from "@/lib/api/types";
import {
  CAMPAIGN_STATUS_LABELS,
  CAMPAIGN_STRATEGY_LABELS,
  TRANSITION_ACTION_LABELS,
  isDestructiveTransition,
  presentReasonCodes,
  renderableTransitionTargets,
  transitionPayload,
  visibleStateLabel,
  errorMessage,
} from "@/lib/decisionInbox";

/**
 * CampaignLifecycleCard：backend-driven lifecycle UI 的单一实现。
 *
 * setup（DRAFT/RESEARCHING/PRE-ENTRY）与 current（ACTIVE/REDUCING）Campaign
 * 共用本组件 —— 不复制 transition handler、不绑死 DecisionInboxCampaignItem。
 * 状态与下一合法动作全部来自 backend；409 等错误如实显示，绝不本地推进状态。
 */
export function CampaignLifecycleCard({
  campaignId,
  securityCode,
  strategy,
  status,
  nextActions,
  setupContext,
  researchContext = false,
  decision,
  onChanged,
}: {
  campaignId: string;
  securityCode: string;
  strategy: CampaignStrategy;
  status: CampaignStatus;
  nextActions: CampaignNextActions | null;
  /** true：尚未进入 current Campaign composition（工作单 §8 诚实标签）。 */
  setupContext: boolean;
  /** true：StockData Candidate Research 上下文，明确区分继续/停止研究。 */
  researchContext?: boolean;
  decision?: { visible_state: string; reason_codes: string[] } | null;
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState<CampaignStatus | null>(null);
  const [error, setError] = useState("");
  const [pendingDestructive, setPendingDestructive] = useState<CampaignStatus | null>(
    null,
  );

  const handleTransition = async (to: CampaignStatus) => {
    if (!nextActions) return;
    setBusy(to);
    setError("");
    setPendingDestructive(null);
    try {
      const { expected_status, to_status } = transitionPayload(nextActions.status, to);
      await api.transitionCampaign(campaignId, expected_status, to_status);
      onChanged();
    } catch (err: unknown) {
      setError(errorMessage(err));
    } finally {
      setBusy(null);
    }
  };

  const onActionClick = (to: CampaignStatus) => {
    if (isDestructiveTransition(to)) {
      setError("");
      setPendingDestructive(to);
      return;
    }
    void handleTransition(to);
  };

  const targets = renderableTransitionTargets(nextActions);
  const advanceTargets = targets.filter((to) => !isDestructiveTransition(to));
  const destructiveTargets = targets.filter((to) => isDestructiveTransition(to));
  const actionLabel = (to: CampaignStatus) =>
    researchContext
      ? isDestructiveTransition(to)
        ? `停止研究（${CAMPAIGN_STATUS_LABELS[to]}）`
        : to === "RESEARCHING" || to === "PRE-ENTRY"
          ? "继续研究"
          : TRANSITION_ACTION_LABELS[to]
      : TRANSITION_ACTION_LABELS[to];
  const reasons = decision ? presentReasonCodes(decision.reason_codes) : null;

  return (
    <article
      className={`rounded-lg border bg-card p-4 space-y-3 ${
        setupContext
          ? "border-border/60 border-l-2 border-l-amber-500/80"
          : "border-border/60 border-l-2 border-l-foreground/55"
      }`}
      data-campaign-id={campaignId}
      data-campaign-status={status}
      data-campaign-strategy={strategy}
      data-campaign-role={setupContext ? "setup" : "current"}
    >
      <header className="flex flex-wrap items-start gap-2">
        <div className="min-w-0 flex-1 space-y-1.5">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-sm font-semibold tracking-tight">
              {securityCode}
            </span>
            <span className="rounded-md bg-muted px-1.5 py-0.5 text-xs font-medium text-foreground">
              {CAMPAIGN_STRATEGY_LABELS[strategy]}
            </span>
            <span
              className={`rounded-md px-1.5 py-0.5 text-xs font-medium ${
                setupContext
                  ? "bg-amber-500/10 text-amber-700 dark:text-amber-400"
                  : "bg-foreground/10 text-foreground"
              }`}
            >
              {CAMPAIGN_STATUS_LABELS[status]}
            </span>
            <span
              className={`rounded-md px-1.5 py-0.5 text-[11px] font-medium ${
                setupContext
                  ? "border border-amber-500/30 text-amber-700 dark:text-amber-400"
                  : "border border-foreground/25 text-foreground"
              }`}
            >
              {setupContext ? "建立中" : "当前投资计划"}
            </span>
          </div>
        </div>
      </header>

      <details className="text-[10px] text-muted-foreground">
        <summary className="cursor-pointer select-none hover:text-foreground">技术详情</summary>
        <p className="mt-1 font-mono">campaign_id：{campaignId}</p>
      </details>

      {setupContext ? (
        <p className="text-xs leading-5 text-amber-700 dark:text-amber-400">
          这项投资计划尚未生效，不能当作当前持仓的有效计划。
        </p>
      ) : (
        <p className="text-xs leading-5 text-muted-foreground">
          这项投资计划当前有效，但不代表买入、持有或其他投资建议已经获批。
        </p>
      )}

      {decision && reasons && (
        <div className="space-y-1.5 text-xs leading-5">
          <p>
            <span className="text-muted-foreground">决策待办：</span>
            <span className="font-medium text-foreground">
              {visibleStateLabel(decision.visible_state)}
            </span>
          </p>
          {reasons.primary.length > 0 && (
            <ul className="space-y-0.5 text-muted-foreground">
              {reasons.primary.map((label) => (
                <li key={label}>{label}</li>
              ))}
              {reasons.extraCount > 0 && (
                <li>另有 {reasons.extraCount} 项评估说明</li>
              )}
            </ul>
          )}
          {reasons.details.length > 0 && (
            <details className="text-muted-foreground">
              <summary className="cursor-pointer select-none hover:text-foreground">
                技术详情
              </summary>
              <ul className="mt-1 space-y-0.5 font-mono text-[11px]">
                {reasons.details.map((item) => (
                  <li key={item.code}>
                    {item.code}
                    {item.label !== item.code ? ` · ${item.label}` : ""}
                  </li>
                ))}
              </ul>
            </details>
          )}
        </div>
      )}

      {nextActions === null && (
        <p className="text-xs leading-5 text-amber-700 dark:text-amber-400" role="status">
          无法获取下一合法动作。刷新后以后端状态为准，不会猜测可执行步骤。
        </p>
      )}

      {targets.length > 0 && (
        <div className="space-y-2">
          {advanceTargets.length > 0 && (
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-xs text-muted-foreground">
                {researchContext ? "继续研究：" : "下一步："}
              </span>
              {advanceTargets.map((to) => (
                <button
                  key={to}
                  type="button"
                  disabled={busy !== null}
                  data-action-kind="advance"
                  onClick={() => onActionClick(to)}
                  className="inline-flex items-center gap-1 rounded-md bg-primary px-2.5 py-1 text-xs font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
                >
                  {busy === to && <Loader2 className="h-3 w-3 animate-spin" />}
                  {actionLabel(to)}
                </button>
              ))}
            </div>
          )}
          {destructiveTargets.length > 0 && (
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-xs text-muted-foreground">
                {researchContext ? "停止研究：" : "结束这项投资计划："}
              </span>
              {destructiveTargets.map((to) => (
                <button
                  key={to}
                  type="button"
                  disabled={busy !== null}
                  data-action-kind="destructive"
                  aria-expanded={pendingDestructive === to}
                  onClick={() => onActionClick(to)}
                  className="inline-flex items-center gap-1 rounded-md border border-destructive/40 px-2.5 py-1 text-xs text-destructive hover:bg-destructive/10 disabled:opacity-50"
                >
                  {busy === to && <Loader2 className="h-3 w-3 animate-spin" />}
                  {actionLabel(to)}
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      {pendingDestructive && (
        <div
          className="rounded-md border border-destructive/30 bg-destructive/5 p-3 space-y-2"
          role="alertdialog"
          aria-labelledby={`confirm-${campaignId}`}
          data-destructive-confirm={pendingDestructive}
        >
          <p id={`confirm-${campaignId}`} className="text-xs leading-5">
            确认{actionLabel(pendingDestructive)}？此操作进入终态后不可再推进。
          </p>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              disabled={busy !== null}
              onClick={() => void handleTransition(pendingDestructive)}
              className="inline-flex items-center gap-1 rounded-md bg-destructive px-2.5 py-1 text-xs font-medium text-destructive-foreground hover:bg-destructive/90 disabled:opacity-50"
            >
              {busy === pendingDestructive && <Loader2 className="h-3 w-3 animate-spin" />}
              确认{actionLabel(pendingDestructive)}
            </button>
            <button
              type="button"
              disabled={busy !== null}
              onClick={() => setPendingDestructive(null)}
              className="rounded-md border border-border/60 px-2.5 py-1 text-xs text-muted-foreground hover:bg-muted"
            >
              取消
            </button>
          </div>
        </div>
      )}

      {nextActions && targets.length === 0 && (
        <p className="text-xs text-muted-foreground">已处于终态，无下一合法动作。</p>
      )}

      {error && (
        <div
          className="flex items-start gap-2 rounded-md border border-red-500/30 bg-red-500/5 p-2 text-xs text-red-600"
          role="alert"
        >
          <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span>未能变更状态：{error}</span>
        </div>
      )}
    </article>
  );
}
