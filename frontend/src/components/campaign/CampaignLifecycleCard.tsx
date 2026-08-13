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
  renderableTransitionTargets,
  transitionPayload,
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
  decision?: { visible_state: string; reason_codes: string[] } | null;
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState<CampaignStatus | null>(null);
  const [error, setError] = useState("");

  const handleTransition = async (to: CampaignStatus) => {
    if (!nextActions) return;
    setBusy(to);
    setError("");
    try {
      // payload 形状由 transitionPayload 保证：expected_status + to_status（CAS）
      const { expected_status, to_status } = transitionPayload(nextActions.status, to);
      await api.transitionCampaign(campaignId, expected_status, to_status);
      onChanged();
    } catch (err: any) {
      // 409 等冲突如实显示 backend detail，绝不伪装成功
      setError(errorMessage(err));
    } finally {
      setBusy(null);
    }
  };

  const targets = renderableTransitionTargets(nextActions);

  return (
    <div
      className="rounded-lg border border-border/60 bg-card p-4 space-y-2"
      data-campaign-id={campaignId}
      data-campaign-status={status}
      data-campaign-strategy={strategy}
    >
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="font-mono font-medium">{securityCode}</span>
        <span className="rounded bg-muted px-1.5 py-0.5 text-xs text-muted-foreground">
          {CAMPAIGN_STRATEGY_LABELS[strategy]}
        </span>
        <span className="text-xs text-muted-foreground">{CAMPAIGN_STATUS_LABELS[status]}</span>
        <span className="ml-auto font-mono text-xs text-muted-foreground">{campaignId}</span>
      </div>

      {setupContext && (
        <p className="text-xs text-amber-600">
          {CAMPAIGN_STATUS_LABELS[status]} / 尚未进入 current Campaign
        </p>
      )}

      {decision && (
        <div className="text-xs text-muted-foreground">
          决策状态：<span className="font-medium text-foreground">{decision.visible_state}</span>
          {decision.reason_codes.length > 0 && (
            <span className="ml-2">{decision.reason_codes.join(" / ")}</span>
          )}
        </div>
      )}

      {targets.length > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs text-muted-foreground">下一合法动作：</span>
          {targets.map((to) => (
            <button
              key={to}
              type="button"
              disabled={busy !== null}
              onClick={() => handleTransition(to)}
              className="inline-flex items-center gap-1 rounded-md border border-border/60 px-2.5 py-1 text-xs hover:border-primary/50 hover:text-primary disabled:opacity-50"
            >
              {busy === to && <Loader2 className="h-3 w-3 animate-spin" />}
              {TRANSITION_ACTION_LABELS[to]}
            </button>
          ))}
        </div>
      )}

      {nextActions && targets.length === 0 && (
        <p className="text-xs text-muted-foreground">已处于终态，无下一合法动作。</p>
      )}

      {error && (
        <div className="flex items-center gap-2 rounded-md border border-red-500/30 bg-red-500/5 p-2 text-xs text-red-600" role="alert">
          <AlertCircle className="h-3.5 w-3.5 shrink-0" />
          {error}
        </div>
      )}
    </div>
  );
}
