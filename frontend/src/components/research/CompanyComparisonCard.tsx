import { useEffect, useRef, useState } from 'react';
import { loadLlm, LLM_CHANGED_EVENT } from '@/lib/llm';
import type { Subject } from '@/lib/companyResearch';
import { comparisonDayValid, comparisonSubjectValid, generateComparison, readComparisonBundle, readComparisonBundles, readComparisonRunPage, type ComparisonBundleChoice, type ComparisonRecord } from '@/lib/companyComparison';
// Native controls must use the same palette as the surrounding theme, including picker chrome.
const controlTheme = "border-border bg-background text-foreground [color-scheme:dark] [.light_&]:[color-scheme:light]";
const same = (a: Subject, b: Subject) => a.market === b.market && a.symbol === b.symbol;
function ComparisonResult({ record }: { record: ComparisonRecord }) {
  return <article className="my-3 space-y-2 rounded border border-border p-3" data-testid="company-comparison-result">
    <p className="text-xs break-all">{record.as_of} · {record.status} · {record.run_id} · 配对哈希 {record.pair_sha256}</p>
    <p className="text-xs text-warning">AI 草稿，事实和数字未核验；币种、单位、报告期可比性尚未建立。未进行结构化排名；文字不构成投资结论。</p>
    {record.subjects.map((s, i) => <section key={`${s.market}:${s.symbol}`} className="space-y-1 border-t border-border pt-2">
      <h4 className="font-semibold">{s.market}:{s.symbol}</h4><p className="break-all text-xs">资料包 {s.bundle_id} · SHA256 {s.expected_bundle_sha256}</p>
      {record.output && <><p className="whitespace-pre-wrap text-sm">{record.output.subjects[i].summary}</p><p className="text-xs">引用：{record.output.subjects[i].citations.map(c => `${c.market}:${c.symbol}/${c.evidence_id}`).join('、') || '无可用来源'}</p><p className="text-xs text-warning">模型列出的缺口与限制：{[...record.output.subjects[i].missingness, ...record.output.subjects[i].caveats].join('；') || '未额外列出，不代表完整'}</p></>}
      <ul className="break-words text-xs">{record.evidence[i].sources.map(r => <li key={r.evidence_id}>{r.fixture && '合成案例（非真实市场验收） · '}{s.market}:{s.symbol}/{r.evidence_id} · {r.source} · {r.status} · 来源时点 {r.source_as_of ?? '未知'} · 采集 {r.captured_at} · 单位与报告期未核验<p className="break-all">来源哈希 {r.payload_sha256}</p></li>)}</ul>
    </section>)}
  </article>;
}
export function CompanyComparisonCard({ subject }: { subject: Subject }) {
  const [market, setMarket] = useState<Subject['market']>('A'); const [symbol, setSymbol] = useState(''); const [asOf, setAsOf] = useState('');
  const [choices, setChoices] = useState<ComparisonBundleChoice[][]>([[], []]); const [selected, setSelected] = useState(['', '']); const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false); const [error, setError] = useState('');
  const [record, setRecord] = useState<ComparisonRecord | null>(null); const [history, setHistory] = useState<ComparisonRecord[]>([]);
  const [historyCursor, setHistoryCursor] = useState<string | null>(null);
  const [resultContext, setResultContext] = useState(''); const [historyContext, setHistoryContext] = useState('');
  const owner = useRef<AbortController | null>(null); const context = `${subject.market}:${subject.symbol}|${market}:${symbol}|${asOf}`; const contextRef = useRef(context); contextRef.current = context;
  const stop = () => { owner.current?.abort(); owner.current = null; setBusy(false); };
  const reset = () => { stop(); setChoices([[], []]); setSelected(['', '']); setLoaded(false); setRecord(null); setHistory([]); setHistoryContext(''); setHistoryCursor(null); setError(''); };
  useEffect(() => { reset(); return () => { owner.current?.abort(); owner.current = null; }; }, [subject.market, subject.symbol]);
  useEffect(() => { const changed = () => { stop(); setError('模型配置已变化；请重新确认预算后手动开始'); }; window.addEventListener(LLM_CHANGED_EVENT, changed); return () => window.removeEventListener(LLM_CHANGED_EVENT, changed); }, []);
  const second = { market, symbol }; const valid = comparisonSubjectValid(subject) && comparisonSubjectValid(second) && !same(subject, second) && comparisonDayValid(asOf);
  const operation = async (work: (signal: AbortSignal, active: () => boolean) => Promise<void>) => {
    if (owner.current) return;
    const controller = new AbortController(); owner.current = controller; const key = context; setBusy(true); setError('');
    const active = () => owner.current === controller && !controller.signal.aborted && contextRef.current === key;
    try { await work(controller.signal, active); } catch (e) { if (active()) setError(e instanceof Error ? e.message : '对比操作未完成'); }
    finally { if (active()) { owner.current = null; setBusy(false); } }
  };
  const read = () => operation(async (signal, active) => {
    if (!valid) throw new Error('请选择两只不同股票和有效归档截止日');
    setLoaded(false); setRecord(null); setChoices([[], []]); setSelected(['', '']);
    const rows = await Promise.all([readComparisonBundles(subject, asOf, signal), readComparisonBundles(second, asOf, signal)]);
    if (active()) { setChoices(rows); setLoaded(true); }
  });
  const readHistory = (before?: string) => operation(async (signal, active) => {
    const page = await readComparisonRunPage(subject, second, asOf, signal, before);
    if (active()) {
      // Show one bounded page at a time, rather than accumulating unbounded history.
      setHistory(page.records); setHistoryCursor(page.next_cursor); setHistoryContext(context);
    }
  });
  const generate = async () => {
    if (!valid || owner.current) return;
    const pair = choices.map((rows, i) => rows.find(b => b.bundle_id === selected[i]));
    if (pair.some(b => !b || b.available_source_count < 1)) { setError('请为两只股票分别选择已冻结资料包'); return; }
    const llm = loadLlm();
    if (!llm || llm.provider.startsWith('cli-')) { setError('两股对比需要 API 模型；订阅运行时暂不支持，不会自动切换模型'); return; }
    let destination = '';
    try { const url = new URL(llm.baseURL); if (!['https:','http:'].includes(url.protocol) || url.username || url.password || url.search || url.hash) throw new Error(); destination = url.origin; }
    catch { setError('模型接收端无效，请检查设置'); return; }
    if (!confirm(`将 ${subject.market}:${subject.symbol} 与 ${market}:${symbol} 的两份已冻结公开资料发送到 ${destination}（${llm.model}）。截止日 ${asOf}；最多1次模型调用、90秒、2500输出token，无自动重试，可能收费。仅生成未核验的并列研究草稿；未知单位与报告期不作排名。继续？`)) return;
    await operation(async (signal, active) => {
      setRecord(null); const bundles = await Promise.all(pair.map(b => readComparisonBundle(b!, signal))); if (!active()) return;
      const result = await generateComparison(bundles, asOf, llm, signal); if (active()) { setRecord(result); setResultContext(context); }
    });
  };
  return <details className="mb-4 rounded-xl border border-border p-4" data-testid="company-comparison">
    <summary className="cursor-pointer font-semibold">两股归档研究对比 · {subject.market}:{subject.symbol}</summary>
    <p className="my-2 text-xs text-muted-foreground">选择另一只股票和共同截止日，再读取已有冻结资料。没有资料时先使用六阶段公司研究的公开资料采集。此处不会自动采集或调用模型；当前存储版本不代表历史当时已知，同截止日不代表币种、单位或报告期可比。</p>
    <div className="flex flex-wrap gap-2 text-sm"><label>对比市场<select aria-label="对比市场" value={market} disabled={busy} onChange={e => { reset(); setMarket(e.target.value as Subject['market']); setSymbol(''); }} className={`${controlTheme} ml-2 min-h-11 rounded border p-2`}><option>A</option><option>HK</option><option>US</option></select></label><label>对比代码<input aria-label="对比代码" value={symbol} maxLength={15} disabled={busy} onChange={e => { reset(); setSymbol(e.target.value.trim().toUpperCase()); }} className={`${controlTheme} ml-2 min-h-11 w-32 rounded border p-2`} /></label><label>共同归档截止日<input aria-label="对比归档截止日" type="date" value={asOf} disabled={busy} onChange={e => { reset(); setAsOf(e.target.value); }} className={`${controlTheme} ml-2 min-h-11 rounded border p-2`} /></label></div>
    <button type="button" disabled={busy || !valid} onClick={() => void read()} className="min-h-11 text-primary disabled:opacity-50">读取两股已有资料（不调用模型）</button>
    {loaded && choices.map((rows, i) => <div key={i} className="my-2 text-xs"><label>{i === 0 ? `${subject.market}:${subject.symbol}` : `${market}:${symbol}`} 冻结资料<select aria-label={`对比资料${i + 1}`} disabled={busy} value={selected[i]} onChange={e => { setSelected(old => old.map((v, j) => j === i ? e.target.value : v)); setRecord(null); }} className={`${controlTheme} block min-h-11 w-full rounded border p-2`}><option value="">请选择资料包</option>{rows.map(b => <option key={b.bundle_id} value={b.bundle_id} disabled={b.available_source_count < 1}>{b.captured_at} · 可用{b.available_source_count}/缺口{b.missing_source_count} · {b.bundle_id}</option>)}</select></label>{!rows.some(b => b.available_source_count > 0) && <p className="text-warning">该身份和截止日没有可用的已冻结资料，不能生成对比</p>}</div>)}
    <div className="flex flex-wrap gap-3"><button type="button" disabled={busy || !valid || selected.some((v, i) => !choices[i].some(b => b.bundle_id === v && b.available_source_count > 0))} onClick={() => void generate()} className="min-h-11 text-primary disabled:opacity-50">确认一次调用预算并开始对比</button>{busy && <button type="button" className="min-h-11" onClick={() => { stop(); setError('已取消；未完成报告不保存为完成，已产生的模型费用可能无法撤销'); }}>取消对比</button>}<button type="button" disabled={busy || !valid} className="min-h-11 text-primary disabled:opacity-50" onClick={() => void readHistory()}>读取该配对历史</button></div>
    {busy && <p role="status" className="text-xs">正在处理当前配对…</p>}{error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    {record && resultContext === context && <ComparisonResult record={record} />}
    {historyContext === context && history.length === 0 && <p className="text-xs">本次未返回该配对和截止日的历史记录</p>}
    {historyContext === context && historyCursor && <button type="button" disabled={busy} className="min-h-11 text-primary" onClick={() => void readHistory(historyCursor)}>读取更早一页（最多50条）</button>}
    {historyContext === context && history.map(row => <details key={row.run_id}><summary className="min-h-11 text-xs">{row.started_at} · {row.status === 'RUNNING' ? '未结束记录（不代表仍在运行）' : row.status}</summary><ComparisonResult record={row} /></details>)}
  </details>;
}
