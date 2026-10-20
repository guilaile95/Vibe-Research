import { useEffect, useRef, useState } from 'react';
import { request as apiRequest, type EvidenceRecord } from '@/lib/api';
import { filingSourceUrl } from '@/lib/filingEvidence';

type Role = 'original' | 'commentary' | 'unknown' | 'correction' | 'amendment';
interface Member { evidence_id: string; role: Role; relates_to: string | null; source_kind: string; evidence_snapshot: EvidenceRecord }
interface Group { group_id: string; anchor_id: string; subject_id: string; period: string; revision: number; members: Member[]; created_at: string }
interface Context { groups: Group[]; history: Group[]; candidates: EvidenceRecord[]; current_members: EvidenceRecord[]; member_conflicts: { evidence_id: string; reason: string }[]; has_more: boolean; ownership_change: { status: string } }
const roles: Record<Role, string> = { original: '用户标注原始公告', commentary: '用户标注评论/报道', unknown: '角色未知', correction: '用户标注更正', amendment: '用户标注修订' };
const input = 'w-full rounded border border-border bg-background p-2 text-sm';
function request<T>(path: string, payload?: unknown): Promise<T> {
  return apiRequest<T>(`/announcement-groups${path}`, payload === undefined ? 'GET' : 'POST', payload);
}

