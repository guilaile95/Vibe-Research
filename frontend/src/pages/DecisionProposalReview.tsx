import { useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { AlertCircle, ArrowLeft, CheckCircle2, Loader2, LockKeyhole } from "lucide-react";
import { PageHeader } from "@/components/ui/PageHeader";
import { ApiError, api, DECISION_CHALLENGE_DIMENSIONS, type DecisionChallengeDimensionInput, type DecisionChallengeDimensionName, type DecisionChallengePacket, type DecisionProposalDraftInput, type DecisionProposalPreview, type CommittedDecisionRuntimeRead } from "@/lib/api";

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

function canonicalReviewBy(value: string): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) throw new Error("请填写有效的 review_by 时间");
  return parsed.toISOString();
}

function parseObject(value: string, label: string): Record<string, unknown> {
  let parsed: unknown;
  try {
    parsed = JSON.parse(value);
  } catch {
    throw new Error(`${label} 必须是合法 JSON 对象`);
  }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error(`${label} 必须是 JSON object`);
  }
  return parsed as Record<string, unknown>;
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

const defaultAsset = JSON.stringify({ view: "ASSET", stance: "WAIT", note: "用户填写资产判断" }, null, 2);
const defaultTrade = JSON.stringify({ view: "TRADE", stance: "WAIT", note: "用户填写交易判断" }, null, 2);
const defaultPortfolio = JSON.stringify({ view: "PORTFOLIO", constraint: "用户填写组合约束" }, null, 2);

