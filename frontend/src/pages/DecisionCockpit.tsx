// 决策舱（/cockpit）—— PR A 范围：「明日行动计划」建设；
// 「今日实时行动」留作 PR B 占位（"将在后续 PR B 建设"）。
//
// 前端绝不提交候选池 / 持仓快照 / 信号 / 证据 / actions / trade_date_override；
// 所有权威数据由后端读取与计算，前端只提交 trade_date + 可选 llm + force。

import { useEffect, useMemo, useState, useCallback } from "react";
import {
  RefreshCw, Target, AlertTriangle, Zap, Clock, ShieldCheck, History,
  ChevronRight, Loader2, Layers,
} from "lucide-react";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import { AskAiButton } from "@/components/ui/AskAiButton";
import { loadLlm, type LlmConfig } from "@/lib/llm";
import { loadLocalDraft } from "@/lib/watchlist";
import {
  getOverview,
  getCurrentPlan,
  generateTomorrowPlan,
  getPlan,
  freezePlan,
  listPlans,
  importLocalWatchlist,
  ApiError,
  type Overview,
  type TomorrowPlanMeta,
  type Signal,
  type Candidate,
} from "@/lib/decisionCockpit";
import { cn } from "@/lib/utils";

type Tab = "tomorrow" | "today";

const today = () => new Date().toISOString().slice(0, 10);

const assessColor = (a: Signal["assessment"]) =>
  a === "strong"
    ? "text-success"
    : a === "weak"
      ? "text-danger"
      : a === "unknown"
        ? "text-muted-foreground"
        : "text-yellow-400";

const assessLabel: Record<Signal["assessment"], string> = {
  strong: "强", medium: "中", weak: "弱", unknown: "未知",
};

function SignalBadge({ s }: { s: Signal }) {
  return (
    <span className={cn("inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-xs font-medium",
      s.assessment === "strong" ? "bg-success/10 text-success" :
      s.assessment === "weak" ? "bg-danger/10 text-danger" :
      "bg-muted text-muted-foreground")}
    >
      <span className={assessColor(s.assessment)}>●</span>
      <span className="font-mono">{s.candidate_code}</span>
      <span className="opacity-80">{s.label}</span>
      <span className={cn("ml-0.5", assessColor(s.assessment))}>{assessLabel[s.assessment]}</span>
    </span>
  );
}

