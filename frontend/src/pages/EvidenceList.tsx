import { useEffect, useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Plus, Loader2, FileText, ChevronLeft, ChevronRight, RotateCcw } from "lucide-react";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import { api, ApiError, type EvidenceRecord } from "@/lib/api";
import { cn } from "@/lib/utils";
import {
  EVIDENCE_PAGE_SIZE, EVIDENCE_SUBJECT_LABELS, parseEvidenceListQuery,
  evidenceFilterQuery, evidencePageQuery, evidenceDateLabel,
} from "@/lib/evidenceListView";

const EVIDENCE_TYPE_LABELS: Record<string, string> = {
  news: "新闻", announcement: "公告", report: "研报", research_note: "研究笔记", financial_filing: "财报", other: "其他",
};
const CLASSIFICATION_LABELS: Record<string, string> = { fact: "事实", inference: "推断", unknown: "未知" };
const CONFIDENCE_LABELS: Record<string, string> = { high: "高", medium: "中", low: "低" };
const controlClass = "min-h-10 rounded-md border border-border bg-background px-3 py-2 text-sm";
const buttonClass = "inline-flex min-h-10 items-center justify-center gap-1.5 rounded-md border border-border px-3 py-2 text-sm hover:bg-muted disabled:cursor-not-allowed disabled:opacity-50";

