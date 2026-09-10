import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import {
  Thermometer, RefreshCw, Loader2, AlertCircle, Info, Gauge, CalendarClock, History, LineChart,
  FlaskConical, Database, ShieldAlert, Table2,
} from "lucide-react";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import { Disclaimer } from "@/components/ui/Disclaimer";
import { EChart } from "@/components/ui/EChart";
import {
  api, ApiError, type GpuRentData, type GpuSpot, type ForwardMonth,
  type HistoricalSignalValidationReport, type HistoricalSignalValidationRequest,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import { benchmarkNegativeSummary, metricText, validationStatusLabel } from "@/lib/historicalSignalValidationView";
import { FactorValidationPanel } from "@/components/signals/FactorValidationPanel";

// 产业信号：每期从公开零鉴权数据源移植一个「一句话信号」小栏目，逐期在此添加。
const TABS = [
  { key: "gpu-rent", label: "GPU租金", icon: Thermometer, desc: "近一年走势 + 现货中位价 + 远期资金预期" },
  { key: "validation", label: "历史验证", icon: FlaskConical, desc: "固定信号定义的历史观察统计（研究用途）" },
  { key: "factor-validation", label: "因子有效性", icon: LineChart, desc: "既有 RDP 指标的横截面 IC 与分桶描述统计" },
];

// 各型号折线颜色（主题橙留给旗舰 B200；中性灰文字两种主题下都可读）
const GPU_COLORS: Record<string, string> = {
  "B200": "#f97316", "H100 SXM": "#0ea5e9", "A100 SXM4": "#a78bfa",
};
const AXIS_COLOR = "#78716c";
const SPLIT_COLOR = "rgba(120,113,108,.18)";
const TOOLTIP_STYLE = {
  backgroundColor: "rgba(28,25,23,.92)", borderColor: "rgba(120,113,108,.3)",
  textStyle: { color: "#e7e5e4", fontSize: 12 },
};

// 数据是旧值回填（本轮抓取失败）时的提示徽标
function StaleBadge({ observedAt, fetchError }: { observedAt?: string | null; fetchError?: string }) {
  return (
    <span
      className="inline-flex items-center gap-1 rounded-full bg-warning/15 px-2 py-0.5 text-[10px] text-warning"
      title={fetchError ? `本轮抓取失败：${fetchError}` : undefined}
    >
      <History className="h-3 w-3" /> 本轮抓取失败 · 显示 {observedAt || "上次"} 的数据
    </span>
  );
}

function SpotCard({ g }: { g: GpuSpot }) {
  if (g.err) {
    return (
      <div className="rounded-xl border border-destructive/30 bg-destructive/5 p-4">
        <div className="font-mono text-sm font-semibold">{g.gpu}</div>
        <p className="mt-2 flex items-start gap-1.5 text-xs text-destructive">
          <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" /> 抓取失败：{g.err}
        </p>
      </div>
    );
  }
  if (g.unavailable) {
    return (
      <div className="rounded-xl border border-border/60 bg-muted/20 p-4">
        <div className="flex items-center justify-between">
          <span className="font-mono text-sm font-semibold">{g.gpu}</span>
          {g.stale && <StaleBadge observedAt={g.observed_at} fetchError={g.fetch_error} />}
        </div>
        <p className="mt-2 text-sm text-muted-foreground">{g.note || "当前无在租报价"}</p>
        <p className="mt-1 text-[11px] text-muted-foreground/60">这是市场状态，不是数据故障。</p>
      </div>
    );
  }
  return (
    <div className="rounded-xl border border-primary/25 bg-primary/5 p-4">
      <div className="flex items-center justify-between">
        <span className="flex items-center gap-1.5 font-mono text-sm font-semibold">
          <span className="h-2 w-2 rounded-full" style={{ background: GPU_COLORS[g.gpu] || "#f97316" }} />
          {g.gpu}
        </span>
        {g.stale && <StaleBadge observedAt={g.observed_at} fetchError={g.fetch_error} />}
      </div>
      <div className="mt-2 flex items-baseline gap-2">
        <span className="text-3xl font-extrabold tracking-tight text-primary text-glow">${g.median?.toFixed(2)}</span>
        <span className="text-xs text-muted-foreground">/卡·时（中位）</span>
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-muted-foreground">
        <span>
          = 上方曲线最新点
          {g.asof_ts != null && `（${new Date(g.asof_ts * 1000).toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" })} 观测）`}
        </span>
        {g.available_gpus != null && g.total_gpus != null && g.total_gpus > 0 && (
          <span>
            可租 {g.available_gpus} / 共 {g.total_gpus} 张（{Math.round((1 - g.available_gpus / g.total_gpus) * 100)}% 在租）
          </span>
        )}
      </div>
    </div>
  );
}

// 远期单月：一句话总结 + 概率分布柱图
function ForwardMonthPanel({ m }: { m: ForwardMonth }) {
  const im = m.implied_median;
  const impliedText = !im ? null
    : im.bound === "exact" ? `$${im.value.toFixed(2)}`
    : im.bound === "above" ? `高于 $${im.value}（最高档之上）`
    : `低于 $${im.value}（最低档之下）`;
  const mlIndex = m.distribution.findIndex((b) => b.label === m.most_likely.label);

  const option = useMemo(() => ({
    grid: { left: 44, right: 16, top: 24, bottom: 44 },
    tooltip: {
      trigger: "axis" as const, ...TOOLTIP_STYLE,
      valueFormatter: (v: unknown) => `${v}%`,
    },
    xAxis: {
      type: "category" as const,
      data: m.distribution.map((b) => b.label),
      axisLabel: { color: AXIS_COLOR, fontSize: 10, rotate: 32 },
      axisLine: { lineStyle: { color: SPLIT_COLOR } },
      axisTick: { show: false },
    },
    yAxis: {
      type: "value" as const,
      axisLabel: { color: AXIS_COLOR, fontSize: 10, formatter: "{value}%" },
      splitLine: { lineStyle: { color: SPLIT_COLOR } },
    },
    series: [{
      name: "概率", type: "bar" as const, barMaxWidth: 34,
      data: m.distribution.map((b, i) => ({
        value: +(b.p * 100).toFixed(1),
        itemStyle: { color: i === mlIndex ? "#f97316" : "rgba(249,115,22,.32)", borderRadius: [4, 4, 0, 0] },
      })),
    }],
  }), [m, mlIndex]);

  return (
    <div>
      {/* 一句话总结：预期多少钱 + 概率多少 */}
      <div className="mb-3 rounded-xl border border-primary/25 bg-primary/5 p-3.5 text-sm leading-relaxed">
        市场当前对 <b className="font-mono">{m.month}</b> 月均租金（B200）的预期：
        {impliedText && <>中位约 <b className="text-primary">{impliedText}</b>/卡·时，</>}
        最可能落在 <b className="text-primary">{m.most_likely.label}</b>
        （概率 <b className="text-primary">{(m.most_likely.p * 100).toFixed(0)}%</b>）。
        <span className="text-xs text-muted-foreground">
          按 Ornn 跨平台指数的整月平均结算——是「整月均价」，与上方「此刻」的现货挂单价口径不同，数值不能直接对比。
        </span>
      </div>
      <EChart option={option} height={230} />
      <p className="mt-1 text-center text-[11px] text-muted-foreground/60">
        {m.month} 月均租金落在各价位区间的预期概率 · {m.close_date} 结算
      </p>
    </div>
  );
}

function GpuRentPanel() {
  const [data, setData] = useState<GpuRentData | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [activeMonth, setActiveMonth] = useState(0);

  useEffect(() => {
    api.gpuRent().then(setData).catch((e) => setErr(e instanceof ApiError ? e.message : "加载失败"));
  }, []);

  const refresh = async () => {
    setRefreshing(true); setErr(null);
    try { setData(await api.gpuRentRefresh()); setActiveMonth(0); }
    catch (e) { setErr(e instanceof ApiError ? e.message : "刷新失败"); }
    finally { setRefreshing(false); }
  };

  const hasData = !!data?.generated_at;
  const fw = data?.forward;
  const months = fw?.months || [];
  const month = months[Math.min(activeMonth, Math.max(months.length - 1, 0))];
  const histGpus = data?.history?.gpus || [];
  const histStale = histGpus.filter((g) => g.stale);

  // 主图：近一年三条日线。刻意不把 Kalshi 远期画进来——它按 Ornn 指数「整月平均」
  // 结算，与 Vast 日中位是两个市场两种口径，拼在一条线上会误导（实测就被看出"冲突"）。
  const trendOption = useMemo(() => {
    const series: Record<string, unknown>[] = histGpus
      .filter((g) => g.points && g.points.length > 0)
      .map((g) => ({
        name: g.gpu, type: "line", showSymbol: false,
        data: g.points!.map(([t, v]) => [t * 1000, v]),
        lineStyle: { width: 1.8 }, itemStyle: { color: GPU_COLORS[g.gpu] || "#f97316" },
        emphasis: { focus: "series" },
      }));
    return {
      grid: { left: 44, right: 20, top: 40, bottom: 28 },
      legend: { top: 4, textStyle: { color: AXIS_COLOR, fontSize: 11 }, itemWidth: 16 },
      tooltip: {
        trigger: "axis" as const, ...TOOLTIP_STYLE,
        valueFormatter: (v: unknown) => (typeof v === "number" ? `$${v.toFixed(2)}` : `${v}`),
      },
      xAxis: {
        type: "time" as const,
        axisLabel: { color: AXIS_COLOR, fontSize: 10 },
        axisLine: { lineStyle: { color: SPLIT_COLOR } },
      },
      yAxis: {
        type: "value" as const,
        axisLabel: { color: AXIS_COLOR, fontSize: 10, formatter: "${value}" },
        splitLine: { lineStyle: { color: SPLIT_COLOR } },
      },
      series,
    };
  }, [histGpus]);

  const settledText = (fw?.settled || [])
    .map((s) => `${s.month} 实际落在 ${s.lo != null && s.hi != null ? `$${s.lo}~${s.hi}` : s.lo != null ? `≥$${s.lo}` : `<$${s.hi}`} 档`)
    .join(" · ");

  // 预期曲线（term structure）：已结算月的实际落点 + 各在市结算月的隐含预期中位。
  // 两段都是 Ornn 指数「月均」口径——同一把尺子，连成一条时间线是合法的
  // （与 Vast 日中位历史曲线不同口径，所以这张图独立放在远期区、不与上方主图混）。
  const curveOption = useMemo(() => {
    // 只画有完整区间的结算月：单边结果（全 yes / 全 no）只是「高于/低于某档」的
    // 开放区间，画成精确点就是把边界当实际值——那些月留在下方文字行里表述
    const actual = (fw?.settled || [])
      .filter((s) => s.lo != null && s.hi != null)
      .map((s) => ({ month: s.month, mid: (s.lo! + s.hi!) / 2 }));
    const expected = months
      .filter((m) => m.implied_median?.bound === "exact")
      .map((m) => ({ month: m.month, mid: m.implied_median!.value }));
    const cats = [...new Set([...actual.map((a) => a.month), ...expected.map((e) => e.month)])].sort();
    const lastActualIdx = actual.length ? cats.indexOf(actual[actual.length - 1].month) : -1;
    const actualData = cats.map((c) => actual.find((a) => a.month === c)?.mid ?? null);
    // 预期线从最后一个实际点起笔，视觉上连续
    const expectedData = cats.map((c, i) => {
      const e = expected.find((x) => x.month === c);
      if (e) return e.mid;
      return i === lastActualIdx ? actual[actual.length - 1].mid : null;
    });
    return {
      grid: { left: 44, right: 20, top: 34, bottom: 28 },
      legend: { top: 2, textStyle: { color: AXIS_COLOR, fontSize: 11 }, itemWidth: 16 },
      tooltip: {
        trigger: "axis" as const, ...TOOLTIP_STYLE,
        valueFormatter: (v: unknown) => (typeof v === "number" ? `$${v.toFixed(2)}` : "—"),
      },
      xAxis: {
        type: "category" as const, data: cats,
        axisLabel: { color: AXIS_COLOR, fontSize: 10, rotate: 28 },
        axisLine: { lineStyle: { color: SPLIT_COLOR } },
        axisTick: { show: false },
      },
      yAxis: {
        type: "value" as const, scale: true,
        axisLabel: { color: AXIS_COLOR, fontSize: 10, formatter: "${value}" },
        splitLine: { lineStyle: { color: SPLIT_COLOR } },
      },
      series: [
        {
          name: "已结算月实际（区间中点）", type: "line" as const, data: actualData,
          symbol: "circle", symbolSize: 7, lineStyle: { width: 2 },
          itemStyle: { color: "#2dd4bf" }, connectNulls: false,
        },
        {
          name: "市场预期中位", type: "line" as const, data: expectedData,
          symbol: "circle", symbolSize: 5, lineStyle: { width: 2, type: "dashed" as const },
          itemStyle: { color: "#f97316" }, connectNulls: false,
        },
      ],
    };
  }, [fw, months]);
  const hasCurve = months.some((m) => m.implied_median?.bound === "exact");

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <span className="text-xs text-muted-foreground">
          {hasData ? `更新于 ${data!.generated_at}` : "历史 / 现货 / 远期三条腿，都来自零鉴权公开接口"}
        </span>
        <button onClick={refresh} disabled={refreshing}
          className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-sm text-muted-foreground hover:text-foreground disabled:opacity-50">
          {refreshing ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
          {refreshing ? "抓取中…（远期 123 张合约逐档拉取，约 1 分钟）" : "刷新"}
        </button>
      </div>

      {err && (
        <div className="mb-3 flex items-center gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
          <AlertCircle className="h-4 w-4 shrink-0" /> {err}
        </div>
      )}
      {data?.errors && data.errors.length > 0 && (
        <div className="mb-3 rounded-lg border border-warning/30 bg-warning/5 p-3 text-xs text-warning">
          <p className="mb-1 font-medium">本轮有数据源抓取失败（对应区块显示上一次的数据）：</p>
          {data.errors.map((e, i) => <p key={i}>· {e}</p>)}
        </div>
      )}

      {!hasData && !err ? (
        <div className="rounded-lg border border-dashed border-border/70 p-8 text-center text-sm text-muted-foreground/70">
          还没有抓取数据，点上方<b className="text-foreground">「刷新」</b>拉取（约 30 秒）。
        </div>
      ) : hasData && (
        <>
          {/* ① 近一年走势 */}
          <div className="mb-1.5 flex items-center gap-1.5 text-sm font-semibold">
            <LineChart className="h-4 w-4 text-primary" /> 近一年租金走势 · 每日中位价
            {histStale.length > 0 && <StaleBadge observedAt={histStale[0].observed_at} fetchError={histStale[0].fetch_error} />}
          </div>
          <p className="mb-2 text-[11px] text-muted-foreground/70">
            {data!.history_source}
          </p>
          {histGpus.some((g) => g.points?.length) ? (
            <EChart option={trendOption} height={320} />
          ) : (
            <p className="py-6 text-center text-sm text-muted-foreground/60">
              历史序列暂不可用{histGpus.find((g) => g.err) ? `：${histGpus.find((g) => g.err)!.err}` : ""}
            </p>
          )}

          {/* ② 现货 */}
          <div className="mb-1.5 mt-6 flex items-center gap-1.5 text-sm font-semibold">
            <Gauge className="h-4 w-4 text-primary" /> 现货租金 · 最新观测值
          </div>
          <p className="mb-3 text-[11px] text-muted-foreground/70">{data!.spot_source}</p>
          <div className="grid gap-3 sm:grid-cols-3">
            {data!.spot.gpus.map((g) => <SpotCard key={g.gpu} g={g} />)}
          </div>

          {/* ③ 远期 */}
          <div className="mb-1.5 mt-6 flex items-center gap-1.5 text-sm font-semibold">
            <CalendarClock className="h-4 w-4 text-primary" /> 远期 · 全球资金的预期概率（仅 B200）
            {fw?.stale && <StaleBadge observedAt={fw.observed_at} fetchError={fw.fetch_error} />}
          </div>
          <p className="mb-3 text-[11px] text-muted-foreground/70">
            {data!.forward_source}
            {fw?.n_contracts != null && ` · 在市合约 ${fw.n_contracts} 张 · 有报价结算月 ${months.length} 个${
              fw.n_months != null && fw.n_months > months.length ? `（另 ${fw.n_months - months.length} 个月暂无报价）` : ""}`}
          </p>
          {fw?.err ? (
            <p className="flex items-start gap-1.5 text-xs text-destructive">
              <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" /> 抓取失败：{fw.err}
            </p>
          ) : fw?.unavailable ? (
            <p className="text-sm text-muted-foreground">{fw.note}（市场状态，非故障）</p>
          ) : months.length > 0 ? (
            <>
              {/* 预期曲线：远期是涨是跌一眼看清（实线=已结算实际，虚线=各月预期中位，同为月均口径） */}
              {hasCurve && (
                <div className="mb-4">
                  <EChart option={curveOption} height={240} />
                  <p className="mt-1 text-center text-[11px] text-muted-foreground/60">
                    同一把尺子（Ornn 指数月均）：实线 = 已结算月的实际落点（取区间中点），虚线 = 各结算月的市场预期中位
                  </p>
                </div>
              )}
              <div className="mb-3 flex flex-wrap gap-2">
                {months.map((m, i) => (
                  <button key={m.month} onClick={() => setActiveMonth(i)}
                    className={cn(
                      "rounded-full border px-3 py-1 font-mono text-xs transition-colors",
                      i === Math.min(activeMonth, months.length - 1)
                        ? "border-primary bg-primary/15 font-medium text-primary shadow-glow"
                        : "border-primary/25 text-muted-foreground hover:border-primary/60 hover:text-foreground",
                    )}>
                    {m.month}
                  </button>
                ))}
              </div>
              {month && <ForwardMonthPanel m={month} />}
              {settledText && (
                <p className="mt-3 text-[11px] text-muted-foreground/70">
                  已结算月份（月均实际落点，可与上方历史曲线互证）：{settledText}
                </p>
              )}
            </>
          ) : null}

          {/* ④ 怎么读 */}
          <div className="mt-6 rounded-xl border border-border/60 bg-muted/20 p-4">
            <div className="mb-2 flex items-center gap-1.5 text-sm font-semibold">
              <Info className="h-4 w-4 text-primary" /> 怎么读这组数（三条口径边界）
            </div>
            <ol className="list-decimal space-y-1 pl-5 text-xs leading-relaxed text-muted-foreground">
              {data!.how_to_read.map((h, i) => <li key={i}>{h}</li>)}
            </ol>
          </div>
        </>
      )}
    </div>
  );
}

function ValidationMetric({ label, value }: { label: string; value: number | null | undefined }) {
  return (
    <div className="rounded-lg border border-border/60 bg-muted/15 p-3">
      <div className="text-[11px] text-muted-foreground">{label}</div>
      <div className="mt-1 font-mono text-sm font-semibold">{metricText(value)}</div>
    </div>
  );
}

function parseCodes(value: string): string[] {
  return [...new Set(value.split(/[\s,，]+/).map((item) => item.trim()).filter(Boolean))];
}

function HistoricalSignalValidationPanel() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [registry, setRegistry] = useState<HistoricalSignalValidationReport["signal"][] | null>(null);
  const [selectedSignal, setSelectedSignal] = useState(searchParams.get("signal") || "sma20_gt_sma60");
  const [codes, setCodes] = useState((searchParams.get("codes") || "600001").split(",").join("\n"));
  const [benchmarkCode, setBenchmarkCode] = useState(searchParams.get("benchmark") || "");
  const [dateFrom, setDateFrom] = useState(searchParams.get("from") || "");
  const [dateTo, setDateTo] = useState(searchParams.get("to") || "");
  const [report, setReport] = useState<HistoricalSignalValidationReport | null>(null);
  const [activeWindow, setActiveWindow] = useState("5");
  const [loadingRegistry, setLoadingRegistry] = useState(true);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let mounted = true;
    api.historicalSignalValidationRegistry()
      .then((payload) => {
        if (!mounted) return;
        setRegistry(payload.signals);
        if (!payload.signals.some((signal) => signal.id === selectedSignal)) {
          setSelectedSignal(payload.signals[0]?.id || "");
        }
      })
      .catch((reason) => {
        if (mounted) setError(reason instanceof ApiError ? reason.message : "历史验证目录加载失败");
      })
      .finally(() => mounted && setLoadingRegistry(false));
    return () => { mounted = false; };
  }, []);

  const evaluate = async (payload: HistoricalSignalValidationRequest, persist: boolean) => {
    setLoading(true);
    setError(null);
    try {
      const next = await api.historicalSignalValidationEvaluate(payload);
      setReport(next);
      const windows = Object.keys(next.results);
      if (windows.length && !windows.includes(activeWindow)) setActiveWindow(windows[0]);
      if (persist) {
        const nextParams = new URLSearchParams({ signal: payload.signal_id, codes: payload.codes.join(",") });
        if (payload.benchmark_code) nextParams.set("benchmark", payload.benchmark_code);
        if (payload.date_from) nextParams.set("from", payload.date_from);
        if (payload.date_to) nextParams.set("to", payload.date_to);
        setSearchParams(nextParams, { replace: true });
      }
    } catch (reason) {
      setReport(null);
      setError(reason instanceof ApiError ? reason.message : "历史验证失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    const storedCodes = searchParams.get("codes");
    if (!registry || report || !storedCodes) return;
    const requestedSignal = searchParams.get("signal") || registry[0]?.id;
    const requestedCodes = parseCodes(storedCodes);
    if (!requestedSignal || !requestedCodes.length) return;
    void evaluate({
      signal_id: requestedSignal,
      codes: requestedCodes,
      benchmark_code: searchParams.get("benchmark") || null,
      date_from: searchParams.get("from") || null,
      date_to: searchParams.get("to") || null,
    }, false);
  }, [registry]);

  const submit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const requestedCodes = parseCodes(codes);
    if (!requestedCodes.length) {
      setError("至少输入一个六位股票代码");
      return;
    }
    void evaluate({
      signal_id: selectedSignal,
      codes: requestedCodes,
      benchmark_code: benchmarkCode.trim() || null,
      date_from: dateFrom || null,
      date_to: dateTo || null,
    }, true);
  };

  const signal = report?.signal || registry?.find((item) => item.id === selectedSignal);
  const result = report?.results[activeWindow] || (report ? Object.values(report.results)[0] : undefined);
  const data = report?.data;
  const negative = result ? benchmarkNegativeSummary(result) : null;
  const protocolWindows = (report?.protocol.observation_windows_stored_observations as number[] | undefined) || [5, 20];

  return (
    <div className="space-y-4" data-testid="historical-signal-validation">
      <div className="rounded-xl border border-warning/40 bg-warning/10 p-4 text-sm leading-relaxed">
        <div className="flex items-center gap-2 font-semibold text-warning">
          <ShieldAlert className="h-4 w-4" /> RESEARCH ONLY · Historical validity not proven
        </div>
        <p className="mt-1 text-xs text-muted-foreground">
          这是固定信号定义的历史观察，不是回测、交易建议或正式决策；不会写入 Thesis、Evidence、Signal Ledger、Portfolio 或 Account。
        </p>
      </div>

      <form onSubmit={submit} className="rounded-xl border border-border/60 bg-muted/15 p-4">
        <div className="mb-3 flex items-center gap-2 text-sm font-semibold">
          <FlaskConical className="h-4 w-4 text-primary" /> 运行固定定义验证
        </div>
        <div className="grid gap-3 lg:grid-cols-[1fr_1.3fr_1fr]">
          <label className="text-xs text-muted-foreground">
            信号
            <select value={selectedSignal} onChange={(event) => setSelectedSignal(event.target.value)} disabled={loadingRegistry}
              className="mt-1 w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground">
              {(registry || []).map((item) => <option key={item.id} value={item.id}>{item.id}</option>)}
            </select>
          </label>
          <label className="text-xs text-muted-foreground">
            显式样本代码（逗号或换行）
            <textarea aria-label="显式样本代码" value={codes} onChange={(event) => setCodes(event.target.value)} rows={2}
              className="mt-1 w-full resize-y rounded-lg border border-border bg-background px-3 py-2 font-mono text-sm text-foreground" />
          </label>
          <label className="text-xs text-muted-foreground">
            可选 benchmark code
            <input aria-label="benchmark code" value={benchmarkCode} onChange={(event) => setBenchmarkCode(event.target.value)} placeholder="例如 000300"
              className="mt-1 w-full rounded-lg border border-border bg-background px-3 py-2 font-mono text-sm text-foreground" />
            <span className="mt-1 block text-[11px] text-muted-foreground/70">两端点缺失时不填充、不当作 0。</span>
          </label>
        </div>
        <div className="mt-3 flex flex-wrap items-end gap-3">
          <label className="text-xs text-muted-foreground">起始日期<input type="date" value={dateFrom} onChange={(event) => setDateFrom(event.target.value)} className="mt-1 block rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground" /></label>
          <label className="text-xs text-muted-foreground">结束日期<input type="date" value={dateTo} onChange={(event) => setDateTo(event.target.value)} className="mt-1 block rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground" /></label>
          <button type="submit" disabled={loading || loadingRegistry || !selectedSignal}
            className="inline-flex items-center gap-1.5 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50">
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <FlaskConical className="h-4 w-4" />}
            {loading ? "计算中…" : "运行验证"}
          </button>
        </div>
      </form>

      {error && <div role="alert" className="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive"><AlertCircle className="mr-1 inline h-4 w-4" />{error}</div>}
      {loadingRegistry && <div role="status" className="rounded-lg border border-dashed border-border/70 p-6 text-center text-sm text-muted-foreground">正在读取稳定信号目录…</div>}

      {report?.status === "unavailable" && (
        <div role="status" className="rounded-xl border border-border/60 bg-muted/20 p-4 text-sm">
          <div className="flex items-center gap-2 font-medium"><Database className="h-4 w-4 text-warning" /> Research Data Plane 不可用</div>
          <p className="mt-2 text-xs text-muted-foreground">没有把缺失数据伪装成空收益；请先配置可验证的 RDP artifact。</p>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-xs text-muted-foreground">{report.limitations.slice(0, 3).map((item) => <li key={item}>{item}</li>)}</ul>
        </div>
      )}

      {!report && !loadingRegistry && !error && (
        <div className="rounded-xl border border-dashed border-border/70 p-8 text-center text-sm text-muted-foreground">
          输入显式样本后运行；页面不会自动选择全市场或写入任何正式账本。
        </div>
      )}

      {report?.status === "normal" && signal && (
        <>
          <div className="grid gap-4 lg:grid-cols-2">
            <div className="rounded-xl border border-border/60 bg-muted/15 p-4">
              <div className="mb-2 flex items-center gap-2 text-sm font-semibold"><FlaskConical className="h-4 w-4 text-primary" /> Signal Definition</div>
              <dl className="space-y-1.5 text-xs leading-relaxed">
                <div><dt className="inline text-muted-foreground">ID / Version：</dt><dd className="inline font-mono">{signal.id} · {signal.version}</dd></div>
                <div><dt className="inline text-muted-foreground">定义：</dt><dd className="inline"> {signal.definition}</dd></div>
                <div><dt className="inline text-muted-foreground">可用时点：</dt><dd className="inline"> {signal.availability}</dd></div>
                <div><dt className="inline text-muted-foreground">事件语义：</dt><dd className="inline"> {signal.event_semantics}</dd></div>
                <div><dt className="inline text-muted-foreground">窗口：</dt><dd className="inline">第 {protocolWindows.join(" / ")} 条已存储观测，不称交易日。</dd></div>
                <div><dt className="inline text-muted-foreground">样本范围：</dt><dd className="inline">仅显式输入 codes；不自动扩展全市场。</dd></div>
              </dl>
            </div>
            <div className="rounded-xl border border-border/60 bg-muted/15 p-4">
              <div className="mb-2 flex items-center gap-2 text-sm font-semibold"><Database className="h-4 w-4 text-primary" /> Data Provenance</div>
              <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
                <dt className="text-muted-foreground">dataset</dt><dd className="font-mono">{data?.dataset_id || "—"}</dd>
                <dt className="text-muted-foreground">adjustment</dt><dd className="font-mono">{data?.adjustment || "—"}</dd>
                <dt className="text-muted-foreground">as-of</dt><dd>{data?.as_of || "—"}</dd>
                <dt className="text-muted-foreground">coverage</dt><dd>{data?.coverage ? `${data.coverage.start} → ${data.coverage.end}` : "—"}</dd>
                <dt className="text-muted-foreground">请求样本</dt><dd className="font-mono">{(data?.requested_sample_codes || []).join(", ") || "—"}</dd>
                <dt className="text-muted-foreground">实际样本</dt><dd className="font-mono">{(data?.sample_codes_with_data || []).join(", ") || "—"}</dd>
                <dt className="text-muted-foreground">缺失样本</dt><dd className="font-mono">{(data?.sample_codes_missing_data || []).join(", ") || "无"}</dd>
              </dl>
            </div>
          </div>

          <div className="rounded-xl border border-border/60 bg-muted/15 p-4">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2 text-sm font-semibold"><Table2 className="h-4 w-4 text-primary" /> Summary</div>
              <div className="flex gap-2">{Object.keys(report.results).map((key) => <button key={key} onClick={() => setActiveWindow(key)} className={cn("rounded-full border px-3 py-1 font-mono text-xs", activeWindow === key ? "border-primary bg-primary/15 text-primary" : "border-border text-muted-foreground")}>{key} 条观测</button>)}</div>
            </div>
            {result ? (
              <>
                <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
                  <div className="rounded-lg border border-border/60 bg-background/40 p-3"><div className="text-[11px] text-muted-foreground">总事件</div><div className="mt-1 font-mono text-lg font-semibold">{result.events_total}</div></div>
                  <div className="rounded-lg border border-border/60 bg-background/40 p-3"><div className="text-[11px] text-muted-foreground">已评估</div><div className="mt-1 font-mono text-lg font-semibold">{result.events_evaluated}</div></div>
                  <div className="rounded-lg border border-border/60 bg-background/40 p-3"><div className="text-[11px] text-muted-foreground">未成熟</div><div className="mt-1 font-mono text-lg font-semibold">{result.events_immature}</div></div>
                  <div className="rounded-lg border border-border/60 bg-background/40 p-3"><div className="text-[11px] text-muted-foreground">退出缺失</div><div className="mt-1 font-mono text-lg font-semibold">{result.events_missing_exit}</div></div>
                  <div className="rounded-lg border border-border/60 bg-background/40 p-3"><div className="text-[11px] text-muted-foreground">先验未知排除</div><div className="mt-1 font-mono text-lg font-semibold">{result.events_excluded_unknown_prior}</div></div>
                </div>
                <div className="mt-3 grid gap-3 sm:grid-cols-3">
                  <ValidationMetric label="均值" value={result.signal_return?.mean} />
                  <ValidationMetric label="中位数" value={result.signal_return?.median} />
                  <ValidationMetric label="P10" value={result.signal_return?.p10} />
                  <ValidationMetric label="P90" value={result.signal_return?.p90} />
                  <ValidationMetric label="最小值" value={result.signal_return?.min} />
                  <ValidationMetric label="最大值" value={result.signal_return?.max} />
                </div>
                <div className="mt-3 rounded-lg border border-border/60 bg-background/40 p-3 text-xs">
                  {result.benchmark_return && result.excess_return && negative ? (
                    <div className="flex flex-wrap gap-x-5 gap-y-1"><span>Benchmark 均值 / 中位数：<b className="font-mono">{metricText(result.benchmark_return.mean)} / {metricText(result.benchmark_return.median)}</b></span><span>超额均值 / 中位数：<b className="font-mono">{metricText(result.excess_return.mean)} / {metricText(result.excess_return.median)}</b></span><span>负超额：<b className="font-mono">{negative.count}/{result.excess_return.count}（{negative.ratio}%）</b></span><span>基准缺失：{result.benchmark_events_missing}</span></div>
                  ) : <div className="flex flex-wrap gap-x-5 gap-y-1 text-muted-foreground"><span>基准缺失：{result.benchmark_events_missing}</span><span>没有可用的完整 benchmark 双端点，不计算 benchmark 统计或负超额比例。</span></div>}
                </div>
              </>
            ) : <p className="text-sm text-muted-foreground">当前范围没有可展示的窗口结果。</p>}
          </div>

          {result && (
            <div className="rounded-xl border border-border/60 bg-muted/15 p-4">
              <div className="mb-3 flex items-center gap-2 text-sm font-semibold"><Table2 className="h-4 w-4 text-primary" /> Event Ledger · {activeWindow} 条已存储观测</div>
              <div className="overflow-x-auto">
                <table className="w-full min-w-[860px] text-left text-xs">
                  <thead className="border-b border-border/60 text-muted-foreground"><tr><th className="px-2 py-2">代码</th><th className="px-2 py-2">信号日</th><th className="px-2 py-2">退出日</th><th className="px-2 py-2">状态</th><th className="px-2 py-2">样本收益</th><th className="px-2 py-2">Benchmark</th><th className="px-2 py-2">超额</th><th className="px-2 py-2">备注</th></tr></thead>
                  <tbody>{result.rows.map((row, index) => <tr key={`${row.code}-${row.signal_date || "excluded"}-${index}`} className="border-b border-border/40 last:border-0"><td className="px-2 py-2 font-mono">{row.code}</td><td className="px-2 py-2">{row.signal_date || "—"}</td><td className="px-2 py-2">{row.exit_date || "—"}</td><td className="px-2 py-2"><span className={cn("rounded-full px-2 py-0.5", row.status === "EVALUATED" ? "bg-primary/15 text-primary" : "bg-muted text-muted-foreground")}>{validationStatusLabel(row.status)}</span></td><td className="px-2 py-2 font-mono">{metricText(row.return_pct)}</td><td className="px-2 py-2 font-mono">{metricText(row.benchmark_return_pct)}</td><td className="px-2 py-2 font-mono">{metricText(row.excess_return_pct)}</td><td className="px-2 py-2 text-muted-foreground">{row.benchmark_missing_reason || (row.is_worst ? "最差绝对收益观察" : "")}</td></tr>)}</tbody>
                </table>
              </div>
              {!result.rows.length && <p className="py-4 text-center text-sm text-muted-foreground">当前范围没有信号事件；没有把空样本当成成功。</p>}
            </div>
          )}

          <div className="rounded-xl border border-warning/30 bg-warning/5 p-4 text-xs leading-relaxed">
            <div className="mb-1 font-semibold text-warning">Data / Limitation · Historical validity not proven</div>
            <ul className="list-disc space-y-1 pl-5 text-muted-foreground">{report.limitations.map((item) => <li key={item}>{item}</li>)}</ul>
          </div>
        </>
      )}
    </div>
  );
}

