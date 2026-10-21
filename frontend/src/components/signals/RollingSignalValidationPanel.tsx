import { useEffect, useRef, useState } from 'react';
import { request, ApiError } from '@/lib/api';
import { ExperimentLedger } from '@/components/research/ExperimentLedger';
import { ExperimentGeneration } from '@/lib/experimentLedger';

type Bucket = { events_total: number; events_evaluated: number; events_immature: number; events_missing_exit: number; events_purged_label_end: number; events_excluded_unknown_prior: number; benchmark_events_missing: number; signal_return: { mean: number } | null; excess_return: { mean: number } | null; rows: Record<string, unknown>[] };
type Coverage = { stored_observations: number; evaluable_observations: number; warmup_observations_before_segment: number; first_date: string | null; last_date: string | null; calendar_gap_count: number; calendar_gaps: { from: string; to: string; calendar_days: number }[]; calendar_gaps_omitted: number };
type Report = { status: string; input_fingerprint: string; data: { snapshot_id: string | null; missing_codes: string[]; benchmark_available: boolean }; trials: { parameter: string; frozen_primary: boolean; segments: { id: string; role: string; from: string; to: string; aggregate: boolean; coverage: Record<string, Coverage>; results: Record<string, Bucket> }[] }[]; limitations: string[] };

