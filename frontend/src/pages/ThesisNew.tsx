import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { ArrowLeft, Save, Loader2, Plus, X } from "lucide-react";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import { api, ApiError } from "@/lib/api";

const SUBJECT_TYPES = [
  { value: "stock", label: "个股" },
  { value: "sector", label: "板块" },
  { value: "theme", label: "主题" },
];

const inputCls = "mt-0.5 w-full rounded border border-border/50 bg-background px-2 py-1.5 text-sm outline-none focus:border-primary/50";
const labelCls = "block text-xs text-muted-foreground";

interface ArrayEditorProps {
  label: string;
  placeholder?: string;
  items: string[];
  onChange: (next: string[]) => void;
}

function ArrayEditor({ label, placeholder, items, onChange }: ArrayEditorProps) {
  const [input, setInput] = useState("");
  const add = () => {
    const v = input.trim();
    if (!v) return;
    onChange([...items, v]);
    setInput("");
  };
  return (
    <div>
      <span className={labelCls}>{label}</span>
      <div className="mt-0.5 flex gap-1.5">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              add();
            }
          }}
          placeholder={placeholder ?? "回车添加一条"}
          className={inputCls}
        />
        <button
          type="button"
          onClick={add}
          className="shrink-0 rounded border border-border/50 px-2 text-muted-foreground hover:border-primary/40 hover:text-primary"
        >
          <Plus className="h-3.5 w-3.5" />
        </button>
      </div>
      {items.length > 0 && (
        <ul className="mt-1.5 space-y-1">
          {items.map((it, i) => (
            <li key={i} className="flex items-start gap-1.5 rounded bg-muted/30 px-2 py-1 text-xs">
              <span className="mt-0.5 font-mono text-muted-foreground/60">{i + 1}.</span>
              <span className="flex-1 whitespace-pre-wrap break-words">{it}</span>
              <button
                type="button"
                onClick={() => onChange(items.filter((_, idx) => idx !== i))}
                className="shrink-0 text-muted-foreground/60 hover:text-destructive"
              >
                <X className="h-3 w-3" />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function ThesisNew() {
  const nav = useNavigate();
  const [searchParams] = useSearchParams();
  const initSubjectType = (searchParams.get("subject_type") as "stock" | "sector" | "theme") || "stock";
  const initSubjectId = searchParams.get("subject_id") || "";
  const [form, setForm] = useState({
    subject_type: initSubjectType,
    subject_id: initSubjectId,
    title: "",
    summary: "",
    core_claims: [] as string[],
    catalysts: [] as string[],
    risks: [] as string[],
    invalidation_conditions: [] as string[],
    change_summary: "",
  });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const set = <K extends keyof typeof form>(k: K, v: (typeof form)[K]) =>
    setForm((p) => ({ ...p, [k]: v }));

  const submit = async () => {
    if (!form.subject_id.trim()) { setErr("请填写主体代码/标识"); return; }
    if (!form.title.trim()) { setErr("请填写标题"); return; }

    setBusy(true);
    setErr(null);
    try {
      const body = {
        subject_type: form.subject_type,
        subject_id: form.subject_id.trim(),
        title: form.title.trim(),
        summary: form.summary.trim(),
        core_claims: form.core_claims,
        catalysts: form.catalysts,
        risks: form.risks,
        invalidation_conditions: form.invalidation_conditions,
        change_summary: form.change_summary.trim() || "创建投资逻辑",
      };
      const r = await api.thesisCreate(body);
      nav(`/thesis/${r.thesis.id}`);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "保存失败");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <Link to="/thesis" className="mb-3 inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
        <ArrowLeft className="h-4 w-4" /> 投资逻辑
      </Link>

      <PageHeader title="新建投资逻辑" subtitle="结构化记录你的核心论点、催化剂与失效条件；关联证据后形成可追溯的版本化账本。" />

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
              placeholder="如 600519 / humanoid"
              className={inputCls}
            />
          </label>
          <label className={`${labelCls} sm:col-span-2`}>
            <p className="text-xs text-muted-foreground/60 -mt-0.5 mb-1">
              市场由股票代码自动识别；新建逻辑初始状态为 active。
            </p>
          </label>
          <label className={`${labelCls} sm:col-span-2`}>
            标题 <span className="text-destructive">*</span>
            <input
              value={form.title}
              onChange={(e) => set("title", e.target.value)}
              placeholder="如：贵茅2024基本面拐点已确立"
              className={inputCls}
            />
          </label>
          <label className={`${labelCls} sm:col-span-2`}>
            摘要
            <textarea
              value={form.summary}
              onChange={(e) => set("summary", e.target.value)}
              rows={3}
              placeholder="一两段话概括这条逻辑的核心论点。"
              className={`${inputCls} resize-y`}
            />
          </label>

          <div className="sm:col-span-2">
            <ArrayEditor
              label="核心论点（core_claims）"
              placeholder="回车添加一条核心论点"
              items={form.core_claims}
              onChange={(v) => set("core_claims", v)}
            />
          </div>
          <div className="sm:col-span-2">
            <ArrayEditor
              label="催化剂（catalysts）"
              placeholder="回车添加一条催化剂"
              items={form.catalysts}
              onChange={(v) => set("catalysts", v)}
            />
          </div>
          <div className="sm:col-span-2">
            <ArrayEditor
              label="风险（risks）"
              placeholder="回车添加一条风险"
              items={form.risks}
              onChange={(v) => set("risks", v)}
            />
          </div>
          <div className="sm:col-span-2">
            <ArrayEditor
              label="失效条件（invalidation_conditions）"
              placeholder="回车添加一条失效条件，便于后续客观证伪"
              items={form.invalidation_conditions}
              onChange={(v) => set("invalidation_conditions", v)}
            />
          </div>

          <label className={`${labelCls} sm:col-span-2`}>
            变更说明（change_summary）
            <input
              value={form.change_summary}
              onChange={(e) => set("change_summary", e.target.value)}
              placeholder="如：首次创建"
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
            to="/thesis"
            className="inline-flex items-center gap-1 rounded-lg border border-border/50 px-3 py-1.5 text-sm text-muted-foreground hover:border-primary/40"
          >
            取消
          </Link>
        </div>
      </GlassCard>
    </div>
  );
}
