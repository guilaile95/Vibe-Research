import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation } from "react-router-dom";
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
  CampaignStatus,
  CampaignStrategy,
  DecisionInboxCampaignItem,
  DecisionInboxHoldingSetupItem,
  DecisionInboxSnapshot,
  PositionBootstrapInput,
  PositionBootstrapPreview,
  ResearchContinuity,
} from "@/lib/api/types";
import {
  CAMPAIGN_STATUS_LABELS,
  CAMPAIGN_STRATEGIES,
  CAMPAIGN_STRATEGY_LABELS,
  collectHoldingUniverseSecurityCodes,
  presentReasonCodes,
  selectSetupCampaigns,
  createCampaignPayload,
  errorMessage,
  reasonCodeLabel,
  visibleStateLabel,
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
import { ResearchEventCalendar } from "@/components/campaign/ResearchEventCalendar";
import { CampaignThesisActivationCard } from "@/components/campaign/CampaignThesisActivationCard";
import { CampaignCommittedDecisionsCard } from "@/components/campaign/CampaignCommittedDecisionsCard";
import { HardRiskPanel } from "@/components/campaign/HardRiskPanel";
import { DecisionActionPanel } from "@/components/campaign/DecisionActionPanel";
import { PageHeader } from "@/components/ui/PageHeader";
import { storageGet, storageSet } from "@/lib/storage";

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
    ? "系统返回了无法识别的决策状态，已停止继续操作。"
    : status === "NOT_EVALUATED"
      ? "尚未完成决策评估。"
      : status === "UNKNOWN"
        ? "当前信息不足，暂时无法判断。"
        : status === "ERROR"
          ? "决策状态读取失败。"
          : "已有可用的正式决策。";
  return (
    <div
      className="space-y-3 rounded-lg border border-border/60 bg-background/35 p-3 text-xs"
      data-formal-decision-inbox-evaluation={evaluation}
      data-formal-decision-evaluation-status={status}
    >
      <div>
        <p className="font-medium">正式决策</p>
        <p className="mt-0.5 text-muted-foreground">当前决策状态：{statusMessage}</p>
        {unsupported ? (
          <details className="mt-1 text-[11px] text-muted-foreground">
            <summary className="cursor-pointer">技术详情</summary>
            <p className="mt-1 font-mono">{FORMAL_DECISION_EVALUATION_UNKNOWN} · {String(evaluation)}</p>
          </details>
        ) : (
          <p className="mt-1 text-muted-foreground">
            {evaluated && "这不代表需要立刻形成新决策；以下操作仍需由你明确选择。"}
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
          确认创建投资计划
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
          持仓记录尚未初始化，当前无法可靠生成决策待办。
          请确认下方持仓信息并明确初始化；这不会自动创建投资计划、投资逻辑或正式决策。
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
              <dt className="text-muted-foreground">期初现金</dt>
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

// ---------------------------------------------------------------------------
// IA 收敛（v1）：左侧紧凑工作列表 + 右侧当前选中对象。
//
// 铁律：
// - 列表身份按 Campaign（campaign_id），不是证券代码：同一证券的多个投资计划
//   各占一行，绝不合并；未建立投资计划的持仓沿用持仓身份（security_code），
//   不为它伪造 Campaign。
// - 分组恒为既有三类，标题与说明逐字保留；页签只是视图分区。
// - 选中只决定「右侧展示谁」，不产生任何写入；创建 / transition / Thesis /
//   正式决策仍走原有组件与原有页面入口。
// ---------------------------------------------------------------------------

/** 分组 key（纯视图分区，不是业务分类）。 */
type InboxGroupKey = "current" | "setup" | "unassigned";

/** 既有三个分组及其原文说明。 */
const INBOX_GROUPS: readonly {
  key: InboxGroupKey;
  label: string;
  description: string;
}[] = [
  {
    key: "current",
    label: "当前投资计划",
    description: "仅进行中或减仓中属于当前期。这里不表示买卖建议已批准。",
  },
  {
    key: "setup",
    label: "正在建立的投资计划",
    description: "草稿、研究中和待入场计划尚未生效，需要你逐步明确推进。",
  },
  {
    key: "unassigned",
    label: "尚未建立投资计划的持仓",
    description: "这些持仓还没有当前投资计划，需要你明确创建。",
  },
];

/** current / setup 投资计划条目：列表身份 = campaign_id。 */
interface CampaignEntry {
  kind: "campaign";
  group: "current" | "setup";
  campaignId: string;
  securityCode: string;
  strategy: CampaignStrategy;
  status: CampaignStatus;
  /** current 分组的 inbox 项；setup 分组为 null（阶段来自 campaigns 列表）。 */
  item: DecisionInboxCampaignItem | null;
}

/** 未建立投资计划的持仓条目：列表身份 = security_code（不伪造 Campaign）。 */
interface HoldingEntry {
  kind: "holding";
  group: "unassigned";
  securityCode: string;
  securityName: string;
  holding: DecisionInboxHoldingSetupItem;
}

type InboxEntry = CampaignEntry | HoldingEntry;

/** 右侧当前选中对象（只做展示选择）。 */
type InboxSelection = { kind: "campaign" | "holding"; id: string };

const INBOX_SELECTION_STORAGE_KEY = "vr-decision-inbox-selection";

/** 列表条目身份（用于 testid 与选中判定）。 */
function entryIdentity(entry: InboxEntry): string {
  return entry.kind === "campaign" ? entry.campaignId : entry.securityCode;
}

function entryKey(entry: InboxEntry): string {
  return entry.kind === "campaign"
    ? `campaign:${entry.campaignId}`
    : `holding:${entry.securityCode}`;
}

function selectionKey(selection: InboxSelection): string {
  return `${selection.kind}:${selection.id}`;
}

function selectionFor(entry: InboxEntry): InboxSelection {
  return entry.kind === "campaign"
    ? { kind: "campaign", id: entry.campaignId }
    : { kind: "holding", id: entry.securityCode };
}

/** 读取上次选中的对象；条目已不存在时由调用方回落到既有数据顺序。 */
function readStoredSelection(): InboxSelection | null {
  const raw = storageGet(INBOX_SELECTION_STORAGE_KEY);
  if (!raw) return null;
  const separator = raw.indexOf(":");
  if (separator <= 0) return null;
  const kind = raw.slice(0, separator);
  const id = raw.slice(separator + 1);
  if (!id || (kind !== "campaign" && kind !== "holding")) return null;
  return { kind, id };
}

/**
 * hash 深链（保持既有行为，命中后先选中再定位）：
 * - `#campaign-<campaign_id>`：事件日历的 Campaign 上下文入口。
 * - `#committed-decision-<campaign_id>-<decision_id>`：已提交决定详情的返回入口。
 */
function entryFromHash(hash: string, entries: readonly InboxEntry[]): InboxEntry | null {
  if (!hash.startsWith("#")) return null;
  let raw = hash.slice(1);
  try {
    raw = decodeURIComponent(raw);
  } catch {
    /* 非法百分号编码：按原样匹配 */
  }
  const prefix = raw.startsWith("committed-decision-")
    ? "committed-decision-"
    : raw.startsWith("campaign-")
      ? "campaign-"
      : null;
  if (!prefix) return null;
  const rest = raw.slice(prefix.length);
  const campaigns = entries.filter((entry): entry is CampaignEntry => entry.kind === "campaign");
  return campaigns.find(
    (entry) => rest === entry.campaignId || rest.startsWith(`${entry.campaignId}-`),
  ) ?? null;
}

/** 右侧小节标题：只新增小节标题，不替换任何组件内文案。 */
function DetailSection({
  title,
  testId,
  children,
}: {
  title: string;
  testId: string;
  children: React.ReactNode;
}) {
  return (
    <section className="space-y-2" data-testid={testId}>
      <h3 className="text-xs font-medium text-muted-foreground">{title}</h3>
      {children}
    </section>
  );
}

export default function DecisionInbox() {
  const location = useLocation();
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
  /** 显式切换过的分组；null = 尚未切换，按选中项或既有数据顺序落位。 */
  const [activeGroup, setActiveGroup] = useState<InboxGroupKey | null>(null);
  /** 选中对象：跨刷新保留；条目消失时回落到当前分组的既有数据顺序。 */
  const [selection, setSelection] = useState<InboxSelection | null>(readStoredSelection);
  /** 深链定位请求：先选中，再滚动到工作列表中的该条目。 */
  const [locateEntryId, setLocateEntryId] = useState<string | null>(null);
  const handledHashRef = useRef<string | null>(null);
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
    // 创建后直接选中新计划：右侧与工作列表都落在同一个对象上。
    setActiveGroup("setup");
    setSelection({ kind: "campaign", id: campaign.campaign_id });
    storageSet(
      INBOX_SELECTION_STORAGE_KEY,
      selectionKey({ kind: "campaign", id: campaign.campaign_id }),
    );
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

  // 工作列表条目：current / setup 按 campaign_id，holding 按 security_code；
  // 顺序沿用既有数据顺序，不做任何「优先级」排序或证券代码合并。
  const entriesByGroup = useMemo<Record<InboxGroupKey, InboxEntry[]>>(() => ({
    current: (snapshot?.campaign_items ?? []).map((item): CampaignEntry => ({
      kind: "campaign",
      group: "current",
      campaignId: item.campaign_id,
      securityCode: item.security_code,
      strategy: item.strategy,
      status: item.campaign_status,
      item,
    })),
    setup: setupCampaigns.map((campaign): CampaignEntry => ({
      kind: "campaign",
      group: "setup",
      campaignId: campaign.campaign_id,
      securityCode: campaign.security_code,
      strategy: campaign.strategy,
      status: campaign.status,
      item: null,
    })),
    unassigned: (snapshot?.holding_setup_items ?? []).map((holding): HoldingEntry => ({
      kind: "holding",
      group: "unassigned",
      securityCode: holding.security_code,
      securityName: holding.security_name,
      holding,
    })),
  }), [snapshot, setupCampaigns]);

  const allEntries = useMemo(
    () => [...entriesByGroup.current, ...entriesByGroup.setup, ...entriesByGroup.unassigned],
    [entriesByGroup],
  );

  // 默认落位：优先「上次选中的对象仍存在」，否则按既有数据顺序取第一个非空分组。
  const defaultGroup = useMemo(
    () => INBOX_GROUPS.find((group) => entriesByGroup[group.key].length > 0)?.key ?? "current",
    [entriesByGroup],
  );
  const storedEntry = useMemo(() => {
    const key = selection ? selectionKey(selection) : "";
    return key ? allEntries.find((entry) => entryKey(entry) === key) ?? null : null;
  }, [allEntries, selection]);
  const resolvedGroup = activeGroup ?? storedEntry?.group ?? defaultGroup;
  const groupEntries = entriesByGroup[resolvedGroup];
  const activeEntry = useMemo<InboxEntry | null>(() => {
    const key = selection ? selectionKey(selection) : "";
    return (key ? groupEntries.find((entry) => entryKey(entry) === key) : undefined)
      ?? groupEntries[0]
      ?? null;
  }, [groupEntries, selection]);

  // 选中对象跨分组变化（例如草稿 → 进行中）时页签跟随它，
  // 避免刷新后停在已不再包含它的分组。
  const selectionGroupRef = useRef<InboxGroupKey | null>(null);
  useEffect(() => {
    if (!storedEntry) return;
    const previous = selectionGroupRef.current;
    selectionGroupRef.current = storedEntry.group;
    if (previous !== null && previous !== storedEntry.group) {
      setActiveGroup(storedEntry.group);
    }
  }, [storedEntry]);

  /** 切换选中对象：只改展示选择，不触发任何请求或写入。 */
  const selectEntry = useCallback((entry: InboxEntry) => {
    const next = selectionFor(entry);
    setSelection(next);
    setActiveGroup(entry.group);
    storageSet(INBOX_SELECTION_STORAGE_KEY, selectionKey(next));
  }, []);

  // hash 深链：命中时先选中对应投资计划（并切到它所在分组），再定位。
  useEffect(() => {
    const hash = location.hash;
    if (!snapshot || !hash || handledHashRef.current === hash) return;
    const target = entryFromHash(hash, allEntries);
    if (!target) return;
    handledHashRef.current = hash;
    selectEntry(target);
    setLocateEntryId(entryIdentity(target));
  }, [location.hash, snapshot, allEntries, selectEntry]);

  useEffect(() => {
    if (!locateEntryId) return;
    const target = document.querySelector<HTMLElement>(
      `[data-testid="decision-inbox-item-${locateEntryId}"]`,
    );
    if (!target) return;
    setLocateEntryId(null);
    target.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [locateEntryId, activeEntry]);

  const isEmpty =
    snapshot?.canonical
    && snapshot.holding_setup_items.length === 0
    && snapshot.campaign_items.length === 0
    && setupCampaigns.length === 0;

  const snapshotReasons = snapshot ? presentReasonCodes(snapshot.reason_codes) : null;
  const groupMeta = INBOX_GROUPS.find((group) => group.key === resolvedGroup) ?? INBOX_GROUPS[0];
  const focusedEntry =
    focusedSetupCampaignId !== null
    && activeEntry?.kind === "campaign"
    && activeEntry.campaignId === focusedSetupCampaignId;
  const detailAnchorId =
    activeEntry?.kind === "campaign" ? `campaign-${activeEntry.campaignId}` : undefined;
  const activeHoldingReasonLabels =
    activeEntry?.kind === "holding"
      ? presentReasonCodes(activeEntry.holding.reason_codes ?? []).details.map((item) => item.label)
      : [];

  /** 左列表的「已有原因摘要」：只摘既有 visible_state 与 reason code 文案。 */
  const reasonSummaryFor = (entry: InboxEntry): string => {
    const codes = entry.kind === "campaign"
      ? entry.item?.reason_codes ?? []
      : entry.holding.reason_codes ?? [];
    const stateLabel = entry.kind === "campaign" && entry.item
      ? visibleStateLabel(entry.item.visible_state)
      : "";
    return [stateLabel, ...presentReasonCodes(codes).primary].filter(Boolean).join(" · ");
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="决策待办"
        subtitle="查看尚未建立、正在研究和当前有效的投资计划。创建及每一步状态变更都需要你明确确认，不会自动推进。"
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

          {/* 真实空列表：只有 canonical 且三类都为 0 才是空，绝不用它掩盖初始化状态 */}
          {snapshot.canonical && isEmpty && (
            <div className="rounded-lg border border-dashed border-border/60 bg-card/50 px-6 py-10 text-center">
              <ClipboardList className="mx-auto h-5 w-5 text-muted-foreground" />
              <p className="mt-2 text-sm font-medium">暂无待办</p>
              <p className="mt-1 text-xs text-muted-foreground">
                当前没有待处理的持仓设置项或投资计划。
              </p>
            </div>
          )}

          {snapshot.canonical && !isEmpty && (
            <>
              {/* 分组页签：纯视图切换，不写业务状态、不触发任何动作。 */}
              <div
                className="flex flex-wrap gap-1 rounded-xl border border-border/60 bg-muted/20 p-1"
                role="tablist"
                aria-label="决策待办分组"
              >
                {INBOX_GROUPS.map((group) => (
                  <button
                    key={group.key}
                    type="button"
                    role="tab"
                    id={`decision-inbox-tab-${group.key}`}
                    aria-selected={resolvedGroup === group.key}
                    aria-controls="decision-inbox-tabpanel"
                    data-testid={`decision-inbox-tab-${group.key}`}
                    onClick={() => {
                      // 页签只切换视图；同时把选中对象落到该分组既有顺序的第一个，
                      // 让「列表高亮 = 右侧预览 = 刷新后落点」保持一致。
                      setActiveGroup(group.key);
                      const first = entriesByGroup[group.key][0];
                      if (first) selectEntry(first);
                    }}
                    className={`rounded-lg px-3 py-1.5 text-sm ${
                      resolvedGroup === group.key
                        ? "bg-background font-medium shadow-sm"
                        : "text-muted-foreground hover:text-foreground"
                    }`}
                  >
                    {group.label}
                  </button>
                ))}
              </div>

              <div
                id="decision-inbox-tabpanel"
                role="tabpanel"
                aria-labelledby={`decision-inbox-tab-${resolvedGroup}`}
                className="space-y-4"
              >
                <div>
                  <h2 className="text-sm font-semibold">{groupMeta.label}</h2>
                  <p className="mt-0.5 text-xs text-muted-foreground">{groupMeta.description}</p>
                </div>

                {/* 视口 ≥1350px（扣除展开侧栏与页面内边距后仍有 ~1100px）才分两栏；
                    更窄时单栏堆叠：工作列表在上、选中对象在下。 */}
                <div className="grid min-w-0 gap-4 min-[1350px]:grid-cols-[360px_minmax(0,1fr)] min-[1350px]:items-start">
                  <div
                    role="listbox"
                    aria-label={`${groupMeta.label}工作列表`}
                    data-testid="decision-inbox-worklist"
                    className="min-w-0 space-y-2"
                  >
                    {groupEntries.length === 0 ? (
                      <p className="rounded-lg border border-dashed border-border/60 px-3 py-6 text-center text-xs text-muted-foreground">
                        该分组当前没有对象。
                      </p>
                    ) : groupEntries.map((entry) => {
                      const selected = activeEntry !== null
                        && entryKey(activeEntry) === entryKey(entry);
                      const summary = reasonSummaryFor(entry);
                      return (
                        <button
                          key={entryKey(entry)}
                          type="button"
                          role="option"
                          aria-selected={selected}
                          data-testid={`decision-inbox-item-${entryIdentity(entry)}`}
                          data-item-kind={entry.kind}
                          data-item-group={entry.group}
                          data-selected={selected ? "true" : "false"}
                          onClick={() => selectEntry(entry)}
                          className={`w-full rounded-lg border px-3 py-2 text-left transition-colors ${
                            selected
                              ? "border-primary/60 bg-primary/5"
                              : "border-border/60 bg-card hover:border-primary/40"
                          }`}
                        >
                          <div className="flex flex-wrap items-center gap-2">
                            <span className="font-mono text-sm font-semibold">
                              {entry.securityCode}
                            </span>
                            {entry.kind === "campaign" ? (
                              <>
                                <span className="rounded-md bg-muted px-1.5 py-0.5 text-xs font-medium">
                                  {CAMPAIGN_STRATEGY_LABELS[entry.strategy]}
                                </span>
                                <span
                                  className={`rounded-md px-1.5 py-0.5 text-xs font-medium ${
                                    entry.group === "setup"
                                      ? "bg-amber-500/10 text-amber-700 dark:text-amber-400"
                                      : "bg-foreground/10 text-foreground"
                                  }`}
                                >
                                  {CAMPAIGN_STATUS_LABELS[entry.status]}
                                </span>
                              </>
                            ) : (
                              <span className="rounded bg-amber-500/10 px-1.5 py-0.5 text-xs text-amber-700 dark:text-amber-400">
                                尚无投资计划
                              </span>
                            )}
                          </div>
                          {entry.kind === "holding" && entry.securityName && (
                            <span className="mt-0.5 block truncate text-xs text-muted-foreground">
                              {entry.securityName}
                            </span>
                          )}
                          {summary && (
                            <span className="mt-1 block truncate text-xs text-muted-foreground">
                              {summary}
                            </span>
                          )}
                        </button>
                      );
                    })}
                  </div>

                  {/* 右：当前选中对象（只读预览；正式决策仍走原有页面入口） */}
                  <div
                    data-testid="decision-inbox-detail"
                    id={detailAnchorId}
                    data-campaign-setup-card={focusedEntry ? (focusedSetupCampaignId ?? undefined) : undefined}
                    data-campaign-setup-focused={focusedEntry ? "true" : "false"}
                    className={`min-w-0 space-y-4 ${
                      focusedEntry
                        ? "rounded-lg ring-2 ring-primary/60 ring-offset-2 ring-offset-background"
                        : ""
                    }`}
                  >
                    {activeEntry === null ? (
                      <p className="rounded-lg border border-dashed border-border/60 px-3 py-10 text-center text-xs text-muted-foreground">
                        当前没有选中的对象。
                      </p>
                    ) : (
                      <>
                        <section
                          className="space-y-2 rounded-lg border border-border/60 bg-card p-4"
                          data-testid="decision-inbox-detail-identity"
                        >
                          <div className="flex flex-wrap items-center gap-2">
                            <span className="font-mono text-sm font-semibold">
                              {activeEntry.securityCode}
                            </span>
                            {activeEntry.kind === "holding" && activeEntry.securityName && (
                              <span className="min-w-0 truncate text-sm text-muted-foreground">
                                {activeEntry.securityName}
                              </span>
                            )}
                            {activeEntry.kind === "campaign" ? (
                              <>
                                <span className="rounded-md bg-muted px-1.5 py-0.5 text-xs font-medium">
                                  {CAMPAIGN_STRATEGY_LABELS[activeEntry.strategy]}
                                </span>
                                <span
                                  className={`rounded-md px-1.5 py-0.5 text-xs font-medium ${
                                    activeEntry.group === "setup"
                                      ? "bg-amber-500/10 text-amber-700 dark:text-amber-400"
                                      : "bg-foreground/10 text-foreground"
                                  }`}
                                >
                                  {CAMPAIGN_STATUS_LABELS[activeEntry.status]}
                                </span>
                              </>
                            ) : (
                              <span className="rounded bg-amber-500/10 px-1.5 py-0.5 text-xs text-amber-700 dark:text-amber-400">
                                尚无投资计划
                              </span>
                            )}
                            <span className="rounded-md border border-border/60 px-1.5 py-0.5 text-[11px] text-muted-foreground">
                              {groupMeta.label}
                            </span>
                          </div>
                          {activeEntry.kind === "campaign" && (
                            <details className="text-[10px] text-muted-foreground">
                              <summary className="cursor-pointer select-none hover:text-foreground">
                                技术详情
                              </summary>
                              <p className="mt-1 font-mono">campaign_id：{activeEntry.campaignId}</p>
                            </details>
                          )}
                          {focusedEntry && (
                            <p
                              className="rounded-md bg-primary/10 px-3 py-2 text-xs font-medium text-primary"
                              data-testid="campaign-setup-continuation"
                            >
                              下一步从这里继续
                            </p>
                          )}
                        </section>

                        <DetailSection
                          title="已有状态与限制"
                          testId="decision-inbox-detail-status"
                        >
                          {activeEntry.kind === "campaign" ? (
                            <div className="space-y-3">
                              <CampaignLifecycleCard
                                campaignId={activeEntry.campaignId}
                                securityCode={activeEntry.securityCode}
                                strategy={activeEntry.strategy}
                                status={activeEntry.status}
                                nextActions={nextActions[activeEntry.campaignId] ?? null}
                                setupContext={activeEntry.group === "setup"}
                                decision={activeEntry.item ? {
                                  visible_state: activeEntry.item.visible_state,
                                  reason_codes: activeEntry.item.reason_codes,
                                } : undefined}
                                onChanged={() => void refresh()}
                                // 详情头已是本列唯一的选中对象身份，卡片不再重复代码/策略/阶段。
                                showIdentity={false}
                              />
                              {activeEntry.item && <HardRiskPanel item={activeEntry.item} />}
                            </div>
                          ) : (
                            <div className="space-y-1.5 rounded-lg border border-border/60 border-l-2 border-l-amber-500/80 bg-card p-4 text-xs leading-5 text-muted-foreground">
                              {activeHoldingReasonLabels.length > 0 ? (
                                <ul className="space-y-0.5">
                                  {activeHoldingReasonLabels.map((label) => (
                                    <li key={label}>{label}</li>
                                  ))}
                                </ul>
                              ) : (
                                <p>尚无投资计划</p>
                              )}
                            </div>
                          )}
                        </DetailSection>

                        {/* 原操作入口：只呈现当前选中对象的入口，全部需要你明确点击。
                            位置在「已有状态与限制」之后、「研究连续性 / 投资逻辑 / 历史正式决定」之前。 */}
                        <section
                          className="space-y-3 rounded-lg border border-primary/30 bg-primary/5 p-4"
                          data-testid="decision-inbox-actions"
                        >
                          <div>
                            <h3 className="text-sm font-semibold">操作入口</h3>
                            <p className="mt-0.5 text-xs leading-5 text-muted-foreground">
                              只呈现当前选中对象的入口；切换对象或分组不会执行任何操作，
                              创建、状态变更与激活都需要你明确点击。
                            </p>
                          </div>
                          {activeEntry.kind === "holding" ? (
                            <>
                              {activeEntry.holding.next_workflow_action === "CREATE_CAMPAIGN"
                                && creatingFor !== activeEntry.securityCode && (
                                <button
                                  type="button"
                                  data-testid={`decision-inbox-create-campaign-${activeEntry.securityCode}`}
                                  onClick={() => {
                                    setCreatingFor(activeEntry.securityCode);
                                    setFormGeneration((n) => n + 1);
                                  }}
                                  className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90"
                                >
                                  <PlusCircle className="h-3.5 w-3.5" />
                                  创建投资计划
                                </button>
                              )}
                              {creatingFor === activeEntry.securityCode && (
                                <CreateCampaignForm
                                  key={`${activeEntry.securityCode}-${formGeneration}`}
                                  holding={activeEntry.holding}
                                  onCreated={handleCreated}
                                  onClose={() => setCreatingFor(null)}
                                />
                              )}
                            </>
                          ) : activeEntry.item ? (
                            <DecisionCommitInboxStatus
                              campaignId={activeEntry.campaignId}
                              evaluation={activeEntry.item.formal_decision_evaluation}
                            />
                          ) : (
                            <p className="text-xs leading-5 text-muted-foreground">
                              这项投资计划尚未生效，当前没有可执行的正式决策入口。
                            </p>
                          )}
                        </section>

                        {activeEntry.kind === "campaign" && activeEntry.item && (
                          <DetailSection title="研究连续性" testId="decision-inbox-detail-continuity">
                            <ResearchContinuityCard
                              campaignId={activeEntry.campaignId}
                              prefetched={continuityByCampaign[activeEntry.campaignId]}
                              awaitingPrefetch={!Object.prototype.hasOwnProperty.call(
                                continuityByCampaign,
                                activeEntry.campaignId,
                              )}
                            />
                          </DetailSection>
                        )}

                        {activeEntry.kind === "campaign" && (
                          <DetailSection title="投资逻辑" testId="decision-inbox-detail-thesis">
                            <CampaignThesisActivationCard
                              campaignId={activeEntry.campaignId}
                              securityCode={activeEntry.securityCode}
                              strategy={activeEntry.strategy}
                              reloadEpoch={thesisReloadEpoch}
                            />
                          </DetailSection>
                        )}

                        {activeEntry.kind === "campaign" && (
                          <DetailSection title="历史正式决定" testId="decision-inbox-detail-history">
                            <div className="space-y-3">
                              {activeEntry.item && <DecisionActionPanel item={activeEntry.item} />}
                              <CampaignCommittedDecisionsCard
                                campaignId={activeEntry.campaignId}
                                securityCode={activeEntry.securityCode}
                                strategy={activeEntry.strategy}
                              />
                            </div>
                          </DetailSection>
                        )}
                      </>
                    )}
                  </div>
                </div>
              </div>
            </>
          )}

        </>
      ) : (
        <div className="flex min-h-[20vh] items-center justify-center gap-2 text-sm text-muted-foreground">
          <ClipboardList className="h-4 w-4" />
          暂无数据
        </div>
      )}

      {/* 研究事件日历：保持可达但排在待办工作区之后；它独立加载，
          读取失败只在本区域呈现，不代表决策待办整体不可用。 */}
      <section
        data-testid="decision-inbox-research-calendar"
        aria-label="研究事件日历"
        className="space-y-3 border-t border-border/60 pt-4"
      >
        <p className="text-xs text-muted-foreground">
          研究事件日历独立加载，读取失败只影响本区域，不代表决策待办不可用。
        </p>
        <ResearchEventCalendar reloadEpoch={thesisReloadEpoch} />
      </section>

      {snapshot && (
        <p className="text-xs text-muted-foreground">
          数据更新时间：{snapshot.as_of}（{snapshot.total_holdings} 个持仓 / {snapshot.total_campaign_items} 个投资计划）
        </p>
      )}
    </div>
  );
}
