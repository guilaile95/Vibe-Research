import React, { useCallback, useEffect, useState } from "react";
import {
  PlusCircle,
  AlertCircle,
  Loader2,
  RefreshCw,
  ClipboardList,
} from "lucide-react";
import { api } from "@/lib/api";
import type {
  CampaignNextActions,
  CampaignRecord,
  CampaignStrategy,
  DecisionInboxHoldingSetupItem,
  DecisionInboxSnapshot,
} from "@/lib/api/types";
import {
  CAMPAIGN_STRATEGIES,
  CAMPAIGN_STRATEGY_LABELS,
  CAMPAIGN_STATUS_LABELS,
  collectHoldingUniverseSecurityCodes,
  presentReasonCodes,
  selectSetupCampaigns,
  createCampaignPayload,
  errorMessage,
  reasonCodeLabel,
} from "@/lib/decisionInbox";
import { CampaignLifecycleCard } from "@/components/campaign/CampaignLifecycleCard";
import { PageHeader } from "@/components/ui/PageHeader";

/** 创建表单：security_code 固定自 holding，strategy 必选，显式确认 DRAFT。 */
function CreateCampaignForm({
  holding,
  onCreated,
  onClose,
}: {
  holding: DecisionInboxHoldingSetupItem;
  onCreated: () => void;
  onClose: () => void;
}) {
  const [strategy, setStrategy] = useState<CampaignStrategy | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [created, setCreated] = useState<CampaignRecord | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!strategy) return;
    setSubmitting(true);
    setError("");
    try {
      const { security_code, strategy: chosen } = createCampaignPayload(
        holding.security_code,
        strategy,
      );
      const campaign = await api.createCampaign(security_code, chosen);
      setCreated(campaign);
      onCreated();
    } catch (err: unknown) {
      setError(errorMessage(err));
    } finally {
      setSubmitting(false);
    }
  };

  if (created) {
    return (
      <div
        className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-4"
        role="status"
      >
        <div className="space-y-1.5 text-sm">
          <p className="font-medium">Campaign 已创建（状态：草稿）</p>
          <p className="text-xs leading-5 text-muted-foreground">
            这只是建立中的草稿，不会自动激活，也不会自动创建投资逻辑或正式决策。
          </p>
          <p className="font-mono text-[11px] text-muted-foreground" title={created.campaign_id}>
            campaign_id：{created.campaign_id}
          </p>
          <p className="text-muted-foreground">
            {CAMPAIGN_STRATEGY_LABELS[created.strategy]} · {CAMPAIGN_STATUS_LABELS[created.status]}
          </p>
          <button
            type="button"
            onClick={onClose}
            className="text-xs text-primary hover:underline"
          >
            关闭
          </button>
        </div>
      </div>
    );
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="rounded-lg border border-border/60 bg-background/40 p-4 space-y-3"
    >
      <div className="grid gap-1.5">
        <label className="text-xs font-medium text-muted-foreground">
          证券代码（固定，不可修改）
        </label>
        <p className="text-sm font-mono">{holding.security_code}</p>
      </div>

      <div className="grid gap-1.5">
        <span className="text-xs font-medium text-muted-foreground">选择策略（必选）</span>
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
          {CAMPAIGN_STRATEGIES.map((value) => (
            <label
              key={value}
              className={`cursor-pointer rounded-md border px-3 py-2 text-center text-sm transition-colors ${
                strategy === value
                  ? "border-primary bg-primary/5 text-primary"
                  : "border-border/60 hover:border-primary/40"
              }`}
            >
              <input
                type="radio"
                name="campaign-strategy"
                value={value}
                checked={strategy === value}
                onChange={() => setStrategy(value)}
                className="sr-only"
              />
              {CAMPAIGN_STRATEGY_LABELS[value]}
            </label>
          ))}
        </div>
      </div>

      <p className="text-xs leading-5 text-muted-foreground">
        创建后为草稿，不会自动激活。后续每一步都要你单独确认。
      </p>

      {error && (
        <div
          className="flex items-center gap-2 rounded-md border border-red-500/30 bg-red-500/5 p-2 text-xs text-red-600"
          role="alert"
        >
          <AlertCircle className="h-3.5 w-3.5 shrink-0" />
          {error}
        </div>
      )}

      <div className="flex flex-wrap gap-2">
        <button
          type="submit"
          disabled={!strategy || submitting}
          className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
        >
          {submitting && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
          确认创建 Campaign
        </button>
        <button
          type="button"
          onClick={onClose}
          className="rounded-md border border-border/60 px-3 py-1.5 text-xs text-muted-foreground hover:bg-muted"
        >
          取消
        </button>
      </div>
    </form>
  );
}

