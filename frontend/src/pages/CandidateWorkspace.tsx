import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { AlertCircle, ArrowLeft, CheckCircle2, FileSearch, Loader2 } from "lucide-react";
import { CandidateCampaignPanel } from "@/components/campaign/CandidateCampaignPanel";
import { NativeIntelSecurityContext } from "@/components/native-intel/NativeIntelSecurityContext";
import { GlassCard } from "@/components/ui/GlassCard";
import { PageHeader } from "@/components/ui/PageHeader";
import {
  candidateWorkspaceHref,
  buildCandidateEvidenceGap,
  deriveCandidatePosition,
  type CandidatePositionPresentation,
} from "@/lib/candidateCampaign";
import { api, ApiError, type EvidenceRecord } from "@/lib/api";

type LoadState<T> =
  | { status: "loading"; value: null; error: "" }
  | { status: "ready"; value: T; error: "" }
  | { status: "error"; value: null; error: string };

const loadingState = <T,>(): LoadState<T> => ({ status: "loading", value: null, error: "" });

const positionTone: Record<CandidatePositionPresentation["state"], string> = {
  HELD: "bg-success/15 text-success",
  NOT_HELD: "bg-primary/10 text-primary",
  UNKNOWN: "bg-warning/15 text-warning",
};

function errorMessage(cause: unknown, fallback: string): string {
  return cause instanceof ApiError ? cause.message : fallback;
}

