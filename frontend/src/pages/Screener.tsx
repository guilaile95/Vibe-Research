import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Filter, Loader2, Play, Plus, Trash2, ChevronDown, ChevronRight,
  AlertCircle, CheckCircle2, XCircle, HelpCircle,
} from "lucide-react";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import { cn } from "@/lib/utils";
import { api, ApiError } from "@/lib/api";
import type { ScreenerCondition, ScreenerConditionId, ScreenerEvaluateResult, ScreenerStockResult } from "@/lib/api/types";
import { loadWatchAuthoritative } from "@/lib/watchlist";
import {
  CONDITION_CATALOG,
  MAX_CODES,
  ScreenerRequestGate,
  buildEvaluatePayload,
  conditionLabel,
  defaultCondition,
  groupResults,
  loadSourceCodes,
  normalizeCodes,
  parseCodeDraft,
  type ScreenerUiPhase,
  validateScreenerDraft,
} from "@/lib/screenerView";

function BucketBadge({ bucket }: { bucket: string }) {
  if (bucket === "matched") {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-emerald-500/15 px-2 py-0.5 text-[11px] font-medium text-emerald-400">
        <CheckCircle2 className="h-3 w-3" /> 命中
      </span>
    );
  }
  if (bucket === "rejected") {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-rose-500/15 px-2 py-0.5 text-[11px] font-medium text-rose-400">
        <XCircle className="h-3 w-3" /> 未命中
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-amber-500/15 px-2 py-0.5 text-[11px] font-medium text-amber-400">
      <HelpCircle className="h-3 w-3" /> 不可评估
    </span>
  );
}

