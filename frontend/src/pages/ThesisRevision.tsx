import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, Loader2, ExternalLink } from "lucide-react";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import { api, ApiError, type ThesisRevision as ThesisRevisionData } from "@/lib/api";
import { cn } from "@/lib/utils";

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

const STANCE_LABELS: Record<string, string> = {
  support: "支撑",
  oppose: "反对",
  neutral: "中性",
};

const STANCE_COLOR: Record<string, string> = {
  support: "bg-success/15 text-success",
  oppose: "bg-danger/15 text-danger",
  neutral: "bg-muted/50 text-muted-foreground",
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

const labelCls = "block text-xs text-muted-foreground";

export function ThesisRevision() {
  const { id, rev } = useParams<{ id: string; rev: string }>();
  const revNum = rev ? Number(rev) : NaN;
  const [data, setData] = useState<ThesisRevisionData | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const runIdRef = useRef(0);

  const load = useCallback(async () => {
    if (!id || !Number.isFinite(revNum)) return;
    const rid = ++runIdRef.current;
    setLoading(true);
    setErr(null);
    try {
      const r = await api.thesisRevision(id, revNum);
      if (rid !== runIdRef.current) return;
      setData(r);
    } catch (e) {
      if (rid !== runIdRef.current) return;
      setErr(e instanceof ApiError ? e.message : "加载版本快照失败");
    } finally {
      if (rid === runIdRef.current) setLoading(false);
    }
  }, [id, revNum]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div>
      <Link
        to={`/thesis/${id}`}
        className="mb-3 inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="h-4 w-4" /> 返回详情
      </Link>

      <PageHeader
        title={data ? `版本 v${data.revision_number} 快照` : "版本快照"}
        subtitle={data ? `${data.change_summary || "（无变更说明）"} · ${fmtDate(data.created_at)}` : undefined}
      />

      {err && (
        <div className="mb-4 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
          {err}
        </div>
      )}

      {loading && !data ? (
        <GlassCard>
          <div className="flex items-center justify-center py-10 text-sm text-muted-foreground">
            <Loader2 className="mr-2 h-4 w-4 animate-spin" /> 加载中…
          </div>
        </GlassCard>
      ) : data ? (
        <div className="space-y-4">
          <GlassCard>
            <div className="mb-4 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
              <span className="rounded bg-secondary px-1.5 py-0.5 font-mono text-secondary-foreground">
                v{data.revision_number}
              </span>
              <span>创建于 {fmtDate(data.created_at)}</span>
              <span>·</span>
              <span className="italic">{data.change_summary || "（无变更说明）"}</span>
            </div>

            {(() => {
              const t = data.snapshot.thesis;
              return (
                <div className="space-y-4">
                  <div>
                    <h2 className="text-lg font-bold">{t.title}</h2>
                    <p className="mt-0.5 text-sm text-muted-foreground">
                      <span className="font-mono">{t.subject_type}/{t.subject_id}</span>
                      {t.market ? ` · ${t.market}` : ""}
                      {" · "}
                      <span className={cn("ml-1 rounded px-1.5 py-0.5 text-[10px]", STATUS_COLOR[t.status] ?? "bg-muted/50 text-muted-foreground")}>
                        {STATUS_LABELS[t.status] ?? t.status}
                      </span>
                    </p>
                  </div>

                  {t.summary && (
                    <div>
                      <p className={labelCls}>摘要</p>
                      <p className="mt-0.5 whitespace-pre-wrap text-sm leading-relaxed">{t.summary}</p>
                    </div>
                  )}

                  <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                    <div>
                      <p className={labelCls}>核心论点</p>
                      {t.core_claims.length === 0 ? (
                        <p className="mt-0.5 text-xs text-muted-foreground/60">（无）</p>
                      ) : (
                        <ul className="mt-0.5 space-y-1 text-sm">
                          {t.core_claims.map((c, i) => (
                            <li key={i} className="flex gap-1.5">
                              <span className="font-mono text-muted-foreground/60">{i + 1}.</span>
                              <span className="whitespace-pre-wrap break-words">{c}</span>
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>
                    <div>
                      <p className={labelCls}>催化剂</p>
                      {t.catalysts.length === 0 ? (
                        <p className="mt-0.5 text-xs text-muted-foreground/60">（无）</p>
                      ) : (
                        <ul className="mt-0.5 space-y-1 text-sm">
                          {t.catalysts.map((c, i) => (
                            <li key={i} className="flex gap-1.5">
                              <span className="font-mono text-muted-foreground/60">{i + 1}.</span>
                              <span className="whitespace-pre-wrap break-words">{c}</span>
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>
                    <div>
                      <p className={labelCls}>风险</p>
                      {t.risks.length === 0 ? (
                        <p className="mt-0.5 text-xs text-muted-foreground/60">（无）</p>
                      ) : (
                        <ul className="mt-0.5 space-y-1 text-sm">
                          {t.risks.map((c, i) => (
                            <li key={i} className="flex gap-1.5">
                              <span className="font-mono text-muted-foreground/60">{i + 1}.</span>
                              <span className="whitespace-pre-wrap break-words">{c}</span>
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>
                    <div>
                      <p className={labelCls}>失效条件</p>
                      {t.invalidation_conditions.length === 0 ? (
                        <p className="mt-0.5 text-xs text-muted-foreground/60">（无）</p>
                      ) : (
                        <ul className="mt-0.5 space-y-1 text-sm">
                          {t.invalidation_conditions.map((c, i) => (
                            <li key={i} className="flex gap-1.5">
                              <span className="font-mono text-muted-foreground/60">{i + 1}.</span>
                              <span className="whitespace-pre-wrap break-words">{c}</span>
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>
                  </div>
                </div>
              );
            })()}
          </GlassCard>

          <GlassCard>
            <h3 className="mb-3 text-sm font-semibold">
              关联证据（{data.snapshot.evidence_links.length}）
            </h3>
            {data.snapshot.evidence_links.length === 0 ? (
              <p className="py-4 text-center text-xs text-muted-foreground/60">
                此版本未关联任何证据
              </p>
            ) : (
              <div className="space-y-2">
                {data.snapshot.evidence_links.map((link) => (
                  <div key={link.evidence_id} className="rounded-lg border border-border/40 bg-background/40 p-3">
                    <div className="flex items-start gap-2">
                      <span className={cn("shrink-0 rounded px-1.5 py-0.5 text-[10px]", STANCE_COLOR[link.stance] ?? "bg-muted/50 text-muted-foreground")}>
                        {STANCE_LABELS[link.stance] ?? link.stance}
                      </span>
                      <div className="min-w-0 flex-1">
                        <p className="text-sm">{link.claim}</p>
                        <p className="mt-0.5 text-[11px] text-muted-foreground/70">
                          {link.source_title || "（无来源）"}
                          {link.source_url && (
                            <a href={link.source_url} target="_blank" rel="noopener noreferrer" className="ml-1 inline-flex items-center gap-0.5 text-primary hover:underline">
                              <ExternalLink className="h-3 w-3" />
                            </a>
                          )}
                          {" · "}{fmtDate(link.source_date)}
                        </p>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </GlassCard>
        </div>
      ) : null}
    </div>
  );
}
