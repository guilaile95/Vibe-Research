import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { applyReviewResponse, reviewRequest, reviewStatus, type EventReview, type ReviewContext, type ReviewEvent } from '@/lib/eventResearchReview';

function Judgment({ review, context, onSave }: { review: EventReview; context: ReviewContext; onSave: (row: EventReview) => void }) {
  const [reason, setReason] = useState('');
  const [outcome, setOutcome] = useState('insufficient');
  const [ids, setIds] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  if (review.judgment) return <div className="mt-2 space-y-1 rounded border p-2">
    <p>{reviewStatus[review.status]} · 已确认，不可改写</p>
    <p>{review.observation.title} · 原预期：{review.expectation}</p><p>{review.judgment.reason}</p>
    <p>审阅于 {review.judgment.reviewed_at}</p>
    {review.judgment.evidence.map(item => <p key={item.id}>{item.source_title}：{item.claim}</p>)}
  </div>;
  return <form className="mt-2 grid gap-2 rounded border p-2" onSubmit={async e => {
    e.preventDefault(); if (busy) return; setBusy(true); setError('');
    try {
      const row = await reviewRequest<EventReview>(`/${encodeURIComponent(review.id)}/judgment`, {
        expected_version: review.version, outcome, reason,
        evidence: context.evidence.filter(item => ids.includes(item.id)).map(item => ({ id: item.id, edit_token: item.edit_token })),
      });
      if (alive.current) onSave(row);
    } catch (err) { if (alive.current) setError(err instanceof Error ? err.message : '保存失败'); }
    finally { if (alive.current) setBusy(false); }
  }}>
    <p>{review.observation.title} · 待复核 · 原预期：{review.expectation}</p>
    <label>复核结论 <select aria-label="复核结论" value={outcome} onChange={e => setOutcome(e.target.value)}>
      <option value="insufficient">证据不足</option><option value="support">支持预期</option><option value="refute">反驳预期</option>
    </select></label>
    <fieldset><legend>选择实际审阅的证据（最多显示 100 条）</legend>
      {context.evidence.map(item => <label className="block" key={item.id}><input type="checkbox" checked={ids.includes(item.id)} onChange={e => setIds(current => e.target.checked ? [...current, item.id] : current.filter(id => id !== item.id))} /> {item.source_title}：{item.claim}</label>)}
      {!context.evidence.length && <p>暂无证据，请先在证据账本添加审阅材料</p>}
    </fieldset>
    <textarea aria-label="复核说明" placeholder="说明证据如何支持、反驳或不足以判断预期" value={reason} maxLength={2000} required onChange={e => setReason(e.target.value)} className="rounded border bg-background p-2" />
    <button disabled={busy || !ids.length || !reason.trim()} type="submit">{busy ? '正在保存…' : '确认并保存不可改写的判断'}</button>
    {error && <p role="alert">{error}</p>}
  </form>;
}

function CampaignReview({ campaignId, event }: { campaignId: string; event?: ReviewEvent }) {
  const [context, setContext] = useState<ReviewContext | null>(null);
  const [expectation, setExpectation] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const generation = useRef(0);
  const mounted = useRef(true);
  const load = () => {
    const request = ++generation.current;
    setContext(null); setError('');
    reviewRequest<ReviewContext>(`/context/${encodeURIComponent(campaignId)}`).then(result => {
      if (applyReviewResponse(request, generation.current, mounted.current)) setContext(result);
    }).catch(err => { if (applyReviewResponse(request, generation.current, mounted.current)) setError(String(err.message)); });
  };
  useEffect(() => { mounted.current = true; load(); return () => { mounted.current = false; generation.current++; }; }, [campaignId]); // selection keyed by parent
  const save = (row: EventReview) => setContext(current => current ? { ...current, reviews: [row, ...current.reviews.filter(item => item.id !== row.id)] } : current);
  const reviews = context?.reviews.filter(row => !event || row.observation.event_id === event.event_id) ?? [];
  const bound = reviews.some(row => row.observation_hash === event?.observation_hash);
  return <div className="mt-2 grid gap-2">
    {error && <p role="alert">{error}</p>}
    <button type="button" disabled={busy} onClick={load}>重新读取逻辑与证据</button>
    {context && <>
      <Link to={`/decision-inbox#campaign-${encodeURIComponent(campaignId)}`}>正式绑定逻辑：{context.thesis.title} · v{context.thesis.current_revision}</Link>
      {event && !bound && <form className="grid gap-2" onSubmit={async e => {
        e.preventDefault(); if (busy) return;
        const request = ++generation.current; setBusy(true); setError('');
        try {
          const row = await reviewRequest<EventReview>('', { campaign_id: campaignId, thesis_id: context.thesis.id,
            expected_thesis_revision: context.thesis.current_revision, event_id: event.event_id, event_type: event.event_type,
            expected_observation_hash: event.observation_hash, observation_receipt: event.observation_receipt, expectation });
          if (applyReviewResponse(request, generation.current, mounted.current)) { save(row); setExpectation(''); }
        } catch (err) { if (applyReviewResponse(request, generation.current, mounted.current)) setError(err instanceof Error ? err.message : '保存失败'); }
        finally { if (applyReviewResponse(request, generation.current, mounted.current)) setBusy(false); }
      }}>
        <textarea aria-label="待验证预期" placeholder="写明此事件要检验的研究预期" required maxLength={2000} value={expectation} onChange={e => setExpectation(e.target.value)} className="rounded border bg-background p-2" />
        <button type="submit" disabled={busy || !expectation.trim() || !event.observation_receipt}>{busy ? '正在绑定…' : '明确绑定此事件版本并待复核'}</button>
        {!event.observation_receipt && <p>请刷新日历取得可验证的事件观察凭据</p>}
      </form>}
      {reviews.map(row => <Judgment key={row.id} review={row} context={context} onSave={save} />)}
    </>}
  </div>;
}