// Remounted by evidence id/edit token: late responses cannot cross subjects.
export function AnnouncementGroupsCard({ evidence }: { evidence: EvidenceRecord }) {
  const [context, setContext] = useState<Context | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [period, setPeriod] = useState('');
  const [selected, setSelected] = useState('');
  const [role, setRole] = useState<Role>('unknown');
  const [anchorRole, setAnchorRole] = useState<Role>('unknown');
  const [target, setTarget] = useState('');
  const [confirmed, setConfirmed] = useState(false);
  const active = useRef(true);
  const inFlight = useRef(false);
  const [reload, setReload] = useState(0);
  useEffect(() => {
    active.current = true;
    let current = true;
    setContext(null); setError('');
    request<Context>(`/context/${encodeURIComponent(evidence.id)}`).then(result => { if (current) setContext(result); }).catch(e => { if (current) setError(e.message); });
    return () => { current = false; active.current = false; };
  }, [evidence.id, reload]);
  const group = context?.groups[0];
  const anchorId = group?.anchor_id ?? evidence.id;
  const candidates = context?.candidates.filter(c => c.id !== anchorId && !group?.members.some(m => m.evidence_id === c.id)) ?? [];
  const canCreate = ['announcement', 'financial_filing'].includes(evidence.evidence_type);
  const save = async () => {
    if (inFlight.current || !context || !confirmed || context.member_conflicts.length) return;
    const ids = group ? group.members.map(m => m.evidence_id) : [evidence.id];
    const current = new Map([...context.candidates, ...context.current_members].map(c => [c.id, c]));
    if ([...ids, selected].some(id => !current.has(id))) { setError('成员不在当前可用证据中，请刷新并检查原证据'); return; }
    const members = group ? group.members.map(m => ({ evidence_id: m.evidence_id, role: m.role, relates_to: m.relates_to, expected_edit_token: current.get(m.evidence_id)!.edit_token })) : [{ evidence_id: evidence.id, role: anchorRole, relates_to: null, expected_edit_token: current.get(evidence.id)!.edit_token }];
    members.push({ evidence_id: selected, role, relates_to: ['correction', 'amendment'].includes(role) ? target : null, expected_edit_token: current.get(selected)!.edit_token });
    inFlight.current = true; setBusy(true); setError('');
    try {
      await request('', { request_id: crypto.randomUUID(), group_id: group?.group_id ?? null, anchor_id: anchorId, period: group?.period ?? period, expected_revision: group?.revision ?? 0, members });
      if (active.current) { setSelected(''); setConfirmed(false); setReload(n => n + 1); }
    } catch (e) { if (active.current) setError(e instanceof Error ? e.message : '保存失败，请刷新核对'); }
    finally { inFlight.current = false; if (active.current) setBusy(false); }
  };
  const renderGroup = (item: Group) => <ul className="space-y-2">{item.members.map(member => <li key={member.evidence_id} className="rounded border border-border p-2">
    <a className="underline" href={`/evidence/${encodeURIComponent(member.evidence_id)}`}>{member.evidence_snapshot.source_title || member.evidence_id}</a>
    <p>{roles[member.role]} · 来源类型（登记值）：{member.source_kind}</p>
    <p className="whitespace-pre-wrap">{member.evidence_snapshot.claim}</p>
    <p className="text-xs">来源日期：{member.evidence_snapshot.source_date || '未知'} · 保留版本：{member.evidence_snapshot.updated_at}</p>
    {member.relates_to && <p>关联原证据：{member.relates_to}</p>}
    {filingSourceUrl(member.evidence_snapshot.source_url) && <a className="underline" target="_blank" rel="noopener noreferrer" href={filingSourceUrl(member.evidence_snapshot.source_url)!}>打开登记来源</a>}
  </li>)}</ul>;
  return <section className="rounded-xl border border-border p-4 space-y-3 text-sm" aria-label="公告中心用户关联">
    <h3 className="font-semibold">公告中心用户关联</h3>
    <p>用户关联 / 未验证为同一事件。仅组织已登记证据，不自动合并同标题，不改变原证据、来源可信度或严格时点资格。原始公告与评论角色未经核验。</p>
    {error && <p role="alert">{error} <button type="button" disabled={busy} onClick={() => setReload(n => n + 1)}>刷新核对</button></p>}
    {!context && !error && <p>正在读取本地关联…</p>}
    {context && <>
      {context.member_conflicts.map(item => <p role="alert" key={item.evidence_id}>成员 {item.evidence_id}：{item.reason}。无法追加，请核对原证据；不会自动删除成员。</p>)}
      {context.groups.map(item => <details key={item.group_id} open><summary>用户声明范围：{item.period} · {item.members.length} 条证据 · 修订 {item.revision}</summary>{renderGroup(item)}</details>)}
      {context.history.length > 1 && <details><summary>保留的全部分组修订（{context.history.length}）</summary>{context.history.map(item => <details key={`${item.group_id}:${item.revision}`}><summary>修订 {item.revision} · {item.created_at}</summary>{renderGroup(item)}</details>)}</details>}
      {(group || canCreate) && <details><summary>{group ? '追加关联证据（保留现有成员）' : '手动登记关联'}</summary><div className="space-y-2 mt-2">
        {!group && <><label className="block">报告期 / 事件范围<input className={input} value={period} maxLength={100} disabled={busy} onChange={e => setPeriod(e.target.value)} /></label>
          <label className="block">中心证据角色<select className={input} value={anchorRole} disabled={busy} onChange={e => setAnchorRole(e.target.value as Role)}><option value="unknown">角色未知</option><option value="original">用户标注原始公告</option></select></label></>}
        <label className="block">同一个股的另一条证据<select className={input} value={selected} disabled={busy} onChange={e => setSelected(e.target.value)}><option value="">请选择</option>{candidates.map(c => <option key={c.id} value={c.id}>{c.source_date || '日期未知'} · {c.source_title} · {c.claim.slice(0, 80)}</option>)}</select></label>
        <label className="block">关系<select className={input} value={role} disabled={busy} onChange={e => setRole(e.target.value as Role)}>{Object.entries(roles).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
        {['correction', 'amendment'].includes(role) && <label className="block">更正 / 修订哪条原证据<select className={input} value={target} disabled={busy} onChange={e => setTarget(e.target.value)}><option value="">请选择</option>{(group?.members.map(m => m.evidence_snapshot) ?? [evidence]).map(c => <option key={c.id} value={c.id}>{c.source_title} · {c.id}</option>)}</select></label>}
        <label className="block"><input type="checkbox" checked={confirmed} disabled={busy} onChange={e => setConfirmed(e.target.checked)} /> 我声明所选证据属于上述同一报告期 / 事件；此关联未经来源核验</label>
        <button type="button" disabled={busy || context.member_conflicts.length > 0 || !selected || !confirmed || (!group && !period.trim()) || (['correction', 'amendment'].includes(role) && !target)} onClick={save}>{busy ? '保存中…' : '保存用户关联'}</button>
      </div></details>}
      {context.has_more && <p>候选仅显示最近 200 条；未加载的证据不能在此追加。</p>}
      <p className="text-xs text-muted-foreground">持股变动卡：尚未实现，缺少已核验的 13D/13G/Form 4 等结构化来源及发行人、持有人、日期与修订身份。用户粘贴文本不替代该来源。</p>
    </>}
  </section>;
}