export function DecisionProposalReview() {
  const { campaignId = "" } = useParams();
  const navigate = useNavigate();
  const [assetText, setAssetText] = useState(defaultAsset);
  const [tradeText, setTradeText] = useState(defaultTrade);
  const [portfolioText, setPortfolioText] = useState(defaultPortfolio);
  const [reviewBy, setReviewBy] = useState("");
  const [horizon, setHorizon] = useState("");
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
  const [bindChallenge, setBindChallenge] = useState(false);

  const draft = useMemo<DecisionProposalDraftInput | null>(() => {
    try {
      if (!reviewBy || !horizon.trim()) return null;
      return {
        asset_view: parseObject(assetText, "Asset View"),
        trade_view: parseObject(tradeText, "Trade View"),
        portfolio_view: parseObject(portfolioText, "Portfolio View"),
        review_by: canonicalReviewBy(reviewBy),
        key_assumptions: splitLines(assumptions),
        event_invalidation_conditions: splitLines(invalidations),
        strategy_horizon: horizon.trim(),
      };
    } catch {
      return null;
    }
  }, [assetText, tradeText, portfolioText, reviewBy, horizon, assumptions, invalidations]);

  const handlePreview = async () => {
    setError("");
    setCommitted(null);
    setConfirmed(false);
    setChallengePacket(null);
    setChallengeConfirmed(false);
    setBindChallenge(false);
    if (!campaignId || !draft) {
      setError("请先填写 review_by、strategy horizon，并确保三个 View 是合法 JSON object。");
      return;
    }
    setBusy("preview");
    try {
      const next = await api.previewDecisionProposal(campaignId, draft);
      setPreview(next);
      try {
        const existing = await api.getDecisionChallengeForProposal(campaignId, next.proposal_fingerprint);
        setChallengePacket(existing?.challenge ?? null);
        setBindChallenge(Boolean(existing?.challenge));
      } catch {
        setChallengePacket(null);
        setBindChallenge(false);
      }
    } catch (err) {
      setPreview(null);
      setError(err instanceof ApiError ? err.message : "Preview 失败，Proposal 未生成。");
    } finally {
      setBusy(null);
    }
  };

  const handleFinalizeChallenge = async () => {
    if (!preview || !draft || !challengeConfirmed || challengePacket) return;
    setBusy("challenge");
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
      setBindChallenge(true);
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setPreview(null);
        setChallengePacket(null);
        setError("Proposal 已失效，Challenge 未写入，请重新 Preview。");
      } else {
        setError(err instanceof ApiError ? err.message : "Decision Challenge Finalize 失败。");
      }
    } finally {
      setBusy(null);
    }
  };

  const handleCommit = async () => {
    if (!preview || !draft || !confirmed) return;
    setBusy("commit");
    setError("");
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
      const reread = await api.getCommittedDecisionRuntime(campaignId, decisionId);
      setCommitted(reread);
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

  const authorities = preview?.authority_evaluations ?? {};
  const material = authorities.material_change;
  const hardRisk = authorities.hard_risk;
  const criticalData = authorities.critical_data;
  const previewAssurance = preview?.decision_assurance as Record<string, unknown> | undefined;
  const dimensions = (previewAssurance?.dimension_states ?? {}) as Record<string, unknown>;
  const envelope = preview?.proposal.action_envelope as Record<string, unknown> | undefined;

  return (
    <div className="space-y-6" data-decision-proposal-page={campaignId}>
      <PageHeader
        title="Formal Decision Review"
        subtitle="Campaign-scoped deterministic proposal。Preview 不写 Frozen Decision；只有显式确认后才允许 Freeze。"
        actions={(
          <button type="button" onClick={() => navigate(-1)} className="inline-flex items-center gap-1.5 rounded border border-border/60 px-3 py-1.5 text-xs text-muted-foreground hover:text-foreground">
            <ArrowLeft className="h-3.5 w-3.5" /> 返回
          </button>
        )}
      />

      <section className="rounded-lg border border-border/60 bg-background/35 p-4 space-y-3">
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <span className="text-muted-foreground">Campaign</span>
          <span className={codeCls}>{campaignId || "缺少 campaign_id"}</span>
          <span className="rounded bg-amber-500/15 px-1.5 py-0.5 text-amber-700">backend authority</span>
        </div>
        <p className="text-xs leading-5 text-muted-foreground">
          证券代码、策略、Thesis id/revision 都由 backend 根据真实 Campaign 与 Current Thesis 读取；页面不提交这些 authority 字段。
        </p>
      </section>

      <section className="grid gap-4 lg:grid-cols-3">
        <label className="text-xs text-muted-foreground">Asset View（JSON object）
          <textarea aria-label="Asset View" value={assetText} onChange={(event) => setAssetText(event.target.value)} rows={7} className={`${inputCls} font-mono text-[11px]`} />
        </label>
        <label className="text-xs text-muted-foreground">Trade View（JSON object）
          <textarea aria-label="Trade View" value={tradeText} onChange={(event) => setTradeText(event.target.value)} rows={7} className={`${inputCls} font-mono text-[11px]`} />
        </label>
        <label className="text-xs text-muted-foreground">Portfolio View（JSON object）
          <textarea aria-label="Portfolio View" value={portfolioText} onChange={(event) => setPortfolioText(event.target.value)} rows={7} className={`${inputCls} font-mono text-[11px]`} />
        </label>
      </section>

      <section className="grid gap-4 rounded-lg border border-border/60 bg-background/35 p-4 sm:grid-cols-2">
        <label className="text-xs text-muted-foreground">Review by（必填，显式用户字段）
          <input aria-label="Review by" type="text" value={reviewBy} onChange={(event) => setReviewBy(event.target.value)} placeholder="2026-08-30T10:00:00Z" className={inputCls} />
        </label>
        <label className="text-xs text-muted-foreground">Strategy horizon（必填，显式用户字段）
          <input aria-label="Strategy horizon" value={horizon} onChange={(event) => setHorizon(event.target.value)} placeholder="例如：2 至 4 周" className={inputCls} />
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
            data-challenge-state={challengePacket ? "FINALIZED" : "UNFINALIZED"}
            data-challenge-id={challengePacket?.challenge_id ?? ""}
            data-decision-quality="NOT_EVALUATED"
          >
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h3 className="text-sm font-semibold">Decision Challenge（可选，不阻断 Freeze）</h3>
              <span className="rounded bg-muted px-1.5 py-0.5 font-mono text-[10px]">
                {challengePacket ? "FINALIZED" : "UNFINALIZED"}
              </span>
            </div>
            <p className="text-[11px] text-muted-foreground">
              四个维度必须由用户显式填写。UNKNOWN 计为覆盖，但不是正面证据。Challenge 不改变 NBA / Action Envelope，也不产生 decision quality score。
            </p>
            <div className="grid gap-3 md:grid-cols-2">
              {DECISION_CHALLENGE_DIMENSIONS.map((name) => {
                const row = challengeDraft[name];
                const finalized = Boolean(challengePacket);
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
            {challengePacket ? (
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
                  disabled={!challengeConfirmed || busy !== null || !draft}
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
                disabled={!challengePacket || busy !== null}
                onChange={(event) => setBindChallenge(event.target.checked)}
                className="mt-0.5"
              />
              <span data-challenge-bind={bindChallenge && challengePacket ? "yes" : "no"}>
                {challengePacket
                  ? "Freeze 将绑定这份已 Finalize 的 Challenge（decision_challenge:<id>）。"
                  : "尚未 Finalize Challenge；Freeze 仍可继续，且不会写入假的 challenge 引用。"}
              </span>
            </label>
          </section>

          <label className="flex items-start gap-2 rounded-md border border-border/60 bg-background/45 p-3 text-xs">
            <input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} className="mt-0.5" />
            <span>我已检查三个独立 View、同一 as_of、Authority 状态与 Action Envelope；确认提交这份 Proposal 为 Frozen Decision。</span>
          </label>
          <button type="button" onClick={() => void handleCommit()} disabled={!confirmed || busy !== null} className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-2 text-xs font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50">
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
          <Link to="/decision-inbox" className="inline-flex text-xs text-primary hover:underline">打开 Decision Inbox →</Link>
        </section>
      )}
    </div>
  );
}

export default DecisionProposalReview;
