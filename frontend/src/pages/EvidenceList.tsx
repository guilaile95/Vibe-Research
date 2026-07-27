import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { Plus, Loader2, FileText, Filter, ChevronLeft, ChevronRight } from "lucide-react";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import { api, ApiError, type EvidenceRecord } from "@/lib/api";
import { cn } from "@/lib/utils";

const PAGE_SIZE = 50;

const SUBJECT_TYPE_LABELS: Record<string, string> = {
  stock: "个股",
  sector: "板块",
  theme: "主题",
};

const EVIDENCE_TYPE_LABELS: Record<string, string> = {
  news: "新闻",
  announcement: "公告",
  report: "研报",
  research_note: "研究笔记",
  financial_filing: "财报",
  other: "其他",
};

const CLASSIFICATION_LABELS: Record<string, string> = {
  fact: "事实",
  inference: "推断",
  unknown: "未知",
};

const CLASSIFICATION_COLOR: Record<string, string> = {
  fact: "bg-success/15 text-success",
  inference: "bg-warning/15 text-warning",
  unknown: "bg-muted/50 text-muted-foreground",
};

const CONFIDENCE_LABELS: Record<string, string> = {
  high: "高",
  medium: "中",
  low: "低",
};

const CONFIDENCE_COLOR: Record<string, string> = {
  high: "bg-success/15 text-success",
  medium: "bg-warning/15 text-warning",
  low: "bg-danger/15 text-danger",
};

const fmtDate = (s: string | null) => {
  if (!s) return "—";
  try {
    return new Date(s).toLocaleString("zh-CN", {
      year: "numeric", month: "2-digit", day: "2-digit",
      hour: "2-digit", minute: "2-digit",
    });
  } catch {
    return s;
  }
};

