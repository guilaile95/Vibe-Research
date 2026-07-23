import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Upload, FileText, Trash2, Download, Loader2, FolderOpen, Search, Pencil, ExternalLink, Save, X } from "lucide-react";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import sectorsData from "@/data/sectors.json";
import { cn } from "@/lib/utils";
import {
  api, ApiError, downloadReport,
  type MyReport, type MyReportsBrowseResult, type MyReportsBrowseGroup,
} from "@/lib/api";

const fmtSize = (b: number) =>
  b < 1024 ? `${b}B` : b < 1048576 ? `${(b / 1024).toFixed(0)}KB` : `${(b / 1048576).toFixed(1)}MB`;
const fmtDate = (ts: number) =>
  new Date(ts).toLocaleDateString("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit" });

const SECTOR_MAP = new Map(sectorsData.sectors.map((s) => [s.key, s.label]));
const sectorLabel = (key: string) => SECTOR_MAP.get(key) ?? key;

const SOURCE_KIND_LABELS: Record<string, string> = {
  report: "研报", whitepaper: "白皮书", company_filing: "公司公告",
  news: "新闻", standard: "标准", other: "其他",
};

const VIEW_LABELS: Record<MyReportsBrowseGroup, string> = {
  year: "按时间", industry: "按产业", institution: "按机构",
};
const VIEWS: MyReportsBrowseGroup[] = ["year", "industry", "institution"];

type EditForm = {
  title: string;
  institution: string;
  publish_date: string;
  sector_keys: string[];
  source_url: string;
  source_kind: string;
};

const EMPTY_EDIT: EditForm = {
  title: "", institution: "", publish_date: "", sector_keys: [], source_url: "", source_kind: "",
};

// 读文件为 dataURL（含 base64）；后端会剥掉 data: 前缀。
const fileToB64 = (file: File): Promise<string> =>
  new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });

