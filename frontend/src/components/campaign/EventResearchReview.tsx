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


export function CampaignEventReviewHistory({ campaignIds }: { campaignIds: string[] }) {
  const [campaignId, setCampaignId] = useState('');
  const selected = campaignIds.includes(campaignId) ? campaignId : '';
  if (!campaignIds.length) return null;
  return <section className="rounded border p-3 text-xs" aria-label="已绑定事件复核记录">
    <h3>已绑定事件复核记录（保留窗口外的历史）</h3>
    <label>Campaign <select aria-label="查看 Campaign 复核历史" value={selected} onChange={e => setCampaignId(e.target.value)}>
      <option value="">请选择</option>{[...new Set(campaignIds)].map(id => <option key={id} value={id}>{id}</option>)}
    </select></label>
    {selected && <CampaignReview key={selected} campaignId={selected} />}
  </section>;
}
