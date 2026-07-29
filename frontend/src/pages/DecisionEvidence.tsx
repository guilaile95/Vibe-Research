import { useState, useEffect, useCallback } from "react";
import { useSearchParams } from "react-router-dom";
import {
  ShieldCheck,
  Search,
  RotateCw,
  AlertCircle,
  X,
  FileText,
  AlertTriangle,
  ChevronLeft,
  ChevronRight,
  Layers,
  Database,
} from "lucide-react";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import {
  api,
  ApiError,
  type DecisionRunRecord,
  type DecisionEvidenceDetailResult,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import {
  traceStatusLabel,
  qualityStatusLabel,
  scopeLabel,
  traceStatusBadgeClass,
  qualityStatusBadgeClass,
  scopeBadgeClass,
  formatEvidenceTime,
  safeRenderText,
  getExplanationEvidences,
} from "@/lib/decisionEvidenceView";

export default function DecisionEvidence() {
  const [searchParams, setSearchParams] = useSearchParams();

  // Filters
  const [code, setCode] = useState(searchParams.get("code") || searchParams.get("symbol") || "");
  const [tradeDate, setTradeDate] = useState(searchParams.get("trade_date") || "");
  const [qualityStatus, setQualityStatus] = useState(searchParams.get("quality_status") || "");
  const [traceStatus, setTraceStatus] = useState(searchParams.get("trace_status") || "");
  const [page, setPage] = useState(1);
  const limit = 10;

  // List State
  const [runs, setRuns] = useState<DecisionRunRecord[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Detail Modal State
  const [detailModalOpen, setDetailModalOpen] = useState(false);
  const [selectedDetail, setSelectedDetail] = useState<DecisionEvidenceDetailResult | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);

  // Fetch runs list
  const fetchList = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.listDecisionEvidence({
        code: code.trim() || undefined,
        trade_date: tradeDate.trim() || undefined,
        quality_status: qualityStatus || undefined,
        trace_status: traceStatus || undefined,
        page,
        limit,
      });

      // Normalize items
      const rawItems = res.items || [];
      const normalizedRuns: DecisionRunRecord[] = rawItems.map((item: any) => ({
        id: item.id || item.decision_run_id || `dr_${item.trade_date}_${item.code}`,
        decision_run_id: item.decision_run_id || item.id,
        code: item.code || item.symbol,
        symbol: item.symbol || item.code,
        trade_date: item.trade_date || "—",
        generated_at: item.generated_at || item.created_at || "—",
        trace_status: item.trace_status || "complete",
        quality_status: item.quality_status || "valid",
        summary: item.summary || item.title || null,
        decision_type: item.decision_type || null,
        action: item.action || null,
        evidence_count: item.evidence_count ?? (item.evidence_items ? item.evidence_items.length : undefined),
        missing_count: item.missing_count,
        created_at: item.created_at,
      }));

      setRuns(normalizedRuns);
      setTotal(res.total || normalizedRuns.length);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "获取决策依据列表失败");
    } finally {
      setLoading(false);
    }
  }, [code, tradeDate, qualityStatus, traceStatus, page]);

  // Load single run detail
  const loadDetail = useCallback(async (runId?: string, adviceQuery?: { trade_date: string; generated_at: string }) => {
    setDetailLoading(true);
    setDetailError(null);
    setDetailModalOpen(true);
    try {
      let detail: DecisionEvidenceDetailResult;
      if (adviceQuery) {
        detail = await api.getDecisionEvidenceByAdvice(adviceQuery);
      } else if (runId) {
        detail = await api.getDecisionEvidence(runId);
      } else {
        throw new Error("未指定查询参数");
      }
      setSelectedDetail(detail);
    } catch (e) {
      setDetailError(e instanceof ApiError ? e.message : "获取决策依据详情失败");
    } finally {
      setDetailLoading(false);
    }
  }, []);

  // Handle URL query parameters on initial load
  useEffect(() => {
    const qRunId = searchParams.get("decision_run_id") || searchParams.get("run_id");
    const qTradeDate = searchParams.get("trade_date");
    const qGeneratedAt = searchParams.get("generated_at");

    if (qRunId) {
      loadDetail(qRunId);
    } else if (qTradeDate && qGeneratedAt) {
      loadDetail(undefined, { trade_date: qTradeDate, generated_at: qGeneratedAt });
    }
  }, []);

  useEffect(() => {
    fetchList();
  }, [fetchList]);

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    setPage(1);
    fetchList();
  };

  const handleReset = () => {
    setCode("");
    setTradeDate("");
    setQualityStatus("");
    setTraceStatus("");
    setPage(1);
    setSearchParams({});
  };

  const totalPages = Math.ceil(total / limit) || 1;

  // Active detail data mapping
  const activeRun = selectedDetail?.run || selectedDetail?.decision_run;
  const activeEvidences = selectedDetail?.evidence_items || [];
  const activeExplanations = selectedDetail?.explanations || selectedDetail?.explanation_items || [];
  const missingEvidences =
    selectedDetail?.missing_evidences ||
    activeEvidences.filter((e) => e.is_missing || e.quality_status === "missing");

  return (
    <div>
      <PageHeader
        title="决策依据"
        subtitle="结构化数据链、质量追溯与 AI 核心结论推演"
        actions={
          <button
            onClick={() => fetchList()}
            disabled={loading}
            className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-sm text-muted-foreground hover:text-foreground disabled:opacity-50"
          >
            <RotateCw className={cn("h-4 w-4", loading && "animate-spin")} />
            刷新
          </button>
        }
      />

      <div className="mb-4 flex items-start gap-2 rounded-lg border border-primary/25 bg-primary/5 p-3 text-xs text-muted-foreground">
        <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
        <span>
          决策依据图谱完整记录每次持仓分析与买卖决策所使用的市场、板块、财务、资金面与风控证据，可追溯数据版本与来源可信度。
        </span>
      </div>

      {/* Filter Form */}
      <GlassCard className="mb-4">
        <form onSubmit={handleSearch} className="flex flex-wrap items-end gap-3">
          <div>
            <label className="mb-1 block text-xs text-muted-foreground">股票代码</label>
            <input
              type="text"
              value={code}
              onChange={(e) => setCode(e.target.value)}
              placeholder="如 600519"
              className="w-32 rounded-lg border border-border bg-black/20 px-3 py-1.5 text-sm outline-none focus:border-primary/50"
            />
          </div>

          <div>
            <label className="mb-1 block text-xs text-muted-foreground">交易日期</label>
            <input
              type="date"
              value={tradeDate}
              onChange={(e) => setTradeDate(e.target.value)}
              className="w-36 rounded-lg border border-border bg-black/20 px-3 py-1.5 text-sm outline-none focus:border-primary/50"
            />
          </div>

          <div>
            <label className="mb-1 block text-xs text-muted-foreground">数据质量状态</label>
            <select
              value={qualityStatus}
              onChange={(e) => setQualityStatus(e.target.value)}
              className="w-36 rounded-lg border border-border bg-black/20 px-3 py-1.5 text-sm outline-none focus:border-primary/50"
            >
              <option value="">全部数据质量</option>
              <option value="valid">高可靠</option>
              <option value="partial">部分缺失</option>
              <option value="missing">关键缺失</option>
              <option value="stale">数据过期</option>
              <option value="unavailable">不可用</option>
            </select>
          </div>

          <div>
            <label className="mb-1 block text-xs text-muted-foreground">追踪状态</label>
            <select
              value={traceStatus}
              onChange={(e) => setTraceStatus(e.target.value)}
              className="w-36 rounded-lg border border-border bg-black/20 px-3 py-1.5 text-sm outline-none focus:border-primary/50"
            >
              <option value="">全部追踪状态</option>
              <option value="complete">完整追踪</option>
              <option value="archived">已归档</option>
              <option value="partial">部分缺失</option>
              <option value="failed">追踪失败</option>
            </select>
          </div>

          <div className="flex items-center gap-2">
            <button
              type="submit"
              disabled={loading}
              className="inline-flex items-center gap-1.5 rounded-lg bg-primary/15 px-4 py-1.5 text-sm font-medium text-primary hover:bg-primary/25 disabled:opacity-50"
            >
              <Search className="h-4 w-4" /> 查询
            </button>
            <button
              type="button"
              onClick={handleReset}
              className="rounded-lg border border-border px-3 py-1.5 text-sm text-muted-foreground hover:text-foreground"
            >
              重置
            </button>
          </div>
        </form>
      </GlassCard>

      {/* Error state */}
      {error && (
        <GlassCard className="mb-4 border-destructive/30 bg-destructive/5">
          <div className="flex items-center justify-between text-destructive">
            <div className="flex items-center gap-2 text-sm">
              <AlertCircle className="h-5 w-5 shrink-0" />
              <span>{error}</span>
            </div>
            <button
              onClick={() => fetchList()}
              className="rounded-lg border border-destructive/30 px-3 py-1 text-xs text-destructive hover:bg-destructive/10"
            >
              重试
            </button>
          </div>
        </GlassCard>
      )}

      {/* List Table */}
      <GlassCard glow>
        <div className="mb-3 flex items-center justify-between">
          <h3 className="font-semibold text-sm">决策追踪记录 ({total})</h3>
        </div>

        {loading ? (
          <div className="py-12 text-center text-sm text-muted-foreground">
            <RotateCw className="mx-auto mb-2 h-6 w-6 animate-spin text-primary" />
            加载决策依据记录…
          </div>
        ) : runs.length === 0 ? (
          <p className="py-8 text-center text-sm text-muted-foreground/60">
            未找到符合条件的决策追踪记录。
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border/50 text-left text-xs text-muted-foreground">
                  <th className="px-3 py-2 font-medium">运行 ID</th>
                  <th className="px-3 py-2 font-medium">代码/标的</th>
                  <th className="px-3 py-2 font-medium">交易日期</th>
                  <th className="px-3 py-2 font-medium">生成时间</th>
                  <th className="px-3 py-2 font-medium">数据质量</th>
                  <th className="px-3 py-2 font-medium">追踪状态</th>
                  <th className="px-3 py-2 font-medium">证据数</th>
                  <th className="px-3 py-2 font-medium text-right">操作</th>
                </tr>
              </thead>
              <tbody>
                {runs.map((r) => {
                  const runId = r.id || r.decision_run_id || "";
                  return (
                    <tr key={runId} className="border-b border-border/30 hover:bg-black/10">
                      <td className="px-3 py-2.5 font-mono text-xs text-muted-foreground">
                        {runId.length > 20 ? `${runId.slice(0, 18)}…` : runId}
                      </td>
                      <td className="px-3 py-2.5 font-mono font-medium">
                        {r.code || r.symbol || "—"}
                      </td>
                      <td className="px-3 py-2.5 text-xs text-muted-foreground">
                        {r.trade_date}
                      </td>
                      <td className="px-3 py-2.5 text-xs text-muted-foreground">
                        {formatEvidenceTime(r.generated_at)}
                      </td>
                      <td className="px-3 py-2.5">
                        <span
                          className={cn(
                            "inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium",
                            qualityStatusBadgeClass(r.quality_status)
                          )}
                        >
                          {qualityStatusLabel(r.quality_status)}
                        </span>
                      </td>
                      <td className="px-3 py-2.5">
                        <span
                          className={cn(
                            "inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium",
                            traceStatusBadgeClass(r.trace_status)
                          )}
                        >
                          {traceStatusLabel(r.trace_status)}
                        </span>
                      </td>
                      <td className="px-3 py-2.5 font-mono text-xs text-muted-foreground">
                        {r.evidence_count ?? "—"}
                        {r.missing_count ? (
                          <span className="ml-1 text-rose-400">({r.missing_count} 缺失)</span>
                        ) : null}
                      </td>
                      <td className="px-3 py-2.5 text-right">
                        <button
                          onClick={() => loadDetail(runId)}
                          className="inline-flex items-center gap-1 rounded-lg border border-primary/30 bg-primary/10 px-2.5 py-1 text-xs font-medium text-primary hover:bg-primary/20"
                        >
                          <FileText className="h-3.5 w-3.5" /> 查看详情
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        {/* Pagination */}
        {totalPages > 1 && (
          <div className="mt-4 flex items-center justify-between border-t border-border/40 pt-3 text-xs text-muted-foreground">
            <span>
              第 {page} / {totalPages} 页 (共 {total} 条)
            </span>
            <div className="flex items-center gap-2">
              <button
                disabled={page <= 1}
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                className="inline-flex items-center gap-1 rounded-lg border border-border px-2.5 py-1 disabled:opacity-40"
              >
                <ChevronLeft className="h-3.5 w-3.5" /> 上一页
              </button>
              <button
                disabled={page >= totalPages}
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                className="inline-flex items-center gap-1 rounded-lg border border-border px-2.5 py-1 disabled:opacity-40"
              >
                下一页 <ChevronRight className="h-3.5 w-3.5" />
              </button>
            </div>
          </div>
        )}
      </GlassCard>

      {/* Detail Modal */}
      {detailModalOpen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm"
          onClick={() => setDetailModalOpen(false)}
        >
          <div
            className="flex max-h-[90vh] w-full max-w-4xl flex-col rounded-xl border border-border bg-background shadow-2xl overflow-hidden"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Modal Header */}
            <div className="flex items-center justify-between border-b border-border/60 bg-black/20 px-5 py-4">
              <div className="flex items-center gap-2">
                <ShieldCheck className="h-5 w-5 text-primary" />
                <h3 className="font-bold text-base">决策依据与链条详情</h3>
              </div>
              <button
                onClick={() => setDetailModalOpen(false)}
                className="rounded-lg p-1 text-muted-foreground hover:bg-black/30 hover:text-foreground"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            {/* Modal Content */}
            <div className="flex-1 overflow-y-auto p-5 space-y-5">
              {detailLoading ? (
                <div className="py-16 text-center text-sm text-muted-foreground">
                  <RotateCw className="mx-auto mb-2 h-7 w-7 animate-spin text-primary" />
                  加载决策证据详情…
                </div>
              ) : detailError ? (
                <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive flex items-center gap-2">
                  <AlertCircle className="h-5 w-5 shrink-0" />
                  <span>{detailError}</span>
                </div>
              ) : (
                <>
                  {/* Run Header info */}
                  {activeRun && (
                    <div className="rounded-lg border border-border/60 bg-black/20 p-4">
                      <div className="flex flex-wrap items-center justify-between gap-2 mb-2">
                        <div className="flex items-center gap-2">
                          <span className="font-mono text-sm font-semibold text-foreground">
                            ID: {activeRun.id || activeRun.decision_run_id}
                          </span>
                          {(activeRun.code || activeRun.symbol) && (
                            <span className="rounded bg-primary/20 px-2 py-0.5 text-xs font-mono text-primary font-bold">
                              {activeRun.code || activeRun.symbol}
                            </span>
                          )}
                        </div>
                        <div className="flex items-center gap-2">
                          <span
                            className={cn(
                              "rounded-full border px-2.5 py-0.5 text-xs font-medium",
                              qualityStatusBadgeClass(activeRun.quality_status)
                            )}
                          >
                            {qualityStatusLabel(activeRun.quality_status)}
                          </span>
                          <span
                            className={cn(
                              "rounded-full border px-2.5 py-0.5 text-xs font-medium",
                              traceStatusBadgeClass(activeRun.trace_status)
                            )}
                          >
                            {traceStatusLabel(activeRun.trace_status)}
                          </span>
                        </div>
                      </div>
                      <div className="grid grid-cols-2 gap-2 text-xs text-muted-foreground sm:grid-cols-4 mt-3">
                        <div>
                          <span className="block text-muted-foreground/60">交易日期</span>
                          <span className="font-mono text-foreground">{activeRun.trade_date}</span>
                        </div>
                        <div>
                          <span className="block text-muted-foreground/60">生成时间</span>
                          <span className="font-mono text-foreground">
                            {formatEvidenceTime(activeRun.generated_at)}
                          </span>
                        </div>
                        {activeRun.action && (
                          <div>
                            <span className="block text-muted-foreground/60">建议动作</span>
                            <span className="font-semibold text-primary">{activeRun.action}</span>
                          </div>
                        )}
                        {activeRun.decision_type && (
                          <div>
                            <span className="block text-muted-foreground/60">决策类型</span>
                            <span className="text-foreground">{activeRun.decision_type}</span>
                          </div>
                        )}
                      </div>
                      {activeRun.summary && (
                        <p className="mt-3 text-xs text-foreground/80 border-t border-border/30 pt-2">
                          {activeRun.summary}
                        </p>
                      )}
                    </div>
                  )}

                  {/* Missing Evidences Warning */}
                  {missingEvidences.length > 0 && (
                    <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-4 text-xs text-amber-800 dark:text-amber-200 space-y-2">
                      <div className="flex items-center gap-1.5 font-semibold text-sm text-amber-600 dark:text-amber-400">
                        <AlertTriangle className="h-4 w-4 shrink-0" />
                        <span>检测到 {missingEvidences.length} 项缺失/异常数据</span>
                      </div>
                      <ul className="list-disc pl-5 space-y-1">
                        {missingEvidences.map((m, i) => (
                          <li key={m.id || i}>
                            <span className="font-medium">{m.title || m.category || scopeLabel(m.scope)}:</span>{" "}
                            {m.missing_reason || "相关指标数据暂时不可用，可能影响相关决策置信度"}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}

                  {/* Explanations & Conclusions */}
                  {activeExplanations.length > 0 && (
                    <div className="space-y-3">
                      <h4 className="flex items-center gap-1.5 font-semibold text-sm text-foreground">
                        <Layers className="h-4 w-4 text-primary" />
                        核心决策结论与推演
                      </h4>
                      {activeExplanations.map((exp, idx) => {
                        const { supporting, limiting } = getExplanationEvidences(
                          exp,
                          activeEvidences
                        );
                        return (
                          <div
                            key={exp.id || exp.explanation_id || idx}
                            className="rounded-lg border border-border/60 bg-black/10 p-4 space-y-2"
                          >
                            <div className="flex items-start justify-between gap-2">
                              <h5 className="font-semibold text-sm text-primary">
                                {exp.claim || (exp.conclusion_type ? `结论 (${exp.conclusion_type})` : `结论 ${idx + 1}`)}
                              </h5>
                              {exp.confidence_score !== undefined && exp.confidence_score !== null && (
                                <span className="rounded bg-primary/10 border border-primary/20 px-2 py-0.5 text-xs text-primary font-mono">
                                  置信分: {(exp.confidence_score * 100).toFixed(0)}%
                                </span>
                              )}
                            </div>
                            {(exp.conclusion || exp.conclusion_value) && (
                              <p className="text-xs text-foreground/90 font-medium bg-black/20 p-2.5 rounded border border-border/30">
                                {exp.conclusion || exp.conclusion_value}
                              </p>
                            )}
                            {(exp.reasoning || exp.explanation_text) && (
                              <p className="text-xs text-muted-foreground leading-relaxed">
                                {exp.reasoning || exp.explanation_text}
                              </p>
                            )}

                            {/* Supporting / Limiting evidence tags */}
                            {(supporting.length > 0 || limiting.length > 0) && (
                              <div className="mt-2 pt-2 border-t border-border/30 grid grid-cols-1 md:grid-cols-2 gap-2 text-xs">
                                {supporting.length > 0 && (
                                  <div className="bg-emerald-500/5 border border-emerald-500/20 p-2 rounded">
                                    <span className="font-semibold text-emerald-400 block mb-1">
                                      支持证据 ({supporting.length})
                                    </span>
                                    <ul className="space-y-1 text-muted-foreground">
                                      {supporting.map((s) => (
                                        <li key={s.id || s.evidence_id} className="truncate">
                                          • {s.title || s.evidence_key || s.category} ({s.source || scopeLabel(s.scope)})
                                        </li>
                                      ))}
                                    </ul>
                                  </div>
                                )}
                                {limiting.length > 0 && (
                                  <div className="bg-rose-500/5 border border-rose-500/20 p-2 rounded">
                                    <span className="font-semibold text-rose-400 block mb-1">
                                      限制/约束证据 ({limiting.length})
                                    </span>
                                    <ul className="space-y-1 text-muted-foreground">
                                      {limiting.map((l) => (
                                        <li key={l.id || l.evidence_id} className="truncate">
                                          • {l.title || l.evidence_key || l.category} ({l.source || scopeLabel(l.scope)})
                                        </li>
                                      ))}
                                    </ul>
                                  </div>
                                )}
                              </div>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  )}

                  {/* Structured Evidence Items */}
                  <div className="space-y-3">
                    <h4 className="flex items-center gap-1.5 font-semibold text-sm text-foreground">
                      <Database className="h-4 w-4 text-primary" />
                      结构化证据链条 ({activeEvidences.length})
                    </h4>
                    {activeEvidences.length === 0 ? (
                      <p className="text-xs text-muted-foreground py-4 text-center">
                        无关联的结构化证据条目。
                      </p>
                    ) : (
                      <div className="grid gap-3 sm:grid-cols-2">
                        {activeEvidences.map((item, idx) => {
                          const valContent = safeRenderText(
                            item.content ?? item.value_json
                          );
                          return (
                            <div
                              key={item.id || item.evidence_id || idx}
                              className="flex flex-col justify-between rounded-lg border border-border/50 bg-black/15 p-3 space-y-2"
                            >
                              <div>
                                <div className="flex items-center justify-between gap-1 mb-1.5">
                                  <span
                                    className={cn(
                                      "rounded border px-1.5 py-0.5 text-[10px] font-medium",
                                      scopeBadgeClass(item.scope)
                                    )}
                                  >
                                    {scopeLabel(item.scope)}
                                  </span>
                                  <span
                                    className={cn(
                                      "rounded-full border px-2 py-0.5 text-[10px] font-medium",
                                      qualityStatusBadgeClass(item.quality_status)
                                    )}
                                  >
                                    {qualityStatusLabel(item.quality_status)}
                                  </span>
                                </div>
                                <h5 className="font-semibold text-xs text-foreground truncate">
                                  {item.title || item.evidence_key || item.category || "未知证据条目"}
                                </h5>
                                <div className="mt-1 font-mono text-xs bg-black/30 p-2 rounded text-muted-foreground whitespace-pre-wrap max-h-28 overflow-y-auto border border-border/30">
                                  {valContent}
                                </div>
                              </div>
                              <div className="flex items-center justify-between text-[10px] text-muted-foreground/70 pt-1 border-t border-border/20">
                                <span>来源: {item.source || "系统观测"}</span>
                                <span>
                                  {formatEvidenceTime(
                                    item.observation_time || item.data_timestamp
                                  )}
                                </span>
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    )}
                  </div>
                </>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