export function MyReports() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [reports, setReports] = useState<MyReport[]>([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [loadFailed, setLoadFailed] = useState(false);
  const [drag, setDrag] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const [view, setView] = useState<MyReportsBrowseGroup>("industry");
  const [browse, setBrowse] = useState<MyReportsBrowseResult | null>(null);
  const [browseErr, setBrowseErr] = useState<string | null>(null);

  const [q, setQ] = useState("");
  const [searching, setSearching] = useState(false);
  const [results, setResults] = useState<MyReport[] | null>(null);

  const [editingId, setEditingId] = useState<string | null>(null);
  const [edit, setEdit] = useState<EditForm>(EMPTY_EDIT);
  const [editBusy, setEditBusy] = useState(false);
  const [editErr, setEditErr] = useState<string | null>(null);
  const [hasLoaded, setHasLoaded] = useState(false);

  // URL 查询参数：report（定位高亮）/ sector / institution / year / month。
  const focusReportId = searchParams.get("report") || undefined;
  const filterSector = searchParams.get("sector") || undefined;
  const filterInstitution = searchParams.get("institution") || undefined;
  const filterYear = searchParams.get("year") || undefined;
  const filterMonth = searchParams.get("month") || undefined;
  // 同步 report + 过滤参数到 URL（前进/后退/刷新不丢失；不得丢掉 report）。
  useEffect(() => {
    const next = new URLSearchParams();
    if (focusReportId) next.set("report", focusReportId);
    if (filterSector) next.set("sector", filterSector);
    if (filterInstitution) next.set("institution", filterInstitution);
    if (filterYear) next.set("year", filterYear);
    if (filterMonth) next.set("month", filterMonth);
    const cur = searchParams.toString();
    if (next.toString() !== cur) setSearchParams(next, { replace: true });
  }, [focusReportId, filterSector, filterInstitution, filterYear, filterMonth, searchParams, setSearchParams]);
  // 由 URL 参数恢复视图：sector/institution/year/month 存在时切换对应视图。
  useEffect(() => {
    if (filterSector) setView("industry");
    else if (filterInstitution) setView("institution");
    else if (filterYear || filterMonth) setView("year");
  }, [filterSector, filterInstitution, filterYear, filterMonth]);

  const load = async () => {
    try {
      const data = await api.myReports();
      setReports(data);
      setLoadFailed(false);
      setErr(null);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "加载研报列表失败");
      setLoadFailed(true);
    } finally {
      setHasLoaded(true);
    }
  };
  useEffect(() => {
    load();
  }, []);

  // 加载分组浏览数据（切换视图 / 上传删除后刷新）。搜索激活时隐藏分组视图。
  const loadBrowse = async (group: MyReportsBrowseGroup) => {
    try {
      const data = await api.browseMyReports(group);
      setBrowse(data);
      setBrowseErr(null);
    } catch (e) {
      setBrowseErr(e instanceof ApiError ? e.message : "加载浏览数据失败");
    }
  };
  useEffect(() => {
    if (!searching) loadBrowse(view);
  }, [view, searching]);

  useEffect(() => {
    if (!q.trim()) {
      setSearching(false);
      setResults(null);
      return;
    }
    setSearching(true);
    let alive = true;
    api.searchMyReports(q)
      .then((r) => { if (alive) setResults(r); })
      .catch(() => { if (alive) setResults([]); });
    return () => { alive = false; };
  }, [q]);

  const refreshAll = async () => {
    await load();
    if (!searching) await loadBrowse(view);
  };

  const upload = async (files: FileList | File[]) => {
    setBusy(true);
    setErr(null);
    try {
      for (const f of Array.from(files)) {
        const b64 = await fileToB64(f);
        await api.uploadReport(f.name, b64);
      }
      await refreshAll();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "上传失败");
    } finally {
      setBusy(false);
    }
  };

  const remove = async (r: MyReport) => {
    if (!confirm(`删除「${r.title || r.name}」？（同时从本地归档目录移除）`)) return;
    try {
      await api.deleteReport(r.id);
      if (editingId === r.id) setEditingId(null);
      await refreshAll();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "删除失败");
    }
  };

  const download = async (r: MyReport) => {
    try {
      await downloadReport(r.id, r.title || r.name);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "下载失败");
    }
  };

  const startEdit = (r: MyReport) => {
    setEditingId(r.id);
    setEdit({
      title: r.title ?? "",
      institution: r.institution ?? "",
      publish_date: r.publish_date ?? "",
      sector_keys: r.sector_keys ?? [],
      source_url: r.source_url ?? "",
      source_kind: r.source_kind ?? "",
    });
    setEditErr(null);
  };

  const toggleSectorKey = (key: string) => {
    setEdit((prev) => ({
      ...prev,
      sector_keys: prev.sector_keys.includes(key)
        ? prev.sector_keys.filter((k) => k !== key)
        : [...prev.sector_keys, key],
    }));
  };

  const saveEdit = async (id: string) => {
    setEditBusy(true);
    setEditErr(null);
    try {
      // 始终发送字符串（含 ""）：后端 "" 清空字段，缺省则保留。
      await api.patchReport(id, {
        title: edit.title,
        institution: edit.institution,
        publish_date: edit.publish_date,
        sector_keys: edit.sector_keys,
        source_url: edit.source_url,
        source_kind: edit.source_kind,
      });
      setEditingId(null);
      await refreshAll();
    } catch (e) {
      setEditErr(e instanceof ApiError ? e.message : "保存失败");
    } finally {
      setEditBusy(false);
    }
  };

  // 默认（产业）视图保留旧有的按行业分组列表 UX，确保加载时体验不变。
  const grouped = useMemo(() => {
    const g: Record<string, MyReport[]> = {};
    for (const r of reports) (g[r.industry] ||= []).push(r);
    return Object.entries(g).sort((a, b) =>
      a[0] === "未分类" ? 1 : b[0] === "未分类" ? -1 : b[1].length - a[1].length,
    );
  }, [reports]);

  const displayTitle = (r: MyReport) => r.title || r.name;
  const displayInstitution = (r: MyReport) => r.institution || "未确认机构";
  const dateOf = (r: MyReport): { label: string; value: string } | null => {
    if (r.publish_date) return { label: "发布日期", value: r.publish_date };
    if (r.imported_at) return { label: "归档日期", value: r.imported_at.slice(0, 10) };
    if (r.ts) return { label: "归档日期", value: fmtDate(r.ts) };
    return null;
  };

  const renderReportRow = (r: MyReport) => {
    const date = dateOf(r);
    const editing = editingId === r.id;
    const highlighted = focusReportId === r.id;
    return (
      <div
        key={r.id}
        id={`report-${r.id}`}
        className={cn(
          "border-b border-border/20 last:border-b-0 transition-colors",
          highlighted && "bg-primary/5 ring-1 ring-primary/30",
        )}
      >
        <div className="flex items-start gap-2.5 py-2.5">
          <FileText className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium">{displayTitle(r)}</p>
            <p className="text-[11px] text-muted-foreground/60">
              {displayInstitution(r)}
              {date ? ` · ${date.label} ${date.value}` : null}
              {" · "}{fmtSize(r.size)}
            </p>
            <div className="mt-1 flex flex-wrap items-center gap-1">
              {(r.sector_keys ?? []).map((key) => (
                <Link
                  key={key}
                  to={`/sectors/${key}`}
                  className="rounded bg-primary/10 px-1.5 py-0.5 text-[10px] font-medium text-primary hover:bg-primary/20"
                >
                  {sectorLabel(key)}
                </Link>
              ))}
              {r.source_kind && SOURCE_KIND_LABELS[r.source_kind] && (
                <span className="rounded bg-secondary px-1.5 py-0.5 text-[10px] text-secondary-foreground">
                  {SOURCE_KIND_LABELS[r.source_kind]}
                </span>
              )}
              {r.source_url && (
                <a
                  href={r.source_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-0.5 text-[10px] text-muted-foreground hover:text-primary"
                  title={r.source_url}
                >
                  <ExternalLink className="h-3 w-3" />
                  来源
                </a>
              )}
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-1">
            <button
              onClick={() => startEdit(r)}
              className={cn("shrink-0 text-muted-foreground/60 hover:text-primary", editing && "text-primary")}
              title="编辑"
            >
              <Pencil className="h-3.5 w-3.5" />
            </button>
            <button
              onClick={() => download(r)}
              className="shrink-0 text-muted-foreground/60 hover:text-primary"
              title="下载"
            >
              <Download className="h-4 w-4" />
            </button>
            <button
              onClick={() => remove(r)}
              className="shrink-0 text-muted-foreground/50 hover:text-destructive"
              title="删除"
            >
              <Trash2 className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>

        {editing && (
          <div className="mb-3 rounded-lg border border-border/40 bg-background/50 p-3">
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
              <label className="block text-xs">
                <span className="text-muted-foreground">标题</span>
                <input
                  value={edit.title}
                  onChange={(e) => setEdit({ ...edit, title: e.target.value })}
                  className="mt-0.5 w-full rounded border border-border/50 bg-background px-2 py-1 text-sm"
                  placeholder={r.name}
                />
              </label>
              <label className="block text-xs">
                <span className="text-muted-foreground">机构</span>
                <input
                  value={edit.institution}
                  onChange={(e) => setEdit({ ...edit, institution: e.target.value })}
                  className="mt-0.5 w-full rounded border border-border/50 bg-background px-2 py-1 text-sm"
                  placeholder="未确认机构"
                />
              </label>
              <label className="block text-xs">
                <span className="text-muted-foreground">发布日期</span>
                <input
                  value={edit.publish_date}
                  onChange={(e) => setEdit({ ...edit, publish_date: e.target.value })}
                  className="mt-0.5 w-full rounded border border-border/50 bg-background px-2 py-1 text-sm"
                  placeholder="YYYY-MM-DD / YYYY-MM / YYYY"
                />
              </label>
              <label className="block text-xs">
                <span className="text-muted-foreground">来源类型</span>
                <select
                  value={edit.source_kind}
                  onChange={(e) => setEdit({ ...edit, source_kind: e.target.value })}
                  className="mt-0.5 w-full rounded border border-border/50 bg-background px-2 py-1 text-sm"
                >
                  <option value="">（未设置）</option>
                  {Object.entries(SOURCE_KIND_LABELS).map(([k, v]) => (
                    <option key={k} value={k}>{v}</option>
                  ))}
                </select>
              </label>
              <label className="block text-xs sm:col-span-2">
                <span className="text-muted-foreground">来源链接</span>
                <input
                  value={edit.source_url}
                  onChange={(e) => setEdit({ ...edit, source_url: e.target.value })}
                  className="mt-0.5 w-full rounded border border-border/50 bg-background px-2 py-1 text-sm"
                  placeholder="https://..."
                />
              </label>
            </div>
            <div className="mt-2">
              <span className="text-xs text-muted-foreground">关联赛道</span>
              <div className="mt-1 flex flex-wrap gap-1">
                {sectorsData.sectors.map((s) => (
                  <button
                    key={s.key}
                    onClick={() => toggleSectorKey(s.key)}
                    className={cn(
                      "rounded border px-1.5 py-0.5 text-[10px] transition-colors",
                      edit.sector_keys.includes(s.key)
                        ? "border-primary bg-primary/15 text-primary"
                        : "border-border/50 text-muted-foreground hover:border-primary/40",
                    )}
                  >
                    {s.label}
                  </button>
                ))}
              </div>
            </div>
            {editErr && (
              <p className="mt-2 text-xs text-destructive">{editErr}</p>
            )}
            <div className="mt-2 flex items-center gap-2">
              <button
                onClick={() => saveEdit(r.id)}
                disabled={editBusy}
                className="inline-flex items-center gap-1 rounded bg-primary px-2.5 py-1 text-xs font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-60"
              >
                <Save className="h-3.5 w-3.5" /> {editBusy ? "保存中…" : "保存"}
              </button>
              <button
                onClick={() => setEditingId(null)}
                className="inline-flex items-center gap-1 rounded border border-border/50 px-2.5 py-1 text-xs text-muted-foreground hover:border-primary/40"
              >
                <X className="h-3.5 w-3.5" /> 取消
              </button>
            </div>
          </div>
        )}
      </div>
    );
  };

  // 按 URL 参数过滤后的研报列表。
  const filteredReports = useMemo(() => {
    return reports.filter((r) => {
      if (filterSector && !(r.sector_keys ?? []).includes(filterSector)) return false;
      if (filterInstitution) {
        const inst = r.institution || "";
        if ((inst ? inst : "__unknown__") !== filterInstitution) return false;
      }
      if (filterYear || filterMonth) {
        let year: string | null = null;
        let month: string | null = null;
        if (r.publish_date) {
          year = r.publish_date.slice(0, 4);
          month = r.publish_date.slice(0, 7);
        } else if (r.imported_at) {
          year = r.imported_at.slice(0, 4);
          month = r.imported_at.slice(0, 7);
        } else if (r.ts) {
          year = new Date(r.ts).getFullYear().toString();
        }
        if (filterYear && year !== filterYear) return false;
        if (filterMonth && month !== filterMonth) return false;
      }
      return true;
    });
  }, [reports, filterSector, filterInstitution, filterYear, filterMonth]);

  // 定位高亮：报告在过滤列表中才滚动。
  useEffect(() => {
    if (focusReportId && filteredReports.some((r) => r.id === focusReportId)) {
      const el = document.getElementById(`report-${focusReportId}`);
      if (el) el.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }
  }, [focusReportId, filteredReports]);

  const showEmpty = !loadFailed && reports.length === 0;
  const listGroups = browse?.groups ?? [];
  const focusReportMissing =
    Boolean(focusReportId)
    && hasLoaded
    && !loadFailed
    && !reports.some((r) => r.id === focusReportId);

  return (
    <div>
      <PageHeader
        title="我的研报"
        subtitle="把自己的研报拖进来归档，自动按行业分类。支持按时间·产业·机构浏览与全文检索。文件只存在本地部署目录、不上传、不进任何仓库。"
      />

      {/* 上传区 */}
      <GlassCard className="mb-4">
        <div
          onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
          onDragLeave={() => setDrag(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDrag(false);
            if (e.dataTransfer.files.length) upload(e.dataTransfer.files);
          }}
          onClick={() => inputRef.current?.click()}
          className={cn(
            "flex cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed py-10 text-center transition-colors",
            drag ? "border-primary bg-primary/10" : "border-border hover:border-primary/50 hover:bg-primary/5",
          )}
        >
          {busy ? (
            <Loader2 className="h-7 w-7 animate-spin text-primary" />
          ) : (
            <Upload className="h-7 w-7 text-primary" />
          )}
          <p className="text-sm font-medium">
            {busy ? "上传中…" : "把研报拖到这里，或点击选择文件"}
          </p>
          <p className="text-xs text-muted-foreground/70">
            支持 PDF / Word / txt / md / 表格 / 图片，单个 ≤ 25MB，可一次多选
          </p>
          <input
            ref={inputRef}
            type="file"
            multiple
            accept=".pdf,.doc,.docx,.txt,.md,.markdown,.csv,.xls,.xlsx,.ppt,.pptx,.png,.jpg,.jpeg,.webp"
            className="hidden"
            onChange={(e) => {
              if (e.target.files?.length) upload(e.target.files);
              e.target.value = "";
            }}
          />
        </div>
      </GlassCard>

      {err && (
        <div className="mb-4 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
          {err}
        </div>
      )}

      {focusReportMissing && (
        <div className="mb-4 rounded-lg border border-border/50 bg-muted/40 p-3 text-sm text-muted-foreground">
          未找到指定研报 id，可能已删除
        </div>
      )}

      {/* 浏览控制：视图切换 + 搜索 */}
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <div className="inline-flex overflow-hidden rounded-lg border border-border/50">
          {VIEWS.map((v) => (
            <button
              key={v}
              onClick={() => setView(v)}
              className={cn(
                "px-3 py-1.5 text-xs font-medium transition-colors",
                view === v ? "bg-primary text-primary-foreground" : "bg-background text-muted-foreground hover:bg-primary/10",
              )}
            >
              {VIEW_LABELS[v]}
            </button>
          ))}
        </div>
        <div className="ml-auto flex items-center gap-1">
          <Search className="h-4 w-4 text-muted-foreground" />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="搜索标题 / 机构 / 赛道…"
            className="w-40 rounded border border-border/50 bg-background px-2 py-1 text-sm placeholder:text-muted-foreground/50 sm:w-56"
          />
        </div>
      </div>

      {/* 搜索结果 */}
      {searching && (
        <div className="mb-4 space-y-2">
          <p className="text-xs text-muted-foreground">
            搜索「{q}」的结果（{results?.length ?? 0} 条）
          </p>
          {results && results.length > 0 ? (
            <GlassCard>
              <div className="divide-y divide-border/30">
                {results.map(renderReportRow)}
              </div>
            </GlassCard>
          ) : (
            <GlassCard>
              <div className="py-6 text-center text-sm text-muted-foreground">没有匹配的研报。</div>
            </GlassCard>
          )}
        </div>
      )}

      {/* 分组浏览（默认产业视图保持旧有 UX） */}
      {!searching && showEmpty ? (
        <GlassCard>
          <div className="flex flex-col items-center gap-2 py-10 text-center text-sm text-muted-foreground">
            <FolderOpen className="h-8 w-8 text-muted-foreground/40" />
            还没有归档的研报。把你收集的研报拖进上面的框，会自动按行业分好类。
          </div>
        </GlassCard>
      ) : !searching && view === "industry" && grouped.length > 0 ? (
        <div className="space-y-4">
          {grouped.map(([industry, items]) => {
            const sectorItems = items.filter((r) =>
              filteredReports.some((f) => f.id === r.id),
            );
            if (sectorItems.length === 0 && filteredReports.length > 0) return null;
            return (
              <GlassCard key={industry}>
                <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold">
                  <span className="rounded bg-primary/15 px-2 py-0.5 text-xs text-primary">{industry}</span>
                  <span className="text-xs font-normal text-muted-foreground">{sectorItems.length} 份</span>
                </h3>
                <div className="divide-y divide-border/30">
                  {sectorItems.map(renderReportRow)}
                </div>
              </GlassCard>
            );
          })}
        </div>
      ) : !searching ? (
        <div className="space-y-4">
          {browseErr && (
            <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
              {browseErr}
            </div>
          )}
          {view === "year" || view === "institution" ? (
            listGroups.length > 0 ? (
              listGroups.map((g) => (
                <GlassCard key={g.key}>
                  <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold">
                    <span className="rounded bg-primary/15 px-2 py-0.5 text-xs text-primary">{g.label}</span>
                    <span className="text-xs font-normal text-muted-foreground">{g.count} 份</span>
                  </h3>
                  {view === "year" && g.months && g.months.length > 0 && (
                    <div className="mb-3 space-y-2">
                      {g.months.map((m) => {
                        const monthReports = filteredReports.filter((r) => {
                          const month = r.publish_date
                            ? r.publish_date.slice(0, 7)
                            : r.imported_at
                              ? r.imported_at.slice(0, 7)
                              : null;
                          return month === m.key;
                        });
                        return (
                          <div key={m.key} className="rounded-lg border border-border/40 p-2">
                            <p className="mb-1 flex items-center gap-1 text-xs font-medium text-muted-foreground">
                              <span className="rounded bg-secondary px-1.5 py-0.5 text-[10px] text-secondary-foreground">
                                {m.label}（{m.count}）
                              </span>
                              <span className="text-[10px] text-muted-foreground/60">发布日期未确认时按归档时间</span>
                            </p>
                            <div className="divide-y divide-border/30">
                              {monthReports.map(renderReportRow)}
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  )}
                  {view !== "year" && (
                    <div className="divide-y divide-border/30">
                      {filteredReports
                        .filter((r) => matchesGroup(r, g.key, view))
                        .map(renderReportRow)}
                    </div>
                  )}
                </GlassCard>
              ))
            ) : (
              <GlassCard>
                <div className="py-6 text-center text-sm text-muted-foreground">该视角下暂无研报。</div>
              </GlassCard>
            )
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

// 判断某条研报是否属于当前分组视图下的某个分组 key。
function matchesGroup(r: MyReport, key: string, view: MyReportsBrowseGroup): boolean {
  if (view === "industry") return (r.industry || "未分类") === key;
  if (view === "institution") {
    const inst = r.institution || "";
    return (inst ? inst : "__unknown__") === key;
  }
  if (view === "year") {
    if (key === "__unknown__" || key === "未知") {
      return !r.publish_date && !r.imported_at && !r.ts;
    }
    let year: string | null = null;
    if (r.publish_date) year = r.publish_date.slice(0, 4);
    else if (r.imported_at) year = r.imported_at.slice(0, 4);
    else if (r.ts) year = new Date(r.ts).getFullYear().toString();
    return year === key;
  }
  return false;
}