export function EventResearchReview({ event }: { event: ReviewEvent }) {
  const [open, setOpen] = useState(false);
  const [campaignId, setCampaignId] = useState('');
  if (!event.campaign_ids.length) return null;
  return <details className="mt-3 text-xs" onToggle={e => setOpen(e.currentTarget.open)}>
    <summary className="cursor-pointer text-primary">绑定研究预期 / 事件复核</summary>
    <p className="my-2">由你明确绑定并判断；事件出现不代表预期成立，不改变正式逻辑、决策或交易。来源更新后可另建复核，历史判断保持不变。</p>
    <label>选择 Campaign <select aria-label="选择复核 Campaign" value={campaignId} onChange={e => setCampaignId(e.target.value)}>
      <option value="">请选择</option>{[...new Set(event.campaign_ids)].map(id => <option key={id} value={id}>{id}</option>)}
    </select></label>
    {open && campaignId && <CampaignReview key={`${campaignId}:${event.event_id}:${event.observation_hash}`} campaignId={campaignId} event={event} />}
  </details>;
}


export function CampaignEventReviewHistory({ securityCode, reloadEpoch = 0 }: { securityCode?: string; reloadEpoch?: number }) {
  const [rows, setRows] = useState<EventReview[]>([]);
  const [next, setNext] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [campaignFilter, setCampaignFilter] = useState('');
  const [appliedCampaign, setAppliedCampaign] = useState('');
  const [reviewCampaign, setReviewCampaign] = useState('');
  const [opened, setOpened] = useState(false);
  const generation = useRef(0);
  const load = (cursor?: string) => {
    const request = ++generation.current;
    setBusy(true); setError('');
    const params = new URLSearchParams();
    if (securityCode) params.set('security_code', securityCode);
    if (appliedCampaign) params.set('campaign_id', appliedCampaign);
    if (cursor) params.set('cursor', cursor);
    reviewRequest<{ items: EventReview[]; next_cursor: string | null }>(`/history?${params}`).then(page => {
      if (request !== generation.current) return;
      setRows(current => cursor ? [...current, ...page.items] : page.items);
      setNext(page.next_cursor);
    }).catch(err => { if (request === generation.current) setError(err instanceof Error ? err.message : '历史读取失败'); })
      .finally(() => { if (request === generation.current) setBusy(false); });
  };
  useEffect(() => {
    setRows([]); setNext(null); setReviewCampaign('');
    if (opened) load();
    return () => { generation.current++; };
  }, [securityCode, appliedCampaign, reloadEpoch, opened]);
  return <section className="rounded border p-3 text-xs space-y-2" aria-label="已绑定事件复核记录">
    <h3>已绑定事件复核记录（包括已关闭、拒绝及过期 Campaign）</h3>
    <p>从保存的复核发现历史，不依赖当前扫描范围。历史浏览只读，不重新开放 Campaign 或新增绑定；待复核可进入原有复核流程。</p>
    <form onSubmit={e => { e.preventDefault(); setAppliedCampaign(campaignFilter.trim()); }}>
      <label>筛选历史 Campaign <input value={campaignFilter} onChange={e => setCampaignFilter(e.target.value)} /></label>
      <button type="submit" disabled={busy}>筛选</button>
    </form>
    <button type="button" disabled={busy} onClick={() => opened ? load() : setOpened(true)}>{opened ? '刷新复核历史' : '读取复核历史'}</button>
    {error && <p role="alert">历史读取失败：{error}</p>}
    {busy && <p>正在读取复核历史…</p>}
    {opened && !busy && !error && !rows.length && <p>暂无已保存的复核记录</p>}
    {rows.map(row => <details key={row.id}>
      <summary>{row.observation.security_code} · Campaign {row.campaign_id} · {row.observation.title} · {reviewStatus[row.status]}</summary>
      <p>原预期：{row.expectation}</p>
      <p>研究逻辑 {row.thesis_id} · 保留版本 {row.thesis_revision}</p>
      <p>事件日期：{row.observation.event_date || '未知'} · 来源：{row.observation.source}</p>
      {row.judgment ? <>
        <p>{row.judgment.reason} · 审阅于 {row.judgment.reviewed_at}</p>
        {row.judgment.evidence.map(item => <p key={item.id}>{item.source_title}：{item.claim}</p>)}
      </> : <><p>待复核；历史只读入口不会更改该状态。</p><button type="button" onClick={() => setReviewCampaign(row.campaign_id)}>继续原有复核</button></>}
    </details>)}
    {reviewCampaign && <CampaignReview key={reviewCampaign} campaignId={reviewCampaign} />}
    {next && <button type="button" disabled={busy} onClick={() => load(next)}>加载更早复核</button>}
  </section>;
}