export function CandidateWorkspace() {
  const { code = "" } = useParams();
  const validCode = /^\d{6}$/.test(code);
  const [position, setPosition] = useState<LoadState<CandidatePositionPresentation>>(loadingState);
  const [evidence, setEvidence] = useState<LoadState<{ records: EvidenceRecord[]; total: number }>>(loadingState);

  useEffect(() => {
    let cancelled = false;
    setPosition(loadingState());
    setEvidence(loadingState());
    if (!validCode) return () => { cancelled = true; };

    const positionRequest = api.getDerivedPositions()
      .then((result) => {
        if (!cancelled) setPosition({ status: "ready", value: deriveCandidatePosition(result, code), error: "" });
      })
      .catch((cause) => {
        if (!cancelled) setPosition({ status: "error", value: null, error: errorMessage(cause, "Position Reality 读取失败") });
      });
    const evidenceRequest = api.evidenceList({ subject_type: "stock", subject_id: code, limit: 200, offset: 0 })
      .then((result) => {
        if (!cancelled) setEvidence({ status: "ready", value: { records: result.items, total: result.total }, error: "" });
      })
      .catch((cause) => {
        if (!cancelled) setEvidence({ status: "error", value: null, error: errorMessage(cause, "Evidence Ledger 读取失败") });
      });
    void Promise.allSettled([positionRequest, evidenceRequest]);

    return () => { cancelled = true; };
  }, [code, validCode]);

  if (!validCode) {
    return (
      <div className="space-y-6" data-testid="candidate-workspace-invalid">
        <PageHeader title="Candidate Workspace" subtitle="候选研究只接受 6 位 A 股代码。" />
        <GlassCard>
          <div className="flex items-start gap-2 text-sm text-warning" role="alert">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
            <span>代码无效或缺失；未读取 Position、Evidence、Native Intel 或 Campaign authority。</span>
          </div>
          <Link to="/stock-data" className="mt-4 inline-flex items-center gap-1.5 text-sm text-primary hover:underline">
            <ArrowLeft className="h-4 w-4" /> 返回个股数据
          </Link>
        </GlassCard>
      </div>
    );
  }

  const evidenceGap = evidence.value ? buildCandidateEvidenceGap(evidence.value.records) : null;
  const returnTo = candidateWorkspaceHref(code);

  return (
    <div className="space-y-6" data-testid="candidate-workspace" data-security-code={code}>
      <PageHeader
        title={`Candidate Workspace · ${code}`}
        subtitle="从候选事实到 Campaign、Formal Thesis 与 Decision 的三步工作区；不会自动买入、建仓或把 UNKNOWN 当事实。"
        actions={(
          <Link
            to={`/stock-data?code=${encodeURIComponent(code)}`}
            className="inline-flex items-center gap-1.5 rounded border border-border/60 px-3 py-1.5 text-xs text-muted-foreground hover:text-foreground"
            data-testid="candidate-stock-data-entry"
          >
            <ArrowLeft className="h-3.5 w-3.5" /> 个股数据
          </Link>
        )}
      />

      <section className="space-y-4" aria-labelledby="candidate-step-context">
        <div>
          <h2 id="candidate-step-context" className="text-base font-semibold">步骤 1 · 核对事实、来源与缺口</h2>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">
            Position 来自 canonical ledger；Native Intel 保留去重观察与来源状态；Evidence gap 只是现有账本库存盘点，不是新的充分性 authority。
          </p>
        </div>

        <GlassCard data-testid="candidate-position-card">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h3 className="text-sm font-semibold">Position Reality</h3>
              <p className="mt-1 text-xs text-muted-foreground">来源：GET /api/position/derived；非 canonical 或未 bootstrap 时保持 UNKNOWN。</p>
            </div>
            {position.status === "loading" ? (
              <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground"><Loader2 className="h-3.5 w-3.5 animate-spin" />读取中</span>
            ) : position.status === "error" ? (
              <span className={`rounded px-2 py-1 text-xs font-semibold ${positionTone.UNKNOWN}`} data-position-state="UNKNOWN">UNKNOWN</span>
            ) : (
              <span className={`rounded px-2 py-1 text-xs font-semibold ${positionTone[position.value.state]}`} data-position-state={position.value.state}>
                {position.value.state}
              </span>
            )}
          </div>
          {position.status === "ready" && (
            <div className="mt-3 space-y-1 text-xs">
              <p>{position.value.reason}</p>
              <p className="text-muted-foreground">shares：{position.value.shares ?? "UNKNOWN"}</p>
            </div>
          )}
          {position.status === "error" && <p className="mt-3 text-xs text-warning" role="alert">{position.error}；不会把读取失败解释为未持有。</p>}
        </GlassCard>

        <NativeIntelSecurityContext code={code} />

        <GlassCard data-testid="candidate-evidence-gap">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h3 className="flex items-center gap-1.5 text-sm font-semibold"><FileSearch className="h-4 w-4 text-primary" />Evidence gap</h3>
              <p className="mt-1 text-xs leading-5 text-muted-foreground">
                只统计 subject=stock/{code} 的 Evidence Ledger 记录。0 条表示本账本未覆盖，不代表外部世界没有证据，也不替代 Evidence Gate。
              </p>
            </div>
            <div className="flex gap-3 text-xs">
              <Link
                to={`/evidence/new?${new URLSearchParams({ subject_type: "stock", subject_id: code, return_to: returnTo }).toString()}`}
                className="text-primary hover:underline"
                data-testid="candidate-add-evidence"
              >
                新增 Evidence
              </Link>
              <Link to="/evidence" className="text-primary hover:underline">打开 Ledger</Link>
            </div>
          </div>
          {evidence.status === "loading" ? (
            <p className="mt-4 flex items-center gap-2 text-xs text-muted-foreground"><Loader2 className="h-3.5 w-3.5 animate-spin" />正在盘点 Evidence Ledger…</p>
          ) : evidence.status === "error" ? (
            <p className="mt-4 text-xs text-warning" role="alert">UNKNOWN · {evidence.error}；不会据此声明 evidence gap 已确认。</p>
          ) : (
            <>
              <div className="mt-4 grid gap-2 sm:grid-cols-3">
                {evidenceGap?.coverage.map((item) => (
                  <div key={item.key} className="rounded-md border border-border/50 bg-background/35 p-3 text-xs" data-evidence-coverage={item.key} data-evidence-gap={item.gap ? "yes" : "no"}>
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-medium">{item.label}</span>
                      {item.gap ? <span className="text-warning">未覆盖</span> : <CheckCircle2 className="h-3.5 w-3.5 text-success" />}
                    </div>
                    <p className="mt-1 text-muted-foreground">Ledger 记录 {item.count} 条</p>
                  </div>
                ))}
              </div>
              <div className="mt-3 grid gap-2 text-xs sm:grid-cols-2 lg:grid-cols-4">
                <div className="rounded border border-border/40 bg-background/35 p-2">
                  <p className="text-muted-foreground">Classification</p>
                  <p className="mt-1">FACT {evidenceGap?.classificationCounts.fact ?? 0} · INFERENCE {evidenceGap?.classificationCounts.inference ?? 0} · UNKNOWN {evidenceGap?.classificationCounts.unknown ?? 0}</p>
                </div>
                <div className="rounded border border-border/40 bg-background/35 p-2">
                  <p className="text-muted-foreground">High-confidence fact</p>
                  <p className="mt-1">{evidenceGap?.highConfidenceFactCount ?? 0} 条</p>
                </div>
                <div className="rounded border border-border/40 bg-background/35 p-2" data-evidence-freshness="NOT_EVALUATED">
                  <p className="text-muted-foreground">Freshness</p>
                  <p className="mt-1 font-mono">NOT_EVALUATED</p>
                  <p className="mt-1 text-[10px] text-muted-foreground">最新 source_date：{evidenceGap?.latestSourceDate ?? "UNKNOWN"}；无 policy，不能判定过期。</p>
                </div>
                <div className="rounded border border-border/40 bg-background/35 p-2" data-evidence-source-conflict="UNKNOWN">
                  <p className="text-muted-foreground">Source conflict</p>
                  <p className="mt-1 font-mono">UNKNOWN</p>
                  <p className="mt-1 text-[10px] text-muted-foreground">Ledger 无 conflict authority，不能声称不存在冲突。</p>
                </div>
              </div>
              <p className="mt-3 text-[11px] text-muted-foreground">当前筛选共 {evidence.value.total} 条；classification 是账本字段，不是本页判断。other 记录未被强行归类。</p>
              {evidenceGap?.highestImpactQuestion && (
                <div className="mt-3 rounded-md border border-warning/30 bg-warning/5 p-3 text-xs" data-testid="candidate-highest-impact-question">
                  <p className="font-medium text-warning">最高影响的下一研究问题</p>
                  <p className="mt-1">{evidenceGap.highestImpactQuestion}</p>
                  {evidenceGap.nextResearchQuestions.length > 1 && (
                    <ol className="mt-2 list-decimal space-y-1 pl-4 text-muted-foreground">
                      {evidenceGap.nextResearchQuestions.slice(1).map((question) => <li key={question}>{question}</li>)}
                    </ol>
                  )}
                </div>
              )}
              {evidence.value.records.length > 0 && (
                <ul className="mt-3 space-y-1.5 border-t border-border/40 pt-3 text-xs">
                  {evidence.value.records.slice(0, 5).map((record) => (
                    <li key={record.id} className="flex min-w-0 items-center gap-2">
                      <span className="rounded bg-muted/50 px-1.5 py-0.5 text-[10px]">{record.evidence_type}</span>
                      <Link to={`/evidence/${encodeURIComponent(record.id)}`} className="min-w-0 flex-1 truncate hover:text-primary hover:underline">{record.claim}</Link>
                      <span className="shrink-0 text-[10px] text-muted-foreground">{record.source_date || "日期未知"}</span>
                    </li>
                  ))}
                </ul>
              )}
            </>
          )}
        </GlassCard>
      </section>

      <CandidateCampaignPanel code={code} workspace returnTo={returnTo} />
    </div>
  );
}

export default CandidateWorkspace;