type Query = ReturnType<typeof parseEvidenceListQuery>;
function EvidenceFilters({ query, loading, onApply, onClear }: {
  query: Query; loading: boolean; onApply: (type: string, id: string) => void; onClear: () => void;
}) {
  const [type, setType] = useState(query.subjectType);
  const [id, setId] = useState(query.subjectId);
  const [error, setError] = useState<string | null>(null);
  function submit(event: FormEvent) {
    event.preventDefault();
    const validation = parseEvidenceListQuery(evidenceFilterQuery(new URLSearchParams(), type, id));
    setError(validation.error);
    if (!validation.error) onApply(type, id);
  }
  return (
    <form onSubmit={submit} aria-label="证据筛选" className="space-y-3">
      <div className="flex flex-wrap items-end gap-3">
        <label className="flex min-w-0 flex-col gap-1.5 text-sm">
          <span>主体类型</span>
          <select className={controlClass} value={type} onChange={event => { setType(event.target.value); setError(null); }} aria-describedby="evidence-filter-help">
            <option value="">全部</option>
            {type && !Object.prototype.hasOwnProperty.call(EVIDENCE_SUBJECT_LABELS, type) && <option value={type}>不支持的类型</option>}
            {Object.entries(EVIDENCE_SUBJECT_LABELS).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
          </select>
        </label>
        <label className="flex min-w-0 flex-1 flex-col gap-1.5 text-sm sm:max-w-xs">
          <span>主体代码/标识</span>
          <input className={cn(controlClass, "w-full")} value={id} placeholder="如 600519" onChange={event => { setId(event.target.value); setError(null); }} aria-describedby="evidence-filter-help" />
        </label>
        <button className={cn(buttonClass, "border-primary/30 bg-primary/10 text-primary")} type="submit" disabled={loading && type === query.subjectType && id.trim() === query.subjectId}>查询</button>
        <button className={buttonClass} type="button" onClick={() => { setType(""); setId(""); setError(null); onClear(); }}>清除筛选</button>
      </div>
      <p id="evidence-filter-help" className="text-xs leading-5 text-muted-foreground">按标的检索时，请同时填写类型和代码。编辑后点击查询；列表仅显示已应用的筛选。</p>
      {error && <p role="alert" className="text-sm text-danger">{error}</p>}
    </form>
  );
}

type Result = { key: string; items: EvidenceRecord[]; total: number; status: "loading" | "success" | "error"; error?: string };

export function EvidenceList() {
  const [searchParams, setSearchParams] = useSearchParams();
  const query = parseEvidenceListQuery(searchParams);
  const { subjectType, subjectId, page, offset, error: queryError } = query;
  const [refresh, setRefresh] = useState(0);
  const requestKey = JSON.stringify([subjectType, subjectId, page, refresh]);
  const [result, setResult] = useState<Result | null>(null);
  // Ownership is checked during render as well as at completion: no frame of old rows under a new label.
  const current = result?.key === requestKey ? result : null;
  const loading = !queryError && (!current || current.status === "loading");
  const items = current?.status === "success" ? current.items : [];
  const total = current?.status === "success" ? current.total : 0;
  const totalPages = Math.max(1, Math.ceil(total / EVIDENCE_PAGE_SIZE));
  const listReturnTo = `/evidence${searchParams.toString() ? `?${searchParams}` : ""}`;

  useEffect(() => {
    if (queryError) return;
    let active = true;
    const controller = new AbortController();
    setResult({ key: requestKey, items: [], total: 0, status: "loading" });
    void api.evidenceList({
      ...(subjectType ? { subject_type: subjectType, subject_id: subjectId } : {}),
      limit: EVIDENCE_PAGE_SIZE, offset, signal: controller.signal,
    }).then(response => {
      if (active) setResult({ key: requestKey, items: response.items ?? [], total: response.total ?? 0, status: "success" });
    }).catch(error => {
      if (active) setResult({ key: requestKey, items: [], total: 0, status: "error", error: error instanceof ApiError ? error.message : "加载证据列表失败，请重试。" });
    });
    return () => { active = false; controller.abort(); };
  }, [requestKey, subjectType, subjectId, offset, queryError]);

  function apply(type: string, id: string) {
    const next = evidenceFilterQuery(searchParams, type, id);
    if (next.toString() === searchParams.toString()) setRefresh(value => value + 1);
    else setSearchParams(next);
  }

  return (
    <div className="min-w-0">
      <PageHeader title="证据库" subtitle="逐条分清资料事实与研究推断，保留来源和时间，再关联投资逻辑。" actions={
        <Link to={`/evidence/new?${new URLSearchParams({ return_to: listReturnTo, ...(subjectType && subjectId && !queryError ? { subject_type: subjectType, subject_id: subjectId } : {}) })}`} className={cn(buttonClass, "border-primary/30 bg-primary/10 text-primary")}><Plus aria-hidden="true" className="h-4 w-4" />新建证据</Link>
      } />
      <GlassCard className="mb-4">
        <EvidenceFilters key={searchParams.toString()} query={query} loading={loading} onApply={apply} onClear={() => apply("", "")} />
      </GlassCard>
      <p className="mb-5 rounded-md border border-warning/30 bg-warning/5 p-3 text-sm leading-6 text-muted-foreground">事实分类表示资料中的陈述，不等于业务事实已经确认。来源日期、记录时间与置信度也不代表已完成核验。</p>
      <section aria-labelledby="evidence-list-heading" aria-busy={loading} className="min-w-0">
        <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
          <h2 id="evidence-list-heading" className="text-lg font-semibold">证据条目</h2>
          <p className="min-w-0 break-all text-sm text-muted-foreground">已应用：{queryError ? "筛选无效" : subjectType ? `${EVIDENCE_SUBJECT_LABELS[subjectType]} / ${subjectId}` : "全部标的"}</p>
        </div>
        {queryError ? <GlassCard><p role="alert" className="text-sm text-danger">{queryError}</p></GlassCard> : loading ? (
          <GlassCard><p role="status" className="flex items-center justify-center gap-2 py-8 text-sm text-muted-foreground"><Loader2 aria-hidden="true" className="h-4 w-4 animate-spin" />正在加载证据…</p></GlassCard>
        ) : current?.status === "error" ? (
          <GlassCard>
            <div role="alert"><h3 className="font-medium">证据加载失败</h3><p className="mt-2 break-words text-sm text-muted-foreground">{current.error}</p></div>
            <button type="button" className={cn(buttonClass, "mt-4")} onClick={() => setRefresh(value => value + 1)}><RotateCcw aria-hidden="true" className="h-4 w-4" />重新加载</button>
          </GlassCard>
        ) : items.length === 0 ? (
          <GlassCard className="py-10 text-center">
            <FileText aria-hidden="true" className="mx-auto mb-3 h-7 w-7 text-muted-foreground" />
            <h3 className="font-medium">{page > 1 ? "此页暂无证据" : subjectType ? "此筛选下暂无证据" : "尚无证据条目"}</h3>
            <p className="mx-auto mt-2 max-w-lg text-sm leading-6 text-muted-foreground">{page > 1 ? "条目可能已发生变化，请返回第一页查看。" : subjectType ? "可以调整标的，或清除筛选查看其他证据。" : "先查看报告原文，记录来源与时间，再区分事实和推断。"}</p>
            <div className="mt-4 flex flex-wrap justify-center gap-3">
              {page > 1 ? <button className={buttonClass} onClick={() => setSearchParams(evidencePageQuery(searchParams, 1))}>返回第一页</button> : subjectType ? <button className={buttonClass} onClick={() => apply("", "")}>查看全部证据</button> : <Link className={buttonClass} to="/my-reports">前往报告库</Link>}
            </div>
          </GlassCard>
        ) : (
          <>
            <p role="status" className="mb-3 text-xs text-muted-foreground">共 {total} 条 · 第 {page} / {totalPages} 页 · 本页 {items.length} 条</p>
            <div className="space-y-3">
              {items.map(evidence => (
                <GlassCard key={evidence.id}>
                  <article className="min-w-0" aria-labelledby={`evidence-${evidence.id}`}>
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <h3 id={`evidence-${evidence.id}`} className="min-w-0 flex-1 break-words text-base font-semibold leading-7 [overflow-wrap:anywhere]">{evidence.claim}</h3>
                      <span className={cn("rounded border px-2 py-1 text-xs", evidence.classification === "fact" ? "border-border text-muted-foreground" : "border-warning/30 bg-warning/10 text-warning")}>{CLASSIFICATION_LABELS[evidence.classification] ?? "未知"}</span>
                    </div>
                    <p className="mt-2 break-words text-sm leading-6 text-muted-foreground [overflow-wrap:anywhere]">{EVIDENCE_SUBJECT_LABELS[evidence.subject_type] ?? evidence.subject_type} / <span className="font-mono">{evidence.subject_id}</span> · {EVIDENCE_TYPE_LABELS[evidence.evidence_type] ?? evidence.evidence_type}</p>
                    <dl className="mt-3 grid min-w-0 gap-x-6 gap-y-2 text-sm leading-6 sm:grid-cols-2">
                      <div className="min-w-0 sm:col-span-2"><dt className="text-xs text-muted-foreground">来源</dt><dd className="break-words [overflow-wrap:anywhere]">{evidence.source_title?.trim() || "未提供来源标题"}</dd></div>
                      <div><dt className="text-xs text-muted-foreground">来源日期</dt><dd>{evidenceDateLabel(evidence.source_date)}</dd></div>
                      <div><dt className="text-xs text-muted-foreground">记录时间</dt><dd>{evidenceDateLabel(evidence.created_at)}</dd></div>
                    </dl>
                    {(!evidence.source_title?.trim() || evidenceDateLabel(evidence.source_date).startsWith("未知")) && <p className="mt-3 text-sm text-warning">来源信息不完整，核验时请补充来源标题或日期。</p>}
                    <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-border pt-3">
                      <p className="text-xs text-muted-foreground">记录置信度：{CONFIDENCE_LABELS[evidence.confidence] ?? "未知"} · 不代表核验状态</p>
                      <Link className={cn(buttonClass, "text-primary")} to={`/evidence/${encodeURIComponent(evidence.id)}?${new URLSearchParams({ return_to: listReturnTo })}`} aria-label={`查看来源与详情：${evidence.claim}`}>查看来源与详情<ChevronRight aria-hidden="true" className="h-4 w-4" /></Link>
                    </div>
                  </article>
                </GlassCard>
              ))}
            </div>
          </>
        )}
        {!loading && current?.status === "success" && (total > EVIDENCE_PAGE_SIZE || page > 1) && (
          <nav aria-label="证据分页" className="mt-4 flex flex-wrap items-center justify-between gap-3">
            <button className={buttonClass} disabled={page === 1} onClick={() => setSearchParams(evidencePageQuery(searchParams, page - 1))}><ChevronLeft aria-hidden="true" className="h-4 w-4" />上一页</button>
            <span className="text-xs text-muted-foreground">第 {page} 页 · 每页最多 {EVIDENCE_PAGE_SIZE} 条</span>
            <button className={buttonClass} disabled={offset + EVIDENCE_PAGE_SIZE >= total} onClick={() => setSearchParams(evidencePageQuery(searchParams, page + 1))}>下一页<ChevronRight aria-hidden="true" className="h-4 w-4" /></button>
          </nav>
        )}
      </section>
    </div>
  );
}