export function RollingSignalValidationPanel() {
  const [codes, setCodes] = useState('600001');
  const [benchmark, setBenchmark] = useState('');
  const [dates, setDates] = useState({ selection_from: '', selection_to: '', holdout_from: '', holdout_to: '' });
  const [days, setDays] = useState(90);
  const [frozen, setFrozen] = useState('20/60');
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const generation = useRef(new ExperimentGeneration());
  const controller = useRef<AbortController | null>(null);
  const input = JSON.stringify({ signal_id: 'sma20_gt_sma60', codes: [...new Set(codes.split(/[\s,，]+/).filter(Boolean))].sort(), benchmark_code: benchmark || null, ...dates, rolling_calendar_days: days, parameter_preset: 'sma-fast-neighbors-v1', frozen_parameter: frozen });
  useEffect(() => { generation.current.next(); controller.current?.abort(); setReport(null); setBusy(false); setError(''); return () => { generation.current.next(); controller.current?.abort(); }; }, [input]);
  async function run(event: React.FormEvent) {
    event.preventDefault();
    const token = generation.current.next();
    controller.current?.abort();
    const active = new AbortController(); controller.current = active;
    setBusy(true); setReport(null); setError('');
    try {
      const result = await request<Report>('/signals/validation/rolling', 'POST', JSON.parse(input), { signal: active.signal, unwrapData: false });
      if (generation.current.current(token)) setReport(result);
    } catch (reason) {
      if (generation.current.current(token)) setError(reason instanceof ApiError ? reason.message : '滚动研究未完成，请核对输入与本地快照');
    } finally { if (generation.current.current(token)) setBusy(false); }
  }
  return <section className="space-y-3 rounded-xl border p-4" data-testid="rolling-signal-validation">
    <h2 className="font-medium">滚动留出与参数邻域研究</h2>
    <p className="text-xs text-muted-foreground">固定预声明 SMA15/60、20/60、25/60 三组全部展示，不选最佳参数。先声明选择段、冻结留出段和主参数，再读取同一快照。修改声明就是新实验；查看留出邻域后，该段不可再视为未见数据。</p>
    <p className="text-xs">5 / 20 个已存储观测，不是交易日。滚动分段按日历日；每段剔除结束日期越界的未来标签。完整历史仅作因果预热。历史股票池、公司行为及可投资回测均为 NOT_EVALUATED。</p>
    <form onSubmit={run} className="grid gap-3 md:grid-cols-2">
      <label className="text-sm">样本代码（最多20个）<input className="block w-full rounded border bg-background p-2" value={codes} onChange={e => setCodes(e.target.value)} required /></label>
      <label className="text-sm">独立基准代码（可选）<input className="block w-full rounded border bg-background p-2" value={benchmark} onChange={e => setBenchmark(e.target.value)} /></label>
      {Object.entries({ selection_from: '选择段开始', selection_to: '选择段结束', holdout_from: '冻结留出开始', holdout_to: '冻结留出结束' }).map(([key, label]) => <label className="text-sm" key={key}>{label}<input type="date" required className="block w-full rounded border bg-background p-2" value={dates[key as keyof typeof dates]} onChange={e => setDates(old => ({ ...old, [key]: e.target.value }))} /></label>)}
      <label className="text-sm">滚动分段（日历日，30–366）<input type="number" min={30} max={366} required className="block w-full rounded border bg-background p-2" value={days} onChange={e => setDays(Number(e.target.value))} /></label>
      <label className="text-sm">事前冻结主参数<select className="block w-full rounded border bg-background p-2" value={frozen} onChange={e => setFrozen(e.target.value)}>{['15/60', '20/60', '25/60'].map(value => <option key={value}>{value}</option>)}</select></label>
      <div className="flex gap-3"><button className="rounded border px-3 py-2" disabled={busy}>{busy ? '正在计算…' : '运行全部预声明参数'}</button>{busy && <button type="button" className="rounded border px-3 py-2" onClick={() => { generation.current.next(); controller.current?.abort(); setBusy(false); setReport(null); setError('已停止接收结果；底层只读计算可能仍在结束'); }}>取消</button>}</div>
    </form>
    {error && <p role="alert">{error}</p>}
    {report && <div className="space-y-3">
      <p role="status">状态：{report.status} · 完成参数：{report.trials.length}/3 · 缺数据代码：{report.data.missing_codes.join('、') || '无'} · 基准：{report.data.benchmark_available ? '可读取，逐事件检查日期' : '未评估'}</p>
      <p className="break-all text-xs">快照：{report.data.snapshot_id || '缺失'}<br />冻结输入身份：{report.input_fingerprint}</p>
      {report.trials.map(trial => <div key={trial.parameter} className="space-y-2 rounded border p-3"><h3>SMA {trial.parameter} {trial.frozen_primary ? '· 事前主参数' : '· 邻域对照'}</h3>
        {trial.segments.map(segment => <details key={segment.id}><summary className="cursor-pointer text-sm">{segment.role === 'selection' ? '选择段' : '冻结留出段'} {segment.aggregate ? '全段' : '滚动分段'} · {segment.from} 至 {segment.to}</summary>
          <div className="overflow-auto"><table className="w-full text-left text-xs"><thead><tr>{['观测窗口', '事件', '已评估', '越界剔除', '未成熟', '缺出口', '未知前态', '基准缺失', '均值%', '超额均值%'].map(x => <th key={x}>{x}</th>)}</tr></thead><tbody>{Object.entries(segment.results).map(([window, bucket]) => <tr key={window}><td>{window}条</td>{[bucket.events_total, bucket.events_evaluated, bucket.events_purged_label_end, bucket.events_immature, bucket.events_missing_exit, bucket.events_excluded_unknown_prior, bucket.benchmark_events_missing, bucket.signal_return?.mean ?? '未定义', bucket.excess_return?.mean ?? '未定义'].map((value, i) => <td key={i}>{value}</td>)}</tr>)}</tbody></table></div>
          {Object.entries(segment.coverage).map(([code, coverage]) => <div className="my-2 text-xs" key={code}>{code}：存储 {coverage.stored_observations} · 可计算 {coverage.evaluable_observations} · 段前预热 {coverage.warmup_observations_before_segment} · 实际 {coverage.first_date || '无'} 至 {coverage.last_date || '无'} · 日历间隔 {coverage.calendar_gap_count}（不推断缺失交易日）<details><summary>查看日历间隔</summary>{coverage.calendar_gaps.map(gap => <p key={gap.from}>{gap.from} → {gap.to}：{gap.calendar_days} 日</p>)}{coverage.calendar_gaps_omitted > 0 && <p>另有 {coverage.calendar_gaps_omitted} 个间隔，展示前20个</p>}</details></div>)}
          <details><summary className="text-xs">逐事件标签日期与状态</summary><pre className="max-h-80 overflow-auto text-xs">{JSON.stringify(segment.results, null, 2)}</pre></details>
        </details>)}
      </div>)}
      {report.limitations.map(text => <p className="text-xs text-muted-foreground" key={text}>{text}</p>)}
    </div>}
    <ExperimentLedger kind="rolling-signal" input={input} />
  </section>;
}