export function EvidenceList() {
  const [items, setItems] = useState<EvidenceRecord[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const [subjectType, setSubjectType] = useState("");
  const [subjectId, setSubjectId] = useState("");

  const runIdRef = useRef(0);

  const load = useCallback(async (off: number) => {
    const rid = ++runIdRef.current;
    setLoading(true);
    setErr(null);
    try {
      const params: Record<string, unknown> = { limit: PAGE_SIZE, offset: off };
      if (subjectType) params.subject_type = subjectType;
      if (subjectId.trim()) params.subject_id = subjectId.trim();
      const r = await api.evidenceList(params as any);
      if (rid !== runIdRef.current) return;
      setItems(r.items ?? []);
      setTotal(r.total ?? 0);
      setOffset(off);
    } catch (e) {
      if (rid !== runIdRef.current) return;
      setErr(e instanceof ApiError ? e.message : "加载证据列表失败");
    } finally {
      if (rid === runIdRef.current) setLoading(false);
    }
  }, [subjectType, subjectId]);

  useEffect(() => {
    void load(0);
  }, [load]);

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const currentPage = Math.floor(offset / PAGE_SIZE) + 1;

  return (
    <div>
      <PageHeader
        title="证据库"
        subtitle="把支撑/反对投资逻辑的证据沉淀下来，按标的检索、关联到逻辑后形成可追溯的证据账本。"
        actions={
          <Link
            to="/evidence/new"
            className="inline-flex items-center gap-1.5 rounded-lg bg-primary/15 px-3 py-1.5 text-sm font-medium text-primary shadow-glow hover:bg-primary/25"
          >
            <Plus className="h-4 w-4" /> 新建证据
          </Link>
        }
      />

      <GlassCard className="mb-4">
        <div className="flex flex-wrap items-end gap-3">
          <div className="flex items-center gap-1.5 text-sm text-muted-foreground">
            <Filter className="h-4 w-4" /> 筛选：
          </div>
          <label className="block text-xs">
            <span className="text-muted-foreground">主体类型</span>
            <select
              value={subjectType}
              onChange={(e) => setSubjectType(e.target.value)}
              className="mt-0.5 block rounded border border-border/50 bg-background px-2 py-1 text-sm"
            >
              <option value="">全部</option>
              {Object.entries(SUBJECT_TYPE_LABELS).map(([k, v]) => (
                <option key={k} value={k}>{v}</option>
              ))}
            </select>
          </label>
          <label className="block text-xs">
            <span className="text-muted-foreground">主体代码/标识</span>
            <input
              value={subjectId}
              onChange={(e) => setSubjectId(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") void load(0); }}
              placeholder="如 600519"
              className="mt-0.5 block w-40 rounded border border-border/50 bg-background px-2 py-1 text-sm"
            />
          </label>
          <button
            onClick={() => void load(0)}
            disabled={loading}
            className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-primary/15 px-3 text-sm text-primary hover:bg-primary/25 disabled:opacity-50"
          >
            {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
            查询
          </button>
          <div className="ml-auto text-xs text-muted-foreground">
            共 {total} 条 · 第 {currentPage} / {totalPages} 页
          </div>
        </div>
      </GlassCard>

      {err && (
        <div className="mb-4 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
          {err}
        </div>
      )}

      <GlassCard>
        {loading && items.length === 0 ? (
          <div className="flex items-center justify-center py-10 text-sm text-muted-foreground">
            <Loader2 className="mr-2 h-4 w-4 animate-spin" /> 加载中…
          </div>
        ) : items.length === 0 ? (
          <div className="flex flex-col items-center gap-2 py-10 text-center text-sm text-muted-foreground">
            <FileText className="h-8 w-8 text-muted-foreground/40" />
            还没有证据。点右上角「新建证据」开始沉淀。
          </div>
        ) : (
          <div className="divide-y divide-border/30">
            {items.map((e) => (
              <Link
                key={e.id}
                to={`/evidence/${e.id}`}
                className="block py-3 transition-colors hover:bg-primary/5"
              >
                <div className="flex items-start gap-2.5">
                  <FileText className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium">{e.claim}</p>
                    <p className="mt-0.5 text-[11px] text-muted-foreground/70">
                      <span className="font-mono">{e.subject_type}/{e.subject_id}</span>
                      {" · "}
                      {EVIDENCE_TYPE_LABELS[e.evidence_type] ?? e.evidence_type}
                      {" · "}
                      {e.source_title || "（无来源标题）"}
                      {" · "}
                      {fmtDate(e.source_date)}
                    </p>
                    <div className="mt-1 flex flex-wrap items-center gap-1">
                      <span className={cn("rounded px-1.5 py-0.5 text-[10px]", CLASSIFICATION_COLOR[e.classification] ?? "bg-muted/50 text-muted-foreground")}>
                        {CLASSIFICATION_LABELS[e.classification] ?? e.classification}
                      </span>
                      <span className={cn("rounded px-1.5 py-0.5 text-[10px]", CONFIDENCE_COLOR[e.confidence] ?? "bg-muted/50 text-muted-foreground")}>
                        置信度 {CONFIDENCE_LABELS[e.confidence] ?? e.confidence}
                      </span>
                    </div>
                  </div>
                </div>
              </Link>
            ))}
          </div>
        )}

        {total > PAGE_SIZE && (
          <div className="mt-3 flex items-center justify-between border-t border-border/30 pt-3 text-sm">
            <button
              onClick={() => void load(Math.max(0, offset - PAGE_SIZE))}
              disabled={offset === 0 || loading}
              className="inline-flex items-center gap-1 rounded border border-border/50 px-2.5 py-1 text-xs text-muted-foreground hover:border-primary/40 disabled:opacity-40"
            >
              <ChevronLeft className="h-3.5 w-3.5" /> 上一页
            </button>
            <span className="text-xs text-muted-foreground">
              第 {currentPage} / {totalPages} 页
            </span>
            <button
              onClick={() => void load(offset + PAGE_SIZE < total ? offset + PAGE_SIZE : offset)}
              disabled={offset + PAGE_SIZE >= total || loading}
              className="inline-flex items-center gap-1 rounded border border-border/50 px-2.5 py-1 text-xs text-muted-foreground hover:border-primary/40 disabled:opacity-40"
            >
              下一页 <ChevronRight className="h-3.5 w-3.5" />
            </button>
          </div>
        )}
      </GlassCard>
    </div>
  );
}
