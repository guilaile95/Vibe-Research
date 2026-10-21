import { useEffect, useRef, useState } from 'react';
import { filingRequest, filingSourceUrl, comparableSections, type FilingContext, type FilingDiff, type FilingDocument } from '@/lib/filingEvidence';
import type { EvidenceRecord } from '@/lib/api';

const inputClass = 'w-full rounded border border-border bg-background p-2 text-sm';
const blank = { source_identity: '', revision: '', source_title: '', source_date: '', source_url: '', form: '10-K', text: '', corrects_id: '' };

// Keyed by evidence identity and edit token at the entry point: navigation or edits
// discard unfinished forms/results and prevent stale responses being displayed.
export function FilingEvidenceCard({ evidence }: { evidence: EvidenceRecord }) {
  const [context, setContext] = useState<FilingContext | null>(null);
  const [form, setForm] = useState(blank);
  const [opened, setOpened] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [before, setBefore] = useState('');
  const [after, setAfter] = useState('');
  const [section, setSection] = useState('document');
  const [diff, setDiff] = useState<FilingDiff | null>(null);
  const [detail, setDetail] = useState<FilingDocument | null>(null);
  const active = useRef(true);
  const inFlight = useRef(false);
  const detailGeneration = useRef(0);
  useEffect(() => {
    active.current = true;
    let current = true;
    filingRequest<FilingContext>(`/context/${encodeURIComponent(evidence.id)}`).then(value => { if (current) setContext(value); }).catch(e => { if (current) setError(e.message); });
    return () => { current = false; active.current = false; };
  }, [evidence.id]);
  const documents = context?.documents ?? [];
  const sections = comparableSections(documents.find(d => d.id === before), documents.find(d => d.id === after));
  const run = async (action: () => Promise<void>) => {
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(true); setError('');
    try { await action(); } catch (e) { if (active.current) setError(e instanceof Error ? e.message : '请求失败'); }
    finally { inFlight.current = false; if (active.current) setBusy(false); }
  };
  const register = () => run(async () => {
    await filingRequest(`/documents/${encodeURIComponent(evidence.id)}`, { ...form, source_date: form.source_date || null, source_url: form.source_url || null, corrects_id: form.corrects_id || null, expected_edit_token: evidence.edit_token });
    const next = await filingRequest<FilingContext>(`/context/${encodeURIComponent(evidence.id)}`);
    if (active.current) { setContext(next); setOpened(false); setForm(blank); setDiff(null); }
  });
  const clearSelection = () => { setDiff(null); setSection('document'); };
  return <section className="space-y-3 rounded-xl border border-border p-4" aria-label="原始文档证据与章节比较">
    <h2 className="font-semibold">原始文档证据与章节比较</h2>
    <p className="text-sm text-muted-foreground">用户录入/未核验原文。来源、申报类型与完整性均为用户声明；不进入严格 as-of 证据。无模型推断，不自动修改证据主张或正式研究逻辑。</p>
    {error && <p role="alert" className="text-danger">{error}</p>}
    {!context && !error && <p role="status">读取已登记文档…</p>}
    {context?.original_text_status === 'UNAVAILABLE' && <p>原始文档不可用：资讯摘要和证据主张不能替代原文。可显式粘贴本地研究文档，登记为未核验原文。</p>}
    {context?.has_more && <p>仅显示最近 100 个文档版本；较早版本仍保留。</p>}
    <button type="button" disabled={busy} onClick={() => { setOpened(!opened); setForm(blank); }}> {opened ? '取消登记' : '登记用户原文'} </button>
    {opened && <div className="space-y-2">
      <p className="text-sm">纯文本保留空格、数字与表格；不抓取链接，不执行 HTML 或文中指令。最多 200000 字。更正会新增版本并保留旧版。</p>
      <label className="block">申报类型<select aria-label="申报类型" className={inputClass} disabled={busy} value={form.form} onChange={e => setForm({ ...form, form: e.target.value })}>{['10-K', '10-K/A', '10-Q', '10-Q/A', '8-K', '8-K/A', 'announcement'].map(f => <option key={f}>{f}</option>)}</select></label>
      {([['source_identity', '来源文档身份（如本地文件名/登记编号）'], ['revision', '版本标识'], ['source_title', '来源标题'], ['source_date', '来源日期（未知可留空）'], ['source_url', '来源链接（可选）']] as const).map(([key, label]) => <label className="block" key={key}>{label}<input aria-label={label} className={inputClass} disabled={busy} maxLength={key === 'source_url' ? 2000 : 300} type={key === 'source_date' ? 'date' : 'text'} value={form[key]} onChange={e => setForm({ ...form, [key]: e.target.value })} /></label>)}
      <label className="block">更正旧版本（可选）<select aria-label="更正旧版本" className={inputClass} disabled={busy} value={form.corrects_id} onChange={e => setForm({ ...form, corrects_id: e.target.value })}><option value="">新文档</option>{documents.filter(d => d.evidence_id === evidence.id).map(d => <option key={d.id} value={d.id}>{d.source_identity} · {d.revision}</option>)}</select></label>
      <label className="block">原文<textarea aria-label="原文" className={`${inputClass} min-h-40 font-mono whitespace-pre`} disabled={busy} maxLength={200000} value={form.text} onChange={e => setForm({ ...form, text: e.target.value })} /></label>
      <button type="button" disabled={busy || !form.text.trim() || !form.source_identity.trim() || !form.revision.trim() || !form.source_title.trim()} onClick={register}>确认保存未核验原文</button>
    </div>}
    {documents.map(d => <article key={d.id} className="rounded border border-border p-3 text-sm space-y-1">
      <p>{d.source_title} · {d.form} · {d.issuer} · {d.revision}</p>
      <p>用户录入/未核验原文 · 来源日期 {d.source_date || '未知'} · 登记时间 {d.registered_at}</p>
      <p>来源身份：{d.source_identity} · {d.evidence_id === evidence.id ? '当前证据' : '同一发行人的其他证据'}</p>
      <p className="break-all">SHA-256：{d.sha256}</p>
      {d.corrects_id && <p>更正版本，原版本保留：{d.corrects_id}</p>}
      <p>附件：未登记；不会推断或下载附件</p>
      {d.warnings.map(w => <p key={w} className="text-warning">{w}</p>)}
      {filingSourceUrl(d.source_url) && <a href={filingSourceUrl(d.source_url)!} target="_blank" rel="noopener noreferrer" className="underline">打开用户声明的来源</a>}
      <button type="button" disabled={busy} onClick={() => run(async () => { const generation = ++detailGeneration.current; const doc = await filingRequest<FilingDocument>(`/documents/${d.id}`); if (active.current && generation === detailGeneration.current) setDetail(doc); })}>查看保留原文与章节</button>
    </article>)}
    {detail && <div><button type="button" onClick={() => { ++detailGeneration.current; setDetail(null); }}>关闭原文</button><p>{detail.source_title} · {detail.revision}</p><p>{detail.sections.map(s => s.title).join(' / ')}</p><pre className="max-h-96 overflow-auto border p-2 text-xs">{detail.text}</pre></div>}
    {documents.length > 1 && <div className="space-y-2">
      <p>选择同一发行人、完全相同类型的两个版本；10-Q 章节按 Part 区分，修订类型不混用</p>
      {([['before', before, setBefore], ['after', after, setAfter]] as const).map(([label, value, setter]) => <label className="block" key={label}>{label === 'before' ? '旧文档' : '新文档'}<select aria-label={label === 'before' ? '旧文档' : '新文档'} className={inputClass} disabled={busy} value={value} onChange={e => { setter(e.target.value); clearSelection(); }}><option value="">请选择</option>{documents.map(d => <option key={d.id} value={d.id}>{d.source_title} · {d.form} · {d.revision}</option>)}</select></label>)}
      <label className="block">相同章节<select aria-label="相同章节" className={inputClass} disabled={busy} value={section} onChange={e => { setSection(e.target.value); setDiff(null); }}>{sections.map(s => <option key={s.key} value={s.key}>{s.title}</option>)}</select></label>
      {before && after && !sections.length && <p>不可比较：需要不同文档、同一发行人及完全相同类型</p>}
      <button type="button" disabled={busy || !sections.some(s => s.key === section)} onClick={() => run(async () => { setDiff(null); const result = await filingRequest<FilingDiff>('/compare', { before_id: before, after_id: after, section }); if (active.current) setDiff(result); })}>比较原文差异</button>
    </div>}
    {diff && <div aria-label="原文差异结果"><h3>确定性逐行文本差异 · 非模型推断</h3><p className="break-all text-xs">旧 SHA-256 {diff.before.sha256} / 新 SHA-256 {diff.after.sha256}</p><p>删除用 −，新增用 +；数字与表格未清洗或截断</p>{diff.changes.map((c, i) => <div key={i}>{c.kind === 'equal' ? <pre className="overflow-auto text-xs">{c.before}</pre> : <>{c.before && <div className="bg-danger/10"><span>− 删除</span><pre className="overflow-auto text-xs">{c.before}</pre></div>}{c.after && <div className="bg-success/10"><span>+ 新增</span><pre className="overflow-auto text-xs">{c.after}</pre></div>}</>}</div>)}</div>}
  </section>;
}
