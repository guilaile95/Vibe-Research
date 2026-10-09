import { useEffect, useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Plus, Loader2, BookOpen, ChevronLeft, ChevronRight, RotateCcw } from "lucide-react";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import { api, ApiError, type InvestmentThesis } from "@/lib/api";
import { EVIDENCE_PAGE_SIZE as PAGE_SIZE, EVIDENCE_SUBJECT_LABELS as SUBJECT_LABELS, evidencePageQuery, evidenceDateLabel } from "@/lib/evidenceListView";
import { THESIS_STATUS_LABELS, parseThesisListQuery, thesisFilterQuery, thesisLifecycleLabel, thesisRevisionLabel } from "@/lib/thesisListView";

const control = "mt-1 block min-h-10 w-full rounded-md border border-border bg-background px-3 py-2 text-sm";
const button = "inline-flex min-h-10 items-center justify-center gap-1.5 rounded-md border border-border px-3 py-2 text-sm hover:bg-muted disabled:cursor-not-allowed disabled:opacity-50";
type Query = ReturnType<typeof parseThesisListQuery>;

function ThesisFilters({ query, loading, onApply }: { query: Query; loading: boolean; onApply: (type: string, id: string, status: string) => void }) {
  const [type, setType] = useState(query.subjectType);
  const [id, setId] = useState(query.subjectId);
  const [status, setStatus] = useState(query.status);
  const [error, setError] = useState<string | null>(null);
  function submit(event: FormEvent) {
    event.preventDefault();
    const validation = parseThesisListQuery(thesisFilterQuery(new URLSearchParams(), type, id, status));
    setError(validation.error);
    if (!validation.error) onApply(type, id, status);
  }
  return <form aria-label="投资逻辑筛选" onSubmit={submit} className="space-y-3">
    <div className="flex flex-wrap items-end gap-3">
      <div><label htmlFor="thesis-subject-type" className="text-sm">主体类型</label>
        <select id="thesis-subject-type" className={control} value={type} onChange={event => { setType(event.target.value); setError(null); }} aria-describedby="thesis-filter-help">
          <option value="">全部</option>
          {type && !Object.prototype.hasOwnProperty.call(SUBJECT_LABELS, type) && <option value={type}>不支持的类型</option>}
          {Object.entries(SUBJECT_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select></div>
      <div className="min-w-[10rem] flex-1 sm:max-w-xs"><label htmlFor="thesis-subject-id" className="text-sm">主体代码/标识</label>
        <input id="thesis-subject-id" className={control} value={id} placeholder="如 600519" onChange={event => { setId(event.target.value); setError(null); }} aria-describedby="thesis-filter-help" /></div>
      <div><label htmlFor="thesis-status" className="text-sm">跟踪状态</label>
        <select id="thesis-status" className={control} value={status} onChange={event => { setStatus(event.target.value); setError(null); }}>
          <option value="">全部</option>
          {status && !Object.prototype.hasOwnProperty.call(THESIS_STATUS_LABELS, status) && <option value={status}>不支持的状态</option>}
          {Object.entries(THESIS_STATUS_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select></div>
      <button type="submit" className={`${button} border-primary/30 bg-primary/10 text-primary`} disabled={loading && type === query.subjectType && id.trim() === query.subjectId && status === query.status}>查询</button>
      <button type="button" className={button} onClick={() => { setType(""); setId(""); setStatus(""); setError(null); onApply("", "", ""); }}>清除筛选</button>
    </div>
    <p id="thesis-filter-help" className="text-xs leading-5 text-muted-foreground">标的类型和代码需成对填写；跟踪状态可单独筛选。编辑后点击查询，返回上一页会恢复已应用的筛选。</p>
    {error && <p role="alert" className="text-sm text-danger">{error}</p>}
  </form>;
}

type Result = { key: string; status: "loading" | "success" | "error"; items: InvestmentThesis[]; total: number; error?: string };
export function ThesisList() {
  const [searchParams, setSearchParams] = useSearchParams();
  const query = parseThesisListQuery(searchParams);
  const { subjectType, subjectId, status, page, offset, error: queryError } = query;
  const [refresh, setRefresh] = useState(0);
  const key = JSON.stringify([subjectType, subjectId, status, page, refresh]);
  const [result, setResult] = useState<Result | null>(null);
  const current = result?.key === key ? result : null;
  const loading = !queryError && (!current || current.status === "loading");
  const items = current?.status === "success" ? current.items : [];
  const total = current?.status === "success" ? current.total : 0;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const returnTo = `/thesis${searchParams.toString() ? `?${searchParams}` : ""}`;
  useEffect(() => {
    if (queryError) return;
    let active = true;
    setResult({ key, status: "loading", items: [], total: 0 });
    void api.thesisList({ ...(subjectType ? { subject_type: subjectType, subject_id: subjectId } : {}), ...(status ? { status } : {}), limit: PAGE_SIZE, offset })
      .then(response => { if (active) setResult({ key, status: "success", items: response.items ?? [], total: response.total ?? 0 }); })
      .catch(error => { if (active) setResult({ key, status: "error", items: [], total: 0, error: error instanceof ApiError ? error.message : "加载投资逻辑失败，请重试。" }); });
    return () => { active = false; };
  }, [key, queryError, subjectType, subjectId, status, offset]);
  function apply(type: string, id: string, nextStatus: string) {
    const next = thesisFilterQuery(searchParams, type, id, nextStatus);
    if (next.toString() === searchParams.toString()) setRefresh(value => value + 1);
    else setSearchParams(next);
  }
  return <div className="min-w-0">
    <PageHeader title="投资逻辑" subtitle="核对记录、正式状态和冻结原貌，沿来源继续研究。" actions={
      <Link className={`${button} border-primary/30 bg-primary/10 text-primary`} to={`/thesis/new?${new URLSearchParams({ return_to: returnTo, ...(!queryError && subjectType ? { subject_type: subjectType, subject_id: subjectId } : {}) })}`}><Plus aria-hidden="true" className="h-4 w-4" />新建逻辑</Link>
    } />
    <GlassCard className="mb-4"><ThesisFilters key={searchParams.toString()} query={query} loading={loading} onApply={apply} /></GlassCard>
    <p className="mb-5 rounded-md border border-warning/30 bg-warning/5 p-3 text-sm leading-6 text-muted-foreground">跟踪状态与正式确认是两回事。记录版本不等于冻结版本；冻结原貌与后续已确认变更，请在详情分别核对。</p>
    <section aria-labelledby="thesis-list-heading" aria-busy={loading}>
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="thesis-list-heading" className="text-lg font-semibold">投资逻辑条目</h2>
        <p className="min-w-0 break-all text-sm text-muted-foreground">已应用：{queryError ? "筛选无效" : `${subjectType ? `${SUBJECT_LABELS[subjectType]} / ${subjectId}` : "全部标的"} · ${status ? THESIS_STATUS_LABELS[status] : "全部跟踪状态"}`}</p>
      </div>
      {queryError ? <GlassCard><p role="alert" className="text-sm text-danger">{queryError}</p></GlassCard> : loading ? (
        <GlassCard><p role="status" className="flex justify-center gap-2 py-8 text-sm text-muted-foreground"><Loader2 aria-hidden="true" className="h-4 w-4 animate-spin" />正在加载投资逻辑…</p></GlassCard>
      ) : current?.status === "error" ? (
        <GlassCard><div role="alert"><h3 className="font-medium">投资逻辑加载失败</h3><p className="mt-2 break-words text-sm text-muted-foreground">{current.error}</p></div><button type="button" className={`${button} mt-4`} onClick={() => setRefresh(value => value + 1)}><RotateCcw aria-hidden="true" className="h-4 w-4" />重新加载</button></GlassCard>
      ) : items.length === 0 ? (
        <GlassCard className="py-10 text-center"><BookOpen aria-hidden="true" className="mx-auto mb-3 h-7 w-7 text-muted-foreground" />
          <h3 className="font-medium">{page > 1 ? "此页暂无投资逻辑" : subjectType || status ? "此筛选下暂无投资逻辑" : "尚无投资逻辑条目"}</h3>
          <p className="mt-2 text-sm text-muted-foreground">{page > 1 ? "条目可能已变化，请返回第一页查看。" : "可调整筛选，或先整理研究记录与证据，再建立投资逻辑。"}</p>
          <div className="mt-4 flex flex-wrap justify-center gap-3">{page > 1 ? <button className={button} onClick={() => setSearchParams(evidencePageQuery(searchParams, 1))}>返回第一页</button> : subjectType || status ? <button className={button} onClick={() => apply("", "", "")}>查看全部投资逻辑</button> : <Link className={button} to="/notes">前往研究记录</Link>}</div>
        </GlassCard>
      ) : <>
        <p role="status" className="mb-3 text-xs text-muted-foreground">共 {total} 条 · 第 {page} / {totalPages} 页 · 本页 {items.length} 条</p>
        <div className="space-y-3">{items.map(thesis => <GlassCard key={thesis.id}>
          <article aria-labelledby={`thesis-${thesis.id}`} className="min-w-0">
            <div className="flex flex-wrap items-start justify-between gap-3"><h3 id={`thesis-${thesis.id}`} className="min-w-0 flex-1 break-words text-base font-semibold leading-7 [overflow-wrap:anywhere]">{thesis.title}</h3>
              <span className="rounded border border-border px-2 py-1 text-xs text-muted-foreground">{thesisLifecycleLabel(thesis)}</span></div>
            <p className="mt-2 break-words text-sm leading-6 [overflow-wrap:anywhere]">{thesis.summary?.trim() || "摘要未提供，请在详情核对原始记录。"}</p>
            <p className="mt-2 break-words text-sm text-muted-foreground">{SUBJECT_LABELS[thesis.subject_type] ?? thesis.subject_type} / <span className="font-mono">{thesis.subject_id}</span> · 跟踪状态：{THESIS_STATUS_LABELS[thesis.status] ?? "未知"}</p>
            <dl className="mt-3 grid gap-x-6 gap-y-2 text-sm leading-6 sm:grid-cols-3">
              <div><dt className="text-xs text-muted-foreground">记录版本</dt><dd>{thesisRevisionLabel(thesis.current_revision)}</dd></div>
              <div><dt className="text-xs text-muted-foreground">冻结版本</dt><dd>{thesis.frozen_revision != null ? thesisRevisionLabel(thesis.frozen_revision) : thesis.formal_state === "frozen" ? "未知 · 需核对" : "未提供冻结版本"}</dd></div>
              <div><dt className="text-xs text-muted-foreground">记录更新</dt><dd>{evidenceDateLabel(thesis.updated_at)}</dd></div>
            </dl>
            {thesis.status === "archived" && <p className="mt-3 text-sm text-muted-foreground">已归档，详情只读。</p>}
            <div className="mt-4 flex justify-end border-t border-border pt-3"><Link className={`${button} text-primary`} aria-label={`查看逻辑与版本：${thesis.title}`} to={`/thesis/${encodeURIComponent(thesis.id)}?${new URLSearchParams({ return_to: returnTo })}`}>查看逻辑与版本<ChevronRight aria-hidden="true" className="h-4 w-4" /></Link></div>
          </article>
        </GlassCard>)}</div>
      </>}
      {!loading && current?.status === "success" && (total > PAGE_SIZE || page > 1) && <nav aria-label="投资逻辑分页" className="mt-4 flex flex-wrap items-center justify-between gap-3">
        <button className={button} disabled={page === 1} onClick={() => setSearchParams(evidencePageQuery(searchParams, page - 1))}><ChevronLeft aria-hidden="true" className="h-4 w-4" />上一页</button>
        <span className="text-xs text-muted-foreground">第 {page} 页 · 每页最多 {PAGE_SIZE} 条</span>
        <button className={button} disabled={offset + PAGE_SIZE >= total} onClick={() => setSearchParams(evidencePageQuery(searchParams, page + 1))}>下一页<ChevronRight aria-hidden="true" className="h-4 w-4" /></button>
      </nav>}
    </section>
  </div>;
}
