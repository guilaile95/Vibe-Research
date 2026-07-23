import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Download, ExternalLink, Loader2, Search } from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import {
  api,
  ApiError,
  type DiscoveredSectorReport,
  type MyReport,
  type SectorReportScope,
} from "@/lib/api";
import { cn } from "@/lib/utils";

type Props = {
  sectorKey: string;
};

type ImportState = {
  loading?: boolean;
  error?: string | null;
  success?: MyReport | null;
};

const SCOPE_OPTIONS: { value: SectorReportScope; label: string }[] = [
  { value: "industry", label: "行业" },
  { value: "company", label: "公司" },
  { value: "all", label: "全部" },
];

function reportKey(r: DiscoveredSectorReport, index: number): string {
  return r.external_id || r.info_code || `row-${index}`;
}

function archivedKey(provider: string | undefined, externalId: string | null | undefined): string | null {
  if (!externalId) return null;
  return `${provider || "eastmoney"}::${externalId}`;
}

export function SectorReportDiscoveryPanel({ sectorKey }: Props) {
  const [scope, setScope] = useState<SectorReportScope>("industry");
  const [days, setDays] = useState(365);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [discovered, setDiscovered] = useState<DiscoveredSectorReport[] | null>(null);
  const [filtered, setFiltered] = useState<DiscoveredSectorReport[] | null>(null);
  const [meta, setMeta] = useState<{ total?: number; returned?: number; truncated?: boolean }>({});
  const [importMap, setImportMap] = useState<Record<string, ImportState>>({});
  const [archived, setArchived] = useState<Map<string, MyReport>>(new Map());

  // 可选：加载已归档 external_id，用于列表标记「已保存」。
  useEffect(() => {
    let cancelled = false;
    api.myReports()
      .then((list) => {
        if (cancelled) return;
        const map = new Map<string, MyReport>();
        for (const r of list) {
          const k = archivedKey(r.source_provider, r.external_id ?? null);
          if (k) map.set(k, r);
        }
        setArchived(map);
      })
      .catch(() => {
        /* 归档列表失败不阻断发现 */
      });
    return () => {
      cancelled = true;
    };
  }, [sectorKey]);

  const rows = useMemo(() => {
    if (!discovered && !filtered) return [];
    const f = filtered ?? [];
    if (f.length > 0) return f;
    return discovered ?? [];
  }, [discovered, filtered]);

  const onDiscover = useCallback(async () => {
    setLoading(true);
    setError(null);
    setDiscovered(null);
    setFiltered(null);
    setImportMap({});
    try {
      const result = await api.discoverSectorReports(sectorKey, {
        days: Number.isFinite(days) && days > 0 ? days : 365,
        scope,
      });
      if (result.error) {
        setError(result.error);
      }
      setDiscovered(result.discovered ?? []);
      setFiltered(result.filtered ?? []);
      setMeta({
        total: result.total_discovered,
        returned: result.returned,
        truncated: result.truncated,
      });
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : e instanceof Error ? e.message : String(e);
      setError(msg);
      setDiscovered([]);
      setFiltered([]);
      setMeta({});
    } finally {
      setLoading(false);
    }
  }, [sectorKey, days, scope]);

  const onImport = useCallback(async (r: DiscoveredSectorReport) => {
    const ext = r.external_id;
    if (!ext) return;
    const key = reportKey(r, 0);
    setImportMap((prev) => ({
      ...prev,
      [key]: { loading: true, error: null, success: null },
    }));
    try {
      const saved = await api.importSectorReport(sectorKey, ext);
      setImportMap((prev) => ({
        ...prev,
        [key]: { loading: false, error: null, success: saved },
      }));
      const ak = archivedKey(saved.source_provider || r.source_provider, saved.external_id ?? ext);
      if (ak) {
        setArchived((prev) => {
          const next = new Map(prev);
          next.set(ak, saved);
          return next;
        });
      }
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : e instanceof Error ? e.message : String(e);
      setImportMap((prev) => ({
        ...prev,
        [key]: { loading: false, error: msg, success: null },
      }));
    }
  }, [sectorKey]);

  return (
    <GlassCard className="p-4 sm:p-5">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div>
          <h3 className="text-sm font-semibold text-foreground">研报发现</h3>
          <p className="mt-0.5 text-xs text-muted-foreground">
            手动发现 · 显式导入 · 不自动归档
          </p>
        </div>
      </div>

      <div className="flex min-w-0 flex-wrap items-end gap-2 sm:gap-3">
        <label className="flex min-w-[6.5rem] flex-col gap-1 text-xs text-muted-foreground">
          范围
          <select
            value={scope}
            onChange={(e) => setScope(e.target.value as SectorReportScope)}
            className="h-9 rounded-lg border border-border/60 bg-background/60 px-2 text-sm text-foreground"
          >
            {SCOPE_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
        </label>
        <label className="flex w-24 flex-col gap-1 text-xs text-muted-foreground">
          天数
          <input
            type="number"
            min={1}
            max={3650}
            value={days}
            onChange={(e) => setDays(Number(e.target.value) || 365)}
            className="h-9 rounded-lg border border-border/60 bg-background/60 px-2 text-sm text-foreground"
          />
        </label>
        <button
          type="button"
          onClick={onDiscover}
          disabled={loading}
          className={cn(
            "inline-flex h-9 items-center gap-1.5 rounded-lg border border-primary/40 bg-primary/15 px-3 text-sm font-medium text-primary",
            "hover:bg-primary/25 disabled:opacity-60",
          )}
        >
          {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
          开始发现
        </button>
      </div>

      {error && (
        <div className="mt-3 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs leading-relaxed text-foreground/90">
          {error}
        </div>
      )}

      {!loading && discovered !== null && rows.length === 0 && !error && (
        <p className="mt-3 text-xs text-muted-foreground">未发现匹配研报，可调整范围或天数后重试。</p>
      )}

      {rows.length > 0 && (
        <p className="mt-3 text-xs text-muted-foreground">
          {meta.truncated && meta.total != null && meta.returned != null
            ? `共发现 ${meta.total} 条，当前展示前 ${meta.returned} 条（按相关性截断，均可在有效期内导入）`
            : `当前展示 ${rows.length} 条`}
        </p>
      )}

      {rows.length > 0 && (
        <ul className="mt-2 space-y-3">
          {rows.map((r, i) => {
            const key = reportKey(r, i);
            const st = importMap[key];
            const ak = archivedKey(r.source_provider, r.external_id);
            const existing = ak ? archived.get(ak) : undefined;
            const canImport = Boolean(r.external_id);
            return (
              <li
                key={key}
                className="rounded-xl border border-border/50 bg-muted/15 px-3 py-3"
              >
                <div className="flex min-w-0 flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium leading-snug text-foreground">
                      {r.title || "（无标题）"}
                    </p>
                    <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-muted-foreground">
                      {r.institution && <span>{r.institution}</span>}
                      {r.publish_date && <span>{r.publish_date}</span>}
                      {(r.company_name || r.company_code) && (
                        <span>
                          {r.company_name || ""}
                          {r.company_code ? ` (${r.company_code})` : ""}
                        </span>
                      )}
                      {r.report_scope && <span>scope: {r.report_scope}</span>}
                      {typeof r.relevance_score === "number" && (
                        <span>相关度 {r.relevance_score}</span>
                      )}
                    </div>
                    {r.matched_keywords && r.matched_keywords.length > 0 && (
                      <div className="mt-1.5 flex flex-wrap gap-1">
                        {r.matched_keywords.map((k) => (
                          <span
                            key={k}
                            className="rounded-full border border-primary/30 bg-primary/10 px-1.5 py-0.5 text-[10px] text-primary"
                          >
                            {k}
                          </span>
                        ))}
                      </div>
                    )}
                    {existing && !st?.success && (
                      <p className="mt-1.5 text-[11px] text-muted-foreground">
                        已归档
                        <Link
                          to={`/my-reports?report=${existing.id}`}
                          className="ml-1 text-primary hover:underline"
                        >
                          查看已归档研报
                        </Link>
                      </p>
                    )}
                    {st?.error && (
                      <p className="mt-1.5 text-[11px] text-amber-600 dark:text-amber-400">{st.error}</p>
                    )}
                    {st?.success && (
                      <p className="mt-1.5 text-[11px] text-emerald-600 dark:text-emerald-400">
                        {st.success.deduped ? "已存在，已补充板块关联" : "已保存到我的研报"}
                        <Link
                          to={`/my-reports?report=${st.success.id}`}
                          className="ml-1 inline-flex items-center gap-0.5 text-primary hover:underline"
                        >
                          查看已归档研报 <ExternalLink className="h-3 w-3" />
                        </Link>
                      </p>
                    )}
                  </div>
                  <div className="flex shrink-0 gap-2">
                    {r.pdf_url && (
                      <a
                        href={r.pdf_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex h-8 items-center gap-1 rounded-lg border border-border/60 px-2 text-xs text-muted-foreground hover:text-foreground"
                        title="打开 PDF 链接"
                      >
                        <ExternalLink className="h-3.5 w-3.5" />
                        PDF
                      </a>
                    )}
                    <button
                      type="button"
                      disabled={!canImport || st?.loading}
                      onClick={() => onImport(r)}
                      className={cn(
                        "inline-flex h-8 items-center gap-1 rounded-lg border border-primary/40 bg-primary/10 px-2.5 text-xs font-medium text-primary",
                        "hover:bg-primary/20 disabled:cursor-not-allowed disabled:opacity-50",
                      )}
                      title={canImport ? "保存到我的研报" : "缺少 external_id，无法导入"}
                    >
                      {st?.loading
                        ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        : <Download className="h-3.5 w-3.5" />}
                      保存到我的研报
                    </button>
                  </div>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </GlassCard>
  );
}
