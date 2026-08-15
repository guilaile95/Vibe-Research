import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import {
  ArrowLeft, Pencil, Save, X, Loader2, Lock, Plus, Link2, Unlink,
  RefreshCw, GitCompareArrows, History, ExternalLink, BookOpen,
} from "lucide-react";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import {
  api, ApiError,
  type ThesisAggregate, type ThesisRevisionListItem, type ThesisDiff,
  type EvidenceRecord, type EvidenceLink, type CampaignStrategy,
  type CampaignThesisBinding, type InvestmentThesis, type ThesisUpdateInput,
} from "@/lib/api";
import {
  STRATEGY_HORIZON_RANGES,
  canConfirmFormalThesis,
  defaultHorizonForStrategy,
} from "@/lib/campaignThesis";
import { cn } from "@/lib/utils";

const STATUSES = [
  { value: "active", label: "生效中" },
  { value: "weakened", label: "走弱" },
  { value: "invalidated", label: "已失效" },
];

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

const inputCls = "mt-0.5 w-full rounded border border-border/50 bg-background px-2 py-1.5 text-sm outline-none focus:border-primary/50 disabled:opacity-60";
const labelCls = "block text-xs text-muted-foreground";

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

interface ArrayEditorProps {
  label: string;
  placeholder?: string;
  items: string[];
  disabled?: boolean;
  onChange: (next: string[]) => void;
}

