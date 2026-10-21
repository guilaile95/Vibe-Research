import assert from 'node:assert/strict';
import test from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';
import { readFileSync } from 'node:fs';
import { request as apiRequest } from '../src/lib/api.ts';
import { filingSourceUrl } from '../src/lib/filingEvidence.ts';
const evidence = { id:'anchor', edit_token:'anchor-token', evidence_type:'announcement',source_title:'Same headline',claim:'<script>untrusted</script>',source_url:'javascript:alert(1)' };
const report = {...evidence,id:'report',edit_token:'report-token',evidence_type:'news'};
const context = {groups:[],history:[],candidates:[evidence,report],current_members:[evidence],member_conflicts:[],has_more:false,ownership_change:{status:'NOT_IMPLEMENTED_PREREQUISITE_MISSING'}};
const nodes = t => t==null||typeof t!=='object'?[]:Array.isArray(t)?t.flatMap(nodes):[t,...nodes(t.props?.children)];
const text = t => t==null||typeof t==='boolean'?'':typeof t!=='object'?String(t):Array.isArray(t)?t.map(text).join(''):text(t.props?.children);
const button = (t,label) => nodes(t).find(n=>n.type==='button'&&text(n).includes(label));
const field = (t,label) => nodes(nodes(t).find(n=>n.type==='label'&&text(n).trim().startsWith(label))).find(n=>['input','select'].includes(n.type));
const tick = () => new Promise(r=>setImmediate(r));
function harness(respond) {
  const slots=[],calls=[];let cursor=0,pending=[];
  const react={useState(init){const i=cursor++;if(!(i in slots))slots[i]=init;return[slots[i],v=>{slots[i]=typeof v==='function'?v(slots[i]):v;}];},useRef(init){const i=cursor++;return slots[i]??={current:init};},useEffect(effect,deps){const i=cursor++,old=slots[i];if(!old||deps.some((d,j)=>d!==old.deps[j]))pending.push(()=>{old?.cleanup?.();slots[i]={deps,cleanup:effect()};});}};
  globalThis.localStorage = {getItem: key => key === 'vr-access-key' ? 'synthetic-test-access' : null};
  globalThis.fetch = async(...args)=>{calls.push(args);return respond(...args);};
  const exports={},mods={'@/lib/api':{request:apiRequest},react,'react/jsx-runtime':{jsx:(type,props)=>({type,props}),jsxs:(type,props)=>({type,props})},'@/lib/filingEvidence':{filingSourceUrl}};
  vm.runInNewContext(ts.transpileModule(readFileSync(new URL('../src/components/research/AnnouncementGroupsCard.tsx',import.meta.url),'utf8'),{compilerOptions:{jsx:ts.JsxEmit.ReactJSX,module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,{exports,require:n=>mods[n],Error,URL,Map,crypto:{randomUUID:()=> 'request-1'}});
  return {calls,unmount(){for(const slot of slots)slot?.cleanup?.();},render(){cursor=0;pending=[];const result=exports.AnnouncementGroupsCard({evidence});pending.forEach(f=>f());return result;}};
}
const response = data => ({ok:true,json:async()=>({data})});
function fill(h,label,value){field(h.render(),label).props.onChange({target:{value}});}
test('opening reads only; explicit declaration and single flight required to save manual grouping',async()=>{
  const h=harness(async()=>response(context));h.render();await tick();
  assert.equal(h.calls.length,1);assert.equal(h.calls[0][1].method,'GET');assert.equal(h.calls[0][1].headers.Authorization,'Bearer synthetic-test-access');
  assert.equal(button(h.render(),'保存用户关联').props.disabled,true);
  fill(h,'报告期','FY2025');fill(h,'同一个股','report');
  field(h.render(),'我声明').props.onChange({target:{checked:true}});
  const save=button(h.render(),'保存用户关联');assert.equal(save.props.disabled,false);save.props.onClick();save.props.onClick();await tick();
  const writes=h.calls.filter(c=>c[1].method==='POST');assert.equal(writes.length,1);assert.equal(writes[0][1].headers.Authorization,'Bearer synthetic-test-access');
  const body=JSON.parse(writes[0][1].body);assert.equal(body.period,'FY2025');assert.equal(body.members[0].role,'unknown');assert.equal(body.members[1].expected_edit_token,'report-token');
  h.render();await tick();assert.match(text(h.render()),/未验证为同一事件/);assert.match(text(h.render()),/尚未实现/);
});
test('preserved revisions render separately and unsafe source URLs never become jumps',async()=>{
  const group={group_id:'g',anchor_id:'anchor',period:'FY2025',revision:1,created_at:'then',members:[{evidence_id:'anchor',role:'unknown',source_kind:'announcement',relates_to:null,evidence_snapshot:evidence}]};
  const second={...group,revision:2};const h=harness(async()=>response({...context,groups:[second],history:[group,second]}));h.render();await tick();const tree=h.render();
  assert.match(text(tree),/保留的全部分组修订/);assert.match(text(tree),/角色未知/);assert.match(text(tree),/<script>untrusted/);
  assert.equal(nodes(tree).some(n=>n.type==='script'||n.props?.dangerouslySetInnerHTML||n.props?.href?.startsWith('javascript:')),false);
});
test('conflict is visible and never retried automatically',async()=>{
  const h=harness(async(path,init)=>init.method==='GET'?response(context):({ok:false,json:async()=>({detail:'分组已变化，请刷新'})}));h.render();await tick();fill(h,'报告期','FY2025');fill(h,'同一个股','report');field(h.render(),'我声明').props.onChange({target:{checked:true}});button(h.render(),'保存用户关联').props.onClick();await tick();
  assert.match(text(h.render()),/分组已变化/);assert.equal(h.calls.filter(c=>c[1].method==='POST').length,1);
});
test('late context after unmount is ignored',async()=>{
  let finish;const h=harness(()=>new Promise(r=>{finish=r;}));h.render();await tick();h.unmount();finish(response(context));await tick();assert.equal(button(h.render(),'保存用户关联'),undefined);
});

for (const grouped of [false, true]) test(`old ${grouped ? 'group members' : 'ungrouped anchor'} outside 200 candidates use current tokens`, async () => {
  const fresh = {...evidence, edit_token:'current-anchor-token'};
  const freshReport = {...report, edit_token:'current-report-token'};
  const candidates = Array.from({length:200}, (_,i)=>({...report,id:`new-${i}`,edit_token:`token-${i}`}));
  const group = {group_id:'g',anchor_id:'anchor',period:'FY2025',revision:1,members:[
    {evidence_id:'anchor',role:'original',relates_to:null,evidence_snapshot:evidence},
    {evidence_id:'report',role:'commentary',relates_to:null,evidence_snapshot:report}]};
  const ctx = {...context,candidates,current_members:grouped?[fresh,freshReport]:[fresh],groups:grouped?[group]:[],has_more:true};
  const h=harness(async()=>response(ctx));h.render();await tick();
  if(!grouped)fill(h,'报告期','FY2025');
  fill(h,'同一个股','new-0');field(h.render(),'我声明').props.onChange({target:{checked:true}});
  button(h.render(),'保存用户关联').props.onClick();await tick();
  const writes=h.calls.filter(c=>c[1].method==='POST');assert.equal(writes.length,1);
  const body=JSON.parse(writes[0][1].body);
  assert.equal(body.members[0].expected_edit_token,'current-anchor-token');
  if(grouped)assert.equal(body.members[1].expected_edit_token,'current-report-token');
  assert.equal(body.members.at(-1).evidence_id,'new-0');
});
test('missing existing member is displayed and cannot be silently removed', async()=>{
  const h=harness(async()=>response({...context,member_conflicts:[{evidence_id:'missing',reason:'证据不存在或已删除'}]}));
  h.render();await tick();fill(h,'报告期','FY2025');fill(h,'同一个股','report');field(h.render(),'我声明').props.onChange({target:{checked:true}});
  assert.equal(button(h.render(),'保存用户关联').props.disabled,true);
  assert.match(text(h.render()),/不会自动删除成员/);
  button(h.render(),'保存用户关联').props.onClick();await tick();
  assert.equal(h.calls.filter(c=>c[1].method==='POST').length,0);
});