export function Signals() {
  // 当前小栏目由路由驱动（/signals/:tab），与侧栏子项联动；不认识的参数回落到第一个
  const { tab: tabParam } = useParams();
  const navigate = useNavigate();
  const tab = TABS.some((t) => t.key === tabParam) ? tabParam! : TABS[0].key;
  const cur = TABS.find((t) => t.key === tab)!;

  return (
    <div>
      <PageHeader title="产业信号" subtitle="一句话产业信号：零鉴权公开数据直连，逐期添加小栏目" />

      <div className="mb-4 flex flex-wrap gap-2">
        {TABS.map(({ key, label, icon: Icon }) => (
          <button key={key} onClick={() => navigate(`/signals/${key}`)}
            className={cn("inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm transition-colors",
              tab === key ? "bg-primary/15 font-medium text-primary shadow-glow" : "text-muted-foreground hover:bg-muted/50")}>
            <Icon className="h-4 w-4" /> {label}
          </button>
        ))}
      </div>

      <GlassCard glow>
        <div className="mb-3 flex items-center gap-2">
          <cur.icon className="h-5 w-5 text-primary" />
          <h3 className="font-semibold">{cur.label}</h3>
          <span className="text-xs text-muted-foreground">{cur.desc}</span>
        </div>
        {cur.key === "gpu-rent" && <GpuRentPanel />}
        {cur.key === "validation" && <HistoricalSignalValidationPanel />}
        {cur.key === "factor-validation" && <FactorValidationPanel />}
      </GlassCard>

      <p className="mt-3 text-[11px] text-muted-foreground/60">
        {tab === "validation" ? "历史验证只做研究观察，不是正式状态写入、交易策略或历史有效性证明。" : "只呈现公开接口的价格事实与合约报价，不产出「过剩 / 短缺」的判断、不构成任何建议——怎么解读，交给你自己接入的 AI（工具名 query_gpu_rent）。"}
      </p>
      <Disclaimer />
    </div>
  );
}
