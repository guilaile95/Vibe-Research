import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { AlertCircle, ArrowLeft, CheckCircle2, Loader2, LockKeyhole } from "lucide-react";
import { PageHeader } from "@/components/ui/PageHeader";
import { ApiError, CommittedDecisionReadError, api, DECISION_CHALLENGE_DIMENSIONS, type DecisionChallengeDimensionInput, type DecisionChallengeDimensionName, type DecisionChallengePacket, type DecisionProposalDraftInput, type DecisionProposalPreview, type CommittedDecisionRuntimeRead } from "@/lib/api";
import { VIEW_STANCE_LABELS, VIEW_STANCE_OPTIONS, buildJudgedView, buildPortfolioView, type ViewStance } from "@/lib/decisionProposalForm";
import { hydratedHorizonValue, resolveDecisionContext, type DecisionContextHydrationResult } from "@/lib/decisionContextHydration";
import { browserTimeZoneName, formatUtcOffsetMinutes, parseReviewBoundary } from "@/lib/reviewBoundaryInput";
import { buildEvaluatedTradeContinuationHref } from "@/lib/tradeContinuation";
import type { CampaignRecord, CampaignThesisBinding, CampaignCurrentThesis, ThesisAggregate } from "@/lib/api";

type ChallengeReadState = "PENDING" | "FOUND" | "ABSENT" | "ERROR";

const challengeLabels: Record<DecisionChallengeDimensionName, string> = {
  STRONGEST_SUPPORTING_EVIDENCE: "Strongest supporting evidence",
  STRONGEST_OPPOSING_EVIDENCE: "Strongest opposing evidence",
  PRE_MORTEM: "Pre-mortem",
  INVALIDATION_FACTS: "Invalidation facts",
};

const emptyChallenge = (): Record<DecisionChallengeDimensionName, DecisionChallengeDimensionInput> => ({
  STRONGEST_SUPPORTING_EVIDENCE: { status: "ANSWERED", text: "" },
  STRONGEST_OPPOSING_EVIDENCE: { status: "ANSWERED", text: "" },
  PRE_MORTEM: { status: "ANSWERED", text: "" },
  INVALIDATION_FACTS: { status: "ANSWERED", text: "" },
});

const inputCls = "mt-1 w-full rounded-md border border-border/60 bg-background px-2.5 py-2 text-sm outline-none focus:border-primary/60";
const codeCls = "rounded bg-muted/60 px-1.5 py-0.5 font-mono text-[11px]";

