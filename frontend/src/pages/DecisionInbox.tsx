import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  PlusCircle,
  AlertCircle,
  Loader2,
  RefreshCw,
  ClipboardList,
  Trash2,
} from "lucide-react";
import { api } from "@/lib/api";
import type {
  CampaignNextActions,
  CampaignRecord,
  CampaignStrategy,
  DecisionInboxHoldingSetupItem,
  DecisionInboxSnapshot,
  PositionBootstrapInput,
  PositionBootstrapPreview,
  ResearchContinuity,
} from "@/lib/api/types";
import {
  CAMPAIGN_STRATEGIES,
  CAMPAIGN_STRATEGY_LABELS,
  collectHoldingUniverseSecurityCodes,
  presentReasonCodes,
  selectSetupCampaigns,
  createCampaignPayload,
  errorMessage,
  reasonCodeLabel,
  formalDecisionEvaluationStatus,
  formalDecisionNextSteps,
  FORMAL_DECISION_EVALUATION_UNKNOWN,
} from "@/lib/decisionInbox";
import {
  ANTI_BUY_NOTICE,
  CONFIRM_CHECKBOX_LABEL,
  PREFILL_NOTICE,
  canCommitBootstrap,
  canPreviewBootstrap,
  commitPayload,
  describeBootstrapCommitError,
  parseBootstrapInput,
  prefillPositionsFromPortfolio,
  previewInvalidated,
  shouldShowBootstrapCard,
} from "@/lib/positionBootstrap";
import type {
  BootstrapFormState,
  BootstrapPositionRow,
} from "@/lib/positionBootstrap";
import { CampaignLifecycleCard } from "@/components/campaign/CampaignLifecycleCard";
import { ResearchContinuityCard } from "@/components/campaign/ResearchContinuityCard";
import { CampaignThesisActivationCard } from "@/components/campaign/CampaignThesisActivationCard";
import { HardRiskPanel } from "@/components/campaign/HardRiskPanel";
import { DecisionActionPanel } from "@/components/campaign/DecisionActionPanel";
import { PageHeader } from "@/components/ui/PageHeader";

