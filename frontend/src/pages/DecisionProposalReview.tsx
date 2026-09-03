import { useEffect, useMemo, useRef, useState } from "react";
import { loadLlm } from "@/lib/llm";
import { Link, useNavigate, useParams } from "react-router-dom";
import { AlertCircle, ArrowLeft, CheckCircle2, Loader2, LockKeyhole } from "lucide-react";
import { PageHeader } from "@/components/ui/PageHeader";
import { ApiError, CommittedDecisionReadError, api, DECISION_CHALLENGE_DIMENSIONS, type DecisionChallengeDimensionInput, type DecisionChallengeDimensionName, type DecisionChallengePacket, type DecisionProposalDraftInput, type DecisionProposalPreview, type CommittedDecisionRuntimeRead } from "@/lib/api";
import { VIEW_STANCE_LABELS, VIEW_STANCE_OPTIONS, buildJudgedView, buildPortfolioView, joinDraftLines, type ViewStance } from "@/lib/decisionProposalForm";
import { hydratedHorizonValue, resolveDecisionContext, type DecisionContextHydrationResult } from "@/lib/decisionContextHydration";
import { browserTimeZoneName, formatUtcOffsetMinutes, parseReviewBoundary } from "@/lib/reviewBoundaryInput";
import { buildEvaluatedTradeContinuationHref } from "@/lib/tradeContinuation";
import { currentThesisStatusLabel, currentThesisStatusValue, decisionActionLabel, decisionEvaluationLabel } from "@/lib/decisionActionView";
import {
  CANDIDATE_CONFIDENCE_LEVELS,
  buildCandidateTradeTerms,
  buildCandidateValuationCase,
  presentPortfolioCapitalContext,
  type CandidateConfidence,
  type CandidateTradeTermsDraft,
  type CandidateValuationCaseDraft,
} from "@/lib/candidateCampaign";
import type { CampaignRecord, CampaignThesisBinding, CampaignCurrentThesis, ThesisAggregate, CampaignAIDraftGenerateResult, DecisionProposalDraftWitness } from "@/lib/api";

type ChallengeReadState = "PENDING" | "FOUND" | "ABSENT" | "ERROR";

const challengeLabels: Record<DecisionChallengeDimensionName, string> = {
  STRONGEST_SUPPORTING_EVIDENCE: "最有力的支持证据",
  STRONGEST_OPPOSING_EVIDENCE: "最有力的反对证据",
  PRE_MORTEM: "如果判断失败，最可能的原因",
  INVALIDATION_FACTS: "哪些事实会推翻判断",
};

const emptyChallenge = (): Record<DecisionChallengeDimensionName, DecisionChallengeDimensionInput> => ({
  STRONGEST_SUPPORTING_EVIDENCE: { status: "ANSWERED", text: "" },
  STRONGEST_OPPOSING_EVIDENCE: { status: "ANSWERED", text: "" },
  PRE_MORTEM: { status: "ANSWERED", text: "" },
  INVALIDATION_FACTS: { status: "ANSWERED", text: "" },
});

const inputCls = "mt-1 w-full rounded-md border border-border/60 bg-background px-2.5 py-2 text-sm outline-none focus:border-primary/60";

type CandidateScenarioName = "bear" | "base" | "bull";
type CandidateConfidenceName = "data_quality" | "evidence_confidence" | "inference_confidence" | "decision_confidence";

const CANDIDATE_SCENARIOS: readonly CandidateScenarioName[] = ["bear", "base", "bull"];
const CANDIDATE_SCENARIO_LABELS: Record<CandidateScenarioName, string> = {
  bear: "悲观",
  base: "基准",
  bull: "乐观",
};
const CANDIDATE_CONFIDENCE_LABELS: Record<CandidateConfidenceName, string> = {
  data_quality: "数据可靠程度",
  evidence_confidence: "证据可信程度",
  inference_confidence: "推断把握程度",
  decision_confidence: "最终判断把握程度",
};
const CANDIDATE_CONFIDENCE_VALUE_LABELS: Record<CandidateConfidence, string> = {
  HIGH: "高",
  MEDIUM: "中",
  LOW: "低",
  UNKNOWN: "信息不足",
};
const DECISION_ASSURANCE_LABELS: Record<string, string> = {
  FORMAL_THESIS: "正式投资逻辑",
  FORMAL_DECISION: "正式决策",
  HARD_RISK: "硬风险",
  MATERIAL_CHANGE: "重大变化",
  CRITICAL_DATA: "关键数据",
};
const CANDIDATE_PRIMARY_FIELDS = [
  ["估值状态", "valuation_status"],
  ["持仓状态", "position_state"],
  ["账户状态", "account_state"],
  ["账户数据是否可信", "account_canonical"],
  ["账户信息可信度", "account_confidence"],
  ["硬风险", "hard_risk_state"],
  ["关键数据", "critical_data_state"],
  ["整体把握程度", "confidence"],
  ["最高可用把握程度", "confidence_ceiling"],
  ["证据状态", "evidence"],
  ["风险收益", "risk_reward"],
  ["风险上限", "risk_cap"],
] as const;

function emptyCandidateCase(): CandidateValuationCaseDraft {
  return {
    assumptions: "",
    inputMetric: "",
    inputValue: "",
    inputPeriod: "",
    source: "",
    dataAt: "",
    priceLow: "",
    priceHigh: "",
    horizon: "",
    changeConditions: "",
  };
}

function isCandidateBuyAction(value: string): boolean {
  return value === "BUY NOW" || value === "BUY SMALL" || value === "SCALE IN";
}

function recordValue(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function presentAuthorityValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "信息不足";
  if (value === "UNKNOWN") return "信息不足";
  if (value === "NOT_EVALUATED") return "尚未评估";
  if (value === "ERROR") return "读取失败";
  if (value === "AVAILABLE") return "可用";
  if (value === "CONSTRAINED") return "受限";
  if (value === "SUPPORTIVE") return "支持当前计划";
  if (value === "NOT_REQUIRED") return "无需复核";
  if (value === "WORTH_REVIEW") return "值得复核";
  if (value === "NOT_PROVEN") return "尚未证明";
  if (value === "AVAILABLE_CANDIDATE") return "候选上限可用";
  if (value === "AVAILABLE_CANONICALITY_UNKNOWN") return "账户可信状态未确认";
  if (typeof value === "number") return String(value);
  if (typeof value === "boolean") return value ? "是" : "否";
  if (typeof value === "string") return "无法识别当前状态";
  if (Array.isArray(value)) return value.map(presentAuthorityValue).join("、") || "—";
  const record = recordValue(value);
  if (!record) return "信息不足";
  const entries = Object.entries(record).map(([key, item]) => `${key}: ${presentAuthorityValue(item)}`);
  return entries.join(" · ") || "—";
}

function candidateEnumLabel(value: unknown, labels: Record<string, string>): string {
  if (value === null || value === undefined || value === "") return "信息不足";
  return typeof value === "string"
    ? labels[value] ?? "无法识别当前状态"
    : "无法识别当前状态";
}