function splitLines(value: string): string[] {
  return value
    .split(/[,\n]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function evaluationOf(value: unknown): string {
  if (!value || typeof value !== "object") return "NOT_EVALUATED";
  const record = value as {
    evaluation?: unknown;
    critical_data_evaluation?: unknown;
    hard_risk_evaluation?: unknown;
    material_change_evaluation?: unknown;
    sell_evaluation?: unknown;
  };
  const evaluation = record.evaluation
    ?? record.critical_data_evaluation
    ?? record.hard_risk_evaluation
    ?? record.material_change_evaluation
    ?? record.sell_evaluation;
  return typeof evaluation === "string" ? evaluation : "NOT_EVALUATED";
}

function authorityLabel(evaluation: string): string {
  if (evaluation === "EVALUATED") return "已评估";
  if (evaluation === "UNKNOWN") return "未知";
  if (evaluation === "ERROR") return "错误";
  return "未评估";
}

function stringList(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : [];
}

function shortestReason(value: unknown): string {
  if (!value || typeof value !== "object") return "—";
  const record = value as Record<string, unknown>;
  const reasons = stringList(record.reason_codes ?? record.reasons);
  return reasons[0] ?? "—";
}

export function DecisionProposalReview() {
  const { campaignId = "" } = useParams();
  const navigate = useNavigate();
  // 三视图结构化输入（P1-DF1）：用户通过 select/text 控件表达判断，
  // payload 由 decisionProposalForm 纯函数生成，不再手写 JSON。
  const [assetStance, setAssetStance] = useState<ViewStance>("WAIT");
  const [assetNote, setAssetNote] = useState("");
  const [tradeStance, setTradeStance] = useState<ViewStance>("WAIT");
  const [tradeNote, setTradeNote] = useState("");
  const [portfolioConstraint, setPortfolioConstraint] = useState("");
  const [reviewByLocal, setReviewByLocal] = useState("");
  const [horizon, setHorizon] = useState("");
  const [campaign, setCampaign] = useState<CampaignRecord | null>(null);
  const [binding, setBinding] = useState<CampaignThesisBinding | null>(null);
  const [currentThesis, setCurrentThesis] = useState<CampaignCurrentThesis | null>(null);
  const [boundThesis, setBoundThesis] = useState<ThesisAggregate | null>(null);
  const [contextState, setContextState] = useState<"loading" | "ready" | "unavailable">("loading");
  const [contextMessage, setContextMessage] = useState("");
  const [hydration, setHydration] = useState<DecisionContextHydrationResult | null>(null);
  const horizonTouched = useRef(false);
  const contextGeneration = useRef(0);
  const [assumptions, setAssumptions] = useState("");
  const [invalidations, setInvalidations] = useState("");
  const [preview, setPreview] = useState<DecisionProposalPreview | null>(null);
  const [committed, setCommitted] = useState<CommittedDecisionRuntimeRead | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState<"preview" | "commit" | "challenge" | null>(null);
  const [error, setError] = useState("");
  const [challengeDraft, setChallengeDraft] = useState(emptyChallenge);
  const [challengeConfirmed, setChallengeConfirmed] = useState(false);
  const [challengePacket, setChallengePacket] = useState<DecisionChallengePacket | null>(null);
  const [challengeReadState, setChallengeReadState] = useState<ChallengeReadState>("ABSENT");
  const [bindChallenge, setBindChallenge] = useState(false);

  useEffect(() => {
    const generation = ++contextGeneration.current;
    let cancelled = false;
    setContextState("loading");
    setContextMessage("");
    setCampaign(null);
    setBinding(null);
    setCurrentThesis(null);
    setBoundThesis(null);
    setHydration(null);
    horizonTouched.current = false;

    if (!campaignId) {
      setContextState("unavailable");
      setContextMessage("缺少 campaign_id；无法读取 Campaign authority。");
      return () => {
        cancelled = true;
        contextGeneration.current += 1;
      };
    }

    void (async () => {
      try {
        const nextCampaign = await api.getCampaign(campaignId);
        const nextBinding = await api.getCampaignThesisBinding(campaignId);
        const [nextCurrent, nextAggregate] = await Promise.all([
          api.getCampaignCurrentThesis(campaignId),
          api.thesisGet(nextBinding.thesis_id),
        ]);
        if (cancelled || generation !== contextGeneration.current) return;
        const result = resolveDecisionContext(nextCampaign, nextBinding, nextCurrent, nextAggregate);
        setCampaign(nextCampaign);
        setBinding(nextBinding);
        setCurrentThesis(nextCurrent);
        setBoundThesis(nextAggregate);
        setHydration(result);
        if (result.status === "READY") {
          setContextState("ready");
          setContextMessage("");
          setHorizon((value) => hydratedHorizonValue(value, horizonTouched.current, result));
        } else {
          setContextState("unavailable");
          setContextMessage(result.reason);
        }
      } catch (err) {
        if (cancelled || generation !== contextGeneration.current) return;
        setContextState("unavailable");
        setContextMessage(err instanceof ApiError ? err.message : "Campaign / Current Thesis authority 读取失败");
      }
    })();

    return () => {
      cancelled = true;
      contextGeneration.current += 1;
    };
  }, [campaignId]);

  // P1-DF3：review boundary 只来自用户在 datetime-local 控件里的显式选择；
  // 过去时间等业务校验仍由 backend Preview authority 负责，这里不复制规则。
  const reviewBoundary = useMemo(() => parseReviewBoundary(reviewByLocal), [reviewByLocal]);

  const draft = useMemo<DecisionProposalDraftInput | null>(() => {
    if (reviewBoundary.status !== "VALID" || !horizon.trim()) return null;
    return {
      asset_view: buildJudgedView("ASSET", assetStance, assetNote),
      trade_view: buildJudgedView("TRADE", tradeStance, tradeNote),
      portfolio_view: buildPortfolioView(portfolioConstraint),
      review_by: reviewBoundary.iso,
      key_assumptions: splitLines(assumptions),
      event_invalidation_conditions: splitLines(invalidations),
      strategy_horizon: horizon.trim(),
    };
  }, [assetStance, assetNote, tradeStance, tradeNote, portfolioConstraint, reviewBoundary, horizon, assumptions, invalidations]);

  const handlePreview = async () => {
    setError("");
    setCommitted(null);
    setConfirmed(false);
    setPreview(null);
    setChallengePacket(null);
    setChallengeReadState("PENDING");
    setChallengeConfirmed(false);
    setBindChallenge(false);
    if (!campaignId || !draft) {
      setChallengeReadState("ERROR");
      setError("请先选择有效的 review 时间、填写 strategy horizon，并确保三个 View 输入合法。");
      return;
    }
    setBusy("preview");
    try {
      const next = await api.previewDecisionProposal(campaignId, draft);
      setPreview(next);
      try {
        const existing = await api.getDecisionChallengeForProposal(campaignId, next.proposal_fingerprint);
        if (existing) {
          setChallengePacket(existing.challenge);
          setChallengeReadState("FOUND");
          setBindChallenge(true);
        } else {
          setChallengeReadState("ABSENT");
          setBindChallenge(false);
        }
      } catch (err) {
        setChallengePacket(null);
        setChallengeReadState("ERROR");
        setBindChallenge(false);
        setError(err instanceof ApiError ? `CHALLENGE_READ_ERROR：${err.message}` : "CHALLENGE_READ_ERROR：Challenge 状态当前无法验证。");
      }
    } catch (err) {
      setPreview(null);
      setChallengeReadState("ERROR");
      setError(err instanceof ApiError ? err.message : "Preview 失败，Proposal 未生成。");
    } finally {
      setBusy(null);
    }
  };

  const handleFinalizeChallenge = async () => {
    if (!preview || !draft || !challengeConfirmed || challengeReadState !== "ABSENT") return;
    setBusy("challenge");
    setChallengeReadState("PENDING");
    setChallengePacket(null);
    setBindChallenge(false);
    setError("");
    try {
      const result = await api.finalizeDecisionChallenge(campaignId, {
        ...draft,
        as_of: preview.proposal.as_of,
        expected_proposal_fingerprint: preview.proposal_fingerprint,
        user_confirmed: true,
        dimensions: challengeDraft,
      });
      const reread = await api.getDecisionChallenge(result.challenge.challenge_id);
      setChallengePacket(reread.challenge);
      setChallengeReadState("FOUND");
      setBindChallenge(true);
    } catch (err) {
      setChallengeReadState("ERROR");
      setChallengePacket(null);
      setBindChallenge(false);
      if (err instanceof ApiError && err.status === 409) {
        setPreview(null);
        setError("Proposal 已失效，Challenge 未写入，请重新 Preview。");
      } else {
        setError(err instanceof ApiError ? `CHALLENGE_READ_ERROR：${err.message}` : "CHALLENGE_READ_ERROR：Challenge 状态当前无法验证。");
      }
    } finally {
      setBusy(null);
    }
  };

  const handleCommit = async () => {
    if (
      !preview
      || !draft
      || !confirmed
      || (challengeReadState !== "FOUND" && challengeReadState !== "ABSENT")
    ) return;
    setBusy("commit");
    setError("");
    setCommitted(null);
    try {
      const result = await api.commitDecisionProposal(campaignId, {
        ...draft,
        as_of: preview.proposal.as_of,
        expected_proposal_fingerprint: preview.proposal_fingerprint,
        user_confirmed: true,
        ...(bindChallenge && challengePacket?.challenge_id
          ? { challenge_id: challengePacket.challenge_id }
          : {}),
      });
      const decisionId = result.committed.decision_id;
      if (typeof decisionId !== "string") throw new Error("提交成功但缺少真实 decision_id");
      // Commit response is not the final UI authority.  Re-read through the
      // backend GET so Formal Decision is never rendered from a write result.
      try {
        const reread = await api.getCommittedDecisionRuntime(campaignId, decisionId);
        setCommitted(reread);
      } catch (err) {
        if (err instanceof ApiError) {
          setError(`COMMITTED_DECISION_READ_ERROR：Commit 已成功，但 durable GET 无法验证（${err.message}）。不会显示已验证的 Frozen Decision，请勿重复提交。`);
        } else if (err instanceof CommittedDecisionReadError) {
          setError(`${err.message}。Commit 已成功，但不会显示未经验证的 Frozen Decision，请勿重复提交。`);
        } else {
          setError("COMMITTED_DECISION_READ_ERROR：Commit 已成功，但 durable GET 状态当前无法验证。不会显示未经验证的 Frozen Decision，请勿重复提交。");
        }
      }
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setPreview(null);
        setConfirmed(false);
        setError("Proposal 已失效，Campaign 或 Current Thesis 已变化，请重新 Preview。");
      } else {
        setError(err instanceof ApiError ? err.message : "Formal Decision 提交失败。");
      }
    } finally {
      setBusy(null);
    }
  };

  const challengeStateLabel = challengeReadState === "FOUND"
    ? "FOUND"
    : challengeReadState === "ABSENT"
      ? "UNFINALIZED"
      : challengeReadState;
  const challengeReadError = challengeReadState === "ERROR";
  const challengeReadPending = challengeReadState === "PENDING";

  const authorities = preview?.authority_evaluations ?? {};
  const material = authorities.material_change;
  const hardRisk = authorities.hard_risk;
  const criticalData = authorities.critical_data;
  const previewAssurance = preview?.decision_assurance as Record<string, unknown> | undefined;
  const dimensions = (previewAssurance?.dimension_states ?? {}) as Record<string, unknown>;
  const envelope = preview?.proposal.action_envelope as Record<string, unknown> | undefined;
  const committedTradeHref = committed && campaign
    ? buildEvaluatedTradeContinuationHref({
        securityCode: campaign.security_code,
        continuationRef: {
          decision_id: committed.committed.decision_id,
          snapshot_hash: committed.committed.snapshot_hash,
        },
        formalDecisionEvaluation: evaluationOf(committed.formal_decision),
      })
    : null;

  return (
    <div className="space-y-6" data-decision-proposal-page={campaignId}>
      <PageHeader
        title="Formal Decision Review"
        subtitle="Campaign-scoped deterministic proposal。Preview 不写 Frozen Decision；只有显式确认后才允许 Freeze。"
        actions={(
          <div className="flex flex-wrap items-center gap-2">
            <Link
              to="/decision-inbox"
              className="inline-flex items-center gap-1.5 rounded border border-border/60 px-3 py-1.5 text-xs text-muted-foreground hover:text-foreground"
              data-testid="decision-inbox-secondary-entry"
            >
              <ArrowLeft className="h-3.5 w-3.5" /> 返回 Decision Inbox
            </Link>
            <button type="button" onClick={() => navigate(-1)} className="inline-flex items-center gap-1.5 rounded border border-border/60 px-3 py-1.5 text-xs text-muted-foreground hover:text-foreground">
              返回
            </button>
          </div>
        )}
      />

      <section className="rounded-lg border border-border/60 bg-background/35 p-4 space-y-3" data-decision-context={contextState} data-context-binding={binding?.thesis_id ?? ""} data-context-bound-thesis={boundThesis?.thesis.id ?? ""}>
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <span className="text-muted-foreground">Campaign</span>
          <span className={codeCls}>{(campaign?.campaign_id ?? campaignId) || "缺少 campaign_id"}</span>
          <span className="rounded bg-amber-500/15 px-1.5 py-0.5 text-amber-700">backend authority</span>
          {contextState === "loading" && <span className="text-muted-foreground">正在读取上下文…</span>}
        </div>
        <div className="grid gap-2 text-xs sm:grid-cols-2 lg:grid-cols-5">
          <div><p className="text-muted-foreground">Security</p><p className="mt-1 font-medium" data-context-security>{campaign?.security_code ?? "UNKNOWN"}</p></div>
          <div><p className="text-muted-foreground">Campaign Strategy</p><p className="mt-1 font-medium" data-context-strategy>{campaign?.strategy ?? "UNKNOWN"}</p></div>
          <div><p className="text-muted-foreground">Current Thesis 状态</p><p className="mt-1 font-medium" data-context-thesis-status>{currentThesis?.ready ? currentThesis.effective_state : currentThesis?.formal_status ?? "UNAVAILABLE"}</p></div>
          <div><p className="text-muted-foreground">Frozen Thesis / revision</p><p className="mt-1 font-medium" data-context-frozen-revision>{hydration?.frozenRevision ? `v${hydration.frozenRevision}` : "UNKNOWN"}</p></div>
          <div><p className="text-muted-foreground">Expected Horizon</p><p className="mt-1 font-medium" data-context-horizon>{hydration?.status === "READY" ? hydration.horizonText : "UNKNOWN"}</p></div>
        </div>
        {contextState === "ready" ? (
          <p className="text-xs leading-5 text-success" data-horizon-source="CURRENT_THESIS">
            Strategy horizon 已从 Current Thesis 的 backend authority 预填。来源：Current Thesis；不是用户重新声明。你仍可按当前 Proposal 需要修改。
          </p>
        ) : contextState === "unavailable" ? (
          <p className="text-xs leading-5 text-warning" role="status" data-horizon-source="MANUAL_FALLBACK">
            Current Thesis authority 当前不可用于合法 horizon（{contextMessage || "UNKNOWN"}）。不会猜测 horizon；请在下方手工填写 strategy horizon。
          </p>
        ) : (
          <p className="text-xs leading-5 text-muted-foreground">证券代码、策略、Thesis id/revision 都由 backend 根据真实 Campaign 与 Current Thesis 读取；页面不提交这些 authority 字段。</p>
        )}
      </section>

      <section className="grid gap-4 lg:grid-cols-3">
        <fieldset className="rounded-md border border-border/50 bg-background/35 p-3 text-xs" data-view-form="asset_view">
          <legend className="px-1 font-medium text-foreground">Asset View</legend>
          <label className="mt-1 block text-muted-foreground">
            资产判断（stance）
            <select
              aria-label="Asset stance"
              value={assetStance}
              onChange={(event) => setAssetStance(event.target.value as ViewStance)}
              className={inputCls}
            >
              {VIEW_STANCE_OPTIONS.map((option) => (
                <option key={option} value={option}>{VIEW_STANCE_LABELS[option]}</option>
              ))}
            </select>
          </label>
          <label className="mt-2 block text-muted-foreground">
            判断说明（选填）
            <input
              aria-label="Asset note"
              type="text"
              value={assetNote}
              onChange={(event) => setAssetNote(event.target.value)}
              placeholder="例如：高端白酒需求稳定"
              className={inputCls}
            />
          </label>
        </fieldset>
        <fieldset className="rounded-md border border-border/50 bg-background/35 p-3 text-xs" data-view-form="trade_view">
          <legend className="px-1 font-medium text-foreground">Trade View</legend>
          <label className="mt-1 block text-muted-foreground">
            交易判断（stance）
            <select
              aria-label="Trade stance"
              value={tradeStance}
              onChange={(event) => setTradeStance(event.target.value as ViewStance)}
              className={inputCls}
            >
              {VIEW_STANCE_OPTIONS.map((option) => (
                <option key={option} value={option}>{VIEW_STANCE_LABELS[option]}</option>
              ))}
            </select>
          </label>
          <label className="mt-2 block text-muted-foreground">
            判断说明（选填）
            <input
              aria-label="Trade note"
              type="text"
              value={tradeNote}
              onChange={(event) => setTradeNote(event.target.value)}
              placeholder="例如：等待缩量回调再入场"
              className={inputCls}
            />
          </label>
        </fieldset>
        <fieldset className="rounded-md border border-border/50 bg-background/35 p-3 text-xs" data-view-form="portfolio_view">
          <legend className="px-1 font-medium text-foreground">Portfolio View</legend>
          <label className="mt-1 block text-muted-foreground">
            组合约束（选填）
            <input
              aria-label="Portfolio constraint"
              type="text"
              value={portfolioConstraint}
              onChange={(event) => setPortfolioConstraint(event.target.value)}
              placeholder="例如：单笔风险不超过组合 2%"
              className={inputCls}
            />
          </label>
        </fieldset>
      </section>

      <section className="grid gap-4 rounded-lg border border-border/60 bg-background/35 p-4 sm:grid-cols-2">
        <div className="text-xs text-muted-foreground">Review by（必填，由你显式选择；不自动生成）
          <input aria-label="Review by" type="datetime-local" value={reviewByLocal} onChange={(event) => setReviewByLocal(event.target.value)} className={inputCls} />
          <p className="mt-1 font-mono text-[10px] text-muted-foreground" data-review-by-canonical>
            {reviewBoundary.status === "VALID" ? reviewBoundary.iso : "尚未选择有效 review 时间"}
          </p>
          <p className="text-[10px] text-muted-foreground" data-review-by-tz>
            解析时区：{browserTimeZoneName()}
            {reviewBoundary.status === "VALID"
              ? `（${formatUtcOffsetMinutes(reviewBoundary.date.getTimezoneOffset())}）`
              : "（选择时间后显示偏移）"}
            ；上方为将提交的 canonical UTC 时间。
          </p>
        </div>
        <label className="text-xs text-muted-foreground">Strategy horizon（必填，显式用户字段）
          <input aria-label="Strategy horizon" value={horizon} onChange={(event) => { horizonTouched.current = true; setHorizon(event.target.value); }} placeholder="例如：2 至 4 周" className={inputCls} />
        </label>
        <label className="text-xs text-muted-foreground">Key assumptions（逗号或换行分隔）
          <textarea aria-label="Key assumptions" value={assumptions} onChange={(event) => setAssumptions(event.target.value)} rows={3} className={inputCls} />
        </label>
        <label className="text-xs text-muted-foreground">Event invalidation conditions（逗号或换行分隔）
          <textarea aria-label="Event invalidation conditions" value={invalidations} onChange={(event) => setInvalidations(event.target.value)} rows={3} className={inputCls} />
        </label>
      </section>

      {error && <div role="alert" className="flex items-center gap-2 rounded-md border border-red-500/30 bg-red-500/5 p-3 text-xs text-red-600"><AlertCircle className="h-4 w-4 shrink-0" />{error}</div>}

      <div className="flex flex-wrap items-center gap-3">
        <button type="button" onClick={() => void handlePreview()} disabled={busy !== null} className="inline-flex items-center gap-1.5 rounded-md border border-border/60 px-3 py-2 text-xs font-medium hover:bg-muted disabled:opacity-50">
          {busy === "preview" && <Loader2 className="h-3.5 w-3.5 animate-spin" />} Preview Proposal
        </button>
        <span className="text-xs text-muted-foreground">Preview 是只读计算，不会创建 Frozen Decision。</span>
      </div>

      {preview && (
        <section className="space-y-4 rounded-lg border border-amber-500/40 bg-amber-500/5 p-4" data-proposal-status="UNCOMMITTED" role="status">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <h2 className="text-sm font-semibold">Decision Proposal <span className="rounded bg-amber-500/15 px-1.5 py-0.5 text-amber-700">UNCOMMITTED</span></h2>
              <p className="mt-1 text-[11px] text-muted-foreground">as_of：<span className="font-mono">{preview.proposal.as_of}</span></p>
            </div>
            <span className="font-mono text-[10px] text-muted-foreground" title={preview.proposal_fingerprint}>fingerprint {preview.proposal_fingerprint.slice(0, 16)}…</span>
          </div>

          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-6">
            {[
              ["Formal Thesis", authorities.formal_thesis],
              ["Formal Decision", authorities.formal_decision],
              ["Hard Risk", hardRisk],
              ["Critical Data", criticalData],
              ["Material Change", material],
              ["Sell Engine", authorities.sell_engine],
            ].map(([label, value]) => {
              const evaluation = evaluationOf(value);
              const isCriticalData = label === "Critical Data";
              const record = value && typeof value === "object" ? value as Record<string, unknown> : undefined;
              return <div
                key={String(label)}
                className="rounded-md border border-border/50 bg-background/45 p-2 text-xs"
                {...(isCriticalData ? {
                  "data-critical-data-state": String(record?.critical_data_state ?? "UNKNOWN"),
                  "data-critical-data-evaluation": evaluation,
                } : {})}
              >
                <p className="text-muted-foreground">{String(label)}</p>
                <p className="mt-1 font-medium">{authorityLabel(evaluation)}</p>
                <span className="font-mono text-[10px] text-muted-foreground">{evaluation}</span>
                {isCriticalData && <>
                  <p className="mt-1 font-mono text-[10px]">state: {String(record?.critical_data_state ?? "UNKNOWN")}</p>
                  <p className="mt-1 truncate text-[10px] text-muted-foreground" title={shortestReason(value)}>reason: {shortestReason(value)}</p>
                </>}
              </div>;
            })}
          </div>

          <div className="grid gap-4 md:grid-cols-3">
            {["asset_view", "trade_view", "portfolio_view"].map((name) => (
              <div key={name} className="rounded-md border border-border/50 bg-background/35 p-3 text-xs"><p className="font-medium">{name}</p><p className="mt-1 text-muted-foreground">USER_DRAFT · 尚未进入 Frozen Decision</p></div>
            ))}
          </div>

          <div className="rounded-md border border-border/50 bg-background/35 p-3 text-xs">
            <p className="font-medium">RA1 Decision Assurance（同一 as_of）</p>
            <div className="mt-2 grid gap-1.5 sm:grid-cols-2 lg:grid-cols-5">
              {Object.entries(dimensions).map(([dimension, value]) => <span key={dimension} className="flex items-center justify-between gap-2 rounded bg-muted/40 px-2 py-1"><span>{dimension}</span><span className="font-mono">{String(value)}</span></span>)}
            </div>
          </div>

          <div className="rounded-md border border-border/50 bg-background/35 p-3 text-xs" data-action-envelope>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="font-medium">Constraints / Action Envelope</p>
              <span className="font-mono text-[10px] text-muted-foreground">{preview.proposal.constraint_evaluation}</span>
            </div>
            <div className="mt-2 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {[
                ["Allowed", "allowed_actions"],
                ["Blocked", "blocked_actions"],
                ["Maintain", "maintain_conditions"],
                ["Upgrade", "upgrade_conditions"],
                ["Downgrade", "downgrade_conditions"],
                ["Invalidation", "invalidation_conditions"],
              ].map(([label, key]) => (
                <div key={key} className="rounded border border-border/40 bg-background/40 p-2">
                  <p className="text-muted-foreground">{label}</p>
                  <ul className="mt-1 list-disc space-y-0.5 pl-4">
                    {stringList(envelope?.[key]).map((item) => <li key={item}>{item}</li>)}
                  </ul>
                </div>
              ))}
            </div>
          </div>

          <div className="rounded-md border border-border/50 bg-background/35 p-3 text-xs">
            <p className="font-medium">Next Best Action</p>
            <p className="mt-1 text-base font-semibold">{preview.proposal.next_best_action}</p>
            <p className="mt-1 text-muted-foreground">任何未评估 authority 都会把 proposal 保持在 WAIT / RESEARCH MORE 的保守 envelope。</p>
          </div>

          <section
            className="space-y-3 rounded-md border border-border/60 bg-background/45 p-3"
            data-challenge-state={challengeReadState}
            data-challenge-id={challengePacket?.challenge_id ?? ""}
            data-decision-quality="NOT_EVALUATED"
          >
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h3 className="text-sm font-semibold">Decision Challenge（可选；读取失败时不会安全降级）</h3>
              <span className="rounded bg-muted px-1.5 py-0.5 font-mono text-[10px]">
                {challengeStateLabel}
              </span>
            </div>
            <p className="text-[11px] text-muted-foreground">
              四个维度必须由用户显式填写。UNKNOWN 计为覆盖，但不是正面证据。Challenge 不改变 NBA / Action Envelope，也不产生 decision quality score。
            </p>
            {challengeReadPending && (
              <p role="status" className="rounded border border-border/40 bg-muted/30 p-2 text-xs">
                正在读取 Challenge 状态；在读取完成前不会开放 Freeze、Finalize 或 Bind。
              </p>
            )}
            {challengeReadError && (
              <p role="alert" className="rounded border border-red-500/30 bg-red-500/5 p-2 text-xs text-red-600">
                CHALLENGE_READ_ERROR：Challenge 状态当前无法验证；本次不会绑定未验证的 Challenge，也不会开放 Freeze、Finalize 或 Bind。
              </p>
            )}
            <div className="grid gap-3 md:grid-cols-2">
              {DECISION_CHALLENGE_DIMENSIONS.map((name) => {
                const row = challengeDraft[name];
                const finalized = challengeReadState === "FOUND" && Boolean(challengePacket);
                return (
                  <label key={name} className="text-xs text-muted-foreground">
                    {challengeLabels[name]}
                    <select
                      aria-label={`${challengeLabels[name]} status`}
                      value={finalized ? String((challengePacket?.dimension_results as Record<string, { status?: string }> | undefined)?.[name]?.status ?? row.status) : row.status}
                      disabled={finalized || busy !== null}
                      onChange={(event) => setChallengeDraft((current) => ({
                        ...current,
                        [name]: { ...current[name], status: event.target.value as "ANSWERED" | "UNKNOWN" },
                      }))}
                      className={inputCls}
                    >
                      <option value="ANSWERED">ANSWERED</option>
                      <option value="UNKNOWN">UNKNOWN</option>
                    </select>
                    <textarea
                      aria-label={challengeLabels[name]}
                      value={finalized ? String((challengePacket?.dimension_results as Record<string, { text?: string }> | undefined)?.[name]?.text ?? row.text ?? "") : row.text ?? ""}
                      disabled={finalized || busy !== null}
                      onChange={(event) => setChallengeDraft((current) => ({
                        ...current,
                        [name]: { ...current[name], text: event.target.value },
                      }))}
                      rows={3}
                      className={inputCls}
                    />
                  </label>
                );
              })}
            </div>
            {challengeReadState === "FOUND" && challengePacket ? (
              <div className="space-y-1 rounded border border-border/40 bg-background/40 p-2 text-[11px]" data-challenge-readback>
                <p>challenge_id：<span className="font-mono">{challengePacket.challenge_id}</span></p>
                <p>packet_state：<span className="font-mono">{challengePacket.packet_state}</span> · evaluation：<span className="font-mono">{challengePacket.challenge_evaluation}</span></p>
                <p>finalized_at：<span className="font-mono">{challengePacket.finalized_at}</span></p>
                <p>decision_quality：<span className="font-mono">{challengePacket.decision_quality}</span> · two-pass independence：<span className="font-mono">{challengePacket.two_pass_semantic_independence_verified}</span></p>
              </div>
            ) : (
              <>
                <label className="flex items-start gap-2 text-xs">
                  <input type="checkbox" checked={challengeConfirmed} onChange={(event) => setChallengeConfirmed(event.target.checked)} className="mt-0.5" />
                  <span>我已显式填写四个挑战维度，确认 Finalize 这份不可变 Challenge Packet。</span>
                </label>
                <button
                  type="button"
                  onClick={() => void handleFinalizeChallenge()}
                  disabled={!challengeConfirmed || busy !== null || !draft || challengeReadState !== "ABSENT"}
                  className="inline-flex items-center gap-1.5 rounded-md border border-border/60 px-3 py-2 text-xs font-medium hover:bg-muted disabled:opacity-50"
                >
                  {busy === "challenge" && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                  Finalize Decision Challenge
                </button>
              </>
            )}
            <label className="flex items-start gap-2 text-xs">
              <input
                type="checkbox"
                checked={bindChallenge}
                disabled={challengeReadState !== "FOUND" || !challengePacket || busy !== null}
                onChange={(event) => setBindChallenge(event.target.checked)}
                className="mt-0.5"
              />
              <span data-challenge-bind={bindChallenge && challengePacket ? "yes" : "no"}>
                {challengeReadState === "FOUND"
                  ? "Freeze 将绑定这份已 Finalize 的 Challenge（decision_challenge:<id>）。"
                  : challengeReadState === "ABSENT"
                    ? "未找到已 Finalize 的 Challenge；Freeze 仍可继续，且不会写入假的 challenge 引用。"
                    : "Challenge 状态当前无法安全验证；读取完成前不会 Freeze，也不会绑定未验证的 Challenge。"}
              </span>
            </label>
          </section>

          <label className="flex items-start gap-2 rounded-md border border-border/60 bg-background/45 p-3 text-xs">
            <input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} className="mt-0.5" />
            <span>我已检查三个独立 View、同一 as_of、Authority 状态与 Action Envelope；确认提交这份 Proposal 为 Frozen Decision。</span>
          </label>
          <button type="button" onClick={() => void handleCommit()} disabled={!confirmed || busy !== null || challengeReadState === "PENDING" || challengeReadState === "ERROR"} className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-2 text-xs font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50">
            {busy === "commit" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <LockKeyhole className="h-3.5 w-3.5" />}
            Freeze Formal Decision
          </button>
        </section>
      )}

      {committed && (
        <section className="space-y-3 rounded-lg border border-success/40 bg-success/5 p-4" data-formal-decision-evaluation={evaluationOf(committed.formal_decision)} role="status">
          <h2 className="flex items-center gap-2 text-sm font-semibold"><CheckCircle2 className="h-4 w-4 text-success" />Frozen Decision 已由 backend re-read</h2>
          <p className="text-xs text-muted-foreground">Formal Decision evaluation：<span className="font-mono">{evaluationOf(committed.formal_decision)}</span> · as_of：<span className="font-mono">{committed.as_of}</span></p>
          <p className="font-mono text-[11px] text-muted-foreground">decision_id：{String(committed.committed.decision_id ?? "—")}</p>
          <div className="grid gap-2 sm:grid-cols-3">
            <div className="rounded border border-border/50 bg-background/40 p-2 text-xs">Formal Thesis：{authorityLabel(evaluationOf(committed.formal_thesis))}</div>
            <div className="rounded border border-border/50 bg-background/40 p-2 text-xs">Hard Risk：{authorityLabel(evaluationOf(committed.hard_risk))}</div>
            <div className="rounded border border-border/50 bg-background/40 p-2 text-xs">Material：{authorityLabel(evaluationOf(committed.material_change))}</div>
          </div>
          <p className="text-xs text-muted-foreground">Decision Inbox 将在下一次 backend snapshot 中读取这条 LAST_FROZEN_DECISION；它不是 CURRENT_RECOMMENDATION。</p>
          <div className="flex flex-wrap gap-x-4 gap-y-2">
            <Link to="/decision-inbox" className="inline-flex text-xs text-primary hover:underline">打开 Decision Inbox →</Link>
            {committedTradeHref ? (
              <Link
                to={committedTradeHref}
                className="inline-flex text-xs font-medium text-primary hover:underline"
                data-testid="committed-decision-trade-continuation"
              >
                如已实际执行，记录交易 →
              </Link>
            ) : null}
          </div>
        </section>
      )}
    </div>
  );
}

export default DecisionProposalReview;
