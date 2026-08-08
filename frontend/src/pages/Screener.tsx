import { useMemo, useRef, useState } from "react";
import { AlertCircle, Filter, Loader2, Play, Plus, Trash2 } from "lucide-react";
import { Link } from "react-router-dom";

import { GlassCard } from "@/components/ui/GlassCard";
import { PageHeader } from "@/components/ui/PageHeader";
import { api, ApiError } from "@/lib/api";
import { recoveredMarketApi } from "@/lib/recoveredMarketApi";
import type {
  ScreenerCondition,
  ScreenerConditionId,
  ScreenerStockResult,
} from "@/lib/recoveredMarketTypes";
import {
  CONDITION_CATALOG,
  MAX_CODES,
  buildEvaluatePayload,
  defaultCondition,
  groupResults,
  loadSourceCodes,
  normalizeCodes,
  parseCodeDraft,
  validateScreenerDraft,
} from "@/lib/recoveredScreener";
import { loadWatchAuthoritative } from "@/lib/watchlist";

function ResultGroup({ title, items }: { title: string; items: ScreenerStockResult[] }) {
  return (
    <GlassCard className="overflow-hidden p-0">
      <div className="border-b border-border/50 px-4 py-3 text-sm font-medium">
        {title} <span className="text-muted-foreground">({items.length})</span>
      </div>
      {items.length === 0 ? (
        <p className="px-4 py-6 text-center text-xs text-muted-foreground">暂无</p>
      ) : (
        <div className="divide-y divide-border/40">
          {items.map((item) => (
            <details key={`${title}-${item.code}`} className="group px-4 py-3">
              <summary className="flex cursor-pointer list-none items-center gap-3 text-sm">
                <span className="font-mono font-medium">{item.code}</span>
                <span className="text-xs text-muted-foreground">{item.trade_date || "—"}</span>
                <span className="ml-auto text-xs text-muted-foreground">{item.technical_status}</span>
              </summary>
              <div className="mt-3 space-y-2 text-xs text-muted-foreground">
                {item.limitations?.map((line) => <p key={line}>{line}</p>)}
                {item.condition_results?.map((condition) => (
                  <div key={condition.id} className="rounded-lg border border-border/50 px-3 py-2">
                    <div className="flex items-center justify-between gap-3">
                      <span>{condition.id}</span>
                      <span>{condition.evaluable ? (condition.passed ? "通过" : "不通过") : "不可评估"}</span>
                    </div>
                    {Object.keys(condition.evidence || {}).length > 0 ? (
                      <pre className="mt-2 overflow-x-auto whitespace-pre-wrap text-[11px]">
                        {JSON.stringify(condition.evidence)}
                      </pre>
                    ) : null}
                  </div>
                ))}
              </div>
            </details>
          ))}
        </div>
      )}
    </GlassCard>
  );
}