function StockRow({ stock }: { stock: ScreenerStockResult }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="border-b border-border/40 last:border-0">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-muted/30"
      >
        {open ? <ChevronDown className="h-3.5 w-3.5 shrink-0" /> : <ChevronRight className="h-3.5 w-3.5 shrink-0" />}
        <span className="font-mono font-medium">{stock.code}</span>
        <BucketBadge bucket={stock.bucket} />
        <span className="text-xs text-muted-foreground">{stock.trade_date || "—"}</span>
        <span className="ml-auto text-xs text-muted-foreground">{stock.technical_status}</span>
      </button>
      {open && (
        <div className="space-y-1.5 bg-muted/10 px-4 py-2 text-xs">
          {stock.limitations?.length > 0 && (
            <p className="text-amber-400">{stock.limitations.join("；")}</p>
          )}
          {(stock.condition_results || []).map((cr) => (
            <div key={cr.id} className="rounded border border-border/40 px-2 py-1.5">
              <div className="flex items-center gap-2">
                <span className="font-medium">{conditionLabel(cr.id)}</span>
                {!cr.evaluable ? (
                  <span className="text-amber-400">不可评估</span>
                ) : cr.passed ? (
                  <span className="text-emerald-400">通过</span>
                ) : (
                  <span className="text-rose-400">不通过</span>
                )}
              </div>
              <pre className="mt-1 overflow-x-auto text-[11px] text-muted-foreground">
                {JSON.stringify(cr.evidence || {}, null, 0)}
              </pre>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function ResultGroup({
  title,
  items,
  empty,
}: {
  title: string;
  items: ScreenerStockResult[];
  empty: string;
}) {
  return (
    <GlassCard className="overflow-hidden p-0">
      <div className="border-b border-border/40 px-3 py-2 text-sm font-medium">
        {title} <span className="text-muted-foreground">({items.length})</span>
      </div>
      {items.length === 0 ? (
        <p className="px-3 py-4 text-center text-xs text-muted-foreground">{empty}</p>
      ) : (
        items.map((s) => <StockRow key={s.code} stock={s} />)
      )}
    </GlassCard>
  );
}

export function Screener() {
  const [codeText, setCodeText] = useState("");
  const [conditions, setConditions] = useState<ScreenerCondition[]>([
    defaultCondition("price_gt_sma20"),
  ]);
  const [phase, setPhase] = useState<ScreenerUiPhase>("idle");
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ScreenerEvaluateResult | null>(null);
  const [loadHint, setLoadHint] = useState<string | null>(null);
  const [addId, setAddId] = useState<ScreenerConditionId>("rsi_between");

  const gateRef = useRef(new ScreenerRequestGate());
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      gateRef.current.abort();
    };
  }, []);

  // Direct input: full deduped list (never silently truncated)
  const codes = useMemo(() => normalizeCodes(parseCodeDraft(codeText)), [codeText]);
  const draftError = useMemo(
    () => validateScreenerDraft(codes, conditions),
    [codes, conditions],
  );
  const runDisabled = phase === "loading" || !!draftError;

  const applySourceLoad = useCallback((incoming: string[]) => {
    const loaded = loadSourceCodes(incoming, MAX_CODES);
    setCodeText(loaded.codes.join(" "));
    setLoadHint(loaded.hint);
    setError(null);
  }, []);

  const loadWatchlist = async () => {
    setLoadHint(null);
    try {
      const w = await loadWatchAuthoritative();
      applySourceLoad(w.codes || []);
    } catch (e) {
      setLoadHint(e instanceof ApiError ? e.message : "载入自选股失败");
    }
  };

  const loadHoldings = async () => {
    setLoadHint(null);
    try {
      const pf = await api.portfolio();
      const hs = (pf?.holdings || []).map((h) => h.code).filter(Boolean);
      applySourceLoad(hs);
    } catch (e) {
      setLoadHint(e instanceof ApiError ? e.message : "载入持仓失败");
    }
  };

  const loadSectorReps = async () => {
    setLoadHint(null);
    try {
      const res = await api.getScreenerSectorRepresentatives();
      applySourceLoad(res.codes || []);
    } catch (e) {
      setLoadHint(e instanceof ApiError ? e.message : "载入板块代表失败");
    }
  };

  const addCondition = () => {
    if (conditions.some((c) => c.id === addId)) {
      setError("条件 id 不能重复");
      return;
    }
    if (conditions.length >= 20) {
      setError("最多 20 个条件");
      return;
    }
    setError(null);
    setConditions((cs) => [...cs, defaultCondition(addId)]);
  };

  const removeCondition = (id: string) => {
    setConditions((cs) => cs.filter((c) => c.id !== id));
  };

  const updateConditionParams = (id: string, patch: Record<string, number>) => {
    setConditions((cs) =>
      cs.map((c) => (c.id === id ? { ...c, params: { ...c.params, ...patch } } : c)),
    );
  };

  const run = async () => {
    // Direct input overflow / invalid draft: block POST (no silent truncate)
    if (draftError) {
      setError(draftError);
      return;
    }

    const token = gateRef.current.beginIfIdle(phase);
    if (!token) return; // single-flight: ignore double click while loading

    setPhase("loading");
    setError(null);

    try {
      const payload = buildEvaluatePayload(codes, conditions);
      const res = await api.evaluateScreener(payload, token.signal);
      if (!mountedRef.current || !gateRef.current.isCurrent(token.generation)) return;
      setResult(res);
      setPhase("success");
    } catch (e) {
      if (!mountedRef.current || !gateRef.current.isCurrent(token.generation)) return;
      if (e instanceof DOMException && e.name === "AbortError") {
        setPhase("idle");
        return;
      }
      // Preserve codes + conditions draft on error
      setError(e instanceof ApiError ? e.message : "筛选失败");
      setPhase("error");
    } finally {
      gateRef.current.end(token.generation);
    }
  };

  const groups = groupResults(result);

  return (
    <div className="space-y-4">
      <PageHeader
        title="信号筛选"
        subtitle="对自选/持仓/板块代表等候选代码做技术条件 AND 筛选（不产生交易建议）"
      />

      <GlassCard className="space-y-3 p-4">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm font-medium">股票代码</span>
          <span
            className={cn(
              "text-xs",
              codes.length > MAX_CODES ? "font-medium text-destructive" : "text-muted-foreground",
            )}
          >
            已解析 {codes.length}/{MAX_CODES}
          </span>
          <div className="ml-auto flex flex-wrap gap-2">
            <button type="button" onClick={loadWatchlist} className="rounded-lg border border-border px-2.5 py-1 text-xs hover:bg-muted/40">
              从自选股载入
            </button>
            <button type="button" onClick={loadHoldings} className="rounded-lg border border-border px-2.5 py-1 text-xs hover:bg-muted/40">
              从持仓载入
            </button>
            <button type="button" onClick={loadSectorReps} className="rounded-lg border border-border px-2.5 py-1 text-xs hover:bg-muted/40">
              从板块代表载入
            </button>
          </div>
        </div>
        <textarea
          value={codeText}
          onChange={(e) => setCodeText(e.target.value)}
          rows={3}
          placeholder="粘贴六位代码，空格/逗号/换行分隔，例如 000001 600519"
          className="w-full rounded-lg border border-border bg-background px-3 py-2 font-mono text-sm outline-none focus:ring-1 focus:ring-primary"
        />
        {loadHint && <p className="text-xs text-muted-foreground">{loadHint}</p>}
      </GlassCard>

      <GlassCard className="space-y-3 p-4">
        <div className="flex items-center gap-2 text-sm font-medium">
          <Filter className="h-4 w-4" /> 筛选条件（AND）
        </div>
        <div className="space-y-2">
          {conditions.map((c) => {
            const meta = CONDITION_CATALOG.find((x) => x.id === c.id);
            return (
              <div key={c.id} className="flex flex-wrap items-center gap-2 rounded-lg border border-border/50 px-3 py-2 text-sm">
                <span className="font-medium">{meta?.label || c.id}</span>
                {meta?.needsParams === "rsi" && (
                  <>
                    <label className="text-xs text-muted-foreground">min</label>
                    <input
                      type="number"
                      value={c.params?.min ?? 30}
                      onChange={(e) => updateConditionParams(c.id, { min: Number(e.target.value) })}
                      className="w-20 rounded border border-border bg-background px-2 py-1 text-xs"
                    />
                    <label className="text-xs text-muted-foreground">max</label>
                    <input
                      type="number"
                      value={c.params?.max ?? 70}
                      onChange={(e) => updateConditionParams(c.id, { max: Number(e.target.value) })}
                      className="w-20 rounded border border-border bg-background px-2 py-1 text-xs"
                    />
                  </>
                )}
                {meta?.needsParams === "threshold" && (
                  <>
                    <label className="text-xs text-muted-foreground">threshold</label>
                    <input
                      type="number"
                      step="0.1"
                      value={c.params?.threshold ?? 1.5}
                      onChange={(e) => updateConditionParams(c.id, { threshold: Number(e.target.value) })}
                      className="w-24 rounded border border-border bg-background px-2 py-1 text-xs"
                    />
                  </>
                )}
                <button
                  type="button"
                  onClick={() => removeCondition(c.id)}
                  className="ml-auto text-muted-foreground hover:text-destructive"
                  aria-label={`删除条件 ${c.id}`}
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>
            );
          })}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <select
            value={addId}
            onChange={(e) => setAddId(e.target.value as ScreenerConditionId)}
            className="rounded-lg border border-border bg-background px-2 py-1.5 text-xs"
          >
            {CONDITION_CATALOG.map((c) => (
              <option key={c.id} value={c.id}>{c.label}</option>
            ))}
          </select>
          <button
            type="button"
            onClick={addCondition}
            className="inline-flex items-center gap-1 rounded-lg border border-border px-2.5 py-1.5 text-xs hover:bg-muted/40"
          >
            <Plus className="h-3.5 w-3.5" /> 添加条件
          </button>
          <button
            type="button"
            onClick={run}
            disabled={runDisabled}
            className={cn(
              "ml-auto inline-flex items-center gap-1.5 rounded-lg bg-primary/15 px-3 py-1.5 text-sm font-medium text-primary hover:bg-primary/25 disabled:opacity-50",
            )}
          >
            {phase === "loading" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
            {phase === "loading" ? "筛选中…" : "运行筛选"}
          </button>
        </div>
        {(error || (codes.length > MAX_CODES && draftError)) && (
          <div className="flex items-center gap-1.5 rounded bg-destructive/10 p-2 text-xs text-destructive">
            <AlertCircle className="h-3.5 w-3.5 shrink-0" /> {error || draftError}
          </div>
        )}
        {!error && draftError && codes.length <= MAX_CODES && (
          <div className="flex items-center gap-1.5 rounded bg-amber-500/10 p-2 text-xs text-amber-500">
            <AlertCircle className="h-3.5 w-3.5 shrink-0" /> {draftError}
          </div>
        )}
      </GlassCard>

      {(phase === "success" || result) && (
        <div className="grid gap-3 lg:grid-cols-3">
          <ResultGroup title="命中" items={groups.matched} empty="无命中" />
          <ResultGroup title="未命中" items={groups.rejected} empty="无未命中" />
          <ResultGroup title="不可评估" items={groups.unavailable} empty="无不可评估" />
        </div>
      )}
      {result && (
        <p className="text-xs text-muted-foreground">
          顶层状态 {result.status} · 评估于 {result.evaluated_at} · 逻辑 {result.logic}
        </p>
      )}
    </div>
  );
}