function DecisionCommitInboxStatus({
  campaignId,
  evaluation,
}: {
  campaignId: string;
  evaluation: string | null | undefined;
}) {
  const status = formalDecisionEvaluationStatus(evaluation);
  if (!status) return null;
  const steps = formalDecisionNextSteps(evaluation, campaignId);
  const evaluated = status === "EVALUATED";
  const unsupported = status === FORMAL_DECISION_EVALUATION_UNKNOWN;
  const statusMessage = unsupported
    ? "Formal Decision evaluation 不属于已知 backend contract，已停止导航。"
    : status === "NOT_EVALUATED"
      ? "尚未完成 Formal Decision 评估。"
      : status === "UNKNOWN"
        ? "当前无法评价 Formal Decision。"
        : status === "ERROR"
          ? "Formal Decision 评估读取失败。"
          : "已读取适用的 Frozen Decision。";
  return (
    <div
      className="space-y-3 rounded-lg border border-border/60 bg-background/35 p-3 text-xs"
      data-formal-decision-inbox-evaluation={evaluation}
      data-formal-decision-evaluation-status={status}
    >
      <div>
        <p className="font-medium">Formal Decision</p>
        <p className="mt-0.5 text-muted-foreground">
          当前 backend Decision Inbox snapshot：<span className="font-mono">{String(evaluation)}</span>
          {unsupported ? "（未知状态）" : `（${statusMessage}）`}
        </p>
        {unsupported ? (
          <p className="mt-1 font-mono text-[11px] text-muted-foreground">
            {FORMAL_DECISION_EVALUATION_UNKNOWN}
          </p>
        ) : (
          <p className="mt-1 text-muted-foreground">
            {statusMessage}
            {evaluated && "已有 Frozen Decision 不代表需要立刻 Freeze 新 Decision；以下入口均需由你显式选择。"}
          </p>
        )}
      </div>
      {steps.length > 0 && (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          {steps.map((step) => (
            <Link
              key={step.kind}
              to={step.href}
              data-testid={`formal-decision-next-step-${step.kind}`}
              className={step.kind === "review" ? "font-medium text-primary hover:underline" : "text-primary hover:underline"}
            >
              {step.label} →
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}

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
      onCreated(campaign);
    } catch (err: unknown) {
      setError(errorMessage(err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <form
      onSubmit={handleSubmit}
      className="rounded-lg border border-border/60 bg-background/40 p-4 space-y-3"
      data-testid="create-campaign-form"
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
                data-testid={`create-campaign-strategy-${value}`}
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
          data-testid="create-campaign-submit"
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

/**
 * P0-AB2 账户初始化激活卡：只在 canonical=false 且 reason 精确为
 * POSITION_LEDGER_NOT_BOOTSTRAPPED 时显示（由父级判定）。
 *
 * legacy portfolio 仅作预填建议；Preview 零写；Commit 必须复用产生当前
 * Preview 的同一份 input payload，且需要显式 checkbox 确认。
 * 成功 / 409 后立即刷新 Decision Inbox，绝不提供覆盖 / 重置。
 */
function BootstrapActivationCard({ onBootstrapped }: { onBootstrapped: () => void }) {
  const [form, setForm] = useState<BootstrapFormState>({
    ledger_start_at: "",
    opening_cash: "",
    note: "",
    positions: [],
  });
  const [prefilling, setPrefilling] = useState(true);
  const [prefillError, setPrefillError] = useState("");
  const [preview, setPreview] = useState<PositionBootstrapPreview | null>(null);
  const [previewedInput, setPreviewedInput] = useState<PositionBootstrapInput | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState<"preview" | "commit" | null>(null);
  const [error, setError] = useState("");

  // legacy portfolio 仅作为 BOOTSTRAP INPUT SUGGESTION：只读一次预填，
  // 绝不自动 commit、绝不写 portfolio.json。
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const portfolio = await api.portfolio();
        if (!cancelled) {
          setForm((prev) => (
            prev.positions.length === 0
              ? { ...prev, positions: prefillPositionsFromPortfolio(portfolio) }
              : prev
          ));
        }
      } catch (err: unknown) {
        if (!cancelled) setPrefillError(errorMessage(err));
      } finally {
        if (!cancelled) setPrefilling(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const currentInput = useMemo(() => parseBootstrapInput(form), [form]);
  const invalidated = previewInvalidated({
    preview,
    previewedInput,
    currentInput,
    confirmed,
  });
  // prefilling 未完成（portfolio 读取中）时 Commit 门 fail-closed：
  // 即使 preview 有效且已确认，也不得开放。
  const commitEnabled = !prefilling && canCommitBootstrap({
    preview,
    previewedInput,
    currentInput,
    confirmed,
  });

  const updatePosition = useCallback((index: number, patch: Partial<BootstrapPositionRow>) => {
    setForm((prev) => ({
      ...prev,
      positions: prev.positions.map((row, i) => (
        i === index ? { ...row, ...patch } : row
      )),
    }));
  }, []);

  const handlePreview = async () => {
    // 运行时 guard：prefilling 未完成（portfolio 预填进行中）时绝不允许发起 preview，
    // 即使按钮被绕过或事件被直接触发。
    if (prefilling || !currentInput) return;
    setBusy("preview");
    setError("");
    try {
      const result = await api.positionBootstrapPreview(currentInput);
      setPreview(result);
      setPreviewedInput(currentInput);
      // 新 preview 生成后必须重新显式确认
      setConfirmed(false);
    } catch (err: unknown) {
      setPreview(null);
      setPreviewedInput(null);
      setError(errorMessage(err));
    } finally {
      setBusy(null);
    }
  };

  const handleCommit = async () => {
    // 运行时 guard：prefilling 未完成（portfolio 预填进行中）时 Commit 门 fail-closed。
    if (prefilling) return;
    const payload = commitPayload({
      preview,
      previewedInput,
      currentInput,
      confirmed,
    });
    if (!payload) return;
    setBusy("commit");
    setError("");
    try {
      await api.positionBootstrapCommit(payload);
      // 成功后立即刷新 Decision Inbox，不停留在成功提示页
      onBootstrapped();
    } catch (err: unknown) {
      const desc = describeBootstrapCommitError(err);
      setError(desc.message);
      if (desc.conflict) {
        // 409：只提示 + 重新读取最新状态，绝不提供覆盖 / 重置
        onBootstrapped();
      }
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-4 space-y-4">
      <div className="space-y-1">
        <h2 className="text-sm font-semibold">初始化持仓事实</h2>
        <p className="text-xs leading-5 text-muted-foreground">
          账户事实尚未初始化：决策待办无法建立 canonical 持仓。
          请确认下方持仓快照并显式初始化；这不会自动创建 Campaign、投资逻辑或正式决策。
        </p>
      </div>

      {prefilling ? (
        <div className="flex items-center gap-2 text-xs text-muted-foreground" aria-busy="true">
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
          正在读取当前持仓…
        </div>
      ) : prefillError ? (
        <div
          className="flex items-center gap-2 rounded-md border border-amber-500/30 bg-amber-500/10 p-2 text-xs text-amber-700 dark:text-amber-400"
          role="alert"
        >
          <AlertCircle className="h-3.5 w-3.5 shrink-0" />
          无法读取当前持仓预填（{prefillError}），你可以手动填写持仓后继续。
        </div>
      ) : null}

      <div className="space-y-3">
        <div className="grid gap-3 sm:grid-cols-3">
          <div className="grid gap-1.5">
            <label className="text-xs font-medium text-muted-foreground" htmlFor="bootstrap-ledger-start">
              账本起始日期（必填）
            </label>
            <input
              id="bootstrap-ledger-start"
              type="date"
              value={form.ledger_start_at}
              onChange={(e) => setForm((prev) => ({ ...prev, ledger_start_at: e.target.value }))}
              className="rounded-md border border-border/60 bg-background px-2.5 py-1.5 text-sm"
            />
            <p className="text-[11px] text-muted-foreground">
              必须显式选择；不会根据持仓历史自动猜测。
            </p>
          </div>
          <div className="grid gap-1.5">
            <label className="text-xs font-medium text-muted-foreground" htmlFor="bootstrap-opening-cash">
              期初可用现金（可选）
            </label>
            <input
              id="bootstrap-opening-cash"
              type="number"
              min="0"
              step="any"
              value={form.opening_cash}
              onChange={(e) => setForm((prev) => ({ ...prev, opening_cash: e.target.value }))}
              placeholder="未知可留空"
              className="rounded-md border border-border/60 bg-background px-2.5 py-1.5 text-sm"
            />
            <p className="text-[11px] text-muted-foreground">不知道就留空，不会当作 0。</p>
          </div>
          <div className="grid gap-1.5">
            <label className="text-xs font-medium text-muted-foreground" htmlFor="bootstrap-note">
              备注（可选）
            </label>
            <input
              id="bootstrap-note"
              type="text"
              value={form.note}
              onChange={(e) => setForm((prev) => ({ ...prev, note: e.target.value }))}
              className="rounded-md border border-border/60 bg-background px-2.5 py-1.5 text-sm"
            />
          </div>
        </div>

        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-muted-foreground">
              持仓快照（必填；可修改 / 删除 / 新增）
            </span>
            <button
              type="button"
              onClick={() => setForm((prev) => ({
                ...prev,
                positions: [...prev.positions, { code: "", name: "", shares: "", cost_basis: "" }],
              }))}
              className="rounded-md border border-border/60 px-2.5 py-1 text-xs text-muted-foreground hover:text-foreground"
            >
              新增持仓
            </button>
          </div>
          <p className="text-[11px] text-muted-foreground">{PREFILL_NOTICE}</p>
          {form.positions.length === 0 ? (
            <p className="rounded-md border border-dashed border-border/60 px-3 py-4 text-center text-xs text-muted-foreground">
              暂无持仓行（可新增，或直接以零持仓初始化）。
            </p>
          ) : (
            <div className="space-y-2">
              {form.positions.map((row, index) => (
                <div
                  key={index}
                  className="grid grid-cols-[3rem_1fr_1fr_1fr_1fr_2rem] items-end gap-2 rounded-md border border-border/60 bg-background/40 p-2"
                >
                  <div className="grid gap-1">
                    <label className="text-[11px] text-muted-foreground">代码</label>
                    <input
                      type="text"
                      value={row.code}
                      onChange={(e) => updatePosition(index, { code: e.target.value })}
                      placeholder="6 位数字"
                      className="rounded-md border border-border/60 bg-background px-2 py-1 text-sm font-mono"
                      aria-label={`持仓 ${index + 1} 代码`}
                    />
                  </div>
                  <div className="grid gap-1">
                    <label className="text-[11px] text-muted-foreground">名称（可选）</label>
                    <input
                      type="text"
                      value={row.name}
                      onChange={(e) => updatePosition(index, { name: e.target.value })}
                      className="rounded-md border border-border/60 bg-background px-2 py-1 text-sm"
                      aria-label={`持仓 ${index + 1} 名称`}
                    />
                  </div>
                  <div className="grid gap-1">
                    <label className="text-[11px] text-muted-foreground">数量（股，整数）</label>
                    <input
                      type="number"
                      min="1"
                      step="1"
                      value={row.shares}
                      onChange={(e) => updatePosition(index, { shares: e.target.value })}
                      className="rounded-md border border-border/60 bg-background px-2 py-1 text-sm"
                      aria-label={`持仓 ${index + 1} 数量`}
                    />
                  </div>
                  <div className="grid gap-1">
                    <label className="text-[11px] text-muted-foreground">成本（每股，可选）</label>
                    <input
                      type="number"
                      min="0"
                      step="any"
                      value={row.cost_basis}
                      onChange={(e) => updatePosition(index, { cost_basis: e.target.value })}
                      placeholder="未知可留空"
                      className="rounded-md border border-border/60 bg-background px-2 py-1 text-sm"
                      aria-label={`持仓 ${index + 1} 成本`}
                    />
                  </div>
                  <button
                    type="button"
                    onClick={() => setForm((prev) => ({
                      ...prev,
                      positions: prev.positions.filter((_, i) => i !== index),
                    }))}
                    className="mb-1 rounded-md border border-border/60 p-1.5 text-muted-foreground hover:text-red-600"
                    aria-label={`删除持仓 ${index + 1}`}
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>

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
            type="button"
            onClick={() => void handlePreview()}
            disabled={prefilling || !canPreviewBootstrap(currentInput) || busy !== null}
            className="inline-flex items-center gap-1.5 rounded-md border border-border/60 px-3 py-1.5 text-xs font-medium text-foreground hover:bg-muted disabled:opacity-50"
          >
            {busy === "preview" && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
            预览初始化
          </button>
        </div>
      </div>

      {preview && (
        <div className="rounded-lg border border-border/60 bg-background/40 p-4 space-y-3" role="status">
          <p className="text-xs font-medium">初始化预览（尚未写入任何账户事实）</p>
          <dl className="grid gap-x-4 gap-y-1.5 text-xs sm:grid-cols-2">
            <div className="flex justify-between gap-2">
              <dt className="text-muted-foreground">账本开始日期</dt>
              <dd className="font-mono">{previewedInput?.ledger_start_at ?? "—"}</dd>
            </div>
            <div className="flex justify-between gap-2">
              <dt className="text-muted-foreground">Opening Cash</dt>
              <dd className="font-mono">
                {previewedInput?.opening_cash !== undefined
                  ? String(previewedInput.opening_cash)
                  : "未填写（未知）"}
              </dd>
            </div>
            <div className="flex justify-between gap-2">
              <dt className="text-muted-foreground">持仓数量</dt>
              <dd className="font-mono">{preview.positions.length}</dd>
            </div>
          </dl>
          <div className="space-y-1.5">
            {preview.positions.map((position) => (
              <div
                key={position.event_id}
                className="grid grid-cols-[1fr_auto] items-start gap-2 rounded-md border border-border/60 px-2.5 py-2 text-xs"
              >
                <div className="space-y-0.5">
                  <p>
                    <span className="font-mono font-semibold">{position.code}</span>
                    {position.name ? <span className="text-muted-foreground"> · {position.name}</span> : null}
                  </p>
                  <p className="text-muted-foreground">
                    数量 {position.shares} 股 · 成本（每股）{" "}
                    {position.cost_basis !== null ? String(position.cost_basis) : "未知"}
                  </p>
                </div>
                <div className="text-right text-muted-foreground">
                  <p>事实类型 = {position.event_type}</p>
                  <p>持仓来源 = {position.origin}</p>
                  <p>历史交易 = {position.historical_trades}</p>
                </div>
              </div>
            ))}
          </div>
          <p className="text-[11px] leading-5 text-muted-foreground">{ANTI_BUY_NOTICE}</p>
        </div>
      )}

      {preview && invalidated && (
        <p className="text-xs text-amber-700 dark:text-amber-400" role="status">
          表单已在预览后修改：确认初始化已禁用，请重新预览。
        </p>
      )}

      <div className="space-y-2 border-t border-border/60 pt-3">
        <label className="flex items-start gap-2 text-xs leading-5 text-muted-foreground">
          <input
            type="checkbox"
            checked={confirmed}
            onChange={(e) => setConfirmed(e.target.checked)}
            className="mt-0.5"
          />
          {CONFIRM_CHECKBOX_LABEL}
        </label>
        <button
          type="button"
          onClick={() => void handleCommit()}
          disabled={!commitEnabled || busy !== null}
          className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
        >
          {busy === "commit" && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
          确认初始化账户事实
        </button>
      </div>
    </div>
  );
}

export default function DecisionInbox() {
  const [snapshot, setSnapshot] = useState<DecisionInboxSnapshot | null>(null);
  const [setupCampaigns, setSetupCampaigns] = useState<CampaignRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [nextActions, setNextActions] = useState<Record<string, CampaignNextActions | null>>({});
  const [continuityByCampaign, setContinuityByCampaign] = useState<Record<string, ResearchContinuity | null>>({});
  const [creatingFor, setCreatingFor] = useState<string | null>(null);
  const [focusedSetupCampaignId, setFocusedSetupCampaignId] = useState<string | null>(null);
  const [formGeneration, setFormGeneration] = useState(0);
  const [thesisReloadEpoch, setThesisReloadEpoch] = useState(0);
  const refreshGenerationRef = useRef(0);

  const refresh = useCallback(async () => {
    const generation = ++refreshGenerationRef.current;
    const isCurrent = () => refreshGenerationRef.current === generation;
    setThesisReloadEpoch((epoch) => epoch + 1);
    setLoadError("");
    setNextActions({});
    setContinuityByCampaign({});
    try {
      const [snap, allCampaigns] = await Promise.all([
        api.getDecisionInbox(),
        api.listCampaigns(),
      ]);
      if (!isCurrent()) return;
      const universe = collectHoldingUniverseSecurityCodes(snap);
      const setup = selectSetupCampaigns(allCampaigns, universe);

      const ids = [
        ...snap.campaign_items.map((item) => item.campaign_id),
        ...setup.map((campaign) => campaign.campaign_id),
      ];
      const continuityIds = snap.campaign_items.map((item) => item.campaign_id);
      setSnapshot(snap);
      setSetupCampaigns(setup);
      setLoading(false);

      void Promise.all(
        ids.map(async (id) => {
          try {
            return [id, await api.getCampaignNextActions(id)] as const;
          } catch {
            return [id, null] as const;
          }
        }),
      ).then((entries) => {
        if (isCurrent()) setNextActions(Object.fromEntries(entries));
      });

      if (continuityIds.length) {
        void api.getResearchContinuityBatch(continuityIds)
          .then((batch) => {
            if (isCurrent()) setContinuityByCampaign(
              Object.fromEntries(continuityIds.map((campaignId) => [
                campaignId,
                batch.items.find((item) => item.campaign_id === campaignId) ?? null,
              ])),
            );
          })
          .catch(() => {
            if (isCurrent()) setContinuityByCampaign(
              Object.fromEntries(continuityIds.map((campaignId) => [campaignId, null])),
            );
          });
      }
    } catch (err: unknown) {
      if (isCurrent()) setLoadError(errorMessage(err));
    } finally {
      if (isCurrent()) setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
    return () => {
      refreshGenerationRef.current += 1;
    };
  }, [refresh]);

  const handleCreated = useCallback((campaign: CampaignRecord) => {
    setCreatingFor(null);
    setFocusedSetupCampaignId(campaign.campaign_id);
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (!focusedSetupCampaignId || !setupCampaigns.some((campaign) => campaign.campaign_id === focusedSetupCampaignId)) {
      return;
    }
    const target = Array.from(
      document.querySelectorAll<HTMLElement>("[data-campaign-setup-card]"),
    ).find((element) => element.dataset.campaignSetupCard === focusedSetupCampaignId);
    if (!target) return;
    target.scrollIntoView({ behavior: "smooth", block: "center" });
    const timeout = window.setTimeout(() => setFocusedSetupCampaignId(null), 5000);
    return () => window.clearTimeout(timeout);
  }, [focusedSetupCampaignId, setupCampaigns]);

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
            shouldShowBootstrapCard(snapshot) ? (
              <BootstrapActivationCard onBootstrapped={() => void refresh()} />
            ) : (
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
            )
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
                        data-testid={`decision-inbox-create-campaign-${holding.security_code}`}
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
              {setupCampaigns.map((campaign) => {
                const focused = focusedSetupCampaignId === campaign.campaign_id;
                return (
                  <div
                    key={campaign.campaign_id}
                    className={`space-y-2 rounded-lg transition-shadow ${focused ? "ring-2 ring-primary/60 ring-offset-2 ring-offset-background" : ""}`}
                    data-campaign-setup-card={campaign.campaign_id}
                    data-campaign-setup-focused={focused ? "true" : "false"}
                  >
                    {focused && (
                      <p
                        className="rounded-md bg-primary/10 px-3 py-2 text-xs font-medium text-primary"
                        data-testid="campaign-setup-continuation"
                      >
                        下一步从这里继续
                      </p>
                    )}
                  <CampaignLifecycleCard
                    campaignId={campaign.campaign_id}
                    securityCode={campaign.security_code}
                    strategy={campaign.strategy}
                    status={campaign.status}
                    nextActions={nextActions[campaign.campaign_id] ?? null}
                    setupContext
                    onChanged={() => void refresh()}
                  />
                    <CampaignThesisActivationCard
                      campaignId={campaign.campaign_id}
                      securityCode={campaign.security_code}
                      strategy={campaign.strategy}
                      reloadEpoch={thesisReloadEpoch}
                    />
                  </div>
                );
              })}
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
                <div key={item.campaign_id} className="space-y-2">
                  <CampaignLifecycleCard
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
                  <ResearchContinuityCard
                    campaignId={item.campaign_id}
                    prefetched={continuityByCampaign[item.campaign_id]}
                    awaitingPrefetch={!Object.prototype.hasOwnProperty.call(continuityByCampaign, item.campaign_id)}
                  />
                  <HardRiskPanel item={item} />
                  <DecisionActionPanel item={item} />
                  <DecisionCommitInboxStatus
                    campaignId={item.campaign_id}
                    evaluation={item.formal_decision_evaluation}
                  />
                  <CampaignThesisActivationCard
                    campaignId={item.campaign_id}
                    securityCode={item.security_code}
                    strategy={item.strategy}
                    reloadEpoch={thesisReloadEpoch}
                  />
                </div>
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