export function DecisionCockpit() {
  const [tab, setTab] = useState<Tab>("tomorrow");
  const [tradeDate, setTradeDate] = useState<string>(today);
  const [overview, setOverview] = useState<Overview | null>(null);
  const [plan, setPlan] = useState<(TomorrowPlanMeta & { signals?: Signal[] }) | null>(null);
  const [loading, setLoading] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [freezing, setFreezing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);

  const llm: LlmConfig | null = useMemo(() => loadLlm(), []);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [ov, cp] = await Promise.all([
        getOverview(tradeDate),
        getCurrentPlan(tradeDate),
      ]);
      setOverview(ov);
      setPlan(cp ?? null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "加载决策舱失败");
    } finally {
      setLoading(false);
    }
  }, [tradeDate]);

  useEffect(() => { refresh(); }, [refresh]);

  const loadPlanById = async (planId: number) => {
    const p = await getPlan(planId);
    if (p) setPlan(p);
    return p;
  };

  const generate = async () => {
    setGenerating(true);
    setError(null);
    setInfo(null);
    try {
      const res = await generateTomorrowPlan(tradeDate, llm, false);
      if (res.skipped) {
        setInfo("该计划日已有冻结计划，未重复生成（可点强制重新生成，或从历史打开草稿）");
        await refresh();
      } else {
        setInfo(`已生成草稿 v${res.version}（草稿不是 current；冻结后才成为当前计划）`);
        await refresh();
        // draft 不是 is_current，必须按 id 加载才能冻结/查看
        if (res.id) await loadPlanById(res.id);
      }
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        setError(e.message || "无法生成：缺少复盘快照或候选池为空。");
      } else {
        setError(e instanceof ApiError ? e.message : "生成失败");
      }
    } finally {
      setGenerating(false);
    }
  };

  const forceRegenerate = async () => {
    setGenerating(true);
    setError(null);
    setInfo(null);
    try {
      const res = await generateTomorrowPlan(tradeDate, llm, true);
      setInfo(
        res.skipped
          ? "强制生成被跳过"
          : `已强制生成草稿 v${res.version}（不影响已冻结 current；冻结本草稿会 supersede 旧 frozen）`,
      );
      await refresh();
      if (res.id && !res.skipped) await loadPlanById(res.id);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "生成失败");
    } finally {
      setGenerating(false);
    }
  };

  const freeze = async () => {
    if (!plan || plan.status !== "draft") return;
    setFreezing(true);
    setError(null);
    try {
      const updated = await freezePlan(plan.id, plan.version);
      setInfo("已冻结该草稿：现为当前计划（同日仅一个 current frozen）");
      setPlan({ ...plan, ...updated, status: updated.status, is_current: updated.is_current ?? 1 });
      await refresh();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "冻结失败");
    } finally {
      setFreezing(false);
    }
  };

  // 前端草稿并入后端自选股（显式迁移入口，刷新候选池）。
  const importLocalDraft = async () => {
    setInfo(null);
    setError(null);
    try {
      // 尝试读取既有 localStorage 草稿，并入后端；无草稿则静默。
      const local = loadLocalDraft();
      if (!local.length) { setInfo("没有检测到本地自选草稿"); return; }
      const res = await importLocalWatchlist(local);
      setInfo(`已并入后端：新增 ${res.added.length} 只，共 ${res.codes.length} 只`);
      await refresh();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "并入失败");
    }
  };

  const marketStatus = overview?.market_short?.status ?? "unavailable";
  const candidateCount = overview?.candidate_pool?.length ?? 0;
  const strongCount = plan?.signals?.filter((s) => s.assessment === "strong").length ?? 0;
  const weakCount = plan?.signals?.filter((s) => s.assessment === "weak").length ?? 0;

  return (
    <div>
      <PageHeader
        title="决策舱"
        subtitle="明日行动计划：基于候选池 + 多维度确定性信号生成"
        actions={
          <div className="flex items-center gap-2">
            <button
              onClick={importLocalDraft}
              className="flex items-center gap-1.5 rounded-lg border border-border bg-card px-3 py-1.5 text-sm transition-colors hover:border-primary hover:text-primary"
              title="把前端 localStorage 自选草稿并入后端权威自选股"
            >
              <Layers className="h-4 w-4" /> 同步自选草稿
            </button>
            <button
              onClick={refresh}
              disabled={loading}
              className="flex items-center gap-1.5 rounded-lg border border-border bg-card px-3 py-1.5 text-sm transition-colors hover:border-primary hover:text-primary disabled:opacity-50"
            >
              {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
              刷新
            </button>
          </div>
        }
      />

      {/* 两个 Tab：明日行动计划（本期建设） / 今日实时行动（PR B 占位） */}
      <div className="mb-4 flex gap-1 border-b border-border/60">
        <button
          onClick={() => setTab("tomorrow")}
          className={cn(
            "flex items-center gap-1.5 border-b-2 px-4 py-2 text-sm font-medium transition-colors",
            tab === "tomorrow"
              ? "border-primary text-primary"
              : "border-transparent text-muted-foreground hover:text-foreground",
          )}
        >
          <Target className="h-4 w-4" /> 明日行动计划
        </button>
        <button
          onClick={() => setTab("today")}
          className={cn(
            "flex items-center gap-1.5 border-b-2 px-4 py-2 text-sm font-medium transition-colors",
            tab === "today"
              ? "border-primary text-primary"
              : "border-transparent text-muted-foreground hover:text-foreground",
          )}
        >
          <Zap className="h-4 w-4" /> 今日实时行动
        </button>
      </div>

      {tab === "today" ? <TodayPlaceholder /> : null}

      {tab === "tomorrow" ? (
        <div className="space-y-4">
          {error && (
            <GlassCard className="flex items-start gap-2 border-danger/30 text-sm text-danger">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
              <span>{error}</span>
            </GlassCard>
          )}
          {info && !error && (
            <GlassCard className="flex items-start gap-2 border-primary/30 text-sm text-primary">
              <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0" />
              <span>{info}</span>
            </GlassCard>
          )}

          {/* 控制条：交易日 + 市场状态 + 生成 */}
          <GlassCard className="space-y-3">
            <div className="flex flex-wrap items-end gap-3">
              <label className="flex flex-col gap-1 text-xs text-muted-foreground">
                交易日
                <input
                  type="date"
                  value={tradeDate}
                  max={today()}
                  onChange={(e) => setTradeDate(e.target.value || today())}
                  className="rounded border border-border bg-card px-2 py-1 text-sm text-foreground"
                />
              </label>
              <div className="flex flex-col gap-1 text-xs">
                <span className="text-muted-foreground">市场状态</span>
                <span className={cn("rounded px-2 py-1 text-sm font-medium",
                  marketStatus === "normal" ? "bg-success/10 text-success" :
                  marketStatus === "partial" ? "bg-yellow-400/10 text-yellow-400" :
                  "bg-danger/10 text-danger")}
                >
                  {marketStatus === "normal" ? "正常" : marketStatus === "partial" ? "部分" : "不可用"}
                </span>
              </div>
              <div className="flex flex-col gap-1 text-xs">
                <span className="text-muted-foreground">候选池</span>
                <span className="rounded bg-muted px-2 py-1 text-sm font-medium">{candidateCount} 只</span>
              </div>
              <div className="flex flex-1 justify-end items-end gap-2">
                <button
                  onClick={generate}
                  disabled={generating || marketStatus === "unavailable"}
                  className="flex items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground transition-opacity hover:opacity-90 disabled:opacity-50"
                  title="基于候选池 + 多维度信号生成新版本（LLM 不可用时自动回退确定性摘要）"
                >
                  {generating ? <Loader2 className="h-4 w-4 animate-spin" /> : <Target className="h-4 w-4" />}
                  生成明日计划
                </button>
                <button
                  onClick={forceRegenerate}
                  disabled={generating}
                  className="flex items-center gap-1.5 rounded-lg border border-border bg-card px-3 py-1.5 text-sm transition-colors hover:border-primary hover:text-primary disabled:opacity-50"
                  title="即使已有冻结计划也强制重新生成新版本"
                >
                  强制重新生成
                </button>
              </div>
            </div>
            <p className="text-xs text-muted-foreground">
              候选池由持仓 + 自选 + 板块代表（受保护）+ 连板 / 成交额 / 高换手组成；
              价值 / 趋势 / 短线 三维信号为纯阈值规则、K 线不复权；生成需绑定不可变复盘快照；
              LLM 仅解释、不可用时自动回退确定性摘要。草稿不会覆盖已冻结计划。
            </p>
          </GlassCard>

          {/* 当前计划 / 正在查看的草稿 */}
          {!plan && !loading ? (
            <GlassCard className="flex flex-col items-center gap-2 py-10 text-center text-muted-foreground">
              <Clock className="h-8 w-8 opacity-40" />
              <p className="text-sm">该交易日还没有已冻结的 current 计划。</p>
              <p className="text-xs">点「生成明日计划」创建草稿，再点「冻结」设为当前。</p>
            </GlassCard>
          ) : plan ? (
            <GlassCard className="space-y-3" data-testid="plan-panel">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <h2 className="text-base font-semibold">
                    {plan.status === "frozen" && plan.is_current ? "当前计划" : "计划详情"}
                  </h2>
                  <span
                    data-testid="plan-status"
                    className={cn("rounded px-2 py-0.5 text-xs font-medium",
                    plan.status === "draft" ? "bg-primary/10 text-primary" :
                    plan.status === "frozen" ? "bg-success/10 text-success" :
                    "bg-muted text-muted-foreground")}
                  >
                    v{plan.version} · {plan.status === "draft" ? "草稿" : plan.status === "frozen" ? "已冻结" : "已废弃"}
                    {plan.is_current ? " · current" : ""}
                  </span>
                </div>
                <div className="flex items-center gap-2">
                  {plan.status === "draft" && (
                    <button
                      onClick={freeze}
                      disabled={freezing}
                      className="flex items-center gap-1.5 rounded-lg border border-border bg-card px-3 py-1 text-sm transition-colors hover:border-success hover:text-success disabled:opacity-50"
                      title="冻结当前版本（冻结后不可再编辑，但会作为历史保留）"
                    >
                      {freezing ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <ShieldCheck className="h-3.5 w-3.5" />}
                      冻结
                    </button>
                  )}
                  <AskAiButton
                    context={buildPlanContext(plan, strongCount, weakCount)}
                    label="解读当前计划"
                  />
                </div>
              </div>
              <p className="text-xs text-muted-foreground">
                生成时间 {plan.generated_at} · 信号 {plan.signals?.length ?? 0} 条（强 {strongCount} / 弱 {weakCount}）
              </p>

              {/* 三维信号：价值 / 趋势 / 短线 */}
              <div data-testid="signals-3d">
                <h3 className="mb-2 text-xs font-semibold text-muted-foreground">
                  信号一览（价值 · 趋势 · 短线）
                </h3>
                {(["value", "trend", "short"] as const).map((dim) => {
                  const dimLabel = dim === "value" ? "价值" : dim === "trend" ? "趋势" : "短线";
                  const dimSigs = (plan.signals ?? []).filter((s) => s.dimension === dim);
                  return (
                    <div key={dim} className="mb-2" data-testid={`signals-${dim}`}>
                      <div className="mb-1 text-[11px] font-medium text-muted-foreground">{dimLabel}</div>
                      <div className="flex flex-wrap gap-1.5">
                        {dimSigs.map((s, i) => (
                          <SignalBadge key={`${s.candidate_code}-${s.dimension}-${s.label}-${i}`} s={s} />
                        ))}
                        {!dimSigs.length && (
                          <span className="text-xs text-muted-foreground">无</span>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>

              {/* 候选池 */}
              {overview?.candidate_pool && overview.candidate_pool.length > 0 && (
                <CandidatePoolBlock pool={overview.candidate_pool} />
              )}
            </GlassCard>
          ) : null}

          {/* 账户 + 持仓建议 只读摘要 */}
          {overview && (
            <SummaryBlock
              account={overview.account_funding}
              advice={overview.advice}
            />
          )}

          {/* 历史 */}
          <HistoryBlock
            tradeDate={tradeDate}
            onOpen={async (planId) => {
              const p = await getPlan(planId);
              if (p) {
                setPlan(p);
                setTradeDate(p.trade_date);
              }
            }}
          />

          {/* AI 解读兜底说明 */}
          {overview && !llm && (
            <GlassCard className="text-xs text-muted-foreground">
              <AlertTriangle className="mb-1 inline h-3.5 w-3.5" />{" "}
              未配置 AI（接入 AI）时，计划解释使用确定性摘要；配置 AI 后可生成自然语言解读。
            </GlassCard>
          )}
        </div>
      ) : null}
    </div>
  );
}

// ---------------------------------------------------------------------------
// 子组件
// ---------------------------------------------------------------------------

function TodayPlaceholder() {
  return (
    <GlassCard className="flex flex-col items-center gap-2 py-12 text-center">
      <Clock className="h-10 w-10 text-muted-foreground/40" />
      <h2 className="text-base font-semibold">今日实时行动</h2>
      <p className="max-w-md text-sm text-muted-foreground">
        该模块将在后续 PR B 建设。本期 PR A 聚焦「明日行动计划」：基于收盘后
        候选池与多维度确定性信号，生成次日的可执行计划草稿。
      </p>
    </GlassCard>
  );
}

function CandidatePoolBlock({ pool }: { pool: Candidate[] }) {
  const [open, setOpen] = useState(false);
  const preview = pool.slice(0, 12);
  return (
    <div>
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1 text-xs font-semibold text-muted-foreground hover:text-foreground"
      >
        <Layers className="h-3.5 w-3.5" />
        候选池（{pool.length} 只）
        <ChevronRight className={cn("h-3.5 w-3.5 transition-transform", open && "rotate-90")} />
      </button>
      {open && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {pool.map((c) => (
            <span key={c.code} className="rounded bg-muted px-2 py-0.5 text-xs">
              <span className="font-mono">{c.code}</span>
              {c.name && <span className="ml-1 text-muted-foreground">{c.name}</span>}
              <span className="ml-1 text-[10px] text-muted-foreground/70">{c.sources.join("/")}</span>
            </span>
          ))}
          {preview.length < pool.length && (
            <span className="text-xs text-muted-foreground">…其余 {pool.length - preview.length} 只</span>
          )}
        </div>
      )}
    </div>
  );
}

function SummaryBlock({ account, advice }: { account: Overview["account_funding"]; advice: Overview["advice"] }) {
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      <GlassCard>
        <h3 className="mb-2 flex items-center gap-1 text-xs font-semibold text-muted-foreground">
          <ShieldCheck className="h-3.5 w-3.5" /> 账户资金（只读）
        </h3>
        {!account.configured ? (
          <p className="text-xs text-muted-foreground" data-testid="cash-unconfigured">
            未配置。请到「我的持仓」填写账户总资产与可用现金。现金可执行性将标记为 cash_unconfigured。
          </p>
        ) : (
          <div className="grid grid-cols-2 gap-2 text-xs">
            <span className="text-muted-foreground">总资产</span><span className="font-mono">{account.data.total_assets}</span>
            <span className="text-muted-foreground">可用现金</span><span className="font-mono">{account.data.available_cash}</span>
            <span className="text-muted-foreground">更新时间</span><span className="font-mono">{account.data.updated_at}</span>
          </div>
        )}
      </GlassCard>
      <GlassCard>
        <h3 className="mb-2 flex items-center gap-1 text-xs font-semibold text-muted-foreground">
          <History className="h-3.5 w-3.5" /> 持仓建议（只读摘要）
        </h3>
        {!advice ? (
          <p className="text-xs text-muted-foreground">暂无持仓建议。请到「我的持仓」生成。</p>
        ) : (
          <div className="grid grid-cols-2 gap-2 text-xs" data-testid="advice-summary">
            <span className="text-muted-foreground">类型</span>
            <span className="font-mono">{advice.result_type ?? "portfolio_advice"}</span>
            <span className="text-muted-foreground">交易日</span>
            <span className="font-mono">{advice.trade_date ?? "—"}</span>
            <span className="text-muted-foreground">版本</span>
            <span className="font-mono">{advice.schema_version ?? "—"}</span>
            <span className="text-muted-foreground">生成时间</span>
            <span className="font-mono">{advice.generated_at ?? "—"}</span>
            <span className="text-muted-foreground">指纹</span>
            <span className="font-mono truncate" title={advice.input_fingerprint ?? ""}>
              {advice.input_fingerprint ? String(advice.input_fingerprint).slice(0, 12) + "…" : "—"}
            </span>
            <span className="text-muted-foreground">payload</span>
            <span className="font-mono truncate" title={advice.payload_hash ?? ""}>
              {advice.payload_hash ? String(advice.payload_hash).slice(0, 12) + "…" : "—"}
            </span>
            <span className="text-muted-foreground">状态</span>
            <span className={cn("font-mono", advice.stale ? "text-danger" : "text-success")}>
              {advice.stale ? "已过期" : "有效"}
            </span>
          </div>
        )}
      </GlassCard>
    </div>
  );
}

function HistoryBlock({ tradeDate, onOpen }: { tradeDate: string; onOpen: (id: number) => void }) {
  const [items, setItems] = useState<TomorrowPlanMeta[]>([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      setItems(await listPlans({ trade_date: tradeDate, limit: 20 }));
    } finally { setLoading(false); }
  };

  useEffect(() => {
    if (open) load();
  }, [open, tradeDate]);

  return (
    <GlassCard>
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between text-sm font-semibold"
      >
        <span className="flex items-center gap-1">
          <History className="h-4 w-4 text-muted-foreground" /> 历史版本
        </span>
        <ChevronRight className={cn("h-4 w-4 text-muted-foreground transition-transform", open && "rotate-90")} />
      </button>
      {open && (
        <div className="mt-2 space-y-1">
          {loading && <p className="text-xs text-muted-foreground">加载中…</p>}
          {!loading && items.length === 0 && <p className="text-xs text-muted-foreground">暂无历史版本</p>}
          {items.map((it) => (
            <button
              key={it.id}
              onClick={() => onOpen(it.id)}
              className="flex w-full items-center justify-between rounded px-2 py-1.5 text-xs transition-colors hover:bg-muted"
            >
              <span className="font-mono">v{it.version} · {it.trade_date}</span>
              <span className={cn("rounded px-1.5 py-0.5 text-[10px] font-medium",
                it.status === "frozen" ? "bg-success/10 text-success" :
                it.status === "draft" ? "bg-primary/10 text-primary" :
                "bg-muted text-muted-foreground")}
              >
                {it.status}
              </span>
            </button>
          ))}
        </div>
      )}
    </GlassCard>
  );
}

function buildPlanContext(plan: TomorrowPlanMeta & { signals?: Signal[] }, strong: number, weak: number): string {
  const byCode: Record<string, Signal[]> = {};
  for (const s of (plan as any).signals ?? []) {
    (byCode[s.candidate_code] ||= []).push(s);
  }
  const lines = [
    `明日计划 v${plan.version}（${plan.status}，${plan.trade_date}）。`,
    `信号 ${plan.signals?.length ?? 0} 条（强 ${strong} / 弱 ${weak}）。`,
  ];
  for (const [code, sigs] of Object.entries(byCode)) {
    const parts = sigs.map((s) => `${s.dimension}/${s.label}=${s.assessment}`).join("；");
    lines.push(`${code}: ${parts}`);
  }
  return lines.join("\n");
}
