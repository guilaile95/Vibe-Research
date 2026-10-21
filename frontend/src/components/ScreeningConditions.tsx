import { useEffect, useRef, useState } from 'react';
import { get, request } from '../lib/api.ts';
import type { FullMarketFilter } from '../lib/recoveredMarketTypes.ts';

type Condition = FullMarketFilter & { observed: number | null; status: string; unit: string; missingness: string | null };
type Row = { code: string; latest_date: string | null; status: string; conditions: Condition[] };
type Card = { id: string; name: string; version: number; filters: FullMarketFilter[] };
type Run = { id: string; card: Card; snapshot_id: string; cutoff: string; as_of: string; provider_id: string; adjustment: string; saved_at: string; counts: Record<string, number>; rows?: Row[]; limitations: string[] };
type Catalog = { cards: Card[]; runs: Run[] };
type Comparison = { before_id: string; after_id: string; rule_changed: boolean; data_changed: boolean; changes: { code: string; transition: string; reasons: string[]; before: Row | null; after: Row | null }[]; limitations: string[] };
const base = '/screener';
const control = 'rounded border border-border bg-background px-2 py-1 disabled:opacity-40';
function Evidence({ row }: { row: Row | null }) {
  if (!row) return <span>UNKNOWN · 覆盖缺失</span>;
  return <div>{row.code} · {row.status} · {row.latest_date || '日期缺失'}{row.conditions.map((c, i) => <div key={i} className="pl-3">{c.metric} {c.operator} {c.value} → {c.status} · 实际 {c.observed ?? '缺失'} {c.unit}{c.missingness ? ` · ${c.missingness}` : ''}</div>)}</div>;
}
export function ScreeningConditions({ filters, cutoff }: { filters: { metric: FullMarketFilter['metric']; operator: FullMarketFilter['operator']; value: string }[]; cutoff: string | null }) {
  const [catalog, setCatalog] = useState<Catalog>({ cards: [], runs: [] });
  const [name, setName] = useState('我的筛选');
  const [cardId, setCardId] = useState('');
  const [before, setBefore] = useState(''); const [after, setAfter] = useState('');
  const [run, setRun] = useState<Run | null>(null); const [comparison, setComparison] = useState<Comparison | null>(null);
  const [error, setError] = useState(''); const [busy, setBusy] = useState(false);
  const generation = useRef(0); const active = useRef<AbortController | null>(null);
  const context = JSON.stringify({ filters, cutoff });
  useEffect(() => { generation.current++; active.current?.abort(); setRun(null); setComparison(null); setBusy(false); }, [context]);
  useEffect(() => { void perform(async (signal) => { const c = await get<Catalog>(`${base}/condition-cards`, { signal, unwrapData: false }); return () => setCatalog(c); }); return () => { generation.current++; active.current?.abort(); }; }, []);
  async function perform(work: (signal: AbortSignal) => Promise<() => void>) {
    const id = ++generation.current; active.current?.abort(); const controller = new AbortController(); active.current = controller;
    setBusy(true); setError(''); setRun(null); setComparison(null);
    try { const apply = await work(controller.signal); if (id === generation.current) apply(); }
    catch { if (id === generation.current && !controller.signal.aborted) setError('筛选归档暂不可用，未显示旧响应；请刷新后重试'); }
    finally { if (id === generation.current) setBusy(false); }
  }
  const reload = (signal: AbortSignal) => get<Catalog>(`${base}/condition-cards`, { signal, unwrapData: false });
  return <section className="space-y-3 rounded border border-border p-3 text-xs" data-testid="screen-condition-cards">
    <h3 className="font-semibold">条件卡与入选 / 退出解释</h3>
    <p className="text-muted-foreground">保存当前条件为命名版本，再显式运行并归档。UNKNOWN 表示历史不足、陈旧或覆盖缺失，不代表基本面恶化。不会自动加入关注或交易。</p>
    <p>收益与均线偏离以小数输入（0.1 = 10%）；运行只采用截止日期之前最新观测，旧 Full Market 数值匹配可能包含陈旧行，此处入选要求全部 PASS。</p>
    <div className="flex flex-wrap gap-2">
      <input aria-label="条件卡名称" className={control} value={name} maxLength={80} disabled={busy} onChange={e => setName(e.target.value)} />
      <button type="button" className={control} disabled={busy || !name.trim() || !filters.length || filters.some(f => !f.value.trim() || !Number.isFinite(Number(f.value)))} onClick={() => void perform(async signal => { const card = await request<Card>(`${base}/condition-cards`, 'POST', { name, filters: filters.map(f => ({ ...f, value: Number(f.value) })) }, { signal, unwrapData: false }); const c = await reload(signal); return () => { setCatalog(c); setCardId(card.id); setRun(null); setComparison(null); }; })}>保存新版本</button>
      <button type="button" className={control} disabled={busy} onClick={() => void perform(async signal => { const c = await reload(signal); return () => { setCatalog(c); setRun(null); setComparison(null); }; })}>刷新已存记录</button>
    </div>
    <div className="flex flex-wrap gap-2">
      <select aria-label="已存条件卡" className={control} value={cardId} disabled={busy} onChange={e => { setCardId(e.target.value); setRun(null); setComparison(null); }}><option value="">选择版本</option>{catalog.cards.map(c => <option key={c.id} value={c.id}>{c.name} v{c.version}</option>)}</select>
      <button type="button" className={control} disabled={busy || !cardId || cutoff === ''} onClick={() => void perform(async signal => { const r = await request<Run>(`${base}/condition-runs`, 'POST', { card_id: cardId, as_of: cutoff }, { signal, unwrapData: false }); const c = await reload(signal); return () => { setCatalog(c); setRun(r); setComparison(null); setAfter(r.id); }; })}>运行选定版本并保存</button>
      <span>截止：{cutoff || '快照最新日'}</span>
    </div>
    {catalog.cards.find(c => c.id === cardId)?.filters.map((f, i) => <p key={i}>已存条件 {i + 1}：{f.metric} {f.operator} {f.value}</p>)}
    {(['before', 'after'] as const).map(side => <label key={side} className="mr-2 inline-flex gap-2">{side === 'before' ? '之前' : '之后'}<select aria-label={side === 'before' ? '之前的运行' : '之后的运行'} className={control} disabled={busy} value={side === 'before' ? before : after} onChange={e => { (side === 'before' ? setBefore : setAfter)(e.target.value); setComparison(null); setRun(null); }}><option value="">选择已存运行</option>{catalog.runs.map(r => <option key={r.id} value={r.id}>{r.card.name} v{r.card.version} · {r.cutoff} · {r.id.slice(0, 8)}</option>)}</select></label>)}
    <button type="button" className={control} disabled={busy || !before || !after || before === after} onClick={() => void perform(async signal => { const c = await get<Comparison>(`${base}/condition-runs/compare?before=${before}&after=${after}`, { signal, unwrapData: false }); return () => { setComparison(c); setRun(null); }; })}>比较入选 / 退出</button>
    <button type="button" className={control} disabled={busy || !after} onClick={() => void perform(async signal => { const r = await get<Run>(`${base}/condition-runs/${after}`, { signal, unwrapData: false }); return () => { setRun(r); setComparison(null); }; })}>读取之后的运行</button>
    {busy && <p role="status">处理中…</p>}{error && <p role="alert" className="text-destructive">{error}</p>}
    {run && <div><p className="break-all">运行 {run.id} · {run.card.name} v{run.card.version} · 快照 {run.snapshot_id} · 截止 {run.cutoff} · 观测 {run.as_of} · {run.provider_id} / {run.adjustment}</p><p>PASS {run.counts.PASS} · FAIL {run.counts.FAIL} · UNKNOWN {run.counts.UNKNOWN}</p><div className="max-h-96 overflow-auto">{run.rows?.map(row => <details key={row.code}><summary>{row.code} · {row.status}</summary><Evidence row={row} /></details>)}</div>{run.limitations.map(x => <p key={x}>{x}</p>)}</div>}
    {comparison && <div><p>规则变化：{comparison.rule_changed ? '有' : '无'} · 数据 / 截止变化：{comparison.data_changed ? '有' : '无'} · 差异 {comparison.changes.length} 条</p><p className="break-all">{comparison.before_id} → {comparison.after_id}</p><div className="max-h-96 overflow-auto">{comparison.changes.map(c => <details key={c.code}><summary>{c.code} · {c.transition} · {c.reasons.join(' / ')}</summary><p>之前</p><Evidence row={c.before} /><p>之后</p><Evidence row={c.after} /></details>)}</div>{comparison.limitations.map(x => <p key={x}>{x}</p>)}</div>}
  </section>;
}
