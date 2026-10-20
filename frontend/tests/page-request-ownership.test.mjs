import test from 'node:test';
import assert from 'node:assert/strict';
import { pageHarness } from './helpers/pageHarness.mjs';
import { flush } from './helpers/askAiHarness.mjs';
const content = h => h.all().flatMap(n=>[n.props?.children].flat(Infinity).filter(v=>typeof v==='string')).join('\n');
const list = code => ({items:[{id:code,code,trade_date:'2026-10-20',summary:`result-${code}`}],total:30});
const revision = (title,rev=1) => ({revision_number:rev,change_summary:title,created_at:null,snapshot:{thesis:{title,core_claims:[],catalysts:[],risks:[],invalidation_conditions:[]},evidence_links:[],evidences:[]}});
const changeCode=(h,code)=>{h.all().find(n=>n.type==='input').props.onChange({target:{value:code}});h.render()};
test('DecisionEvidence current query owns list, errors, loading and page1 submit',async()=>{
 const h=pageHarness('src/pages/DecisionEvidence.tsx','default');const first=h.requests[0];changeCode(h,'B');const second=h.requests[1];
 second.resolve(list('B'));await flush();h.render();assert.match(content(h),/\nB\n/);
 first.resolve(list('A'));await flush();h.render();assert.match(content(h),/\nB\n/);assert.doesNotMatch(content(h),/\nA\n/);
 changeCode(h,'C');const third=h.requests.at(-1);changeCode(h,'D');const fourth=h.requests.at(-1);
 third.reject(new Error('old'));await flush();h.render();assert.match(content(h),/加载决策依据/);assert.doesNotMatch(content(h),/获取决策依据列表失败/);
 fourth.resolve(list('D'));await flush();h.render();
 h.all().find(n=>n.type==='button'&&[n.props.children].flat().includes('下一页 ')).props.onClick();h.render();assert.equal(h.requests.at(-1).args[0].page,2);
 h.requests.at(-1).resolve(list('D'));await flush();h.render();const before=h.requests.length;
 h.all().find(n=>n.type==='form').props.onSubmit({preventDefault(){}});h.render();assert.equal(h.requests.length,before+1);assert.equal(h.requests.at(-1).args[0].page,1);
 h.unmount();h.requests.at(-1).resolve(list('late'));await flush();h.render();assert.doesNotMatch(content(h),/\nlate\n/);
});
test('DecisionEvidence closing and reopening detail invalidates late responses',async()=>{
 const h=pageHarness('src/pages/DecisionEvidence.tsx','default');h.requests[0].resolve({items:[...list('A').items,...list('B').items],total:2});await flush();h.render();
 const buttons=()=>h.all().filter(n=>n.type==='button'&&[n.props.children].flat().some(v=>typeof v==='string'&&v.includes('查看')));
 assert.equal(buttons().length,2);buttons()[0].props.onClick();h.render();const first=h.requests.at(-1);
 const close=()=>h.all().find(n=>n.type==='div'&&n.props.className?.includes('fixed inset-0')).props.onClick();
 close();h.render();buttons()[1].props.onClick();h.render();const second=h.requests.at(-1);
 second.resolve({run:{id:'B',code:'B',summary:'DETAIL-B'},evidence_items:[]});await flush();h.render();
 first.resolve({run:{id:'A',code:'A',summary:'DETAIL-A'},evidence_items:[]});await flush();h.render();assert.match(content(h),/DETAIL-B/);assert.doesNotMatch(content(h),/DETAIL-A/);
 close();h.render();assert.doesNotMatch(content(h),/DETAIL-B/);
});
test('ThesisRevision routes hide stale snapshots, reject late requests and invalid parameters',async()=>{
 const h=pageHarness('src/pages/ThesisRevision.tsx','ThesisRevision',{id:'A',rev:'1'});h.requests[0].resolve(revision('SNAPSHOT-A'));await flush();h.render();assert.match(content(h),/SNAPSHOT-A/);
 h.params({id:'B',rev:'2'});assert.doesNotMatch(content(h),/SNAPSHOT-A/);const second=h.requests.at(-1);second.reject(new Error('missing'));await flush();h.render();assert.doesNotMatch(content(h),/SNAPSHOT-A/);assert.match(content(h),/加载版本快照失败/);
 h.all().find(n=>n.type==='button').props.onClick();h.render();const retry=h.requests.at(-1);h.params({id:'C',rev:'3'});h.requests.at(-1).resolve(revision('SNAPSHOT-C',3));await flush();h.render();retry.resolve(revision('SNAPSHOT-B',2));await flush();h.render();assert.match(content(h),/SNAPSHOT-C/);assert.doesNotMatch(content(h),/SNAPSHOT-B/);
 const before=h.requests.length;h.params({id:'C',rev:'bad'});assert.equal(h.requests.length,before);assert.doesNotMatch(content(h),/SNAPSHOT-C/);assert.match(content(h),/版本参数无效/);
 h.params({id:'D',rev:'1'});const pending=h.requests.at(-1);h.params({id:'D',rev:'0'});pending.resolve(revision('SNAPSHOT-D'));await flush();h.render();assert.doesNotMatch(content(h),/SNAPSHOT-D/);h.unmount();
});
