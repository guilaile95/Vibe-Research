import { useMemo, useRef, useState } from "react";
import { AlertCircle, Filter, Loader2, Play, Plus, Trash2 } from "lucide-react";
import { Link } from "react-router-dom";

import type {
  FullMarketFilterOperator,
  FullMarketMetric,
  FullMarketQuery,
  FullMarketResult,
} from "@/lib/recoveredMarketTypes";

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
  FULL_MARKET_FILTER_OPERATORS,
  FULL_MARKET_METRIC_CATALOG,
  MAX_CODES,
  buildEvaluatePayload,
  buildFullMarketQuery,
  defaultCondition,
  formatFullMarketMetric,
  groupResults,
  loadSourceCodes,
  normalizeCodes,
  parseCodeDraft,
  validateScreenerDraft,
} from "@/lib/recoveredScreener";
import { loadWatchAuthoritative } from "@/lib/watchlist";

type FullMarketValueMetric = Exclude<FullMarketMetric, "code" | "latest_date">;

function FullMarketResultTable({ result }: { result: FullMarketResult }) {
  const metric = (row: FullMarketResult["rows"][number], key: FullMarketValueMetric) => {
    const value = row[key];
    const status = row.metric_status?.[key];
    return status === "INSUFFICIENT_HISTORY" ? "历史不足" : formatFullMarketMetric(key, value);
  };
  return (
    <GlassCard className="overflow-hidden p-0" data-testid="full-market-results">
      <div className="border-b border-border/50 px-4 py-3 text-sm font-medium">
        Full Market 结果 <span className="text-muted-foreground">({result.total_rows})</span>
      </div>
      {result.rows.length === 0 ? (
        <p className="px-4 py-6 text-center text-xs text-muted-foreground">暂无可评估结果</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[900px] text-xs">
            <thead className="border-b border-border/40 text-left text-muted-foreground">
              <tr>
                <th className="px-4 py-2">代码</th>
                <th className="px-4 py-2">最新日期</th>
                <th className="px-4 py-2">收盘</th>
                <th className="px-4 py-2">5D</th>
                <th className="px-4 py-2">20D</th>
                <th className="px-4 py-2">60D</th>
                <th className="px-4 py-2">收盘/MA20</th>
                <th className="px-4 py-2">收盘/MA60</th>
                <th className="px-4 py-2">量比（20D均量）</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border/40">
              {result.rows.map((row) => (
                <tr key={row.code} className="hover:bg-muted/30">
                  <td className="px-4 py-2 font-mono font-medium"><Link className="hover:text-primary hover:underline" to={`/stock-data?code=${row.code}`}>{row.code}</Link></td>
                  <td className="px-4 py-2">{row.latest_date || "—"}</td>
                  <td className="px-4 py-2">{metric(row, "latest_close")}</td>
                  <td className="px-4 py-2">{metric(row, "return_5d")}</td>
                  <td className="px-4 py-2">{metric(row, "return_20d")}</td>
                  <td className="px-4 py-2">{metric(row, "return_60d")}</td>
                  <td className="px-4 py-2">{metric(row, "close_vs_ma20")}</td>
                  <td className="px-4 py-2">{metric(row, "close_vs_ma60")}</td>
                  <td className="px-4 py-2">{metric(row, "volume_ratio_20d")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </GlassCard>
  );
}

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
  const [mode, setMode] = useState<"candidate" | "full-market">("candidate");
  const [codeText, setCodeText] = useState("");
  const [conditions, setConditions] = useState<ScreenerCondition[]>([
    defaultCondition("price_gt_sma20"),
  ]);
  const [addId, setAddId] = useState<ScreenerConditionId>("rsi_between");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hint, setHint] = useState<string | null>(null);
  const [result, setResult] = useState<Awaited<ReturnType<typeof recoveredMarketApi.evaluateScreener>> | null>(null);
  const [fullMarketResult, setFullMarketResult] = useState<FullMarketResult | null>(null);
  const [fullMarketAsOf, setFullMarketAsOf] = useState("");
  const [fullMarketLatest, setFullMarketLatest] = useState(true);
  const [fullMarketMetric, setFullMarketMetric] = useState<Exclude<FullMarketMetric, "code" | "latest_date">>("return_20d");
  const [fullMarketOperator, setFullMarketOperator] = useState<FullMarketFilterOperator>("gte");
  const [fullMarketValue, setFullMarketValue] = useState("0");
  const [fullMarketSort, setFullMarketSort] = useState<FullMarketMetric>("return_20d");
  const [fullMarketSortOrder, setFullMarketSortOrder] = useState<"asc" | "desc">("desc");
  const [fullMarketOffset, setFullMarketOffset] = useState(0);
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

  const runFullMarket = async (offset = fullMarketOffset) => {
    if (loading) return;
    const numericValue = Number(fullMarketValue);
    if (!Number.isFinite(numericValue)) {
      setFullMarketResult(null);
      setError("全市场阈值必须是有效数字");
      return;
    }
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    setFullMarketResult(null);
    setLoading(true);
    setError(null);
    setHint(null);
    try {
      const query: FullMarketQuery = buildFullMarketQuery({
        as_of: fullMarketAsOf || undefined,
        latest: fullMarketLatest,
        filter_metric: fullMarketMetric,
        filter_operator: fullMarketOperator,
        filter_value: numericValue,
        sort_by: fullMarketSort,
        sort_order: fullMarketSortOrder,
        limit: 50,
        offset,
      });
      const next = await recoveredMarketApi.getFullMarket(query, controller.signal);
      if (!controller.signal.aborted && controllerRef.current === controller) {
        setFullMarketResult(next);
        setFullMarketOffset(offset);
      }
    } catch (cause) {
      if (controller.signal.aborted) return;
      setFullMarketResult(null);
      setError(cause instanceof ApiError ? cause.message : cause instanceof Error ? cause.message : "全市场查询失败");
    } finally {
      if (controllerRef.current === controller) {
        controllerRef.current = null;
        setLoading(false);
      }
    }
  };

  const switchMode = (nextMode: "candidate" | "full-market") => {
    controllerRef.current?.abort();
    controllerRef.current = null;
    setLoading(false);
    setFullMarketResult(null);
    setMode(nextMode);
    setError(null);
    setHint(null);
  };

  return (
    <div className="space-y-5">
      <PageHeader
        title="信号筛选"
        subtitle={mode === "candidate" ? "对候选代码执行技术条件 AND 筛选；结果用于研究，不产生交易建议。" : "基于本地 RDP artifact 的有界全市场横截面；结果用于研究，不产生交易建议。"}
      />

      <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        <span>{mode === "candidate" ? `恢复自历史功能链 · 最多 ${MAX_CODES} 个代码` : "Full Market · set-based · 不回退逐票请求"}</span>
        <span>·</span>
        <Link className="hover:text-foreground" to="/market-history">查看北向成交历史</Link>
      </div>

      <div className="flex gap-1 rounded-xl border border-border/60 bg-muted/20 p-1" role="tablist" aria-label="筛选模式">
        <button type="button" role="tab" aria-selected={mode === "candidate"} data-testid="candidate-pool-tab" onClick={() => switchMode("candidate")} className={`rounded-lg px-3 py-1.5 text-sm ${mode === "candidate" ? "bg-background font-medium shadow-sm" : "text-muted-foreground hover:text-foreground"}`}>
          Candidate Pool
        </button>
        <button type="button" role="tab" aria-selected={mode === "full-market"} data-testid="full-market-tab" onClick={() => switchMode("full-market")} className={`rounded-lg px-3 py-1.5 text-sm ${mode === "full-market" ? "bg-background font-medium shadow-sm" : "text-muted-foreground hover:text-foreground"}`}>
          Full Market
        </button>
      </div>

      {mode === "candidate" ? (
        <>
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
        </>
      ) : (
        <GlassCard className="space-y-4 p-4" data-testid="full-market-form">
          <div className="flex flex-wrap items-center gap-3">
            <label className="inline-flex items-center gap-2 text-sm">
              <input type="checkbox" checked={fullMarketLatest} onChange={(event) => setFullMarketLatest(event.target.checked)} />
              使用最新可用日期
            </label>
            {!fullMarketLatest ? (
              <label className="flex items-center gap-2 text-xs text-muted-foreground">
                As of
                <input aria-label="Full Market as of" type="date" value={fullMarketAsOf} onChange={(event) => setFullMarketAsOf(event.target.value)} className="rounded border border-border bg-background px-2 py-1 text-xs text-foreground" />
              </label>
            ) : null}
          </div>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <label className="space-y-1 text-xs text-muted-foreground">
              筛选指标
              <select aria-label="Full Market filter metric" value={fullMarketMetric} onChange={(event) => setFullMarketMetric(event.target.value as FullMarketValueMetric)} className="w-full rounded-lg border border-border bg-background px-2 py-1.5 text-xs text-foreground">
                {FULL_MARKET_METRIC_CATALOG.filter((item) => item.id !== "latest_date" && item.id !== "code").map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
              </select>
            </label>
            <label className="space-y-1 text-xs text-muted-foreground">
              运算符
              <select aria-label="Full Market filter operator" value={fullMarketOperator} onChange={(event) => setFullMarketOperator(event.target.value as FullMarketFilterOperator)} className="w-full rounded-lg border border-border bg-background px-2 py-1.5 text-xs text-foreground">
                {FULL_MARKET_FILTER_OPERATORS.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
              </select>
            </label>
            <label className="space-y-1 text-xs text-muted-foreground">
              阈值
              <input aria-label="Full Market filter value" type="number" step="any" value={fullMarketValue} onChange={(event) => setFullMarketValue(event.target.value)} className="w-full rounded-lg border border-border bg-background px-2 py-1.5 text-xs text-foreground" />
            </label>
            <label className="space-y-1 text-xs text-muted-foreground">
              排序指标
              <select aria-label="Full Market sort metric" value={fullMarketSort} onChange={(event) => setFullMarketSort(event.target.value as FullMarketMetric)} className="w-full rounded-lg border border-border bg-background px-2 py-1.5 text-xs text-foreground">
                {FULL_MARKET_METRIC_CATALOG.filter((item) => item.id !== "latest_date" && item.id !== "code").map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
                <option value="code">代码</option>
              </select>
            </label>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <label className="flex items-center gap-2 text-xs text-muted-foreground">
              排序方向
              <select aria-label="Full Market sort order" value={fullMarketSortOrder} onChange={(event) => setFullMarketSortOrder(event.target.value as "asc" | "desc")} className="rounded-lg border border-border bg-background px-2 py-1.5 text-xs text-foreground">
                <option value="desc">降序</option><option value="asc">升序</option>
              </select>
            </label>
            <button type="button" data-testid="run-full-market" onClick={() => runFullMarket(0)} disabled={loading} className="ml-auto inline-flex items-center gap-1.5 rounded-lg bg-foreground px-3 py-1.5 text-sm font-medium text-background disabled:opacity-40">
              {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
              {loading ? "查询中…" : "运行 Full Market"}
            </button>
          </div>
          {error ? <div className="flex items-center gap-2 text-xs text-destructive"><AlertCircle className="h-4 w-4" />{error}</div> : null}
          <p className="text-xs text-muted-foreground">当前 RDP schema 仅有 volume；不声明 turnover、amount 或 liquidity amount。历史不足保持不可评估。</p>
        </GlassCard>
      )}

      {mode === "candidate" && result ? (
        <>
          <GlassCard className="space-y-2 p-4" data-testid="screener-research-source">
            <div className="flex flex-wrap items-center gap-2 text-sm font-medium">
              <span>研究数据来源</span>
              <span className={result.research_data.status === "normal" ? "text-emerald-600" : "text-destructive"}>
                {result.research_data.status === "normal" ? "可用" : "不可评估"}
              </span>
            </div>
            <div className="grid gap-1 text-xs text-muted-foreground sm:grid-cols-2 lg:grid-cols-4">
              <span>Dataset：{result.research_data.dataset_id}</span>
              <span>Provider：{result.research_data.provider_id}</span>
              <span>调整：{result.research_data.adjustment}</span>
              <span>As of：{result.research_data.as_of || "未知"}</span>
            </div>
            {result.research_data.coverage ? (
              <p className="text-xs text-muted-foreground">
                覆盖：{String(result.research_data.coverage.start || "未知")} 至 {String(result.research_data.coverage.end || "未知")} · {String(result.research_data.coverage.row_count || 0)} 行 · {String(result.research_data.coverage.code_count || 0)} 个代码
              </p>
            ) : (
              <p className="text-xs text-destructive">无本地研究数据，当前结果不可评估。</p>
            )}
            <p className="text-xs text-muted-foreground">
              Artifact：{String(result.research_data.provenance.artifact_sha256 || result.research_data.provenance.source_name || "未提供")}
            </p>
            {result.research_data.limitations.map((line) => <p key={line} className="text-xs text-muted-foreground">{line}</p>)}
          </GlassCard>
          <div className="grid gap-3 lg:grid-cols-3">
            <ResultGroup title="命中" items={groups.matched} />
            <ResultGroup title="未命中" items={groups.rejected} />
            <ResultGroup title="不可评估" items={groups.unavailable} />
          </div>
          <p className="text-xs text-muted-foreground">状态 {result.status} · {result.logic} · {result.evaluated_at}</p>
        </>
      ) : null}

      {mode === "full-market" && fullMarketResult ? (
        <>
          <GlassCard className="space-y-3 p-4" data-testid="full-market-summary">
            <div className="flex flex-wrap items-center gap-2 text-sm font-medium">
              <span>Full Market 数据</span>
              <span className={fullMarketResult.status === "normal" ? "text-emerald-600" : "text-destructive"}>{fullMarketResult.status === "normal" ? "可用" : "不可用"}</span>
              <span className="text-xs text-muted-foreground">As of：{fullMarketResult.as_of || "未知"}</span>
            </div>
            {fullMarketResult.coverage ? (
              <p className="text-xs text-muted-foreground">覆盖：{fullMarketResult.coverage.start} 至 {fullMarketResult.coverage.end} · {fullMarketResult.coverage.row_count} 行 · {fullMarketResult.coverage.code_count} 个代码 · 当前横截面 {fullMarketResult.coverage.universe_count} 个代码</p>
            ) : <p className="text-xs text-destructive">RDP 不可用，Full Market 不可用；没有逐票请求回退。</p>}
            <div className="grid gap-2 text-xs sm:grid-cols-2">
              {(["ma20", "ma60"] as const).map((key) => {
                const breadth = fullMarketResult.breadth[key];
                return <span key={key}>Breadth {key.toUpperCase()}：{breadth.breadth == null ? "不可评估" : `${(breadth.breadth * 100).toFixed(1)}%`} · 可评估 {breadth.evaluable_count} · 历史不足 {breadth.insufficient_count}</span>;
              })}
            </div>
            <p className="text-xs text-muted-foreground">Artifact：{fullMarketResult.provenance.artifact_sha256 || "未提供"} · Source：{fullMarketResult.provenance.source_name || fullMarketResult.provenance.source_kind || "未知"}</p>
            {fullMarketResult.limitations.map((line) => <p key={line} className="text-xs text-muted-foreground">{line}</p>)}
          </GlassCard>
          <FullMarketResultTable result={fullMarketResult} />
          <div className="flex items-center justify-between text-xs text-muted-foreground">
            <span>显示 {fullMarketResult.returned_rows} / {fullMarketResult.total_rows}</span>
            <div className="flex gap-2">
              <button type="button" onClick={() => runFullMarket(Math.max(0, fullMarketOffset - 50))} disabled={loading || fullMarketOffset === 0} className="rounded-lg border border-border px-2.5 py-1.5 disabled:opacity-40">上一页</button>
              <button type="button" onClick={() => fullMarketResult.next_offset != null && runFullMarket(fullMarketResult.next_offset)} disabled={loading || fullMarketResult.next_offset == null} className="rounded-lg border border-border px-2.5 py-1.5 disabled:opacity-40">下一页</button>
            </div>
          </div>
        </>
      ) : null}
    </div>
  );
}