function presentCandidateValue(key: string, value: unknown): string {
  if (key === "valuation_status") {
    return candidateEnumLabel(value, { READY: "资料已就绪", EVALUATED: "已评估", UNKNOWN: "信息不足" });
  }
  if (key === "position_state") {
    return candidateEnumLabel(value, { HELD: "当前持有", NOT_HELD: "当前未持有", UNKNOWN: "信息不足" });
  }
  if (key === "account_state") {
    return candidateEnumLabel(value, { USABLE: "可用", AVAILABLE: "可用", UNAVAILABLE: "不可用", CONSTRAINED: "受限", UNKNOWN: "信息不足" });
  }
  if (key === "account_canonical") {
    return value === true ? "已确认可信" : value === false ? "未形成完整可信账户" : "信息不足";
  }
  if (key === "account_confidence" || key === "confidence_ceiling") {
    return candidateEnumLabel(value, CANDIDATE_CONFIDENCE_VALUE_LABELS);
  }
  if (key === "hard_risk_state") {
    return candidateEnumLabel(value, { CLEAR: "未发现硬风险", CONFIRMED: "已确认硬风险", NOT_PROVEN: "尚未证明", NOT_EVALUATED: "尚未评估", UNKNOWN: "信息不足", ERROR: "读取失败" });
  }
  if (key === "critical_data_state") {
    return candidateEnumLabel(value, { USABLE: "可用", UNAVAILABLE: "不可用", NOT_EVALUATED: "尚未评估", UNKNOWN: "信息不足", ERROR: "读取失败" });
  }
  if (key === "confidence") {
    if (typeof value === "string") return candidateEnumLabel(value, CANDIDATE_CONFIDENCE_VALUE_LABELS);
    const confidence = recordValue(value);
    if (!confidence) return "信息不足";
    return (Object.keys(CANDIDATE_CONFIDENCE_LABELS) as CandidateConfidenceName[])
      .map((name) => `${CANDIDATE_CONFIDENCE_LABELS[name]}：${candidateEnumLabel(confidence[name], CANDIDATE_CONFIDENCE_VALUE_LABELS)}`)
      .join("；");
  }
  if (key === "evidence") {
    const evidence = recordValue(value);
    if (!evidence) return "信息不足";
    const status = candidateEnumLabel(evidence.status, {
      SUFFICIENT: "证据充分",
      INSUFFICIENT: "证据不足",
      CONFLICT: "证据存在冲突",
      UNKNOWN: "信息不足",
    });
    return typeof evidence.total_count === "number" ? `${status}（共 ${evidence.total_count} 条）` : status;
  }
  if (key === "risk_reward") {
    const riskReward = recordValue(value);
    if (!riskReward) return "信息不足";
    const status = candidateEnumLabel(riskReward.status, { AVAILABLE: "可用", UNKNOWN: "信息不足" });
    if (riskReward.status !== "AVAILABLE") return status;
    const ratio = typeof riskReward.ratio === "number" ? riskReward.ratio : null;
    const required = typeof riskReward.required_ratio === "number"
      ? riskReward.required_ratio
      : typeof riskReward.gate === "number" ? riskReward.gate : null;
    return ratio === null ? status : `${status} · 风险收益比 ${ratio}${required === null ? "" : `（最低 ${required}）`}`;
  }
  if (key === "risk_cap") {
    const riskCap = recordValue(value);
    if (!riskCap) return "信息不足";
    const status = candidateEnumLabel(riskCap.status, {
      AVAILABLE: "可用",
      AVAILABLE_CANDIDATE: "候选上限可用",
      AVAILABLE_CANONICALITY_UNKNOWN: "账户可信状态未确认",
      UNKNOWN: "信息不足",
    });
    const maxValue = typeof riskCap.max_position_value === "number"
      ? ` · 最高仓位金额 ¥${riskCap.max_position_value.toLocaleString("zh-CN")}`
      : "";
    const maxShares = typeof riskCap.max_shares === "number" ? ` · 最多 ${riskCap.max_shares} 股` : "";
    return `${status}${maxValue}${maxShares}`;
  }
  return "无法识别当前状态";
}

function portfolioCapitalBadgeClass(state: string): string {
  if (state === "AVAILABLE" || state === "SUPPORTIVE" || state === "NOT_REQUIRED") {
    return "bg-success/15 text-success";
  }
  return state === "UNKNOWN"
    ? "bg-warning/15 text-warning"
    : "bg-amber-500/15 text-amber-700 dark:text-amber-300";
}