export default function DecisionInbox() {
  const [snapshot, setSnapshot] = useState<DecisionInboxSnapshot | null>(null);
  const [setupCampaigns, setSetupCampaigns] = useState<CampaignRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [nextActions, setNextActions] = useState<Record<string, CampaignNextActions | null>>({});
  const [creatingFor, setCreatingFor] = useState<string | null>(null);
  const [formGeneration, setFormGeneration] = useState(0);

  const refresh = useCallback(async () => {
    setLoadError("");
    try {
      const snap = await api.getDecisionInbox();
      const allCampaigns = await api.listCampaigns();
      const universe = collectHoldingUniverseSecurityCodes(snap);
      const setup = selectSetupCampaigns(allCampaigns, universe);

      const ids = [
        ...snap.campaign_items.map((item) => item.campaign_id),
        ...setup.map((campaign) => campaign.campaign_id),
      ];
      const entries = await Promise.all(
        ids.map(async (id) => {
          try {
            const actions = await api.getCampaignNextActions(id);
            return [id, actions] as const;
          } catch {
            return [id, null] as const;
          }
        }),
      );
      setSnapshot(snap);
      setSetupCampaigns(setup);
      setNextActions(Object.fromEntries(entries));
    } catch (err: unknown) {
      setLoadError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const handleCreated = useCallback(() => {
    void refresh();
  }, [refresh]);

  const isEmpty =
    snapshot?.canonical
    && snapshot.holding_setup_items.length === 0
    && snapshot.campaign_items.length === 0
    && setupCampaigns.length === 0;

  const snapshotReasons = snapshot ? presentReasonCodes(snapshot.reason_codes) : null;

  return (
    <div className="space-y-6">
      <PageHeader
        title="决策待办"
        subtitle="查看未建立、正在建立与已进入当前期的 Campaign。创建和每一步生命周期变更都需要你单独确认，不会自动推进。"
        actions={
          <button
            type="button"
            onClick={() => void refresh()}
            className="inline-flex shrink-0 items-center gap-1.5 rounded-md border border-border/60 px-3 py-1.5 text-xs text-muted-foreground hover:text-foreground"
          >
            <RefreshCw className="h-3.5 w-3.5" />
            刷新
          </button>
        }
      />

      {loading ? (
        <div
          className="flex min-h-[20vh] items-center justify-center gap-2 text-sm text-muted-foreground"
          aria-busy="true"
          aria-live="polite"
        >
          <Loader2 className="h-4 w-4 animate-spin" />
          正在加载决策待办…
        </div>
      ) : loadError ? (
        <div
          className="flex items-center gap-2 rounded-lg border border-red-500/30 bg-red-500/5 p-4 text-sm text-red-600"
          role="alert"
        >
          <AlertCircle className="h-4 w-4 shrink-0" />
          {loadError}
        </div>
      ) : snapshot ? (
        <>
          {!snapshot.canonical && (
            <div
              className="flex items-start gap-2 rounded-lg border border-amber-500/30 bg-amber-500/5 p-4 text-sm"
              role="status"
            >
              <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" />
              <div className="space-y-1">
                <p>决策待办暂不可用</p>
                {snapshotReasons && snapshotReasons.primary.length > 0 && (
                  <p className="text-xs text-muted-foreground">
                    {snapshotReasons.primary.join("；")}
                  </p>
                )}
                {snapshot.reason_codes.length > 0 && (
                  <details className="text-xs text-muted-foreground">
                    <summary className="cursor-pointer">技术详情</summary>
                    <p className="mt-1 font-mono">
                      {snapshot.reason_codes.map((code) => reasonCodeLabel(code)).join(" / ")}
                      {" · "}
                      {snapshot.reason_codes.join(" / ")}
                    </p>
                  </details>
                )}
              </div>
            </div>
          )}

          {isEmpty && (
            <div className="rounded-lg border border-dashed border-border/60 bg-card/50 px-6 py-10 text-center">
              <ClipboardList className="mx-auto h-5 w-5 text-muted-foreground" />
              <p className="mt-2 text-sm font-medium">暂无待办</p>
              <p className="mt-1 text-xs text-muted-foreground">
                当前没有待处理的持仓设置项或 Campaign。
              </p>
            </div>
          )}

          {snapshot.holding_setup_items.length > 0 && (
            <section className="space-y-3">
              <div>
                <h2 className="text-sm font-semibold">待建立 Campaign 的持仓</h2>
                <p className="mt-0.5 text-xs text-muted-foreground">
                  这些持仓还没有当前 Campaign，需要你显式创建。
                </p>
              </div>
              {snapshot.holding_setup_items.map((holding) => (
                <div
                  key={holding.security_code}
                  className="rounded-lg border border-border/60 border-l-2 border-l-amber-500/80 bg-card p-4 space-y-3"
                >
                  <div className="flex flex-wrap items-center gap-2 text-sm">
                    <span className="font-mono font-semibold">{holding.security_code}</span>
                    <span className="text-muted-foreground">{holding.security_name}</span>
                    <span className="rounded bg-amber-500/10 px-1.5 py-0.5 text-xs text-amber-700 dark:text-amber-400">
                      未分配 Campaign
                    </span>
                    {holding.next_workflow_action === "CREATE_CAMPAIGN"
                      && creatingFor !== holding.security_code && (
                      <button
                        type="button"
                        onClick={() => {
                          setCreatingFor(holding.security_code);
                          setFormGeneration((n) => n + 1);
                        }}
                        className="ml-auto inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90"
                      >
                        <PlusCircle className="h-3.5 w-3.5" />
                        创建 Campaign
                      </button>
                    )}
                  </div>
                  {creatingFor === holding.security_code && (
                    <CreateCampaignForm
                      key={`${holding.security_code}-${formGeneration}`}
                      holding={holding}
                      onCreated={handleCreated}
                      onClose={() => setCreatingFor(null)}
                    />
                  )}
                </div>
              ))}
            </section>
          )}

          {setupCampaigns.length > 0 && (
            <section className="space-y-3">
              <div>
                <h2 className="text-sm font-semibold">正在建立的 Campaign</h2>
                <p className="mt-0.5 text-xs text-muted-foreground">
                  草稿 / 研究中 / 待入场尚未进入当前 Campaign，需要逐步显式推进。
                </p>
              </div>
              {setupCampaigns.map((campaign) => (
                <CampaignLifecycleCard
                  key={campaign.campaign_id}
                  campaignId={campaign.campaign_id}
                  securityCode={campaign.security_code}
                  strategy={campaign.strategy}
                  status={campaign.status}
                  nextActions={nextActions[campaign.campaign_id] ?? null}
                  setupContext
                  onChanged={() => void refresh()}
                />
              ))}
            </section>
          )}

          {snapshot.campaign_items.length > 0 && (
            <section className="space-y-3">
              <div>
                <h2 className="text-sm font-semibold">当前 Campaign</h2>
                <p className="mt-0.5 text-xs text-muted-foreground">
                  仅进行中或减仓中属于当前期。这里不表示买卖建议已批准。
                </p>
              </div>
              {snapshot.campaign_items.map((item) => (
                <CampaignLifecycleCard
                  key={item.campaign_id}
                  campaignId={item.campaign_id}
                  securityCode={item.security_code}
                  strategy={item.strategy}
                  status={item.campaign_status}
                  nextActions={nextActions[item.campaign_id] ?? null}
                  setupContext={false}
                  decision={{
                    visible_state: item.visible_state,
                    reason_codes: item.reason_codes,
                  }}
                  onChanged={() => void refresh()}
                />
              ))}
            </section>
          )}

          <p className="text-xs text-muted-foreground">
            快照时间：{snapshot.as_of}（{snapshot.total_holdings} 持仓 / {snapshot.total_campaign_items} Campaign 项）
          </p>
        </>
      ) : (
        <div className="flex min-h-[20vh] items-center justify-center gap-2 text-sm text-muted-foreground">
          <ClipboardList className="h-4 w-4" />
          暂无数据
        </div>
      )}
    </div>
  );
}
