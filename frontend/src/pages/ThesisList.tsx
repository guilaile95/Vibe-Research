import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Plus, Loader2, BookOpen, Filter, ChevronLeft, ChevronRight, Lock } from "lucide-react";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import { api, ApiError, type InvestmentThesis } from "@/lib/api";
import { cn } from "@/lib/utils";

const PAGE_SIZE = 50;

const SUBJECT_TYPE_LABELS: Record<string, string> = {
  stock: "个股",
  sector: "板块",
  theme: "主题",
};

const STATUS_LABELS: Record<string, string> = {
  active: "生效中",
  weakened: "走弱",
  invalidated: "已失效",
  archived: "已归档",
};

const STATUS_COLOR: Record<string, string> = {
  active: "bg-success/15 text-success",
  weakened: "bg-warning/15 text-warning",
  invalidated: "bg-danger/15 text-danger",
  archived: "bg-muted/50 text-muted-foreground",
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

function readFiltersFromParams(sp: URLSearchParams) {
  return {
    subjectType: sp.get("subject_type") || "",
    subjectId: sp.get("subject_id") || "",
    status: sp.get("status") || "",
  };
}

function buildFilterParams(subjectType: string, subjectId: string, status: string) {
  const params: {
    subject_type?: string;
    subject_id?: string;
    status?: string;
  } = {};
  // subject_id 与 subject_type 成对提交
  const typeOk = Boolean(subjectType);
  const idOk = Boolean(subjectId.trim());
  if (typeOk && idOk) {
    params.subject_type = subjectType;
    params.subject_id = subjectId.trim();
  }
  if (status) params.status = status;
  return params;
}

function filtersToSearchParams(subjectType: string, subjectId: string, status: string): URLSearchParams {
  const next = new URLSearchParams();
  const typeOk = Boolean(subjectType);
  const idOk = Boolean(subjectId.trim());
  if (typeOk && idOk) {
    next.set("subject_type", subjectType);
    next.set("subject_id", subjectId.trim());
  }
  if (status) next.set("status", status);
  return next;
}

export function ThesisList() {
  const [searchParams, setSearchParams] = useSearchParams();
  const initial = readFiltersFromParams(searchParams);
  const [items, setItems] = useState<InvestmentThesis[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const [subjectType, setSubjectType] = useState(initial.subjectType);
  const [subjectId, setSubjectId] = useState(initial.subjectId);
  const [status, setStatus] = useState(initial.status);

  const runIdRef = useRef(0);
  const skipUrlSyncRef = useRef(true);

  // 筛选变更时同步 URL，保证刷新后状态不丢失
  useEffect(() => {
    if (skipUrlSyncRef.current) {
      skipUrlSyncRef.current = false;
      return;
    }
    const next = filtersToSearchParams(subjectType, subjectId, status);
    if (next.toString() !== searchParams.toString()) {
      setSearchParams(next, { replace: true });
    }
  }, [subjectType, subjectId, status, searchParams, setSearchParams]);

  const load = useCallback(async (off: number) => {
    const rid = ++runIdRef.current;
    setLoading(true);
    setErr(null);
    try {
      const filterParams = buildFilterParams(subjectType, subjectId, status);
      const r = await api.thesisList({
        ...filterParams,
        limit: PAGE_SIZE,
        offset: off,
      });
      if (rid !== runIdRef.current) return;
      setItems(r.items ?? []);
      setTotal(r.total ?? 0);
      setOffset(off);
    } catch (e) {
      if (rid !== runIdRef.current) return;
      setErr(e instanceof ApiError ? e.message : "加载投资逻辑列表失败");
    } finally {
      if (rid === runIdRef.current) setLoading(false);
    }
  }, [subjectType, subjectId, status]);

  useEffect(() => {
    void load(0);
  }, [load]);

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const currentPage = Math.floor(offset / PAGE_SIZE) + 1;

  return (
    <div>
      <PageHeader
        title="投资逻辑"
        subtitle="把对个股/板块/主题的投资逻辑结构化沉淀，关联证据后形成可追溯、可回滚的版本化账本。"
        actions={
          <Link
            to="/thesis/new"
            className="inline-flex items-center gap-1.5 rounded-lg bg-primary/15 px-3 py-1.5 text-sm font-medium text-primary shadow-glow hover:bg-primary/25"
          >
            <Plus className="h-4 w-4" /> 新建逻辑
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
          <label className="block text-xs">
            <span className="text-muted-foreground">状态</span>
            <select
              value={status}
              onChange={(e) => setStatus(e.target.value)}
              className="mt-0.5 block rounded border border-border/50 bg-background px-2 py-1 text-sm"
            >
              <option value="">全部</option>
              {Object.entries(STATUS_LABELS).map(([k, v]) => (
                <option key={k} value={k}>{v}</option>
              ))}
            </select>
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
            <BookOpen className="h-8 w-8 text-muted-foreground/40" />
            还没有投资逻辑。点右上角「新建逻辑」开始沉淀。
          </div>
        ) : (
          <div className="divide-y divide-border/30">
            {items.map((t) => {
              const archived = t.status === "archived";
              return (
                <Link
                  key={t.id}
                  to={`/thesis/${t.id}`}
                  className={cn(
                    "block py-3 transition-colors hover:bg-primary/5",
                    archived && "opacity-70",
                  )}
                >
                  <div className="flex items-start gap-2.5">
                    {archived ? (
                      <Lock className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
                    ) : (
                      <BookOpen className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
                    )}
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <p className="truncate text-sm font-medium">{t.title}</p>
                        <span className={cn("shrink-0 rounded px-1.5 py-0.5 text-[10px]", STATUS_COLOR[t.status] ?? "bg-muted/50 text-muted-foreground")}>
                          {STATUS_LABELS[t.status] ?? t.status}
                        </span>
                        <span className="shrink-0 rounded bg-secondary px-1.5 py-0.5 text-[10px] text-secondary-foreground">
                          v{t.current_revision}
                        </span>
                      </div>
                      <p className="mt-0.5 line-clamp-1 text-[11px] text-muted-foreground/70">
                        {t.summary || "（无摘要）"}
                      </p>
                      <p className="mt-0.5 text-[11px] text-muted-foreground/60">
                        <span className="font-mono">{t.subject_type}/{t.subject_id}</span>
                        {" · "}
                        更新 {fmtDate(t.updated_at)}
                      </p>
                    </div>
                  </div>
                </Link>
              );
            })}
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
