import React, { useCallback, useEffect, useState } from "react";
import {
  Inbox,
  PlusCircle,
  AlertCircle,
  CheckCircle2,
  Loader2,
  RefreshCw,
  ClipboardList,
} from "lucide-react";
import { api } from "@/lib/api";
import type {
  CampaignNextActions,
  CampaignRecord,
  CampaignStatus,
  CampaignStrategy,
  DecisionInboxCampaignItem,
  DecisionInboxHoldingSetupItem,
  DecisionInboxSnapshot,
} from "@/lib/api/types";
import {
  CAMPAIGN_STRATEGIES,
  CAMPAIGN_STRATEGY_LABELS,
  CAMPAIGN_STATUS_LABELS,
  TRANSITION_ACTION_LABELS,
  createCampaignPayload,
  transitionPayload,
  errorMessage,
} from "@/lib/decisionInbox";

/** 创建表单：security_code 固定自 holding，strategy 必选，显式确认 DRAFT。 */
function CreateCampaignForm({
  holding,
  onCreated,
  onClose,
}: {
  holding: DecisionInboxHoldingSetupItem;
  onCreated: (campaign: CampaignRecord) => void;
  onClose: () => void;
}) {
  const [strategy, setStrategy] = useState<CampaignStrategy | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [created, setCreated] = useState<CampaignRecord | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!strategy) return; // strategy selection required
    setSubmitting(true);
    setError("");
    try {
      // payload 形状由 createCampaignPayload 保证：只含 security_code + strategy
      const { security_code, strategy: chosen } = createCampaignPayload(
        holding.security_code,
        strategy,
      );
      const campaign = await api.createCampaign(security_code, chosen);
      setCreated(campaign);
      onCreated(campaign);
    } catch (err: any) {
      // API 失败不伪造成功
      setError(errorMessage(err));
    } finally {
      setSubmitting(false);
    }
  };

  if (created) {
    return (
      <div className="rounded-lg border border-green-500/30 bg-green-500/5 p-4" role="status">
        <div className="flex items-start gap-2">
          <CheckCircle2 className="mt-0.5 h-4 w-4 text-green-600" />
          <div className="space-y-1 text-sm">
            <p className="font-medium">Campaign 已创建（状态：草稿）</p>
            <p className="text-muted-foreground">
              campaign_id：<code className="text-xs">{created.campaign_id}</code>
            </p>
            <p className="text-muted-foreground">
              strategy：{CAMPAIGN_STRATEGY_LABELS[created.strategy]} / status：{CAMPAIGN_STATUS_LABELS[created.status]}
            </p>
            <p className="text-xs text-muted-foreground">
              创建后为 DRAFT，不会自动激活；后续每一步 lifecycle 均需你显式操作。
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
      </div>
    );
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="rounded-lg border border-border/60 bg-card p-4 space-y-3"
    >
      <div className="grid gap-1.5">
        <label className="text-xs font-medium text-muted-foreground">证券代码（固定，不可修改）</label>
        <p className="text-sm font-mono">{holding.security_code}</p>
      </div>

      <div className="grid gap-1.5">
        <span className="text-xs font-medium text-muted-foreground">选择策略（必选）</span>
        <div className="flex gap-2">
          {CAMPAIGN_STRATEGIES.map((value) => (
            <label
              key={value}
              className={`flex-1 cursor-pointer rounded-md border px-3 py-2 text-center text-sm transition-colors ${
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

      <p className="text-xs text-muted-foreground">
        创建后状态为 DRAFT，不会自动激活。
      </p>

      {error && (
        <div className="flex items-center gap-2 rounded-md border border-red-500/30 bg-red-500/5 p-2 text-xs text-red-600" role="alert">
          <AlertCircle className="h-3.5 w-3.5 shrink-0" />
          {error}
        </div>
      )}

      <div className="flex gap-2">
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

/** Campaign 行：真实 status + 下一合法动作按钮（全部显式点击，绝不链式）。 */
function CampaignRow({
  item,
  actions,
  onChanged,
}: {
  item: DecisionInboxCampaignItem;
  actions: CampaignNextActions | null;
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState<CampaignStatus | null>(null);
  const [error, setError] = useState("");

  const handleTransition = async (to: CampaignStatus) => {
    if (!actions) return;
    setBusy(to);
    setError("");
    try {
      // payload 形状由 transitionPayload 保证：expected_status + to_status（CAS）
      const { expected_status, to_status } = transitionPayload(actions.status, to);
      await api.transitionCampaign(item.campaign_id, expected_status, to_status);
      onChanged();
    } catch (err: any) {
      // 409 等冲突如实显示 backend detail，绝不伪装成功
      setError(errorMessage(err));
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="rounded-lg border border-border/60 bg-card p-4 space-y-2">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="font-mono font-medium">{item.security_code}</span>
        <span className="rounded bg-muted px-1.5 py-0.5 text-xs text-muted-foreground">
          {CAMPAIGN_STRATEGY_LABELS[item.strategy]}
        </span>
        <span className="text-xs text-muted-foreground">{CAMPAIGN_STATUS_LABELS[item.campaign_status]}</span>
        <span className="ml-auto font-mono text-xs text-muted-foreground">{item.campaign_id}</span>
      </div>

      <div className="text-xs text-muted-foreground">
        决策状态：<span className="font-medium text-foreground">{item.visible_state}</span>
        {item.reason_codes.length > 0 && (
          <span className="ml-2">{item.reason_codes.join(" / ")}</span>
        )}
      </div>

      {actions && actions.next_actions.length > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs text-muted-foreground">下一合法动作：</span>
          {actions.next_actions.map((to) => (
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

      {actions && actions.next_actions.length === 0 && (
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

export default function DecisionInbox() {
  const [snapshot, setSnapshot] = useState<DecisionInboxSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [nextActions, setNextActions] = useState<Record<string, CampaignNextActions | null>>({});
  const [creatingFor, setCreatingFor] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoadError("");
    try {
      const snap = await api.getDecisionInbox();
      setSnapshot(snap);
      const entries = await Promise.all(
        snap.campaign_items.map(async (item) => {
          try {
            const actions = await api.getCampaignNextActions(item.campaign_id);
            return [item.campaign_id, actions] as const;
          } catch {
            return [item.campaign_id, null] as const;
          }
        }),
      );
      setNextActions(Object.fromEntries(entries));
    } catch (err: any) {
      setLoadError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const handleCreated = useCallback(() => {
    setCreatingFor(null);
    void refresh();
  }, [refresh]);

  return (
    <div className="space-y-6">
      {/* Page header */}
      <div className="flex items-center gap-3">
        <Inbox className="h-6 w-6 text-primary" />
        <div>
          <h1 className="text-xl font-bold">决策待办</h1>
          <p className="text-sm text-muted-foreground">
            未建立 Campaign 的持仓与已激活 Campaign 的决策状态（只读，所有变更经显式操作）
          </p>
        </div>
        <button
          type="button"
          onClick={() => void refresh()}
          className="ml-auto inline-flex items-center gap-1.5 rounded-md border border-border/60 px-3 py-1.5 text-xs text-muted-foreground hover:text-foreground"
        >
          <RefreshCw className="h-3.5 w-3.5" />
          刷新
        </button>
      </div>

      {loading ? (
        <div className="flex min-h-[20vh] items-center justify-center text-sm text-muted-foreground">
          加载中…
        </div>
      ) : loadError ? (
        <div className="flex items-center gap-2 rounded-lg border border-red-500/30 bg-red-500/5 p-4 text-sm text-red-600" role="alert">
          <AlertCircle className="h-4 w-4 shrink-0" />
          {loadError}
        </div>
      ) : snapshot ? (
        <>
          {!snapshot.canonical && (
            <div className="flex items-center gap-2 rounded-lg border border-amber-500/30 bg-amber-500/5 p-4 text-sm" role="status">
              <AlertCircle className="h-4 w-4 shrink-0 text-amber-600" />
              决策待办暂不可用：{snapshot.reason_codes.join(" / ")}
            </div>
          )}

          {snapshot.canonical && snapshot.holding_setup_items.length === 0 && snapshot.campaign_items.length === 0 && (
            <div className="rounded-lg border border-border/60 bg-card p-6 text-sm text-muted-foreground">
              当前没有待处理的持仓设置项或 Campaign。
            </div>
          )}

          {/* UNASSIGNED_HOLDING → CREATE_CAMPAIGN */}
          {snapshot.holding_setup_items.length > 0 && (
            <section className="space-y-3">
              <h2 className="text-sm font-semibold">待建立 Campaign 的持仓</h2>
              {snapshot.holding_setup_items.map((holding) => (
                <div key={holding.security_code} className="rounded-lg border border-border/60 bg-card p-4 space-y-3">
                  <div className="flex flex-wrap items-center gap-2 text-sm">
                    <span className="font-mono font-medium">{holding.security_code}</span>
                    <span className="text-muted-foreground">{holding.security_name}</span>
                    <span className="rounded bg-amber-500/10 px-1.5 py-0.5 text-xs text-amber-600">
                      未分配 Campaign
                    </span>
                    {holding.next_workflow_action === "CREATE_CAMPAIGN" && creatingFor !== holding.security_code && (
                      <button
                        type="button"
                        onClick={() => setCreatingFor(holding.security_code)}
                        className="ml-auto inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90"
                      >
                        <PlusCircle className="h-3.5 w-3.5" />
                        创建 Campaign
                      </button>
                    )}
                  </div>
                  {creatingFor === holding.security_code && (
                    <CreateCampaignForm
                      holding={holding}
                      onCreated={handleCreated}
                      onClose={() => setCreatingFor(null)}
                    />
                  )}
                </div>
              ))}
            </section>
          )}

          {/* campaign items */}
          {snapshot.campaign_items.length > 0 && (
            <section className="space-y-3">
              <h2 className="text-sm font-semibold">Campaign 决策项</h2>
              {snapshot.campaign_items.map((item) => (
                <CampaignRow
                  key={item.campaign_id}
                  item={item}
                  actions={nextActions[item.campaign_id] ?? null}
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
