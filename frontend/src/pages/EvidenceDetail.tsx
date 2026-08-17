import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, Pencil, Save, X, Trash2, Loader2, ExternalLink } from "lucide-react";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import { api, ApiError, type EvidenceRecord, type EvidenceTemporalAuthority } from "@/lib/api";
import { cn } from "@/lib/utils";

const SUBJECT_TYPES = [
  { value: "stock", label: "个股" },
  { value: "sector", label: "板块" },
  { value: "theme", label: "主题" },
];

const EVIDENCE_TYPES = [
  { value: "news", label: "新闻" },
  { value: "announcement", label: "公告" },
  { value: "report", label: "研报" },
  { value: "research_note", label: "研究笔记" },
  { value: "financial_filing", label: "财报" },
  { value: "other", label: "其他" },
];

const CLASSIFICATIONS = [
  { value: "fact", label: "事实" },
  { value: "inference", label: "推断" },
  { value: "unknown", label: "未知" },
];

const CONFIDENCES = [
  { value: "high", label: "高" },
  { value: "medium", label: "中" },
  { value: "low", label: "低" },
];

const CLASSIFICATION_COLOR: Record<string, string> = {
  fact: "bg-success/15 text-success",
  inference: "bg-warning/15 text-warning",
  unknown: "bg-muted/50 text-muted-foreground",
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

const fmtDateOnly = (s: string | null) => {
  if (!s) return "—";
  try {
    // source_date is YYYY-MM-DD, display as-is without timezone conversion
    return s;
  } catch {
    return s;
  }
};

const toDateInput = (s: string | null) => {
  if (!s) return "";
  // source_date is already YYYY-MM-DD, use as-is
  return s;
};

const toDateTimeLocal = (s: string | null) => {
  if (!s) return "";
  try {
    const d = new Date(s);
    const pad = (n: number) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
  } catch {
    return "";
  }
};

const inputCls = "mt-0.5 w-full rounded border border-border/50 bg-background px-2 py-1.5 text-sm outline-none focus:border-primary/50";
const labelCls = "block text-xs text-muted-foreground";

const toCanonicalUtc = (value: string) => {
  if (!value) return null;
  const iso = new Date(value).toISOString();
  return iso.replace(/\.\d{3}Z$/, ".000000Z");
};

const temporalStateLabel: Record<string, string> = {
  PROVEN: "已证明",
  UNPROVEN: "未证明",
  ERROR: "错误（已拒绝）",
};

const temporalStateColor: Record<string, string> = {
  PROVEN: "bg-success/15 text-success",
  UNPROVEN: "bg-warning/15 text-warning",
  ERROR: "bg-danger/15 text-danger",
};

const temporalBasisLabel: Record<string, string> = {
  SOURCE_PUBLISHED_AT: "来源发布时间",
  EVENT_OCCURRED_AT: "事件发生时间",
  NONE: "无权威时间",
};

export function EvidenceDetail() {
  const { id } = useParams<{ id: string }>();
  const [record, setRecord] = useState<EvidenceRecord | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState<Partial<EvidenceRecord>>({});
  const [busy, setBusy] = useState(false);
  const [editErr, setEditErr] = useState<string | null>(null);
  const [temporal, setTemporal] = useState<EvidenceTemporalAuthority | null>(null);
  const [temporalLoading, setTemporalLoading] = useState(false);
  const [temporalErr, setTemporalErr] = useState<string | null>(null);
  const [temporalBusy, setTemporalBusy] = useState(false);
  const [temporalForm, setTemporalForm] = useState({
    source_identity: "",
    source_published_at: "",
    event_identity: "",
    event_occurred_at: "",
    observed_at: "",
    created_at: "",
    ingested_at: "",
  });

  const runIdRef = useRef(0);

  const load = useCallback(async () => {
    if (!id) return;
    const rid = ++runIdRef.current;
    setLoading(true);
    setErr(null);
    try {
      const r = await api.evidenceGet(id);
      if (rid !== runIdRef.current) return;
      setRecord(r);
      setTemporalLoading(true);
      try {
        const t = await api.evidenceTemporalAuthority(id);
        if (rid === runIdRef.current) setTemporal(t);
      } catch (e) {
        if (rid === runIdRef.current) setTemporalErr(e instanceof ApiError ? e.message : "加载时间权威失败");
      } finally {
        if (rid === runIdRef.current) setTemporalLoading(false);
      }
    } catch (e) {
      if (rid !== runIdRef.current) return;
      setErr(e instanceof ApiError ? e.message : "加载证据失败");
    } finally {
      if (rid === runIdRef.current) setLoading(false);
    }
  }, [id]);

  const submitTemporalIntake = async () => {
    if (!id) return;
    setTemporalBusy(true);
    setTemporalErr(null);
    try {
      const body = {
        source_identity: temporalForm.source_identity.trim() || null,
        source_published_at: toCanonicalUtc(temporalForm.source_published_at),
        event_identity: temporalForm.event_identity.trim() || null,
        event_occurred_at: toCanonicalUtc(temporalForm.event_occurred_at),
        observed_at: toCanonicalUtc(temporalForm.observed_at),
        created_at: toCanonicalUtc(temporalForm.created_at),
        ingested_at: toCanonicalUtc(temporalForm.ingested_at),
      };
      const result = await api.evidenceTemporalIntake(id, body);
      setTemporal(result);
      setTemporalForm({
        source_identity: "", source_published_at: "", event_identity: "", event_occurred_at: "",
        observed_at: "", created_at: "", ingested_at: "",
      });
    } catch (e) {
      setTemporalErr(e instanceof ApiError ? e.message : "保存时间元数据失败");
    } finally {
      setTemporalBusy(false);
    }
  };

  useEffect(() => {
    void load();
  }, [load]);

  const startEdit = () => {
    if (!record) return;
    setForm({
      subject_type: record.subject_type,
      subject_id: record.subject_id,
      evidence_type: record.evidence_type,
      claim: record.claim,
      source_title: record.source_title,
      source_url: record.source_url ?? "",
      source_date: toDateInput(record.source_date),
      accessed_at: toDateTimeLocal(record.accessed_at),
      classification: record.classification,
      confidence: record.confidence,
    });
    setEditErr(null);
    setEditing(true);
  };

  const set = <K extends keyof EvidenceRecord>(k: K, v: EvidenceRecord[K]) =>
    setForm((p) => ({ ...p, [k]: v }));

  const save = async () => {
    if (!id || !record) return;
    if (!form.claim?.trim()) { setEditErr("请填写证据论断"); return; }
    if (!form.source_title?.trim()) { setEditErr("请填写来源标题"); return; }

    setBusy(true);
    setEditErr(null);
    try {
      const body: import("@/lib/api").EvidenceUpdateInput = {
        evidence_type: form.evidence_type!,
        claim: form.claim.trim(),
        source_title: form.source_title.trim(),
        source_url: form.source_url?.trim() || null,
        source_date: form.source_date as string || null,
        accessed_at: form.accessed_at ? new Date(form.accessed_at).toISOString() : record.accessed_at,
        classification: form.classification!,
        confidence: form.confidence!,
      };
      const r = await api.evidenceUpdate(id, body);
      setRecord(r);
      setEditing(false);
    } catch (e) {
      setEditErr(e instanceof ApiError ? e.message : "保存失败");
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    if (!id || !record) return;
    if (!confirm(`删除证据「${record.claim.slice(0, 40)}${record.claim.length > 40 ? "…" : ""}」？\n\n证据将从当前列表移除，但历史版本中的证据快照仍会保留。`)) return;
    setBusy(true);
    setEditErr(null);
    try {
      await api.evidenceDelete(id);
      // 跳回列表
      window.location.href = "/evidence";
    } catch (e) {
      setEditErr(e instanceof ApiError ? e.message : "删除失败");
      setBusy(false);
    }
  };

  if (loading && !record) {
    return (
      <div>
        <Link to="/evidence" className="mb-3 inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
          <ArrowLeft className="h-4 w-4" /> 证据库
        </Link>
        <div className="flex items-center justify-center py-20 text-sm text-muted-foreground">
          <Loader2 className="mr-2 h-4 w-4 animate-spin" /> 加载中…
        </div>
      </div>
    );
  }

  if (err && !record) {
    return (
      <div>
        <Link to="/evidence" className="mb-3 inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
          <ArrowLeft className="h-4 w-4" /> 证据库
        </Link>
        <div className="mb-4 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
          {err}
        </div>
      </div>
    );
  }

  if (!record) return null;

  return (
    <div>
      <Link to="/evidence" className="mb-3 inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
        <ArrowLeft className="h-4 w-4" /> 证据库
      </Link>

      <PageHeader
        title={record.claim}
        subtitle={`主体 ${record.subject_type}/${record.subject_id} · 创建于 ${fmtDate(record.created_at)}`}
        actions={
          !editing ? (
            <div className="flex items-center gap-2">
              <button
                onClick={startEdit}
                className="inline-flex items-center gap-1.5 rounded-lg border border-border/50 px-3 py-1.5 text-sm text-muted-foreground hover:border-primary/40 hover:text-primary"
              >
                <Pencil className="h-4 w-4" /> 编辑
              </button>
              <button
                onClick={remove}
                disabled={busy}
                className="inline-flex items-center gap-1.5 rounded-lg border border-destructive/30 px-3 py-1.5 text-sm text-muted-foreground hover:border-destructive hover:text-destructive disabled:opacity-50"
              >
                <Trash2 className="h-4 w-4" /> 删除
              </button>
            </div>
          ) : null
        }
      />

      {err && (
        <div className="mb-4 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
          {err}
        </div>
      )}

      <GlassCard>
        {!editing ? (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <div>
                <p className={labelCls}>主体</p>
                <p className="mt-0.5 font-mono text-sm">{record.subject_type}/{record.subject_id}</p>
              </div>
              <div>
                <p className={labelCls}>证据类型</p>
                <p className="mt-0.5 text-sm">{EVIDENCE_TYPES.find((t) => t.value === record.evidence_type)?.label ?? record.evidence_type}</p>
              </div>
              <div>
                <p className={labelCls}>分类</p>
                <span className={cn("mt-0.5 inline-block rounded px-1.5 py-0.5 text-[11px]", CLASSIFICATION_COLOR[record.classification] ?? "bg-muted/50 text-muted-foreground")}>
                  {CLASSIFICATIONS.find((t) => t.value === record.classification)?.label ?? record.classification}
                </span>
              </div>
              <div>
                <p className={labelCls}>置信度</p>
                <span className={cn("mt-0.5 inline-block rounded px-1.5 py-0.5 text-[11px]", CONFIDENCE_COLOR[record.confidence] ?? "bg-muted/50 text-muted-foreground")}>
                  {CONFIDENCES.find((t) => t.value === record.confidence)?.label ?? record.confidence}
                </span>
              </div>
            </div>

            <div>
              <p className={labelCls}>证据论断</p>
              <p className="mt-0.5 whitespace-pre-wrap text-sm leading-relaxed">{record.claim}</p>
            </div>

            <div>
              <p className={labelCls}>来源</p>
              <div className="mt-0.5 text-sm">
                <p>{record.source_title}</p>
                {record.source_url && (
                  <a
                    href={record.source_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="mt-1 inline-flex items-center gap-1 text-xs text-primary hover:underline"
                  >
                    <ExternalLink className="h-3 w-3" /> {record.source_url}
                  </a>
                )}
                <p className="mt-1 text-[11px] text-muted-foreground/70">
                  来源日期：{fmtDateOnly(record.source_date)} · 查阅于：{fmtDate(record.accessed_at)}
                </p>
              </div>
            </div>

            <div className="border-t border-border/30 pt-4">
              <div className="flex items-center justify-between gap-2">
                <div>
                  <p className="text-sm font-medium">Temporal authority</p>
                  <p className="mt-0.5 text-[11px] text-muted-foreground/70">Observed time is not effective time.</p>
                </div>
                {temporalLoading ? (
                  <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
                ) : temporal ? (
                  <span className={cn("rounded px-2 py-1 text-[11px]", temporalStateColor[temporal.temporal_state] ?? "bg-muted/50 text-muted-foreground")}>
                    {temporalStateLabel[temporal.temporal_state] ?? temporal.temporal_state}
                  </span>
                ) : null}
              </div>
              {temporalErr && <p className="mt-2 text-xs text-destructive">{temporalErr}</p>}
              {temporal && (
                <div className="mt-3 grid grid-cols-1 gap-2 text-xs sm:grid-cols-3">
                  <div><span className="text-muted-foreground">Basis：</span>{temporalBasisLabel[temporal.temporal_basis] ?? temporal.temporal_basis}</div>
                  <div><span className="text-muted-foreground">Effective at：</span><span className="font-mono">{temporal.effective_at ?? "—"}</span></div>
                  <div><span className="text-muted-foreground">EC1：</span>{temporal.ec1_evaluation}</div>
                  <div className="sm:col-span-3"><span className="text-muted-foreground">Reason：</span>{temporal.reason_codes.join(" · ") || "—"}</div>
                </div>
              )}
              <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
                <label className={labelCls}>Source identity<input value={temporalForm.source_identity} onChange={(e) => setTemporalForm((p) => ({ ...p, source_identity: e.target.value }))} className={inputCls} placeholder="真实来源标识" /></label>
                <label className={labelCls}>Source published at<input type="datetime-local" value={temporalForm.source_published_at} onChange={(e) => setTemporalForm((p) => ({ ...p, source_published_at: e.target.value }))} className={inputCls} /></label>
                <label className={labelCls}>Event identity<input value={temporalForm.event_identity} onChange={(e) => setTemporalForm((p) => ({ ...p, event_identity: e.target.value }))} className={inputCls} placeholder="真实事件标识" /></label>
                <label className={labelCls}>Event occurred at<input type="datetime-local" value={temporalForm.event_occurred_at} onChange={(e) => setTemporalForm((p) => ({ ...p, event_occurred_at: e.target.value }))} className={inputCls} /></label>
                <label className={labelCls}>Observed at<input type="datetime-local" value={temporalForm.observed_at} onChange={(e) => setTemporalForm((p) => ({ ...p, observed_at: e.target.value }))} className={inputCls} /></label>
                <label className={labelCls}>Created at<input type="datetime-local" value={temporalForm.created_at} onChange={(e) => setTemporalForm((p) => ({ ...p, created_at: e.target.value }))} className={inputCls} /></label>
                <label className={labelCls}>Ingested at<input type="datetime-local" value={temporalForm.ingested_at} onChange={(e) => setTemporalForm((p) => ({ ...p, ingested_at: e.target.value }))} className={inputCls} /></label>
              </div>
              <button onClick={() => void submitTemporalIntake()} disabled={temporalBusy} className="mt-3 inline-flex items-center gap-1.5 rounded-lg bg-primary/15 px-3 py-1.5 text-xs text-primary hover:bg-primary/25 disabled:opacity-50">
                {temporalBusy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null} 保存 factual temporal metadata
              </button>
            </div>

            <div className="border-t border-border/30 pt-3 text-[11px] text-muted-foreground/60">
              ID: <span className="font-mono">{record.id}</span> · 创建 {fmtDate(record.created_at)} · 更新 {fmtDate(record.updated_at)}
              {record.deleted ? <span className="ml-2 text-warning">已删除</span> : null}
            </div>
          </div>
        ) : (
          <div>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <label className={labelCls}>
                主体类型 <span className="text-xs text-muted-foreground/70">(只读)</span>
                <select
                  value={form.subject_type ?? "stock"}
                  disabled
                  className={`${inputCls} opacity-60 cursor-not-allowed`}
                >
                  {SUBJECT_TYPES.map((t) => (
                    <option key={t.value} value={t.value}>{t.label}</option>
                  ))}
                </select>
              </label>
              <label className={labelCls}>
                主体代码/标识 <span className="text-xs text-muted-foreground/70">(只读)</span>
                <input
                  value={form.subject_id ?? ""}
                  disabled
                  className={`${inputCls} opacity-60 cursor-not-allowed`}
                />
              </label>
              <label className={labelCls}>
                证据类型
                <select
                  value={form.evidence_type ?? "news"}
                  onChange={(e) => set("evidence_type", e.target.value as EvidenceRecord["evidence_type"])}
                  className={inputCls}
                >
                  {EVIDENCE_TYPES.map((t) => (
                    <option key={t.value} value={t.value}>{t.label}</option>
                  ))}
                </select>
              </label>
              <label className={labelCls}>
                分类
                <select
                  value={form.classification ?? "fact"}
                  onChange={(e) => set("classification", e.target.value as EvidenceRecord["classification"])}
                  className={inputCls}
                >
                  {CLASSIFICATIONS.map((t) => (
                    <option key={t.value} value={t.value}>{t.label}</option>
                  ))}
                </select>
              </label>
              <label className={labelCls}>
                置信度
                <select
                  value={form.confidence ?? "medium"}
                  onChange={(e) => set("confidence", e.target.value as EvidenceRecord["confidence"])}
                  className={inputCls}
                >
                  {CONFIDENCES.map((t) => (
                    <option key={t.value} value={t.value}>{t.label}</option>
                  ))}
                </select>
              </label>
              <label className={`${labelCls} sm:col-span-2`}>
                证据论断
                <textarea
                  value={form.claim ?? ""}
                  onChange={(e) => set("claim", e.target.value)}
                  rows={4}
                  className={`${inputCls} resize-y`}
                />
              </label>
              <label className={`${labelCls} sm:col-span-2`}>
                来源标题
                <input
                  value={form.source_title ?? ""}
                  onChange={(e) => set("source_title", e.target.value)}
                  className={inputCls}
                />
              </label>
              <label className={labelCls}>
                来源 URL
                <input
                  value={form.source_url ?? ""}
                  onChange={(e) => set("source_url", e.target.value)}
                  placeholder="https://..."
                  className={inputCls}
                />
              </label>
              <label className={labelCls}>
                来源日期
                <input
                  type="date"
                  value={(form.source_date as string) ?? ""}
                  onChange={(e) => set("source_date", e.target.value as any)}
                  className={inputCls}
                />
              </label>
              <label className={labelCls}>
                查阅时间
                <input
                  type="datetime-local"
                  value={(form.accessed_at as string) ?? ""}
                  onChange={(e) => set("accessed_at", e.target.value as any)}
                  className={inputCls}
                />
              </label>
            </div>

            {editErr && (
              <p className="mt-3 text-sm text-destructive">{editErr}</p>
            )}

            <div className="mt-4 flex items-center gap-2">
              <button
                onClick={save}
                disabled={busy}
                className="inline-flex items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-60"
              >
                {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                {busy ? "保存中…" : "保存"}
              </button>
              <button
                onClick={() => { setEditing(false); setEditErr(null); }}
                disabled={busy}
                className="inline-flex items-center gap-1 rounded-lg border border-border/50 px-3 py-1.5 text-sm text-muted-foreground hover:border-primary/40 disabled:opacity-50"
              >
                <X className="h-4 w-4" /> 取消
              </button>
            </div>
          </div>
        )}
      </GlassCard>
    </div>
  );
}