export function Screener() {
  const [codeText, setCodeText] = useState("");
  const [conditions, setConditions] = useState<ScreenerCondition[]>([
    defaultCondition("price_gt_sma20"),
  ]);
  const [addId, setAddId] = useState<ScreenerConditionId>("rsi_between");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hint, setHint] = useState<string | null>(null);
  const [result, setResult] = useState<Awaited<ReturnType<typeof recoveredMarketApi.evaluateScreener>> | null>(null);
  const controllerRef = useRef<AbortController | null>(null);

  const codes = useMemo(() => normalizeCodes(parseCodeDraft(codeText)), [codeText]);
  const draftError = useMemo(() => validateScreenerDraft(codes, conditions), [codes, conditions]);
  const groups = groupResults(result);

  const applySource = (incoming: string[]) => {
    const loaded = loadSourceCodes(incoming);
    setCodeText(loaded.codes.join(" "));
    setHint(loaded.hint);
    setError(null);
  };

  const loadWatchlist = async () => {
    try {
      const watch = await loadWatchAuthoritative();
      applySource(watch.codes || []);
    } catch {
      setHint("载入自选股失败");
    }
  };

  const loadHoldings = async () => {
    try {
      const portfolio = await api.portfolio();
      applySource((portfolio.holdings || []).map((item) => item.code).filter(Boolean));
    } catch {
      setHint("载入持仓失败");
    }
  };

  const loadSectorReps = async () => {
    try {
      const response = await recoveredMarketApi.getScreenerSectorRepresentatives();
      applySource(response.codes || []);
    } catch {
      setHint("载入板块代表失败");
    }
  };

  const addCondition = () => {
    if (conditions.some((item) => item.id === addId)) {
      setError("条件 id 不能重复");
      return;
    }
    setError(null);
    setHint(null);
    setConditions((current) => [...current, defaultCondition(addId)]);
  };

  const updateParams = (id: ScreenerConditionId, patch: Record<string, number>) => {
    setHint(null);
    setConditions((current) => current.map((item) => (
      item.id === id ? { ...item, params: { ...item.params, ...patch } } : item
    )));
  };

  const run = async () => {
    if (loading || draftError) {
      if (draftError) setError(draftError);
      return;
    }
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    setLoading(true);
    setError(null);
    setHint(null);
    try {
      const payload = buildEvaluatePayload(codes, conditions);
      const next = await recoveredMarketApi.evaluateScreener(payload, controller.signal);
      if (!controller.signal.aborted) setResult(next);
    } catch (cause) {
      if (controller.signal.aborted) return;
      setError(cause instanceof ApiError ? cause.message : "筛选失败");
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  };

  return (
    <div className="space-y-5">
      <PageHeader
        title="信号筛选"
        subtitle="对候选代码执行技术条件 AND 筛选；结果用于研究，不产生交易建议。"
      />

      <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        <span>恢复自历史功能链 · 最多 {MAX_CODES} 个代码</span>
        <span>·</span>
        <Link className="hover:text-foreground" to="/market-history">查看北向成交历史</Link>
      </div>

      <GlassCard className="space-y-3 p-4">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm font-medium">股票代码</span>
          <span className="text-xs text-muted-foreground">已解析 {codes.length}/{MAX_CODES}</span>
          <div className="ml-auto flex flex-wrap gap-2">
            <button type="button" onClick={loadWatchlist} className="rounded-lg border border-border px-2.5 py-1 text-xs hover:bg-muted/50">从自选股载入</button>
            <button type="button" onClick={loadHoldings} className="rounded-lg border border-border px-2.5 py-1 text-xs hover:bg-muted/50">从持仓载入</button>
            <button type="button" onClick={loadSectorReps} className="rounded-lg border border-border px-2.5 py-1 text-xs hover:bg-muted/50">从板块代表载入</button>
          </div>
        </div>
        <textarea
          value={codeText}
          onChange={(event) => {
            setCodeText(event.target.value);
            setHint(null);
          }}
          rows={3}
          placeholder="000001 600519"
          className="w-full rounded-lg border border-border bg-background px-3 py-2 font-mono text-sm outline-none focus:ring-1 focus:ring-ring"
        />
        {hint ? <p className="text-xs text-muted-foreground">{hint}</p> : null}
      </GlassCard>

      <GlassCard className="space-y-3 p-4">
        <div className="flex items-center gap-2 text-sm font-medium"><Filter className="h-4 w-4" />筛选条件（AND）</div>
        <div className="space-y-2">
          {conditions.map((condition) => {
            const meta = CONDITION_CATALOG.find((item) => item.id === condition.id);
            return (
              <div key={condition.id} className="flex flex-wrap items-center gap-2 rounded-lg border border-border/50 px-3 py-2 text-sm">
                <span className="font-medium">{meta?.label || condition.id}</span>
                {meta?.needsParams === "rsi" ? (
                  <>
                    <input aria-label="RSI min" type="number" value={condition.params?.min ?? 30} onChange={(e) => updateParams(condition.id, { min: Number(e.target.value) })} className="w-20 rounded border border-border bg-background px-2 py-1 text-xs" />
                    <span className="text-xs text-muted-foreground">至</span>
                    <input aria-label="RSI max" type="number" value={condition.params?.max ?? 70} onChange={(e) => updateParams(condition.id, { max: Number(e.target.value) })} className="w-20 rounded border border-border bg-background px-2 py-1 text-xs" />
                  </>
                ) : null}
                {meta?.needsParams === "threshold" ? (
                  <input aria-label="量比阈值" type="number" step="0.1" value={condition.params?.threshold ?? 1.5} onChange={(e) => updateParams(condition.id, { threshold: Number(e.target.value) })} className="w-24 rounded border border-border bg-background px-2 py-1 text-xs" />
                ) : null}
                <button type="button" aria-label={`删除条件 ${condition.id}`} onClick={() => setConditions((current) => current.filter((item) => item.id !== condition.id))} className="ml-auto text-muted-foreground hover:text-destructive">
                  <Trash2 className="h-4 w-4" />
                </button>
              </div>
            );
          })}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <select value={addId} onChange={(event) => setAddId(event.target.value as ScreenerConditionId)} className="rounded-lg border border-border bg-background px-2 py-1.5 text-xs">
            {CONDITION_CATALOG.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
          </select>
          <button type="button" onClick={addCondition} className="inline-flex items-center gap-1 rounded-lg border border-border px-2.5 py-1.5 text-xs hover:bg-muted/50"><Plus className="h-3.5 w-3.5" />添加条件</button>
          <button type="button" onClick={run} disabled={loading || Boolean(draftError)} className="ml-auto inline-flex items-center gap-1.5 rounded-lg bg-foreground px-3 py-1.5 text-sm font-medium text-background disabled:opacity-40">
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
            {loading ? "筛选中…" : "运行筛选"}
          </button>
        </div>
        {(error || draftError) ? <div className="flex items-center gap-2 text-xs text-destructive"><AlertCircle className="h-4 w-4" />{error || draftError}</div> : null}
      </GlassCard>

      {result ? (
        <>
          <div className="grid gap-3 lg:grid-cols-3">
            <ResultGroup title="命中" items={groups.matched} />
            <ResultGroup title="未命中" items={groups.rejected} />
            <ResultGroup title="不可评估" items={groups.unavailable} />
          </div>
          <p className="text-xs text-muted-foreground">状态 {result.status} · {result.logic} · {result.evaluated_at}</p>
        </>
      ) : null}
    </div>
  );
}
