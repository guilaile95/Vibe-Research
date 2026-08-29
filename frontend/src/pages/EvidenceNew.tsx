import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { ArrowLeft, Save, Loader2 } from "lucide-react";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import { api, ApiError } from "@/lib/api";

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
  { value: "fact", label: "事实（可直接核验的客观信息）" },
  { value: "inference", label: "推断（基于事实的演绎/假设）" },
  { value: "unknown", label: "未知 / 不确定" },
];

const CONFIDENCES = [
  { value: "high", label: "高（多源交叉验证）" },
  { value: "medium", label: "中（单一可信来源）" },
  { value: "low", label: "低（传闻 / 推测）" },
];

const inputCls = "mt-0.5 w-full rounded border border-border/50 bg-background px-2 py-1.5 text-sm outline-none focus:border-primary/50";
const labelCls = "block text-xs text-muted-foreground";

const nowLocal = () => {
  // 本地时间 ISO 字符串（带时区），适合 <input type="datetime-local"> 的格式
  const d = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
};

export function EvidenceNew() {
  const nav = useNavigate();
  const [searchParams] = useSearchParams();
  const querySubjectType = searchParams.get("subject_type");
  const querySubjectId = searchParams.get("subject_id") ?? "";
  const queryReturnTo = searchParams.get("return_to") ?? "";
  const initialSubjectType = querySubjectType === "stock" || querySubjectType === "sector" || querySubjectType === "theme"
    ? querySubjectType
    : "stock";
  const initialSubjectId = initialSubjectType === "stock" && /^\d{6}$/.test(querySubjectId) ? querySubjectId : "";
  const returnTo = queryReturnTo === `/candidates/${initialSubjectId}` ? queryReturnTo : "";
  const [form, setForm] = useState(() => ({
    subject_type: initialSubjectType as "stock" | "sector" | "theme",
    subject_id: initialSubjectId,
    evidence_type: "news" as "news" | "announcement" | "report" | "research_note" | "financial_filing" | "other",
    claim: "",
    source_title: "",
    source_url: "",
    source_date: "",
    accessed_at: nowLocal(),
    classification: "fact" as "fact" | "inference" | "unknown",
    confidence: "medium" as "high" | "medium" | "low",
  }));
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const set = <K extends keyof typeof form>(k: K, v: (typeof form)[K]) =>
    setForm((p) => ({ ...p, [k]: v }));

  const submit = async () => {
    if (!form.subject_id.trim()) { setErr("请填写主体代码/标识"); return; }
    if (!form.claim.trim()) { setErr("请填写证据论断（claim）"); return; }
    if (!form.source_title.trim()) { setErr("请填写来源标题"); return; }
    if (!form.accessed_at) { setErr("请填写查阅时间"); return; }

    setBusy(true);
    setErr(null);
    try {
      const body: import("@/lib/api").EvidenceCreateInput = {
        subject_type: form.subject_type,
        subject_id: form.subject_id.trim(),
        evidence_type: form.evidence_type,
        claim: form.claim.trim(),
        source_title: form.source_title.trim(),
        source_url: form.source_url.trim() || null,
        source_date: form.source_date || null,
        accessed_at: new Date(form.accessed_at).toISOString(),
        classification: form.classification,
        confidence: form.confidence,
      };
      const r = await api.evidenceCreate(body);
      nav(returnTo || `/evidence/${r.id}`);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "保存失败");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <Link to={returnTo || "/evidence"} className="mb-3 inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
        <ArrowLeft className="h-4 w-4" /> {returnTo ? "Candidate Workspace" : "证据库"}
      </Link>

      <PageHeader title="新建证据" subtitle="记录一条可追溯到来源的客观信息或推断，便于后续关联到投资逻辑。" />

      {err && (
        <div className="mb-4 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
          {err}
        </div>
      )}

      <GlassCard>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <label className={labelCls}>
            主体类型 <span className="text-destructive">*</span>
            <select
              value={form.subject_type}
              onChange={(e) => set("subject_type", e.target.value as any)}
              className={inputCls}
            >
              {SUBJECT_TYPES.map((t) => (
                <option key={t.value} value={t.value}>{t.label}</option>
              ))}
            </select>
          </label>
          <label className={labelCls}>
            主体代码/标识 <span className="text-destructive">*</span>
            <input
              value={form.subject_id}
              onChange={(e) => set("subject_id", e.target.value)}
              placeholder="如 600519 / humanoid / AI算力"
              className={inputCls}
            />
          </label>
          <label className={labelCls}>
            证据类型 <span className="text-destructive">*</span>
            <select
              value={form.evidence_type}
              onChange={(e) => set("evidence_type", e.target.value as any)}
              className={inputCls}
            >
              {EVIDENCE_TYPES.map((t) => (
                <option key={t.value} value={t.value}>{t.label}</option>
              ))}
            </select>
          </label>
          <label className={labelCls}>
            分类 <span className="text-destructive">*</span>
            <select
              value={form.classification}
              onChange={(e) => set("classification", e.target.value as any)}
              className={inputCls}
            >
              {CLASSIFICATIONS.map((t) => (
                <option key={t.value} value={t.value}>{t.label}</option>
              ))}
            </select>
          </label>
          <label className={`${labelCls} sm:col-span-2`}>
            证据论断（claim） <span className="text-destructive">*</span>
            <textarea
              value={form.claim}
              onChange={(e) => set("claim", e.target.value)}
              rows={3}
              placeholder="一句话陈述这条证据说了什么。例如：公司2024Q3营收同比+25%，超出市场一致预期+18%。"
              className={`${inputCls} resize-y`}
            />
          </label>
          <label className={`${labelCls} sm:col-span-2`}>
            来源标题 <span className="text-destructive">*</span>
            <input
              value={form.source_title}
              onChange={(e) => set("source_title", e.target.value)}
              placeholder="如：《XX公司2024年三季报点评》"
              className={inputCls}
            />
          </label>
          <label className={labelCls}>
            来源 URL
            <input
              value={form.source_url}
              onChange={(e) => set("source_url", e.target.value)}
              placeholder="https://..."
              className={inputCls}
            />
          </label>
          <label className={labelCls}>
            来源日期
            <input
              type="date"
              value={form.source_date}
              onChange={(e) => set("source_date", e.target.value)}
              className={inputCls}
            />
          </label>
          <label className={labelCls}>
            置信度 <span className="text-destructive">*</span>
            <select
              value={form.confidence}
              onChange={(e) => set("confidence", e.target.value as any)}
              className={inputCls}
            >
              {CONFIDENCES.map((t) => (
                <option key={t.value} value={t.value}>{t.label}</option>
              ))}
            </select>
          </label>
          <label className={labelCls}>
            查阅时间 <span className="text-destructive">*</span>
            <input
              type="datetime-local"
              value={form.accessed_at}
              onChange={(e) => set("accessed_at", e.target.value)}
              className={inputCls}
            />
          </label>
        </div>

        <div className="mt-4 flex items-center gap-2">
          <button
            onClick={submit}
            disabled={busy}
            className="inline-flex items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-60"
          >
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
            {busy ? "保存中…" : "保存"}
          </button>
          <Link
            to={returnTo || "/evidence"}
            className="inline-flex items-center gap-1 rounded-lg border border-border/50 px-3 py-1.5 text-sm text-muted-foreground hover:border-primary/40"
          >
            取消
          </Link>
        </div>
      </GlassCard>
    </div>
  );
}