function ArrayEditor({ label, placeholder, items, disabled, onChange }: ArrayEditorProps) {
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
          disabled={disabled}
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
          disabled={disabled}
          className="shrink-0 rounded border border-border/50 px-2 text-muted-foreground hover:border-primary/40 hover:text-primary disabled:opacity-50"
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
                disabled={disabled}
                onClick={() => onChange(items.filter((_, idx) => idx !== i))}
                className="shrink-0 text-muted-foreground/60 hover:text-destructive disabled:opacity-50"
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

interface EditForm {
  title: string;
  summary: string;
  status: "active" | "weakened" | "invalidated";
  core_claims: string[];
  catalysts: string[];
  risks: string[];
  invalidation_conditions: string[];
  strategy: CampaignStrategy | "";
  horizon_min: string;
  horizon_max: string;
  free_notes: string;
  change_summary: string;
}

interface LinkForm {
  evidence_id: string;
  stance: "support" | "oppose" | "neutral";
  change_summary: string;
}

interface StanceForm {
  evidenceId: string;
  stance: "support" | "oppose" | "neutral";
  change_summary: string;
}

const renderValue = (v: unknown): string => {
  if (v === null || v === undefined) return "—";
  if (Array.isArray(v)) return v.length === 0 ? "[]" : v.map((x) => String(x)).join(", ");
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
};

const toEditForm = (
  thesis: InvestmentThesis,
  campaignStrategy: CampaignStrategy | null,
): EditForm => {
  const strategy = thesis.strategy ?? campaignStrategy ?? "";
  const fallback = strategy ? defaultHorizonForStrategy(strategy) : null;
  const horizon = thesis.expected_horizon ?? fallback;
  return {
    title: thesis.title,
    summary: thesis.summary,
    status: thesis.status === "archived" ? "invalidated" : thesis.status,
    core_claims: [...thesis.core_claims],
    catalysts: [...thesis.catalysts],
    risks: [...thesis.risks],
    invalidation_conditions: [...thesis.invalidation_conditions],
    strategy,
    horizon_min: horizon ? String(horizon.min) : "",
    horizon_max: horizon ? String(horizon.max) : "",
    free_notes: thesis.free_notes ?? "",
    change_summary: "",
  };
};

export function ThesisDetail() {
  const { id } = useParams<{ id: string }>();
  const [searchParams] = useSearchParams();
  const campaignId = searchParams.get("campaign_id") || "";
  const securityCode = searchParams.get("security_code") || "";
  const strategyParam = searchParams.get("strategy");
  const campaignStrategy = (["SHORT", "SWING", "MEDIUM"] as const).includes(
    strategyParam as CampaignStrategy,
  ) ? strategyParam as CampaignStrategy : null;
  const returnParam = searchParams.get("return_to");
  const returnTo = returnParam?.startsWith("/") && !returnParam.startsWith("//")
    ? returnParam
    : "/thesis";
  const campaignContext = Boolean(campaignId && securityCode && campaignStrategy);
  const setupError = searchParams.get("setup_error") === "1";
  const [aggregate, setAggregate] = useState<ThesisAggregate | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState<EditForm | null>(null);
  const [busy, setBusy] = useState(false);
  const [editErr, setEditErr] = useState<string | null>(null);
  const [conflict, setConflict] = useState<string | null>(null);
  const [binding, setBinding] = useState<CampaignThesisBinding | null>(null);
  const [lifecycleBusy, setLifecycleBusy] = useState(false);
  const [lifecycleErr, setLifecycleErr] = useState<string | null>(null);

  // 链接证据面板
  const [showLinkPanel, setShowLinkPanel] = useState(false);
  const [evidenceOptions, setEvidenceOptions] = useState<EvidenceRecord[]>([]);
  const [evidenceLoading, setEvidenceLoading] = useState(false);
  const [linkForm, setLinkForm] = useState<LinkForm>({
    evidence_id: "",
    stance: "support",
    change_summary: "",
  });
  const [linkErr, setLinkErr] = useState<string | null>(null);

  // 修改立场
  const [stanceEdit, setStanceEdit] = useState<StanceForm | null>(null);
  const [stanceErr, setStanceErr] = useState<string | null>(null);

  // 版本历史
  const [revisions, setRevisions] = useState<ThesisRevisionListItem[]>([]);
  const [revisionsLoading, setRevisionsLoading] = useState(false);
  const [activeTab, setActiveTab] = useState<"detail" | "history" | "diff">("detail");

  // Diff
  const [fromRev, setFromRev] = useState<number | "">("");
  const [toRev, setToRev] = useState<number | "">("");
  const [diff, setDiff] = useState<ThesisDiff | null>(null);
  const [diffLoading, setDiffLoading] = useState(false);
  const [diffErr, setDiffErr] = useState<string | null>(null);

  const runIdRef = useRef(0);

  const load = useCallback(async () => {
    if (!id) return;
    const rid = ++runIdRef.current;
    setLoading(true);
    setErr(null);
    setConflict(null);
    try {
      const r = await api.thesisGet(id);
      if (rid !== runIdRef.current) return;
      setAggregate(r);
    } catch (e) {
      if (rid !== runIdRef.current) return;
      setErr(e instanceof ApiError ? e.message : "加载投资逻辑失败");
    } finally {
      if (rid === runIdRef.current) setLoading(false);
    }
  }, [id]);

  const loadRevisions = useCallback(async () => {
    if (!id) return;
    setRevisionsLoading(true);
    try {
      const r = await api.thesisRevisions(id);
      setRevisions(r.items ?? []);
    } catch (e) {
      // 静默忽略，避免抢占主面板错误
    } finally {
      setRevisionsLoading(false);
    }
  }, [id]);

  const loadBinding = useCallback(async () => {
    if (!campaignContext) {
      setBinding(null);
      return;
    }
    try {
      setBinding(await api.getCampaignThesisBinding(campaignId));
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) {
        setBinding(null);
        return;
      }
      setLifecycleErr(e instanceof ApiError ? e.message : "Campaign Thesis 绑定状态读取失败");
    }
  }, [campaignContext, campaignId]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    void loadBinding();
  }, [loadBinding]);

  useEffect(() => {
    if (id && (activeTab === "history" || activeTab === "diff") && revisions.length === 0) {
      void loadRevisions();
    }
  }, [id, activeTab, revisions.length, loadRevisions]);

  const archived = aggregate?.thesis.status === "archived";
  const formalState = aggregate?.thesis.formal_state ?? null;
  const contentLocked = archived || formalState === "confirmed" || formalState === "frozen";

  // 处理 409 冲突：保留用户输入，不覆盖；显示提示并提供 reload 按钮
  const handleConflict = (e: unknown): boolean => {
    if (e instanceof ApiError && e.status === 409) {
      setConflict(e.message || "投资逻辑已发生变化，请重新加载后重试");
      return true;
    }
    return false;
  };

  // 编辑
  const startEdit = () => {
    if (!aggregate) return;
    setForm(toEditForm(aggregate.thesis, campaignStrategy));
    setEditErr(null);
    setConflict(null);
    setEditing(true);
  };

  const saveEdit = async () => {
    if (!id || !aggregate || !form) return;
    if (!form.title.trim()) { setEditErr("请填写标题"); return; }
    let formalFields: Pick<ThesisUpdateInput, "strategy" | "expected_horizon" | "free_notes"> = {};
    if (aggregate.thesis.formal_state === "draft") {
      if (!form.strategy) { setEditErr("请选择 Formal Thesis 策略"); return; }
      const min = Number(form.horizon_min);
      const max = Number(form.horizon_max);
      const [rangeMin, rangeMax] = STRATEGY_HORIZON_RANGES[form.strategy];
      if (!Number.isInteger(min) || !Number.isInteger(max) || min < rangeMin || max > rangeMax || max < min) {
        setEditErr(`${form.strategy} 的预期周期必须在 ${rangeMin}-${rangeMax} 个交易日内`);
        return;
      }
      formalFields = {
        strategy: form.strategy,
        expected_horizon: { unit: "TRADING_DAY", min, max, anchor: "FREEZE_AT" },
        free_notes: form.free_notes.trim() || null,
      };
    }
    setBusy(true);
    setEditErr(null);
    setConflict(null);
    try {
      const body: ThesisUpdateInput = {
        title: form.title.trim(),
        summary: form.summary.trim(),
        status: form.status,
        core_claims: form.core_claims,
        catalysts: form.catalysts,
        risks: form.risks,
        invalidation_conditions: form.invalidation_conditions,
        expected_revision: aggregate.thesis.current_revision,
        change_summary: form.change_summary.trim() || "更新投资逻辑",
        ...formalFields,
      };
      const r = await api.thesisUpdate(id, body);
      setAggregate(r);
      setEditing(false);
      // 失效版本历史
      setRevisions([]);
    } catch (e) {
      if (handleConflict(e)) return;
      setEditErr(e instanceof ApiError ? e.message : "保存失败");
    } finally {
      setBusy(false);
    }
  };

  const beginFormalization = async () => {
    if (!id || !aggregate || aggregate.thesis.formal_state !== null) return;
    setLifecycleBusy(true);
    setLifecycleErr(null);
    setConflict(null);
    try {
      const next = await api.thesisBeginFormalization(id);
      setAggregate(next);
      setForm(toEditForm(next.thesis, campaignStrategy));
      setEditing(true);
      setRevisions([]);
    } catch (e) {
      if (handleConflict(e)) return;
      setLifecycleErr(e instanceof ApiError ? e.message : "开始 Formal 化失败");
    } finally {
      setLifecycleBusy(false);
    }
  };

  const confirmFormalization = async () => {
    if (!id || !aggregate || !canConfirmFormalThesis(aggregate.thesis)) return;
    if (!window.confirm("确认后内容将锁定；下一步仍需你显式冻结。是否确认这份 Formal Thesis？")) return;
    setLifecycleBusy(true);
    setLifecycleErr(null);
    try {
      const next = await api.thesisConfirm(id);
      setAggregate(next);
      setEditing(false);
    } catch (e) {
      if (handleConflict(e)) return;
      setLifecycleErr(e instanceof ApiError ? e.message : "确认 Formal Thesis 失败");
    } finally {
      setLifecycleBusy(false);
    }
  };

  const freezeFormalization = async () => {
    if (!id || !aggregate || aggregate.thesis.formal_state !== "confirmed") return;
    if (!window.confirm("冻结会生成不可变的 Formal Original 版本。冻结后不可编辑，是否继续？")) return;
    setLifecycleBusy(true);
    setLifecycleErr(null);
    setConflict(null);
    try {
      await api.thesisFreeze(id, aggregate.thesis.current_revision);
      setAggregate(await api.thesisGet(id));
      setRevisions([]);
    } catch (e) {
      if (handleConflict(e)) return;
      setLifecycleErr(e instanceof ApiError ? e.message : "冻结 Formal Thesis 失败");
    } finally {
      setLifecycleBusy(false);
    }
  };

  const bindToCampaign = async () => {
    if (!id || !aggregate || !campaignContext || binding) return;
    if (aggregate.thesis.formal_state !== "frozen") return;
    if (!window.confirm(`绑定到 Campaign ${securityCode} 后不可更换。是否确认建立不可变绑定？`)) return;
    setLifecycleBusy(true);
    setLifecycleErr(null);
    try {
      setBinding(await api.bindCampaignThesis(campaignId, id));
    } catch (e) {
      if (handleConflict(e)) return;
      setLifecycleErr(e instanceof ApiError ? e.message : "绑定 Campaign 失败");
    } finally {
      setLifecycleBusy(false);
    }
  };

  const archive = async () => {
    if (!id || !aggregate) return;
    const summary = prompt("请输入归档原因（change_summary）", "归档：逻辑已不再追踪");
    if (summary === null) return;
    setBusy(true);
    setConflict(null);
    try {
      const r = await api.thesisArchive(id, aggregate.thesis.current_revision, summary.trim() || undefined);
      setAggregate(r);
      setRevisions([]);
    } catch (e) {
      if (handleConflict(e)) return;
      setErr(e instanceof ApiError ? e.message : "归档失败");
    } finally {
      setBusy(false);
    }
  };

  // 加载证据选项
  const openLinkPanel = async () => {
    if (!aggregate) return;
    setShowLinkPanel(true);
    setLinkErr(null);
    setLinkForm({ evidence_id: "", stance: "support", change_summary: "" });
    if (evidenceOptions.length === 0) {
      setEvidenceLoading(true);
      try {
        // 拉取同主体的证据，最多 100 条
        const r = await api.evidenceList({
          subject_type: aggregate.thesis.subject_type,
          subject_id: aggregate.thesis.subject_id,
          limit: 100,
          offset: 0,
        });
        setEvidenceOptions(r.items ?? []);
      } catch (e) {
        setLinkErr(e instanceof ApiError ? e.message : "加载证据失败");
      } finally {
        setEvidenceLoading(false);
      }
    }
  };

  const submitLink = async () => {
    if (!id || !aggregate) return;
    if (!linkForm.evidence_id) { setLinkErr("请选择一条证据"); return; }
    setBusy(true);
    setLinkErr(null);
    setConflict(null);
    try {
      const body = {
        evidence_id: linkForm.evidence_id,
        stance: linkForm.stance,
        expected_revision: aggregate.thesis.current_revision,
        change_summary: linkForm.change_summary.trim() || "关联证据",
      };
      const r = await api.thesisLinkEvidence(id, body);
      setAggregate(r);
      setShowLinkPanel(false);
      setRevisions([]);
    } catch (e) {
      if (handleConflict(e)) return;
      setLinkErr(e instanceof ApiError ? e.message : "关联失败");
    } finally {
      setBusy(false);
    }
  };

  const startStanceEdit = (link: EvidenceLink) => {
    setStanceEdit({
      evidenceId: link.evidence_id,
      stance: link.stance,
      change_summary: "",
    });
    setStanceErr(null);
  };

  const saveStance = async () => {
    if (!id || !aggregate || !stanceEdit) return;
    setBusy(true);
    setStanceErr(null);
    setConflict(null);
    try {
      const body = {
        stance: stanceEdit.stance,
        expected_revision: aggregate.thesis.current_revision,
        change_summary: stanceEdit.change_summary.trim() || "修改立场",
      };
      const r = await api.thesisUpdateStance(id, stanceEdit.evidenceId, body);
      setAggregate(r);
      setStanceEdit(null);
      setRevisions([]);
    } catch (e) {
      if (handleConflict(e)) return;
      setStanceErr(e instanceof ApiError ? e.message : "保存失败");
    } finally {
      setBusy(false);
    }
  };

  const unlink = async (link: EvidenceLink) => {
    if (!id || !aggregate) return;
    if (!confirm(`取消关联证据「${link.claim.slice(0, 40)}${link.claim.length > 40 ? "…" : ""}」？`)) return;
    setBusy(true);
    setConflict(null);
    try {
      const r = await api.thesisUnlinkEvidence(
        id, link.evidence_id, aggregate.thesis.current_revision, "取消关联证据",
      );
      setAggregate(r);
      setRevisions([]);
    } catch (e) {
      if (handleConflict(e)) return;
      setErr(e instanceof ApiError ? e.message : "取消关联失败");
    } finally {
      setBusy(false);
    }
  };

  const loadDiff = async () => {
    if (!id) return;
    if (fromRev === "" || toRev === "") { setDiffErr("请选择起止版本"); return; }
    setDiffLoading(true);
    setDiffErr(null);
    try {
      const r = await api.thesisDiff(id, Number(fromRev), Number(toRev));
      setDiff(r);
    } catch (e) {
      setDiffErr(e instanceof ApiError ? e.message : "加载对比失败");
    } finally {
      setDiffLoading(false);
    }
  };

  if (loading && !aggregate) {
    return (
      <div>
        <Link to={returnTo} className="mb-3 inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
          <ArrowLeft className="h-4 w-4" /> {campaignContext ? "返回决策待办" : "投资逻辑"}
        </Link>
        <div className="flex items-center justify-center py-20 text-sm text-muted-foreground">
          <Loader2 className="mr-2 h-4 w-4 animate-spin" /> 加载中…
        </div>
      </div>
    );
  }

  if (err && !aggregate) {
    return (
      <div>
        <Link to={returnTo} className="mb-3 inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
          <ArrowLeft className="h-4 w-4" /> {campaignContext ? "返回决策待办" : "投资逻辑"}
        </Link>
        <div className="mb-4 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
          {err}
        </div>
      </div>
    );
  }

  if (!aggregate) return null;
  const t = aggregate.thesis;

  return (
    <div>
      <Link to={returnTo} className="mb-3 inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
        <ArrowLeft className="h-4 w-4" /> {campaignContext ? "返回决策待办" : "投资逻辑"}
      </Link>

      {setupError && (
        <div className="mb-4 rounded-lg border border-warning/30 bg-warning/5 p-3 text-sm text-warning">
          基础 Thesis 已创建，但 Formal 草稿设置未全部完成。请核对并显式继续，不会自动确认、冻结或绑定。
        </div>
      )}

      {archived && (
        <div className="mb-4 flex items-center gap-2 rounded-lg border border-warning/30 bg-warning/5 p-3 text-sm text-warning">
          <Lock className="h-4 w-4 shrink-0" />
          <span>已归档，内容冻结。所有编辑/关联/取消关联/归档操作均不可用。</span>
        </div>
      )}

      {conflict && (
        <div className="mb-4 flex items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
          <RefreshCw className="mt-0.5 h-4 w-4 shrink-0" />
          <div className="flex-1">
            <p>{conflict}</p>
            <p className="mt-1 text-xs text-destructive/80">你的输入未丢失。请重新加载后再保存。</p>
          </div>
          <button
            onClick={() => { setConflict(null); void load(); }}
            className="shrink-0 rounded border border-destructive/30 px-2 py-1 text-xs hover:bg-destructive/10"
          >
            重新加载
          </button>
        </div>
      )}

      <PageHeader
        title={t.title}
        subtitle={`主体 ${t.subject_type}/${t.subject_id} · v${t.current_revision} · 更新于 ${fmtDate(t.updated_at)}`}
        actions={
          !editing ? (
            <div className="flex items-center gap-2">
              <button
                onClick={startEdit}
                disabled={contentLocked || busy}
                className="inline-flex items-center gap-1.5 rounded-lg border border-border/50 px-3 py-1.5 text-sm text-muted-foreground hover:border-primary/40 hover:text-primary disabled:opacity-50"
              >
                <Pencil className="h-4 w-4" /> 编辑
              </button>
              <button
                onClick={archive}
                disabled={archived || busy || formalState !== null}
                title={formalState !== null ? "Formal Thesis 使用独立生命周期，不通过 legacy 归档入口处理" : undefined}
                className="inline-flex items-center gap-1.5 rounded-lg border border-warning/30 px-3 py-1.5 text-sm text-muted-foreground hover:border-warning hover:text-warning disabled:opacity-50"
              >
                <Lock className="h-4 w-4" /> 归档
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

      <GlassCard className="mb-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold">Formal Thesis 生命周期</h2>
            <p className="mt-1 text-xs text-muted-foreground">
              状态：{t.formal_state ?? "legacy"} · 当前 v{t.current_revision} · 冻结版本 {t.frozen_revision ? `v${t.frozen_revision}` : "—"}
            </p>
            <p className="mt-1 text-xs text-muted-foreground">
              策略：{t.strategy ?? "—"} · 预期周期：{t.expected_horizon
                ? `${t.expected_horizon.min}-${t.expected_horizon.max} 个交易日`
                : "—"} · 更新：{fmtDate(t.updated_at)}
            </p>
            {campaignContext && (
              <p className="mt-1 text-xs text-muted-foreground">
                Campaign：{securityCode} / {campaignStrategy} · 绑定：{binding
                  ? binding.thesis_id === t.id ? "当前 Thesis（不可变）" : `其他 Thesis ${binding.thesis_id}`
                  : "未绑定"}
              </p>
            )}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {t.formal_state === null && (
              <button
                type="button"
                onClick={beginFormalization}
                disabled={lifecycleBusy || archived}
                className="rounded-lg bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
              >
                开始 Formal 化
              </button>
            )}
            {t.formal_state === "draft" && (
              <button
                type="button"
                onClick={confirmFormalization}
                disabled={lifecycleBusy || editing || !canConfirmFormalThesis(t)}
                className="rounded-lg bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
              >
                确认 Formal Thesis
              </button>
            )}
            {t.formal_state === "confirmed" && (
              <button
                type="button"
                onClick={freezeFormalization}
                disabled={lifecycleBusy}
                className="rounded-lg bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
              >
                冻结 Formal Original
              </button>
            )}
            {t.formal_state === "frozen" && campaignContext && !binding && (
              <button
                type="button"
                onClick={bindToCampaign}
                disabled={lifecycleBusy || t.strategy !== campaignStrategy || t.subject_id !== securityCode}
                className="rounded-lg bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
              >
                绑定到当前 Campaign
              </button>
            )}
            {binding?.thesis_id === t.id && (
              <Link to={returnTo} className="rounded-lg border border-success/30 px-3 py-1.5 text-sm text-success hover:bg-success/10">
                返回 Decision Inbox
              </Link>
            )}
          </div>
        </div>
        {t.formal_state === "draft" && !canConfirmFormalThesis(t) && (
          <p className="mt-3 text-xs text-warning">
            确认门尚未满足：需要 active 状态、3-5 条核心论点、策略及合法预期周期。先编辑并保存草稿。
          </p>
        )}
        {t.formal_state === "frozen" && campaignContext && t.strategy !== campaignStrategy && (
          <p className="mt-3 text-xs text-warning">Thesis 策略与 Campaign 不一致，后端将拒绝绑定。</p>
        )}
        {lifecycleErr && <p className="mt-3 text-sm text-destructive" role="alert">{lifecycleErr}</p>}
      </GlassCard>

      {/* Tab 切换 */}
      <div className="mb-4 flex items-center gap-1 border-b border-border/30">
        {[
          { key: "detail", label: "逻辑详情", icon: BookOpen },
          { key: "history", label: "版本历史", icon: History },
          { key: "diff", label: "版本对比", icon: GitCompareArrows },
        ].map((tab) => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key as typeof activeTab)}
            className={cn(
              "inline-flex items-center gap-1.5 border-b-2 px-3 py-2 text-sm transition-colors",
              activeTab === tab.key
                ? "border-primary text-primary"
                : "border-transparent text-muted-foreground hover:text-foreground",
            )}
          >
            <tab.icon className="h-3.5 w-3.5" />
            {tab.label}
          </button>
        ))}
      </div>

      {/* ============ 详情 Tab ============ */}
      {activeTab === "detail" && (
        <div className="space-y-4">
          <GlassCard>
            {!editing ? (
              <div className="space-y-4">
                <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                  <div>
                    <p className={labelCls}>主体</p>
                    <p className="mt-0.5 font-mono text-sm">{t.subject_type}/{t.subject_id}</p>
                  </div>
                  <div>
                    <p className={labelCls}>市场</p>
                    <p className="mt-0.5 text-sm">{t.market ?? "—"}</p>
                  </div>
                  <div>
                    <p className={labelCls}>状态</p>
                    <span className={cn("mt-0.5 inline-block rounded px-1.5 py-0.5 text-[11px]", STATUS_COLOR[t.status] ?? "bg-muted/50 text-muted-foreground")}>
                      {STATUS_LABELS[t.status] ?? t.status}
                    </span>
                  </div>
                  <div>
                    <p className={labelCls}>版本</p>
                    <p className="mt-0.5 text-sm font-mono">v{t.current_revision}</p>
                  </div>
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

                <div className="border-t border-border/30 pt-3 text-[11px] text-muted-foreground/60">
                  ID: <span className="font-mono">{t.id}</span> · 创建 {fmtDate(t.created_at)} · 更新 {fmtDate(t.updated_at)}
                </div>
              </div>
            ) : (
              <div>
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                  <label className={labelCls}>
                    状态
                    <select
                      value={form?.status ?? "active"}
                      onChange={(e) => setForm((p) => p ? { ...p, status: e.target.value as EditForm["status"] } : p)}
                      className={inputCls}
                    >
                      {STATUSES.map((s) => (
                        <option key={s.value} value={s.value}>{s.label}</option>
                      ))}
                    </select>
                  </label>
                  <label className={`${labelCls} sm:col-span-2`}>
                    标题 <span className="text-destructive">*</span>
                    <input
                      value={form?.title ?? ""}
                      onChange={(e) => setForm((p) => p ? { ...p, title: e.target.value } : p)}
                      className={inputCls}
                    />
                  </label>
                  <label className={`${labelCls} sm:col-span-2`}>
                    摘要
                    <textarea
                      value={form?.summary ?? ""}
                      onChange={(e) => setForm((p) => p ? { ...p, summary: e.target.value } : p)}
                      rows={3}
                      className={`${inputCls} resize-y`}
                    />
                  </label>
                  {t.formal_state === "draft" && (
                    <div className="sm:col-span-2 rounded-lg border border-primary/20 bg-primary/5 p-3">
                      <p className="text-xs font-medium">Formal 设置</p>
                      <div className="mt-3 grid gap-3 sm:grid-cols-3">
                        <label className={labelCls}>
                          策略
                          <select
                            value={form?.strategy ?? ""}
                            disabled={campaignContext}
                            onChange={(e) => {
                              const strategy = e.target.value as CampaignStrategy | "";
                              const horizon = strategy ? defaultHorizonForStrategy(strategy) : null;
                              setForm((p) => p ? {
                                ...p,
                                strategy,
                                horizon_min: horizon ? String(horizon.min) : "",
                                horizon_max: horizon ? String(horizon.max) : "",
                              } : p);
                            }}
                            className={inputCls}
                          >
                            <option value="">请选择…</option>
                            <option value="SHORT">SHORT</option>
                            <option value="SWING">SWING</option>
                            <option value="MEDIUM">MEDIUM</option>
                          </select>
                        </label>
                        <label className={labelCls}>
                          最短交易日
                          <input
                            type="number"
                            value={form?.horizon_min ?? ""}
                            onChange={(e) => setForm((p) => p ? { ...p, horizon_min: e.target.value } : p)}
                            className={inputCls}
                          />
                        </label>
                        <label className={labelCls}>
                          最长交易日
                          <input
                            type="number"
                            value={form?.horizon_max ?? ""}
                            onChange={(e) => setForm((p) => p ? { ...p, horizon_max: e.target.value } : p)}
                            className={inputCls}
                          />
                        </label>
                        <label className={`${labelCls} sm:col-span-3`}>
                          Formal 备注（可选）
                          <textarea
                            value={form?.free_notes ?? ""}
                            onChange={(e) => setForm((p) => p ? { ...p, free_notes: e.target.value } : p)}
                            rows={2}
                            className={`${inputCls} resize-y`}
                          />
                        </label>
                      </div>
                    </div>
                  )}
                  <div className="sm:col-span-2">
                    <ArrayEditor
                      label="核心论点"
                      items={form?.core_claims ?? []}
                      onChange={(v) => setForm((p) => p ? { ...p, core_claims: v } : p)}
                    />
                  </div>
                  <div className="sm:col-span-2">
                    <ArrayEditor
                      label="催化剂"
                      items={form?.catalysts ?? []}
                      onChange={(v) => setForm((p) => p ? { ...p, catalysts: v } : p)}
                    />
                  </div>
                  <div className="sm:col-span-2">
                    <ArrayEditor
                      label="风险"
                      items={form?.risks ?? []}
                      onChange={(v) => setForm((p) => p ? { ...p, risks: v } : p)}
                    />
                  </div>
                  <div className="sm:col-span-2">
                    <ArrayEditor
                      label="失效条件"
                      items={form?.invalidation_conditions ?? []}
                      onChange={(v) => setForm((p) => p ? { ...p, invalidation_conditions: v } : p)}
                    />
                  </div>
                  <label className={`${labelCls} sm:col-span-2`}>
                    变更说明（change_summary）
                    <input
                      value={form?.change_summary ?? ""}
                      onChange={(e) => setForm((p) => p ? { ...p, change_summary: e.target.value } : p)}
                      placeholder="如：调整催化剂清单"
                      className={inputCls}
                    />
                  </label>
                </div>

                {editErr && (
                  <p className="mt-3 text-sm text-destructive">{editErr}</p>
                )}

                <div className="mt-4 flex items-center gap-2">
                  <button
                    onClick={saveEdit}
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

          {/* 证据关联 */}
          <GlassCard>
            <div className="mb-3 flex items-center justify-between">
              <h3 className="flex items-center gap-1.5 text-sm font-semibold">
                <Link2 className="h-4 w-4 text-primary" />
                关联证据
                <span className="text-xs font-normal text-muted-foreground">（{aggregate.evidence_links.length}）</span>
              </h3>
              <button
                onClick={openLinkPanel}
                disabled={contentLocked || busy}
                className="inline-flex items-center gap-1.5 rounded-lg bg-primary/15 px-2.5 py-1 text-xs text-primary hover:bg-primary/25 disabled:opacity-50"
              >
                <Plus className="h-3.5 w-3.5" /> 关联证据
              </button>
            </div>

            {showLinkPanel && (
              <div className="mb-3 rounded-lg border border-border/40 bg-muted/20 p-3">
                <h4 className="mb-2 text-xs font-medium text-muted-foreground">从证据库选择一条证据关联到当前逻辑</h4>
                {evidenceLoading ? (
                  <div className="flex items-center gap-2 py-2 text-xs text-muted-foreground">
                    <Loader2 className="h-3.5 w-3.5 animate-spin" /> 加载证据列表…
                  </div>
                ) : evidenceOptions.length === 0 ? (
                  <p className="py-2 text-xs text-muted-foreground">
                    没有同主体的证据。<Link to="/evidence/new" className="text-primary">去新建一条</Link>
                  </p>
                ) : (
                  <div className="space-y-2">
                    <select
                      value={linkForm.evidence_id}
                      onChange={(e) => setLinkForm((p) => ({ ...p, evidence_id: e.target.value }))}
                      className={inputCls}
                    >
                      <option value="">请选择证据…</option>
                      {evidenceOptions.map((e) => (
                        <option key={e.id} value={e.id}>
                          {e.claim.slice(0, 80)}{e.claim.length > 80 ? "…" : ""} ({e.source_title})
                        </option>
                      ))}
                    </select>
                    <div className="flex items-center gap-2">
                      <label className={labelCls}>
                        立场
                        <select
                          value={linkForm.stance}
                          onChange={(e) => setLinkForm((p) => ({ ...p, stance: e.target.value as LinkForm["stance"] }))}
                          className={`${inputCls} w-32`}
                        >
                          <option value="support">支撑</option>
                          <option value="oppose">反对</option>
                          <option value="neutral">中性</option>
                        </select>
                      </label>
                      <label className={`${labelCls} flex-1`}>
                        变更说明
                        <input
                          value={linkForm.change_summary}
                          onChange={(e) => setLinkForm((p) => ({ ...p, change_summary: e.target.value }))}
                          placeholder="如：关联财报证据"
                          className={inputCls}
                        />
                      </label>
                    </div>
                  </div>
                )}
                {linkErr && <p className="mt-2 text-xs text-destructive">{linkErr}</p>}
                <div className="mt-2 flex items-center gap-2">
                  <button
                    onClick={submitLink}
                    disabled={busy || !linkForm.evidence_id}
                    className="inline-flex items-center gap-1 rounded bg-primary px-2.5 py-1 text-xs font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-60"
                  >
                    {busy ? <Loader2 className="h-3 w-3 animate-spin" /> : <Link2 className="h-3 w-3" />}
                    关联
                  </button>
                  <button
                    onClick={() => { setShowLinkPanel(false); setLinkErr(null); }}
                    disabled={busy}
                    className="inline-flex items-center gap-1 rounded border border-border/50 px-2.5 py-1 text-xs text-muted-foreground hover:border-primary/40"
                  >
                    取消
                  </button>
                </div>
              </div>
            )}

            {aggregate.evidence_links.length === 0 ? (
              <p className="py-4 text-center text-xs text-muted-foreground/60">
                还没关联证据。点上方「关联证据」开始建立证据账本。
              </p>
            ) : (
              <div className="space-y-2">
                {aggregate.evidence_links.map((link) => (
                  <div key={link.evidence_id} className="rounded-lg border border-border/40 bg-background/40 p-3">
                    {stanceEdit?.evidenceId === link.evidence_id ? (
                      <div>
                        <p className="mb-2 text-xs text-muted-foreground">修改立场</p>
                        <div className="flex items-center gap-2">
                          <select
                            value={stanceEdit.stance}
                            onChange={(e) => setStanceEdit((p) => p ? { ...p, stance: e.target.value as StanceForm["stance"] } : p)}
                            className={`${inputCls} w-32`}
                          >
                            <option value="support">支撑</option>
                            <option value="oppose">反对</option>
                            <option value="neutral">中性</option>
                          </select>
                          <input
                            value={stanceEdit.change_summary}
                            onChange={(e) => setStanceEdit((p) => p ? { ...p, change_summary: e.target.value } : p)}
                            placeholder="变更说明"
                            className={inputCls}
                          />
                        </div>
                        {stanceErr && <p className="mt-1 text-xs text-destructive">{stanceErr}</p>}
                        <div className="mt-2 flex items-center gap-2">
                          <button
                            onClick={saveStance}
                            disabled={busy}
                            className="inline-flex items-center gap-1 rounded bg-primary px-2.5 py-1 text-xs text-primary-foreground hover:bg-primary/90 disabled:opacity-60"
                          >
                            {busy ? <Loader2 className="h-3 w-3 animate-spin" /> : <Save className="h-3 w-3" />} 保存
                          </button>
                          <button
                            onClick={() => { setStanceEdit(null); setStanceErr(null); }}
                            disabled={busy}
                            className="inline-flex items-center gap-1 rounded border border-border/50 px-2.5 py-1 text-xs text-muted-foreground"
                          >
                            取消
                          </button>
                        </div>
                      </div>
                    ) : (
                      <div>
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
                            <div className="mt-1 flex flex-wrap items-center gap-1">
                              <span className={cn("rounded px-1.5 py-0.5 text-[10px]", CLASSIFICATION_COLOR[link.classification] ?? "bg-muted/50 text-muted-foreground")}>
                                {link.classification}
                              </span>
                              <span className={cn("rounded px-1.5 py-0.5 text-[10px]", CONFIDENCE_COLOR[link.confidence] ?? "bg-muted/50 text-muted-foreground")}>
                                置信度 {link.confidence}
                              </span>
                              <Link
                                to={`/evidence/${link.evidence_id}`}
                                className="ml-auto text-[10px] text-muted-foreground hover:text-primary"
                              >
                                查看证据 →
                              </Link>
                            </div>
                          </div>
                        </div>
                        <div className="mt-2 flex items-center justify-end gap-2">
                          <button
                            onClick={() => startStanceEdit(link)}
                            disabled={contentLocked || busy}
                            className="inline-flex items-center gap-1 rounded border border-border/50 px-2 py-1 text-[11px] text-muted-foreground hover:border-primary/40 hover:text-primary disabled:opacity-50"
                          >
                            <Pencil className="h-3 w-3" /> 修改立场
                          </button>
                          <button
                            onClick={() => unlink(link)}
                            disabled={contentLocked || busy}
                            className="inline-flex items-center gap-1 rounded border border-border/50 px-2 py-1 text-[11px] text-muted-foreground hover:border-destructive/40 hover:text-destructive disabled:opacity-50"
                          >
                            <Unlink className="h-3 w-3" /> 取消关联
                          </button>
                        </div>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </GlassCard>
        </div>
      )}

      {/* ============ 版本历史 Tab ============ */}
      {activeTab === "history" && (
        <GlassCard>
          <div className="mb-3 flex items-center justify-between">
            <h3 className="flex items-center gap-1.5 text-sm font-semibold">
              <History className="h-4 w-4 text-primary" /> 版本历史
            </h3>
            <button
              onClick={() => void loadRevisions()}
              disabled={revisionsLoading}
              className="text-muted-foreground hover:text-primary"
              title="刷新"
            >
              <RefreshCw className={cn("h-3.5 w-3.5", revisionsLoading && "animate-spin")} />
            </button>
          </div>
          {revisionsLoading && revisions.length === 0 ? (
            <div className="flex items-center justify-center py-6 text-sm text-muted-foreground">
              <Loader2 className="mr-2 h-4 w-4 animate-spin" /> 加载中…
            </div>
          ) : revisions.length === 0 ? (
            <p className="py-6 text-center text-sm text-muted-foreground/60">暂无历史版本</p>
          ) : (
            <div className="divide-y divide-border/30">
              {revisions.map((r) => (
                <Link
                  key={r.id}
                  to={`/thesis/${id}/revision/${r.revision_number}`}
                  className="block py-2.5 transition-colors hover:bg-primary/5"
                >
                  <div className="flex items-center gap-2">
                    <span className="rounded bg-secondary px-1.5 py-0.5 text-[10px] font-mono text-secondary-foreground">
                      v{r.revision_number}
                    </span>
                    <span className="flex-1 truncate text-sm">{r.change_summary || "（无变更说明）"}</span>
                    <span className="shrink-0 text-[11px] text-muted-foreground/60">{fmtDate(r.created_at)}</span>
                  </div>
                </Link>
              ))}
            </div>
          )}
        </GlassCard>
      )}

      {/* ============ 版本对比 Tab ============ */}
      {activeTab === "diff" && (
        <GlassCard>
          <h3 className="mb-3 flex items-center gap-1.5 text-sm font-semibold">
            <GitCompareArrows className="h-4 w-4 text-primary" /> 版本对比
          </h3>
          <div className="mb-4 flex flex-wrap items-end gap-3">
            <label className={labelCls}>
              起始版本
              <select
                value={fromRev}
                onChange={(e) => setFromRev(e.target.value === "" ? "" : Number(e.target.value))}
                className={`${inputCls} w-32`}
              >
                <option value="">选择…</option>
                {revisions.map((r) => (
                  <option key={r.id} value={r.revision_number}>v{r.revision_number}</option>
                ))}
              </select>
            </label>
            <label className={labelCls}>
              目标版本
              <select
                value={toRev}
                onChange={(e) => setToRev(e.target.value === "" ? "" : Number(e.target.value))}
                className={`${inputCls} w-32`}
              >
                <option value="">选择…</option>
                {revisions.map((r) => (
                  <option key={r.id} value={r.revision_number}>v{r.revision_number}</option>
                ))}
              </select>
            </label>
            <button
              onClick={loadDiff}
              disabled={diffLoading || fromRev === "" || toRev === ""}
              className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-primary/15 px-3 text-sm text-primary hover:bg-primary/25 disabled:opacity-50"
            >
              {diffLoading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <GitCompareArrows className="h-3.5 w-3.5" />}
              对比
            </button>
          </div>

          {revisions.length === 0 && (
            <p className="py-4 text-center text-xs text-muted-foreground/60">
              {revisionsLoading ? "加载版本列表中…" : "暂无可对比的版本"}
            </p>
          )}

          {diffErr && (
            <div className="mb-4 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
              {diffErr}
            </div>
          )}

          {diff && (
            <div className="space-y-4">
              <p className="text-xs text-muted-foreground">
                对比 v{diff.from_revision} → v{diff.to_revision}
              </p>

              {/* Thesis 字段变化 */}
              <div>
                <h4 className="mb-2 text-xs font-semibold text-muted-foreground">逻辑字段变化</h4>
                {Object.keys(diff.thesis_changes).length === 0 ? (
                  <p className="text-xs text-muted-foreground/60">（无字段变化）</p>
                ) : (
                  <div className="overflow-hidden rounded-lg border border-border/40">
                    <table className="w-full text-xs">
                      <thead className="bg-muted/30">
                        <tr>
                          <th className="px-2 py-1.5 text-left font-medium text-muted-foreground">字段</th>
                          <th className="px-2 py-1.5 text-left font-medium text-muted-foreground">v{diff.from_revision}</th>
                          <th className="px-2 py-1.5 text-left font-medium text-muted-foreground">v{diff.to_revision}</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-border/30">
                        {Object.entries(diff.thesis_changes).map(([field, ch]) => (
                          <tr key={field}>
                            <td className="px-2 py-1.5 font-mono text-muted-foreground">{field}</td>
                            <td className="px-2 py-1.5 text-muted-foreground/80">{renderValue(ch.from)}</td>
                            <td className="px-2 py-1.5 text-foreground">{renderValue(ch.to)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>

              {/* 证据变化 */}
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                <div>
                  <h4 className="mb-2 text-xs font-semibold text-success">新增证据（{diff.evidence_added.length}）</h4>
                  {diff.evidence_added.length === 0 ? (
                    <p className="text-xs text-muted-foreground/60">—</p>
                  ) : (
                    <ul className="space-y-1 text-xs">
                      {diff.evidence_added.map((e) => (
                        <li key={e.evidence_id} className="rounded bg-success/5 p-1.5">
                          <span className={cn("mr-1 inline-block rounded px-1 py-0.5 text-[9px]", STANCE_COLOR[e.to.stance] ?? "bg-muted/50 text-muted-foreground")}>
                            {STANCE_LABELS[e.to.stance] ?? e.to.stance}
                          </span>
                          <span className="break-words">{e.to.claim}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
                <div>
                  <h4 className="mb-2 text-xs font-semibold text-destructive">移除证据（{diff.evidence_removed.length}）</h4>
                  {diff.evidence_removed.length === 0 ? (
                    <p className="text-xs text-muted-foreground/60">—</p>
                  ) : (
                    <ul className="space-y-1 text-xs">
                      {diff.evidence_removed.map((e) => (
                        <li key={e.evidence_id} className="rounded bg-danger/5 p-1.5">
                          <span className={cn("mr-1 inline-block rounded px-1 py-0.5 text-[9px]", STANCE_COLOR[e.from.stance] ?? "bg-muted/50 text-muted-foreground")}>
                            {STANCE_LABELS[e.from.stance] ?? e.from.stance}
                          </span>
                          <span className="break-words">{e.from.claim}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
                <div>
                  <h4 className="mb-2 text-xs font-semibold text-warning">变更证据（{diff.evidence_changed.length}）</h4>
                  {diff.evidence_changed.length === 0 ? (
                    <p className="text-xs text-muted-foreground/60">—</p>
                  ) : (
                    <ul className="space-y-1 text-xs">
                      {diff.evidence_changed.map((e) => (
                        <li key={e.evidence_id} className="rounded bg-warning/5 p-1.5">
                          <span className="font-mono text-[10px] text-muted-foreground/60">{e.evidence_id.slice(0, 8)}…</span>
                          <ul className="mt-0.5 ml-3">
                            {Object.entries(e.changes).map(([k, c]) => (
                              <li key={k}>
                                <span className="font-mono text-muted-foreground">{k}:</span>{" "}
                                <span className="text-muted-foreground/80">{renderValue(c.from)}</span>
                                {" → "}
                                <span className="text-foreground">{renderValue(c.to)}</span>
                              </li>
                            ))}
                          </ul>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              </div>
            </div>
          )}
        </GlassCard>
      )}
    </div>
  );
}