function formatConfirmedCash(value: number | null): string {
  return value === null
    ? "信息不足"
    : `¥${value.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

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
  const [candidateCases, setCandidateCases] = useState<Record<CandidateScenarioName, CandidateValuationCaseDraft>>({
    bear: emptyCandidateCase(),
    base: emptyCandidateCase(),
    bull: emptyCandidateCase(),
  });
  const [candidateConfidence, setCandidateConfidence] = useState<Record<CandidateConfidenceName, CandidateConfidence | "">>({
    data_quality: "",
    evidence_confidence: "",
    inference_confidence: "",
    decision_confidence: "",
  });
  const [candidateTrade, setCandidateTrade] = useState<CandidateTradeTermsDraft>({
    entryLow: "",
    entryHigh: "",
    invalidationPrice: "",
    executionStyle: "",
  });
  const [candidateAnchorsUnavailable, setCandidateAnchorsUnavailable] = useState(false);
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
  const [aiDraft, setAiDraft] = useState<CampaignAIDraftGenerateResult | null>(null);
  const [draftWitness, setDraftWitness] = useState<DecisionProposalDraftWitness | null>(null);
  const [aiBusy, setAiBusy] = useState(false);
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
      setContextMessage("缺少投资计划编号，无法读取决策上下文。");
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
        setContextMessage(err instanceof ApiError ? err.message : "投资计划或当前投资逻辑读取失败");
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

  const candidateConfidenceValues = useMemo(() => {
    if (
      !candidateConfidence.data_quality
      || !candidateConfidence.evidence_confidence
      || !candidateConfidence.inference_confidence
      || !candidateConfidence.decision_confidence
    ) return null;
    return candidateConfidence as Record<CandidateConfidenceName, CandidateConfidence>;
  }, [candidateConfidence]);

  const candidateValuation = useMemo(() => {
    const cases = {
      bear: buildCandidateValuationCase(candidateCases.bear),
      base: buildCandidateValuationCase(candidateCases.base),
      bull: buildCandidateValuationCase(candidateCases.bull),
    };
    if (
      !cases.bear
      || !cases.base
      || !cases.bull
      || !candidateConfidenceValues
    ) return null;
    return { cases, confidence: candidateConfidenceValues };
  }, [candidateCases, candidateConfidenceValues]);

  const candidateTradeTerms = useMemo(() => buildCandidateTradeTerms(candidateTrade), [candidateTrade]);
  const isPreEntry = campaign?.status === "PRE-ENTRY";

  const draft = useMemo<DecisionProposalDraftInput | null>(() => {
    if (reviewBoundary.status !== "VALID" || !horizon.trim()) return null;
    if (isPreEntry && !candidateConfidenceValues) return null;
    if (isPreEntry && !candidateAnchorsUnavailable && (!candidateValuation || !candidateTradeTerms)) return null;
    const assetView: Record<string, unknown> = buildJudgedView("ASSET", assetStance, assetNote);
    const tradeView: Record<string, unknown> = buildJudgedView("TRADE", tradeStance, tradeNote);
    if (isPreEntry && candidateConfidenceValues) {
      Object.assign(assetView, candidateConfidenceValues);
      if (!candidateAnchorsUnavailable && candidateValuation && candidateTradeTerms) {
        assetView.candidate_valuation = candidateValuation.cases;
        Object.assign(tradeView, candidateTradeTerms);
      }
    }
    return {
      asset_view: assetView,
      trade_view: tradeView,
      portfolio_view: buildPortfolioView(portfolioConstraint),
      review_by: reviewBoundary.iso,
      key_assumptions: splitLines(assumptions),
      event_invalidation_conditions: splitLines(invalidations),
      strategy_horizon: horizon.trim(),
      ...(draftWitness ? { draft_witness: draftWitness } : {}),
    };
  }, [assetStance, assetNote, tradeStance, tradeNote, portfolioConstraint, reviewBoundary, horizon, assumptions, invalidations, draftWitness, isPreEntry, candidateConfidenceValues, candidateAnchorsUnavailable, candidateValuation, candidateTradeTerms]);

  const applyAIDraft = (result: CampaignAIDraftGenerateResult) => {
    const fields = result.generated_fields;
    const asset = fields.asset_view as { stance?: ViewStance; note?: string };
    const trade = fields.trade_view as { stance?: ViewStance; note?: string };
    const portfolio = fields.portfolio_view as { constraint?: string };
    setAssetStance(asset.stance === "SUPPORT" || asset.stance === "OPPOSE" || asset.stance === "WAIT" ? asset.stance : "WAIT");
    setAssetNote(typeof asset.note === "string" ? asset.note : "");
    setTradeStance(trade.stance === "SUPPORT" || trade.stance === "OPPOSE" || trade.stance === "WAIT" ? trade.stance : "WAIT");
    setTradeNote(typeof trade.note === "string" ? trade.note : "");
    setPortfolioConstraint(typeof portfolio.constraint === "string" ? portfolio.constraint : "");
    const date = new Date(fields.review_by);
    if (!Number.isNaN(date.getTime())) {
      const local = new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
      setReviewByLocal(local);
    }
    setAssumptions(joinDraftLines(fields.key_assumptions));
    setInvalidations(joinDraftLines(fields.event_invalidation_conditions));
    setHorizon(fields.strategy_horizon);
    horizonTouched.current = true;
    setDraftWitness(result.draft_witness);
    setPreview(null);
    setConfirmed(false);
  };

  const handleGenerateAIDraft = async () => {
    setError("");
    const llm = loadLlm();
    if (!campaignId || !llm) {
      setError("请先在「接入 AI」配置模型，并确保投资计划上下文可用。");
      return;
    }
    setAiBusy(true);
    try {
      const result = await api.generateCampaignAIDraft(campaignId, llm);
      setAiDraft(result);
      applyAIDraft(result);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "AI Draft 生成失败。");
    } finally {
      setAiBusy(false);
    }
  };

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
      setError(isPreEntry
        ? "请明确选择四项把握程度；若估值依据可用，请完整填写悲观、基准、乐观三种情景、计划入场区间和失效价格；若不可用，请勾选“关键锚不可用”并选择有效复核时间。"
        : "请先选择有效复核时间、填写关注时间范围，并确保三组判断输入完整。" );
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
        setError(err instanceof ApiError ? `决策挑战读取失败：${err.message}` : "决策挑战状态当前无法验证。");
      }
    } catch (err) {
      setPreview(null);
      setChallengeReadState("ERROR");
      setError(err instanceof ApiError ? err.message : "预览失败，未生成决策草案。");
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
        setError("决策草案已失效，挑战记录未写入，请重新预览。");
      } else {
        setError(err instanceof ApiError ? `决策挑战读取失败：${err.message}` : "决策挑战状态当前无法验证。");
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
      || (campaign?.status === "PRE-ENTRY"
        && isCandidateBuyAction(preview.proposal.next_best_action)
        && (challengeReadState !== "FOUND" || !bindChallenge || !challengePacket?.challenge_id))
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
          setError(`正式决策已保存，但暂时无法重新读取验证（${err.message}）。系统不会显示未经验证的结果，请勿重复提交。`);
        } else if (err instanceof CommittedDecisionReadError) {
          setError(`${err.message}。正式决策已保存，但系统不会显示未经验证的结果，请勿重复提交。`);
        } else {
          setError("正式决策已保存，但当前无法重新读取验证。系统不会显示未经验证的结果，请勿重复提交。");
        }
      }
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setPreview(null);
        setConfirmed(false);
        setError("决策草案已失效，投资计划或当前投资逻辑已经变化，请重新预览。");
      } else {
        setError(err instanceof ApiError ? err.message : "正式决策提交失败。");
      }
    } finally {
      setBusy(null);
    }
  };

  const challengeStateLabel = {
    FOUND: "已完成",
    ABSENT: "尚未完成",
    PENDING: "正在读取",
    ERROR: "读取失败",
  }[challengeReadState];
  const challengeReadError = challengeReadState === "ERROR";
  const challengeReadPending = challengeReadState === "PENDING";

  const authorities = preview?.authority_evaluations ?? {};
  const material = authorities.material_change;
  const hardRisk = authorities.hard_risk;
  const criticalData = authorities.critical_data;
  const previewAssurance = preview?.decision_assurance as Record<string, unknown> | undefined;
  const dimensions = (previewAssurance?.dimension_states ?? {}) as Record<string, unknown>;
  const envelope = preview?.proposal.action_envelope as Record<string, unknown> | undefined;
  const portfolioCapital = presentPortfolioCapitalContext(preview?.proposal.portfolio_view, envelope);
  const candidateOpportunity = recordValue(preview?.proposal.authority_facts?.candidate_opportunity);
  const challengeRequiredForFreeze = Boolean(preview?.commit_requirements.challenge_required)
    || (campaign?.status === "PRE-ENTRY" && Boolean(preview && isCandidateBuyAction(preview.proposal.next_best_action)));
  const requiredChallengeReady = !challengeRequiredForFreeze
    || (challengeReadState === "FOUND" && bindChallenge && Boolean(challengePacket?.challenge_id));
  const committedTradeHref = committed && campaign
    ? buildEvaluatedTradeContinuationHref({
        securityCode: campaign.security_code,
        campaignId,
        decisionId: committed.committed.decision_id,
        nextBestAction: committed.committed.next_best_action,
        formalDecisionEvaluation: evaluationOf(committed.formal_decision),
      })
    : null;

  return (
    <div className="space-y-6" data-decision-proposal-page={campaignId}>
      <PageHeader
        title="正式决策"
        subtitle="先预览系统根据当前事实形成的决策草案；只有你明确确认后，才会保存为不可变的正式决策。"
        actions={(
          <div className="flex flex-wrap items-center gap-2">
            <Link
              to="/decision-inbox"
              className="inline-flex items-center gap-1.5 rounded border border-border/60 px-3 py-1.5 text-xs text-muted-foreground hover:text-foreground"
              data-testid="decision-inbox-secondary-entry"
            >
              <ArrowLeft className="h-3.5 w-3.5" /> 返回决策待办
            </Link>
            <button type="button" onClick={() => navigate(-1)} className="inline-flex items-center gap-1.5 rounded border border-border/60 px-3 py-1.5 text-xs text-muted-foreground hover:text-foreground">
              返回
            </button>
          </div>
        )}
      />

      <section className="rounded-lg border border-border/60 bg-background/35 p-4 space-y-3" data-decision-context={contextState} data-context-binding={binding?.thesis_id ?? ""} data-context-bound-thesis={boundThesis?.thesis.id ?? ""}>
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <span className="text-muted-foreground">投资计划</span>
          <span className="rounded bg-amber-500/15 px-1.5 py-0.5 text-amber-700">系统读取</span>
          {contextState === "loading" && <span className="text-muted-foreground">正在读取上下文…</span>}
        </div>
        <div className="grid gap-2 text-xs sm:grid-cols-2 lg:grid-cols-5">
          <div><p className="text-muted-foreground">股票代码</p><p className="mt-1 font-medium" data-context-security>{campaign?.security_code ?? "信息不足"}</p></div>
          <div><p className="text-muted-foreground">研究策略</p><p className="mt-1 font-medium" data-context-strategy>{campaign?.strategy ?? "信息不足"}</p></div>
          <div>
            <p className="text-muted-foreground">当前投资逻辑</p>
            <p
              className="mt-1 font-medium"
              data-context-thesis-status={currentThesis ? currentThesisStatusValue(currentThesis) : "UNAVAILABLE"}
            >
              {currentThesis
                ? currentThesisStatusLabel(currentThesisStatusValue(currentThesis))
                : "不可用"}
            </p>
          </div>
          <div><p className="text-muted-foreground">已冻结逻辑版本</p><p className="mt-1 font-medium" data-context-frozen-revision>{hydration?.frozenRevision ? `v${hydration.frozenRevision}` : "信息不足"}</p></div>
          <div><p className="text-muted-foreground">关注时间范围</p><p className="mt-1 font-medium" data-context-horizon>{hydration?.status === "READY" ? hydration.horizonText : "信息不足"}</p></div>
        </div>
        <details className="text-[10px] text-muted-foreground">
          <summary className="cursor-pointer select-none hover:text-foreground">技术详情</summary>
          <p className="mt-1 font-mono">campaign_id：{(campaign?.campaign_id ?? campaignId) || "MISSING"}</p>
          {currentThesis ? (
            <>
              <p className="font-mono">formal_status：{currentThesis.formal_status}</p>
              {currentThesis.ready ? <p className="font-mono">effective_state：{currentThesis.effective_state}</p> : null}
            </>
          ) : null}
        </details>
        {contextState === "ready" ? (
          <p className="text-xs leading-5 text-success" data-horizon-source="CURRENT_THESIS">
            关注时间范围已从当前投资逻辑预填，不是新的用户声明；你仍可按本次判断需要修改。
          </p>
        ) : contextState === "unavailable" ? (
          <p className="text-xs leading-5 text-warning" role="status" data-horizon-source="MANUAL_FALLBACK">
            当前投资逻辑无法提供可信的关注时间范围（{contextMessage || "信息不足"}）。系统不会猜测，请在下方手工填写。
          </p>
        ) : (
          <p className="text-xs leading-5 text-muted-foreground">正在读取股票、策略和当前投资逻辑；页面不会让你重复填写这些系统已有信息。</p>
        )}
      </section>

      <section className="grid gap-4 lg:grid-cols-3">
        <fieldset className="rounded-md border border-border/50 bg-background/35 p-3 text-xs" data-view-form="asset_view">
          <legend className="px-1 font-medium text-foreground">对这只股票的判断</legend>
          <label className="mt-1 block text-muted-foreground">
            判断方向
            <select
              aria-label="对这只股票的判断"
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
              aria-label="股票判断说明"
              type="text"
              value={assetNote}
              onChange={(event) => setAssetNote(event.target.value)}
              placeholder="例如：高端白酒需求稳定"
              className={inputCls}
            />
          </label>
        </fieldset>
        <fieldset className="rounded-md border border-border/50 bg-background/35 p-3 text-xs" data-view-form="trade_view">
          <legend className="px-1 font-medium text-foreground">当前操作倾向</legend>
          <label className="mt-1 block text-muted-foreground">
            操作方向
            <select
              aria-label="当前操作倾向"
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
              aria-label="操作倾向说明"
              type="text"
              value={tradeNote}
              onChange={(event) => setTradeNote(event.target.value)}
              placeholder="例如：等待缩量回调再入场"
              className={inputCls}
            />
          </label>
        </fieldset>
        <fieldset className="rounded-md border border-border/50 bg-background/35 p-3 text-xs" data-view-form="portfolio_view">
          <legend className="px-1 font-medium text-foreground">组合层面的限制</legend>
          <label className="mt-1 block text-muted-foreground">
            组合约束（选填）
            <input
              aria-label="组合层面的限制"
              type="text"
              value={portfolioConstraint}
              onChange={(event) => setPortfolioConstraint(event.target.value)}
              placeholder="例如：单笔风险不超过组合 2%"
              className={inputCls}
            />
          </label>
        </fieldset>
      </section>

      {isPreEntry && (
        <section
          className="space-y-4 rounded-lg border border-primary/30 bg-primary/5 p-4"
          data-testid="pre-entry-candidate-form"
          data-candidate-form-valid={candidateConfidenceValues && (candidateAnchorsUnavailable || (candidateValuation && candidateTradeTerms)) ? "yes" : "no"}
        >
          <div>
            <h2 className="text-sm font-semibold">入场前候选判断</h2>
            <p className="mt-1 text-xs leading-5 text-muted-foreground">
              分别填写悲观、基准、乐观三种情景及来源日期、估值区间和入场失效条件。持仓、账户和风险上限由系统读取，不由浏览器猜测。
              把握程度可以明确选择“信息不足”；系统会保守地收窄为“继续研究”，不会伪装成低置信度结论。
            </p>
          </div>

          <label className="flex items-start gap-2 rounded-md border border-warning/30 bg-background/50 p-3 text-xs">
            <input
              type="checkbox"
              aria-label="关键盈利估值和入场依据不可用"
              checked={candidateAnchorsUnavailable}
              onChange={(event) => setCandidateAnchorsUnavailable(event.target.checked)}
              className="mt-0.5"
            />
            <span>
              <span className="font-medium">关键盈利 / 估值 / 入场锚当前不可用</span>
              <span className="mt-1 block text-muted-foreground">勾选后不会提交三种情景或入场、失效价格；你仍需明确选择各项把握程度，系统会保持“信息不足 / 继续研究”，而不是伪造价格。</span>
            </span>
          </label>

          <fieldset>
            <legend className="text-xs font-medium">把握程度（全部明确选择）</legend>
            <div className="mt-2 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              {(Object.keys(CANDIDATE_CONFIDENCE_LABELS) as CandidateConfidenceName[]).map((name) => (
                <label key={name} className="text-xs text-muted-foreground">
                  {CANDIDATE_CONFIDENCE_LABELS[name]}
                  <select
                    aria-label={CANDIDATE_CONFIDENCE_LABELS[name]}
                    value={candidateConfidence[name]}
                    onChange={(event) => setCandidateConfidence((current) => ({
                      ...current,
                      [name]: event.target.value as CandidateConfidence | "",
                    }))}
                    className={inputCls}
                  >
                    <option value="">请选择</option>
                    {CANDIDATE_CONFIDENCE_LEVELS.map((level) => <option key={level} value={level}>{CANDIDATE_CONFIDENCE_VALUE_LABELS[level]}</option>)}
                  </select>
                </label>
              ))}
            </div>
          </fieldset>

          <div className="grid gap-4 xl:grid-cols-3" aria-disabled={candidateAnchorsUnavailable}>
            {CANDIDATE_SCENARIOS.map((scenario) => {
              const row = candidateCases[scenario];
              const update = (name: keyof CandidateValuationCaseDraft, value: string) => setCandidateCases((current) => ({
                ...current,
                [scenario]: { ...current[scenario], [name]: value },
              }));
              return (
                <fieldset key={scenario} disabled={candidateAnchorsUnavailable} className="space-y-2 rounded-md border border-border/60 bg-background/50 p-3 disabled:opacity-50" data-candidate-scenario={scenario}>
                  <legend className="px-1 text-sm font-semibold">{CANDIDATE_SCENARIO_LABELS[scenario]}情景</legend>
                  <div className="grid grid-cols-2 gap-2">
                    <label className="text-xs text-muted-foreground">价格下限
                      <input aria-label={`${CANDIDATE_SCENARIO_LABELS[scenario]} price low`} type="number" min="0" step="any" value={row.priceLow} onChange={(event) => update("priceLow", event.target.value)} className={inputCls} />
                    </label>
                    <label className="text-xs text-muted-foreground">价格上限
                      <input aria-label={`${CANDIDATE_SCENARIO_LABELS[scenario]} price high`} type="number" min="0" step="any" value={row.priceHigh} onChange={(event) => update("priceHigh", event.target.value)} className={inputCls} />
                    </label>
                  </div>
                  <label className="block text-xs text-muted-foreground">情景假设（逗号或换行分隔）
                    <textarea aria-label={`${CANDIDATE_SCENARIO_LABELS[scenario]} assumptions`} rows={2} value={row.assumptions} onChange={(event) => update("assumptions", event.target.value)} className={inputCls} />
                  </label>
                  <div className="grid grid-cols-3 gap-2">
                    <label className="text-xs text-muted-foreground">估值指标
                      <input aria-label={`${CANDIDATE_SCENARIO_LABELS[scenario]} input metric`} value={row.inputMetric} onChange={(event) => update("inputMetric", event.target.value)} placeholder="EPS" className={inputCls} />
                    </label>
                    <label className="text-xs text-muted-foreground">指标值
                      <input aria-label={`${CANDIDATE_SCENARIO_LABELS[scenario]} input value`} value={row.inputValue} onChange={(event) => update("inputValue", event.target.value)} placeholder="8.5" className={inputCls} />
                    </label>
                    <label className="text-xs text-muted-foreground">对应期间
                      <input aria-label={`${CANDIDATE_SCENARIO_LABELS[scenario]} input period`} value={row.inputPeriod} onChange={(event) => update("inputPeriod", event.target.value)} placeholder="2026E" className={inputCls} />
                    </label>
                  </div>
                  <label className="block text-xs text-muted-foreground">来源
                    <input aria-label={`${CANDIDATE_SCENARIO_LABELS[scenario]} source`} value={row.source} onChange={(event) => update("source", event.target.value)} placeholder="公告 / 研报标题" className={inputCls} />
                  </label>
                  <div className="grid grid-cols-2 gap-2">
                    <label className="text-xs text-muted-foreground">数据日期
                      <input aria-label={`${CANDIDATE_SCENARIO_LABELS[scenario]} data at`} type="date" value={row.dataAt} onChange={(event) => update("dataAt", event.target.value)} className={inputCls} />
                    </label>
                    <label className="text-xs text-muted-foreground">关注期限
                      <input aria-label={`${CANDIDATE_SCENARIO_LABELS[scenario]} horizon`} value={row.horizon} onChange={(event) => update("horizon", event.target.value)} placeholder="12 个月" className={inputCls} />
                    </label>
                  </div>
                  <label className="block text-xs text-muted-foreground">哪些变化会改变此情景（逗号或换行分隔）
                    <textarea aria-label={`${CANDIDATE_SCENARIO_LABELS[scenario]} change conditions`} rows={2} value={row.changeConditions} onChange={(event) => update("changeConditions", event.target.value)} className={inputCls} />
                  </label>
                </fieldset>
              );
            })}
          </div>

          <fieldset disabled={candidateAnchorsUnavailable} className="rounded-md border border-border/60 bg-background/50 p-3 disabled:opacity-50">
            <legend className="px-1 text-sm font-semibold">入场与失效条件</legend>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <label className="text-xs text-muted-foreground">计划入场下限
                <input aria-label="Candidate entry low" type="number" min="0" step="any" value={candidateTrade.entryLow} onChange={(event) => setCandidateTrade((current) => ({ ...current, entryLow: event.target.value }))} className={inputCls} />
              </label>
              <label className="text-xs text-muted-foreground">计划入场上限
                <input aria-label="Candidate entry high" type="number" min="0" step="any" value={candidateTrade.entryHigh} onChange={(event) => setCandidateTrade((current) => ({ ...current, entryHigh: event.target.value }))} className={inputCls} />
              </label>
              <label className="text-xs text-muted-foreground">失效价格
                <input aria-label="Candidate invalidation price" type="number" min="0" step="any" value={candidateTrade.invalidationPrice} onChange={(event) => setCandidateTrade((current) => ({ ...current, invalidationPrice: event.target.value }))} className={inputCls} />
              </label>
              <label className="text-xs text-muted-foreground">执行方式（选填）
                <select aria-label="Candidate execution style" value={candidateTrade.executionStyle} onChange={(event) => setCandidateTrade((current) => ({ ...current, executionStyle: event.target.value as "" | "SCALE_IN" }))} className={inputCls}>
                  <option value="">未指定</option>
                  <option value="SCALE_IN">分批建仓</option>
                </select>
              </label>
            </div>
            <p className="mt-2 text-[11px] text-muted-foreground">必须满足：0 &lt; 失效价格 &lt; 入场下限 ≤ 入场上限；不合法时不会生成可预览的草案。</p>
          </fieldset>
        </section>
      )}

      <section className="grid gap-4 rounded-lg border border-border/60 bg-background/35 p-4 sm:grid-cols-2">
        <div className="text-xs text-muted-foreground">下次必须重新检查的时间（必填，由你明确选择）
          <input aria-label="下次必须重新检查的时间" type="datetime-local" value={reviewByLocal} onChange={(event) => setReviewByLocal(event.target.value)} className={inputCls} />
          <p className="mt-1 font-mono text-[10px] text-muted-foreground" data-review-by-canonical>
            {reviewBoundary.status === "VALID" ? reviewBoundary.iso : "尚未选择有效复核时间"}
          </p>
          <p className="text-[10px] text-muted-foreground" data-review-by-tz>
            解析时区：{browserTimeZoneName()}
            {reviewBoundary.status === "VALID"
              ? `（${formatUtcOffsetMinutes(reviewBoundary.date.getTimezoneOffset())}）`
              : "（选择时间后显示偏移）"}
            ；上方为系统将保存的标准 UTC 时间。
          </p>
        </div>
        <label className="text-xs text-muted-foreground">这次判断关注的时间范围（必填）
          <input aria-label="这次判断关注的时间范围" value={horizon} onChange={(event) => { horizonTouched.current = true; setHorizon(event.target.value); }} placeholder="例如：2 至 4 周" className={inputCls} />
        </label>
        <label className="text-xs text-muted-foreground">这个判断成立依赖什么（逗号或换行分隔）
          <textarea aria-label="这个判断成立依赖什么" value={assumptions} onChange={(event) => setAssumptions(event.target.value)} rows={3} className={inputCls} />
        </label>
        <label className="text-xs text-muted-foreground">出现什么情况说明判断错了（逗号或换行分隔）
          <textarea aria-label="出现什么情况说明判断错了" value={invalidations} onChange={(event) => setInvalidations(event.target.value)} rows={3} className={inputCls} />
        </label>
      </section>

      {error && <div role="alert" className="flex items-center gap-2 rounded-md border border-red-500/30 bg-red-500/5 p-3 text-xs text-red-600"><AlertCircle className="h-4 w-4 shrink-0" />{error}</div>}

      <div className="flex flex-wrap items-center gap-3">
        <button type="button" onClick={() => void handleGenerateAIDraft()} disabled={busy !== null || aiBusy || contextState !== "ready"} className="inline-flex items-center gap-1.5 rounded-md border border-primary/50 px-3 py-2 text-xs font-medium hover:bg-muted disabled:opacity-50" data-testid="generate-ai-draft">
          {aiBusy && <Loader2 className="h-3.5 w-3.5 animate-spin" />} 生成 AI 草稿
        </button>
        <button type="button" onClick={() => void handlePreview()} disabled={busy !== null || aiBusy} className="inline-flex items-center gap-1.5 rounded-md border border-border/60 px-3 py-2 text-xs font-medium hover:bg-muted disabled:opacity-50">
          {busy === "preview" && <Loader2 className="h-3.5 w-3.5 animate-spin" />} 预览决策草案
        </button>
        <span className="text-xs text-muted-foreground">AI 草稿只填入可编辑内容；预览仅做只读计算，不会创建正式决策。</span>
      </div>
      {aiDraft && (
        <section className="rounded-md border border-primary/40 bg-primary/5 p-3 text-xs" data-ai-draft-status="UNCOMMITTED">
          <p className="font-medium">AI 草稿 / 尚未提交</p>
          <p className="mt-1 text-muted-foreground">已填入下方表单。你修改任一判断后，系统会把该部分视为用户草稿。</p>
          <details className="mt-1 text-[10px] text-muted-foreground">
            <summary className="cursor-pointer select-none hover:text-foreground">技术详情</summary>
            <p className="mt-1 font-mono">draft_id：{aiDraft.draft_id}</p>
          </details>
          <button type="button" onClick={() => applyAIDraft(aiDraft)} disabled={busy !== null || aiBusy} className="mt-2 rounded border border-border/60 px-2 py-1 hover:bg-muted">再次填入</button>
        </section>
      )}

      {preview && (
        <section className="space-y-4 rounded-lg border border-amber-500/40 bg-amber-500/5 p-4" data-proposal-status="UNCOMMITTED" role="status">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <h2 className="text-sm font-semibold">决策草案 <span className="rounded bg-amber-500/15 px-1.5 py-0.5 text-amber-700">尚未提交</span></h2>
              <p className="mt-1 text-[11px] text-muted-foreground">评估时间：<span className="font-mono">{preview.proposal.as_of}</span></p>
            </div>
            <details className="text-[10px] text-muted-foreground">
              <summary className="cursor-pointer select-none hover:text-foreground">技术详情</summary>
              <p className="mt-1 font-mono">fingerprint：{preview.proposal_fingerprint}</p>
            </details>
          </div>

          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-6">
            {[
              ["正式投资逻辑", authorities.formal_thesis],
              ["正式决策", authorities.formal_decision],
              ["硬风险", hardRisk],
              ["关键数据", criticalData],
              ["重大变化", material],
              ["卖出复核", authorities.sell_engine],
            ].map(([label, value]) => {
              const evaluation = evaluationOf(value);
              const isCriticalData = label === "关键数据";
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
                <p className="mt-1 font-medium">{decisionEvaluationLabel(evaluation)}</p>
                <details className="mt-1 text-[10px] text-muted-foreground">
                  <summary className="cursor-pointer">技术状态</summary>
                  <p className="mt-1 font-mono">{evaluation}</p>
                  {isCriticalData && <>
                    <p className="mt-1 font-mono">state: {String(record?.critical_data_state ?? "UNKNOWN")}</p>
                    <p className="truncate" title={shortestReason(value)}>reason: {shortestReason(value)}</p>
                  </>}
                </details>
              </div>;
            })}
          </div>

          {candidateOpportunity && (
            <section className="space-y-3 rounded-md border border-primary/30 bg-primary/5 p-3 text-xs" data-testid="candidate-opportunity-authority">
              <div>
                <h3 className="font-semibold">候选机会判断</h3>
                <p className="mt-1 text-[11px] text-muted-foreground">这些状态由系统根据当前事实计算；页面只读呈现，不会从表单或浏览器猜测仓位。</p>
              </div>
              <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
                {CANDIDATE_PRIMARY_FIELDS.map(([label, key]) => (
                  <div
                    key={key}
                    className="rounded border border-border/50 bg-background/45 p-2"
                    data-candidate-field={key}
                    data-candidate-raw={typeof candidateOpportunity[key] === "object" ? JSON.stringify(candidateOpportunity[key]) : String(candidateOpportunity[key] ?? "")}
                  >
                    <p className="text-muted-foreground">{label}</p>
                    <p className="mt-1 break-words font-medium">{presentCandidateValue(key, candidateOpportunity[key])}</p>
                  </div>
                ))}
              </div>
              <details className="text-muted-foreground">
                <summary className="cursor-pointer font-medium">技术详情</summary>
                {stringList(candidateOpportunity.evidence_refs).length > 0 && (
                  <div className="mt-1">
                    <p>证据引用</p>
                    <ul className="mt-1 list-disc space-y-0.5 pl-4 font-mono text-[11px]">
                      {stringList(candidateOpportunity.evidence_refs).map((ref) => <li key={ref}>{ref}</li>)}
                    </ul>
                  </div>
                )}
                {stringList(candidateOpportunity.reason_codes).length > 0 && (
                  <div className="mt-1">
                    <p>原因代码</p>
                    <ul className="mt-1 list-disc space-y-0.5 pl-4 font-mono text-[11px]">
                      {stringList(candidateOpportunity.reason_codes).map((reason) => <li key={reason}>{reason}</li>)}
                    </ul>
                  </div>
                )}
                <pre className="mt-1 overflow-auto whitespace-pre-wrap break-all font-mono text-[10px]">{JSON.stringify(candidateOpportunity, null, 2)}</pre>
              </details>
            </section>
          )}

          {isPreEntry && (
            <section
              className="space-y-3 rounded-md border border-border/60 bg-background/35 p-3 text-xs"
              data-testid="portfolio-capital-context"
              data-capital-availability={portfolioCapital.capitalAvailability.state}
              data-portfolio-fit={portfolioCapital.portfolioFit.state}
              data-replacement-review={portfolioCapital.replacementReview.state}
              data-capital-context-valid={portfolioCapital.valid ? "true" : "false"}
              aria-labelledby="portfolio-capital-context-title"
            >
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div>
                  <h3 id="portfolio-capital-context-title" className="font-semibold">资金与组合限制</h3>
                  <p className="mt-1 text-[11px] text-muted-foreground">
                    这里展示系统读取到的资金与组合约束，只用于本次决策预览，不会从浏览器输入猜测账户事实。
                  </p>
                </div>
                <details className="text-[10px] text-muted-foreground">
                  <summary className="cursor-pointer">技术版本</summary>
                  <span className="font-mono">{portfolioCapital.schemaVersion ?? "UNKNOWN"}</span>
                </details>
              </div>

              <div className="grid gap-2 md:grid-cols-3">
                {[
                  {
                    key: "capital-availability",
                    label: "可用资金",
                    state: portfolioCapital.capitalAvailability.state,
                    metricLabel: "已确认现金",
                    metricValue: formatConfirmedCash(portfolioCapital.capitalAvailability.confirmedCash),
                    metricTestId: "portfolio-capital-confirmed-cash",
                    reasonCodes: portfolioCapital.capitalAvailability.reasonCodes,
                  },
                  {
                    key: "portfolio-fit",
                    label: "组合适配情况",
                    state: portfolioCapital.portfolioFit.state,
                    metricLabel: "现有持仓数",
                    metricValue: portfolioCapital.portfolioFit.existingPositionCount === null
                      ? "信息不足"
                      : String(portfolioCapital.portfolioFit.existingPositionCount),
                    metricTestId: "portfolio-capital-existing-positions",
                    reasonCodes: portfolioCapital.portfolioFit.reasonCodes,
                  },
                  {
                    key: "replacement-review",
                    label: "是否需要替换复核",
                    state: portfolioCapital.replacementReview.state,
                    metricLabel: "待复核候选数",
                    metricValue: portfolioCapital.replacementReview.state === "UNKNOWN"
                      ? "信息不足"
                      : String(portfolioCapital.replacementReview.candidates.length),
                    metricTestId: "portfolio-capital-replacement-count",
                    reasonCodes: portfolioCapital.replacementReview.reasonCodes,
                  },
                ].map((item) => (
                  <div key={item.key} className="rounded border border-border/50 bg-background/45 p-2" data-capital-dimension={item.key}>
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <p className="text-muted-foreground">{item.label}</p>
                      <span className={`rounded px-1.5 py-0.5 font-mono text-[10px] font-medium ${portfolioCapitalBadgeClass(item.state)}`}>
                        {presentAuthorityValue(item.state)}
                      </span>
                    </div>
                    <p className="mt-2">
                      {item.metricLabel}: <span className="font-mono font-medium" data-testid={item.metricTestId}>{item.metricValue}</span>
                    </p>
                    <p className="mt-2 text-[10px] text-muted-foreground">原因</p>
                    {item.reasonCodes.length > 0 ? (
                      <details className="mt-1 text-muted-foreground">
                        <summary className="cursor-pointer">查看技术原因</summary>
                        <ul className="mt-1 list-disc space-y-0.5 pl-4 font-mono text-[10px]">
                          {item.reasonCodes.map((reason) => <li key={reason}>{reason}</li>)}
                        </ul>
                      </details>
                    ) : (
                      <p className="mt-1 text-[10px] text-muted-foreground">{item.state === "UNKNOWN" ? "信息不足" : "—"}</p>
                    )}
                  </div>
                ))}
              </div>

              <div className="grid gap-2 sm:grid-cols-2">
                <div className="rounded border border-border/50 bg-background/45 p-2">
                  <p className="text-muted-foreground">仓位计算状态</p>
                  <p className="mt-1 font-medium" data-testid="portfolio-capital-position-sizing">{presentAuthorityValue(portfolioCapital.positionSizingStatus)}</p>
                </div>
                <div className="rounded border border-border/50 bg-background/45 p-2" data-testid="portfolio-capital-final-actions">
                  <p className="text-muted-foreground">最终允许的操作</p>
                  {portfolioCapital.finalAllowedActions === null ? (
                    <p className="mt-1 font-medium text-warning">信息不足</p>
                  ) : portfolioCapital.finalAllowedActions.length > 0 ? (
                    <div className="mt-1 flex flex-wrap gap-1.5">
                      {portfolioCapital.finalAllowedActions.map((action) => (
                        <span key={action} className="rounded bg-muted px-1.5 py-0.5 text-[10px]" data-action-enum={action}>
                          {decisionActionLabel(action)}
                        </span>
                      ))}
                    </div>
                  ) : (
                    <p className="mt-1 font-medium">无</p>
                  )}
                </div>
              </div>

              {portfolioCapital.replacementReview.candidates.length > 0 && (
                <div className="space-y-1.5" data-testid="portfolio-capital-replacement-candidates">
                  <p className="font-medium">需要对比复核的现有计划</p>
                  {portfolioCapital.replacementReview.candidates.map((candidate) => (
                    <div key={`${candidate.campaign_id}:${candidate.security_code}`} className="rounded border border-border/40 bg-background/40 p-2">
                      <p className="text-[11px]">{candidate.security_code} · {candidate.strategy}</p>
                      <details className="mt-1 text-[10px] text-muted-foreground">
                        <summary className="cursor-pointer select-none hover:text-foreground">技术详情</summary>
                        <p className="mt-1 font-mono">campaign_id：{candidate.campaign_id}</p>
                        <p className="font-mono">reason_codes：{candidate.reason_codes.length > 0 ? candidate.reason_codes.join(" · ") : "—"}</p>
                      </details>
                    </div>
                  ))}
                </div>
              )}

              {portfolioCapital.authorityRefs.length > 0 && (
                <details className="text-muted-foreground">
                  <summary className="cursor-pointer select-none hover:text-foreground">技术依据（{portfolioCapital.authorityRefs.length}）</summary>
                  <ul className="mt-1 space-y-0.5 font-mono text-[10px]">
                    {portfolioCapital.authorityRefs.map((ref) => <li key={ref}>{ref}</li>)}
                  </ul>
                </details>
              )}

              <p className="text-[11px] leading-5 text-muted-foreground">
                替换复核只用于提醒你人工比较，不会自动换仓、买卖、减仓、再平衡或创建交易。
              </p>
            </section>
          )}

          <div className="grid gap-4 md:grid-cols-3">
            {["asset_view", "trade_view", "portfolio_view"].map((name) => (
              <div key={name} className="rounded-md border border-border/50 bg-background/35 p-3 text-xs"><p className="font-medium">{name === "asset_view" ? "股票判断" : name === "trade_view" ? "操作倾向" : "组合限制"}</p><p className="mt-1 text-muted-foreground">用户草稿 · 尚未成为正式决策</p></div>
            ))}
          </div>

          <div className="rounded-md border border-border/50 bg-background/35 p-3 text-xs" data-testid="decision-assurance">
            <p className="font-medium">决策完整性检查（同一评估时点）</p>
            <p className="mt-1 text-muted-foreground">
              {previewAssurance?.coverage_complete === true
                ? "所有必要检查项均已完成。"
                : previewAssurance?.coverage_complete === false
                  ? "仍有检查项未完成或信息不足；系统不会据此放宽决策。"
                  : "当前无法确认检查完整性；系统会保持保守。"}
            </p>
            <div className="mt-2 grid gap-1.5 sm:grid-cols-2 lg:grid-cols-5">
              {Object.entries(dimensions).map(([dimension, value]) => (
                <span key={dimension} className="flex items-center justify-between gap-2 rounded bg-muted/40 px-2 py-1">
                  <span>{DECISION_ASSURANCE_LABELS[dimension] ?? "未识别检查项"}</span>
                  <span>{decisionEvaluationLabel(value)}</span>
                </span>
              ))}
            </div>
            <details className="mt-2 text-[10px] text-muted-foreground">
              <summary className="cursor-pointer select-none hover:text-foreground">技术详情</summary>
              <pre className="mt-1 overflow-auto whitespace-pre-wrap break-all font-mono">{JSON.stringify(dimensions, null, 2)}</pre>
            </details>
          </div>

          <div className="rounded-md border border-border/50 bg-background/35 p-3 text-xs" data-action-envelope>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="font-medium">限制条件与可执行范围</p>
              <span className="text-[10px] text-muted-foreground" data-constraint-evaluation={preview.proposal.constraint_evaluation}>
                {decisionEvaluationLabel(preview.proposal.constraint_evaluation)}
              </span>
            </div>
            <div className="mt-2 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {[
                ["允许", "allowed_actions"],
                ["禁止", "blocked_actions"],
                ["维持条件", "maintain_conditions"],
                ["升级条件", "upgrade_conditions"],
                ["降级条件", "downgrade_conditions"],
                ["失效条件", "invalidation_conditions"],
              ].map(([label, key]) => (
                <div key={key} className="rounded border border-border/40 bg-background/40 p-2">
                  <p className="text-muted-foreground">{label}</p>
                  <ul className="mt-1 list-disc space-y-0.5 pl-4">
                    {stringList(envelope?.[key]).map((item) => (
                      <li key={item} {...(key === "allowed_actions" || key === "blocked_actions" ? { "data-action-enum": item } : {})}>
                        {key === "allowed_actions" || key === "blocked_actions" ? decisionActionLabel(item) : item}
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          </div>

          <div className="rounded-md border border-border/50 bg-background/35 p-3 text-xs">
            <p className="font-medium">当前建议的下一步</p>
            <p className="mt-1 text-base font-semibold" data-next-best-action={preview.proposal.next_best_action}>
              {decisionActionLabel(preview.proposal.next_best_action)}
            </p>
            <p className="mt-1 text-muted-foreground">任何尚未评估或信息不足的关键状态，都会把草案收窄到“等待 / 继续研究”，不会开放更激进的操作。</p>
          </div>

          <section
            className="space-y-3 rounded-md border border-border/60 bg-background/45 p-3"
            data-challenge-state={challengeReadState}
            data-challenge-id={challengePacket?.challenge_id ?? ""}
            data-decision-quality="NOT_EVALUATED"
          >
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h3 className="text-sm font-semibold">
                决策挑战（{challengeRequiredForFreeze ? "本次新增风险操作必需" : "可选"}；读取失败时不会放宽要求）
              </h3>
              <span className="rounded bg-muted px-1.5 py-0.5 text-[10px]">
                {challengeStateLabel}
              </span>
            </div>
            <p className="text-[11px] text-muted-foreground">
              四个问题必须由你明确填写。“信息不足”表示已经正视缺口，但不是正面证据。挑战记录不会改变系统的确定性限制，也不会产生决策质量评分。
            </p>
            {challengeReadPending && (
              <p role="status" className="rounded border border-border/40 bg-muted/30 p-2 text-xs">
                正在读取决策挑战状态；在读取完成前不会开放确认、冻结或绑定。
              </p>
            )}
            {challengeReadError && (
              <p role="alert" className="rounded border border-red-500/30 bg-red-500/5 p-2 text-xs text-red-600">
                决策挑战读取失败：当前状态无法验证；本次不会绑定未验证的记录，也不会开放确认或冻结。
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
                      <option value="ANSWERED">已回答</option>
                      <option value="UNKNOWN">信息不足</option>
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
                <p className="font-medium">决策挑战已完成并可绑定。</p>
                <details className="text-muted-foreground">
                  <summary className="cursor-pointer">技术详情</summary>
                  <p className="mt-1">challenge_id：<span className="font-mono">{challengePacket.challenge_id}</span></p>
                  <p>packet_state：<span className="font-mono">{challengePacket.packet_state}</span> · evaluation：<span className="font-mono">{challengePacket.challenge_evaluation}</span></p>
                  <p>finalized_at：<span className="font-mono">{challengePacket.finalized_at}</span></p>
                  <p>decision_quality：<span className="font-mono">{challengePacket.decision_quality}</span> · two-pass independence：<span className="font-mono">{challengePacket.two_pass_semantic_independence_verified}</span></p>
                </details>
              </div>
            ) : (
              <>
                <label className="flex items-start gap-2 text-xs">
                  <input type="checkbox" checked={challengeConfirmed} onChange={(event) => setChallengeConfirmed(event.target.checked)} className="mt-0.5" />
                  <span>我已明确填写四个挑战问题，确认保存这份不可变记录。</span>
                </label>
                <button
                  type="button"
                  onClick={() => void handleFinalizeChallenge()}
                  disabled={!challengeConfirmed || busy !== null || !draft || challengeReadState !== "ABSENT"}
                  className="inline-flex items-center gap-1.5 rounded-md border border-border/60 px-3 py-2 text-xs font-medium hover:bg-muted disabled:opacity-50"
                >
                  {busy === "challenge" && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                  完成决策挑战
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
                  ? "正式决策将绑定这份已完成的挑战记录。"
                  : challengeReadState === "ABSENT"
                    ? challengeRequiredForFreeze
                      ? "本次草案允许新增风险；必须先完成并绑定决策挑战，才会开放正式确认。"
                      : "尚无已完成的决策挑战；本次不新增风险，可以继续确认，系统不会写入虚假引用。"
                    : "决策挑战状态当前无法安全验证；读取完成前不会确认，也不会绑定未验证的记录。"}
              </span>
            </label>
          </section>

          <label className="flex items-start gap-2 rounded-md border border-border/60 bg-background/45 p-3 text-xs">
            <input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} className="mt-0.5" />
            <span>我已检查股票判断、操作倾向、组合限制、同一评估时点及系统限制，确认把这份草案保存为不可变的正式决策。</span>
          </label>
          <button type="button" onClick={() => void handleCommit()} disabled={!confirmed || busy !== null || challengeReadState === "PENDING" || challengeReadState === "ERROR" || !requiredChallengeReady} className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-2 text-xs font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50">
            {busy === "commit" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <LockKeyhole className="h-3.5 w-3.5" />}
            确认并冻结正式决策
          </button>
        </section>
      )}

      {committed && (
        <section
          className="space-y-3 rounded-lg border border-success/40 bg-success/5 p-4"
          data-formal-decision-evaluation={evaluationOf(committed.formal_decision)}
          data-committed-decision-id={String(committed.committed.decision_id ?? "")}
          role="status"
        >
          <h2 className="flex items-center gap-2 text-sm font-semibold"><CheckCircle2 className="h-4 w-4 text-success" />正式决策已保存并重新读取确认</h2>
          <p className="text-xs text-muted-foreground">当前决策状态：{decisionEvaluationLabel(evaluationOf(committed.formal_decision))} · 评估时间：<span className="font-mono">{committed.as_of}</span></p>
          <div className="grid gap-2 sm:grid-cols-3">
            <div className="rounded border border-border/50 bg-background/40 p-2 text-xs">正式投资逻辑：{decisionEvaluationLabel(evaluationOf(committed.formal_thesis))}</div>
            <div className="rounded border border-border/50 bg-background/40 p-2 text-xs">硬风险：{decisionEvaluationLabel(evaluationOf(committed.hard_risk))}</div>
            <div className="rounded border border-border/50 bg-background/40 p-2 text-xs">重大变化：{decisionEvaluationLabel(evaluationOf(committed.material_change))}</div>
          </div>
          <details className="text-[10px] text-muted-foreground">
            <summary className="cursor-pointer select-none hover:text-foreground">技术详情</summary>
            <p className="mt-1 font-mono">decision_id：{String(committed.committed.decision_id ?? "—")}</p>
            <p className="font-mono">evaluation：{evaluationOf(committed.formal_decision)}</p>
          </details>
          <p className="text-xs text-muted-foreground">决策待办会在下次刷新时读取这条记录；它是已确认的历史决策，不等于系统自动给出的当前建议。</p>
          <div className="flex flex-wrap gap-x-4 gap-y-2">
            <Link to="/decision-inbox" className="inline-flex text-xs text-primary hover:underline">打开决策待办 →</Link>
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
