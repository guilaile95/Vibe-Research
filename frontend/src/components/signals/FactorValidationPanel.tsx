import { useEffect, useState } from "react";
import { AlertCircle, Database, FlaskConical, Loader2, ShieldAlert, Table2 } from "lucide-react";
import { api, ApiError, type FactorValidationReport, type FactorValidationRequest } from "@/lib/api";
import { cn } from "@/lib/utils";
import {
  factorAggregateLabel,
  factorIcText,
  factorObservationHasCoverageLimitation,
  factorRatioText,
  factorValidationReasonLabel,
  factorReturnText,
  factorValidationStatusLabel,
} from "@/lib/factorValidationView";

const WINDOWS = [5, 20];

function FactorMetric({ label, value, format }: { label: string; value: number | null | undefined; format: (value: number | null | undefined) => string }) {
  return (
    <div className="rounded-lg border border-border/60 bg-background/40 p-3">
      <div className="text-[11px] text-muted-foreground">{label}</div>
      <div className="mt-1 font-mono text-lg font-semibold">{format(value)}</div>
    </div>
  );
}

export function FactorValidationPanel() {
  const [registry, setRegistry] = useState<FactorValidationReport["factor"][] | null>(null);
  const [selectedFactor, setSelectedFactor] = useState("return_5d");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [report, setReport] = useState<FactorValidationReport | null>(null);
  const [activeWindow, setActiveWindow] = useState("5");
  const [loadingRegistry, setLoadingRegistry] = useState(true);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let mounted = true;
    api.factorValidationRegistry()
      .then((payload) => {
        if (!mounted) return;
        setRegistry(payload.factors);
        if (payload.factors.length && !payload.factors.some((factor) => factor.factor_id === selectedFactor)) {
          setSelectedFactor(payload.factors[0].factor_id);
        }
      })
      .catch((reason) => {
        if (mounted) setError(reason instanceof ApiError ? reason.message : "因子目录加载失败");
      })
      .finally(() => mounted && setLoadingRegistry(false));
    return () => { mounted = false; };
  }, []);

  const evaluate = async (payload: FactorValidationRequest, persist: boolean) => {
    setLoading(true);
    setError(null);
    try {
      const next = await api.factorValidationEvaluate({ ...payload, forward_windows: WINDOWS });
      setReport(next);
      const availableWindows = Object.keys(next.results);
      if (availableWindows.length && !availableWindows.includes(activeWindow)) setActiveWindow(availableWindows[0]);
      if (persist) {
        const params = new URLSearchParams({ factor: payload.factor_id });
        if (payload.date_from) params.set("from", payload.date_from);
        if (payload.date_to) params.set("to", payload.date_to);
        window.history.replaceState({}, "", `/signals/factor-validation?${params.toString()}`);
      }
    } catch (reason) {
      setReport(null);
      setError(reason instanceof ApiError ? reason.message : "因子有效性验证失败");
    } finally {
      setLoading(false);
    }
  };

  const submit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    void evaluate({
      factor_id: selectedFactor,
      forward_windows: WINDOWS,
      date_from: dateFrom || null,
      date_to: dateTo || null,
    }, true);
  };

  const factor = report?.factor || registry?.find((item) => item.factor_id === selectedFactor);
  const aggregate = report?.results[activeWindow] || (report ? Object.values(report.results)[0] : undefined);
  const sample = report?.sample;

  return (
    <div className="space-y-4" data-testid="factor-validation">
      <div className="rounded-xl border border-warning/40 bg-warning/10 p-4 text-sm leading-relaxed">
        <div className="flex items-center gap-2 font-semibold text-warning">
          <ShieldAlert className="h-4 w-4" /> RESEARCH ONLY · Historical validity not proven
        </div>
        <p className="mt-1 text-xs text-muted-foreground">
          因子统计只描述当前 RDP observed cross-section；不是未来预测、策略回测、交易组合或买卖建议，不会写入任何正式账本。
        </p>
      </div>

      <form onSubmit={submit} className="rounded-xl border border-border/60 bg-muted/15 p-4">
        <div className="mb-3 flex items-center gap-2 text-sm font-semibold">
          <FlaskConical className="h-4 w-4 text-primary" /> 运行因子有效性验证
        </div>
        <div className="grid gap-3 lg:grid-cols-[1fr_1fr_1fr]">
          <label className="text-xs text-muted-foreground">
            Factor
            <select aria-label="Factor" value={selectedFactor} onChange={(event) => setSelectedFactor(event.target.value)} disabled={loadingRegistry}
              className="mt-1 w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground">
              {(registry || []).map((item) => <option key={item.factor_id} value={item.factor_id}>{item.label} · {item.factor_id}</option>)}
            </select>
          </label>
          <label className="text-xs text-muted-foreground">
            样本起始日期
            <input aria-label="因子验证起始日期" type="date" value={dateFrom} onChange={(event) => setDateFrom(event.target.value)}
              className="mt-1 block w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground" />
          </label>
          <label className="text-xs text-muted-foreground">
            样本结束日期
            <input aria-label="因子验证结束日期" type="date" value={dateTo} onChange={(event) => setDateTo(event.target.value)}
              className="mt-1 block w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground" />
          </label>
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <span className="text-xs text-muted-foreground">Forward：5 / 20 条已存储观测</span>
          <button type="submit" disabled={loading || loadingRegistry || !selectedFactor}
            className="inline-flex items-center gap-1.5 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50">
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <FlaskConical className="h-4 w-4" />}
            {loading ? "计算中…" : "运行因子验证"}
          </button>
        </div>
      </form>

      {error && <div role="alert" className="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive"><AlertCircle className="mr-1 inline h-4 w-4" />{error}</div>}
      {loadingRegistry && <div role="status" className="rounded-lg border border-dashed border-border/70 p-6 text-center text-sm text-muted-foreground">正在读取透明 Factor 目录…</div>}

      {report?.status === "unavailable" && (
        <div role="status" className="rounded-xl border border-border/60 bg-muted/20 p-4 text-sm">
          <div className="flex items-center gap-2 font-medium"><Database className="h-4 w-4 text-warning" /> Research Data Plane 不可用</div>
          <p className="mt-2 text-xs text-muted-foreground">没有把缺失数据伪装成零 IC 或零 spread；请先配置可验证的 RDP artifact。</p>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-xs text-muted-foreground">{report.limitations.slice(0, 3).map((item) => <li key={item}>{item}</li>)}</ul>
        </div>
      )}

      {!report && !loadingRegistry && !error && (
        <div className="rounded-xl border border-dashed border-border/70 p-8 text-center text-sm text-muted-foreground">
          选择一个已有 RDP Factor 与样本范围后运行；页面不会自动选股、回测或写入正式状态。
        </div>
      )}

      {report?.status === "normal" && factor && aggregate && sample && (
        <div data-testid="factor-validation-results" className="space-y-4">
          <div className="rounded-xl border border-primary/25 bg-primary/5 p-4 text-sm">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="font-semibold">{factor.label} · {factor.factor_id}</div>
              <span className="rounded-full bg-primary/15 px-2 py-0.5 text-xs text-primary">Factor value parity · PROVEN</span>
            </div>
            <p className="mt-1 text-xs text-muted-foreground">source metric：<span className="font-mono">{factor.source_metric}</span> · required history：{factor.required_history} 条 · {factor.higher_value_semantics}</p>
          </div>

          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-7">
            <FactorMetric label="样本区间" value={undefined} format={() => `${sample.effective_date_from || "—"} → ${sample.effective_date_to || "—"}`} />
            <FactorMetric label="有效横截面日期数" value={undefined} format={() => String(aggregate.factor_dates_evaluated)} />
            <FactorMetric label="Mean IC" value={aggregate.mean_ic} format={factorIcText} />
            <FactorMetric label="Median IC" value={aggregate.median_ic} format={factorIcText} />
            <FactorMetric label="Positive IC Ratio" value={aggregate.positive_ic_date_ratio} format={factorRatioText} />
            <FactorMetric label="High-Low Mean Spread" value={aggregate.mean_high_minus_low_spread} format={factorReturnText} />
            <FactorMetric label="Pair 总数" value={undefined} format={() => String(aggregate.pair_count_total)} />
          </div>

          <div className="rounded-xl border border-border/60 bg-muted/15 p-4 text-xs leading-relaxed" data-testid="factor-validation-date-eligibility">
            <div className="mb-1 font-medium">当日横截面日期资格</div>
            <div className="flex flex-wrap gap-x-5 gap-y-1">
              <span>当日有效横截面累计：<span className="font-mono">{sample.exact_date_rows_total}</span></span>
              <span>排除旧日期数据：<span className="font-mono">{sample.stale_source_rows_total}</span></span>
              <span>Full Market as-of rows：<span className="font-mono">{sample.source_asof_rows_total}</span></span>
            </div>
            <div className="mt-1 text-muted-foreground">当日横截面只包含 factor date 当天在 RDP 中有真实观测的证券；只有更早最后已知数据的证券不会参与当日 IC 或 High-Low。</div>
          </div>

          <div className="rounded-xl border border-border/60 bg-muted/15 p-4 text-xs leading-relaxed">
            <div className="mb-2 flex flex-wrap gap-x-5 gap-y-1 font-medium">
              <span>requested：{sample.requested_date_from || "artifact start"} → {sample.requested_date_to || "artifact end"}</span>
              <span>attempted：{sample.factor_dates_attempted}</span>
              <span>evaluated：{sample.factor_dates_evaluated[activeWindow] ?? 0}</span>
              <span>immature：{sample.immature_factor_dates[activeWindow] ?? 0}</span>
              {sample.truncated && <span className="text-warning">已按最多 {sample.max_factor_dates} 个 factor dates 截断</span>}
            </div>
            <div className="text-muted-foreground">Observed universe：<span className="font-mono">{sample.universe}</span>；eligibility：factor date 当天存在 stored observation；不等于历史成分股 Universe。当前研究数据为 <span className="font-mono">{report.source.adjustment}</span>；历史统计不等于未来预测。</div>
            <div className="mt-1 text-muted-foreground">Parity：{report.parity.security_factor_values_checked} 个 source rows · {report.parity.exact_date_factor_values_checked ?? "—"} 个 exact-date factor values · {report.parity.factor_dates_checked} 个日期 · mismatches {report.parity.mismatches ?? "—"}。</div>
          </div>

          <div className="rounded-xl border border-border/60 bg-muted/15 p-4">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2 text-sm font-semibold"><Table2 className="h-4 w-4 text-primary" /> 历史横截面稳定性</div>
              <div className="flex gap-2">{WINDOWS.map((window) => <button key={window} type="button" onClick={() => setActiveWindow(String(window))} className={cn("rounded-full border px-3 py-1 text-xs", activeWindow === String(window) ? "border-primary bg-primary/15 text-primary" : "border-border text-muted-foreground")}>{window} 条已存储观测</button>)}</div>
            </div>
            <div className="grid gap-2 sm:grid-cols-4">
              <FactorMetric label="IC Stddev" value={aggregate.ic_stddev} format={factorIcText} />
              <FactorMetric label="Spread Median" value={aggregate.median_high_minus_low_spread} format={factorReturnText} />
              <FactorMetric label="Positive Spread Ratio" value={aggregate.positive_spread_date_ratio} format={factorRatioText} />
              <FactorMetric label="当前窗口" value={undefined} format={() => factorAggregateLabel(aggregate)} />
            </div>

            <details open className="mt-3 rounded-lg border border-border/60 bg-background/30 p-3">
              <summary className="cursor-pointer text-sm font-medium">展开历史横截面（{aggregate.observations.length} 个 factor dates）</summary>
              <div className="mt-3 overflow-x-auto">
                <table className="w-full min-w-[1250px] text-left text-xs" data-testid="factor-validation-observations">
                  <thead className="border-b border-border/60 text-muted-foreground"><tr><th className="px-2 py-2">日期</th><th className="px-2 py-2">Source as-of</th><th className="px-2 py-2">当日有效横截面</th><th className="px-2 py-2">旧日期排除</th><th className="px-2 py-2">Pairs</th><th className="px-2 py-2">IC</th><th className="px-2 py-2">High</th><th className="px-2 py-2">Low</th><th className="px-2 py-2">Spread</th><th className="px-2 py-2">状态 / 说明</th></tr></thead>
                  <tbody>{aggregate.observations.map((observation) => <tr key={`${observation.factor_date}-${observation.forward_window}`} className="border-b border-border/40 last:border-0"><td className="px-2 py-2 font-mono">{observation.factor_date}</td><td className="px-2 py-2">{observation.source_asof_row_count}</td><td className="px-2 py-2">{observation.exact_date_universe_count} / {observation.factor_non_null_count}</td><td className="px-2 py-2 text-warning">{observation.stale_source_row_count}</td><td className="px-2 py-2">{observation.pair_count}</td><td className="px-2 py-2 font-mono">{factorIcText(observation.rank_ic)}</td><td className="px-2 py-2 font-mono">{factorReturnText(observation.high_bucket_mean_return)}</td><td className="px-2 py-2 font-mono">{factorReturnText(observation.low_bucket_mean_return)}</td><td className="px-2 py-2 font-mono">{factorReturnText(observation.high_minus_low_spread)}</td><td className="px-2 py-2"><span className={cn("rounded-full px-2 py-0.5", observation.status === "EVALUATED" ? "bg-primary/15 text-primary" : "bg-muted text-muted-foreground")}>{factorValidationStatusLabel(observation.status)}</span>{observation.reason && <span className="ml-2 text-muted-foreground">{factorValidationReasonLabel(observation.reason)}</span>}{factorObservationHasCoverageLimitation(observation) && <div className="mt-1 text-warning">存在排除：旧日期数据 {observation.stale_source_row_count} · factor null {observation.factor_null_count} · immature {observation.immature_outcome_count}</div>}</td></tr>)}</tbody>
                </table>
              </div>
              {!aggregate.observations.length && <p className="py-4 text-center text-sm text-muted-foreground">该范围没有 RDP factor date。</p>}
            </details>
          </div>

          <div className="rounded-xl border border-warning/30 bg-warning/5 p-4 text-xs leading-relaxed">
            <div className="mb-1 font-semibold text-warning">Data / Limitation · Historical validity not proven</div>
            <ul className="list-disc space-y-1 pl-5 text-muted-foreground">{report.limitations.map((item) => <li key={item}>{item}</li>)}</ul>
          </div>
        </div>
      )}
    </div>
  );
}
