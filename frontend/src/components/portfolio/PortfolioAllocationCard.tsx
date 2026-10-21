import { useEffect, useRef, useState } from 'react';
import { GlassCard } from '@/components/ui/GlassCard';
import { readAllocation, saveAllocation, parseTargets, type AllocationComparison } from '@/lib/allocationTargets';

const percent = (value: number | null) => value === null ? '未知' : `${value.toFixed(2)}%`;
export function PortfolioAllocationCard({ snapshotToken }: { snapshotToken?: unknown }) {
  const [data, setData] = useState<AllocationComparison | null>(null);
  const [error, setError] = useState('');
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [text, setText] = useState('');
  const [date, setDate] = useState('');
  const [coverage, setCoverage] = useState<'PARTIAL' | 'FULL'>('PARTIAL');
  const [editVersion, setEditVersion] = useState(0);
  const generation = useRef(0);
  const mounted = useRef(true);
  const [expired, setExpired] = useState(false);
  async function load() {
    const request = ++generation.current;
    setBusy(true); setData(null); setError('');
    try {
      const next = await readAllocation();
      if (mounted.current && generation.current === request) { setData(next); setExpired(false); }
    } catch (e) { if (mounted.current && generation.current === request) setError(e instanceof Error ? e.message : '读取失败'); }
    finally { if (mounted.current && generation.current === request) setBusy(false); }
  }
  useEffect(() => { mounted.current = true; void load(); return () => { mounted.current = false; generation.current++; }; }, [snapshotToken]);
  useEffect(() => {
    if (!data) return;
    // Old comparisons disappear on expiry; refresh never leaves stale percentages visible.
    const timer = setTimeout(() => setExpired(true), Math.max(0, Date.parse(data.valid_until) - Date.now()));
    return () => clearTimeout(timer);
  }, [data]);
  function edit() {
    if (!data) return;
    const latest = data.versions[data.versions.length - 1];
    setText(latest ? Object.entries(latest.input.targets).map(([key, value]) => `${key} ${value}`).join('\n') : '');
    setDate(latest?.input.effective_date ?? ''); setCoverage(latest?.input.coverage ?? 'PARTIAL');
    setEditVersion(data.latest_version); setEditing(true); setError('');
  }
  async function save() {
    try {
      const targets = parseTargets(text);
      if (!date) throw new Error('请填写生效日期');
      const total = Object.values(targets).reduce((sum, value) => sum + Math.round(value * 100), 0);
      if (total > 10000 || coverage === 'FULL' && total !== 10000) throw new Error('完整目标合计须为 100%；部分目标不能超过 100%');
      setBusy(true); setData(null); generation.current++;
      await saveAllocation({ expected_version: editVersion, effective_date: date, coverage, targets, market: 'CN', currency: 'CNY', basis: 'CONFIRMED_ACCOUNT_ASSETS' });
      if (!mounted.current) return;
      setEditing(false); await load();
    } catch (e) { if (mounted.current) { setError(e instanceof Error ? e.message : '保存失败'); setBusy(false); } }
  }
  return <GlassCard className="mb-4" data-testid="allocation-target-card">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <h3 className="text-sm font-semibold">自定义配置目标 vs 实际</h3>
      <div className="flex gap-3 text-xs"><button disabled={busy} onClick={() => void load()}>刷新比较</button><button disabled={busy || !data} onClick={edit}>配置目标</button></div>
    </div>
    <p className="my-2 text-xs text-muted-foreground">CN / CNY · 证券与现金 · 分母为已确认账户总资产；偏离为实际减目标（百分点）。不生成交易或调仓建议</p>
    {error && <p role="alert" className="text-xs text-destructive">{error}。刷新可重新读取当前版本，编辑内容仍保留</p>}
    {busy && <p className="text-xs">读取或保存中…</p>}
    {editing && <form className="my-3 space-y-2 text-xs" onSubmit={e => { e.preventDefault(); void save(); }}>
      <label className="block">生效日期（UTC）<input aria-label="目标生效日期" type="date" required value={date} onChange={e => setDate(e.target.value)} className="ml-2 rounded border bg-background p-1" /></label>
      <label className="block">目标范围<select aria-label="目标范围" value={coverage} onChange={e => setCoverage(e.target.value as 'PARTIAL' | 'FULL')} className="ml-2 rounded border bg-background p-1"><option value="PARTIAL">部分目标（未指定部分保持未知）</option><option value="FULL">完整目标（合计 100%）</option></select></label>
      <label className="block">每行：证券代码或 CASH + 目标百分比<textarea aria-label="配置目标百分比" value={text} onChange={e => setText(e.target.value)} rows={5} className="mt-1 block w-full rounded border bg-background p-2 font-mono" /></label>
      <p>未填写目标不会默认为 0 或现金。保存为新版本，未来日期不会提前生效。当前编辑基于版本 {editVersion}</p>
      <button disabled={busy} className="rounded border px-3 py-1" type="submit">保存新目标版本</button><button type="button" disabled={busy} className="ml-3" onClick={() => setEditing(false)}>取消</button>
    </form>}
    {data && <>
      <p className="text-xs">{data.status === 'NOT_CONFIGURED' ? '尚未配置目标；没有默认目标组合' : data.status === 'NOT_EFFECTIVE' ? '目标尚未生效' : `生效版本 ${data.active_version} · 最新版本 ${data.latest_version} · ${data.status === 'COMPARABLE' && !expired ? '同口径可比较' : '实际数据不足或已过期，偏离未知'}`}</p>
      <p className="mt-1 text-xs text-muted-foreground">账户分母 {data.denominator === null ? '未知' : `CNY ${data.denominator.toFixed(2)}`} · 行情覆盖 {data.coverage.priced_count}/{data.coverage.holding_count} · 未知行业 {data.coverage.unknown_industry_count}</p>
      {expired && <p role="status" className="text-xs">比较已过期，请刷新；旧实际占比和偏离已隐藏</p>}
      <div className="mt-2 space-y-1 text-xs">{data.rows.map(row => <div key={row.key} className="flex flex-wrap justify-between gap-2 rounded border p-2"><span>{row.key}</span><span>目标 {percent(row.target_pct)} · 实际 {percent(expired ? null : row.actual_pct)} · 偏离 {expired || row.drift_pp === null ? '未知' : `${row.drift_pp > 0 ? '+' : ''}${row.drift_pp.toFixed(2)} pp`}</span>{row.reason && <span className="w-full text-muted-foreground">{row.reason}</span>}</div>)}</div>
      {!!data.reasons.length && <p className="mt-2 break-words text-xs text-amber-700">{data.reasons.join(' · ')}</p>}
      <details className="mt-2 text-xs text-muted-foreground"><summary>版本与数据限制</summary>{data.versions.map(v => <p key={v.version}>v{v.version} · {v.input.effective_date} · {v.input.coverage} · 已配置 {Object.values(v.input.targets).reduce((a,b) => a+b,0).toFixed(2)}%</p>)}{data.limitations.map(x => <p key={x}>{x}</p>)}</details>
    </>}
  </GlassCard>;
}
