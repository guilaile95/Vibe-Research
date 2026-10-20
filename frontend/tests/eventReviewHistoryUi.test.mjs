import assert from 'node:assert/strict';
import test from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';
import { readFileSync } from 'node:fs';
import * as review from '../src/lib/eventResearchReview.ts';
const nodes = t => t==null||typeof t!=='object'?[]:Array.isArray(t)?t.flatMap(nodes):[t,...nodes(t.props?.children)];
const text = t => t==null||typeof t==='boolean'?'':typeof t!=='object'?String(t):Array.isArray(t)?t.map(text).join(''):text(t.props?.children);
const button=(tree,label)=>nodes(tree).find(n=>n.type==='button'&&text(n)===label);
const tick=()=>new Promise(r=>setImmediate(r));
const row=(id,code='600519')=>({id,campaign_id:'closed-campaign',thesis_id:'t1',thesis_revision:1,expectation:'Saved expectation',observation:{security_code:code,title:'Archived event',source:'fixture'},status:'support',judgment:{reason:'Saved judgment',reviewed_at:'then',evidence:[]}});
function harness(respond){
 const slots=[],calls=[];let cursor=0,pending=[];
 const react={useState(init){const i=cursor++;if(!(i in slots))slots[i]=init;return[slots[i],v=>{slots[i]=typeof v==='function'?v(slots[i]):v;}];},useRef(init){const i=cursor++;return slots[i]??={current:init};},useEffect(effect,deps){const i=cursor++,old=slots[i];if(!old||deps.some((d,j)=>d!==old.deps[j]))pending.push(()=>{old?.cleanup?.();slots[i]={deps,cleanup:effect()};});}};
 globalThis.fetch=async(url,init)=>{calls.push({url,init});return respond(url,init);};
 const exports={},mods={react,'react-router-dom':{Link:'a'},'@/lib/eventResearchReview':review,'react/jsx-runtime':{jsx:(type,props)=>({type,props}),jsxs:(type,props)=>({type,props})}};
 vm.runInNewContext(ts.transpileModule(readFileSync(new URL('../src/components/campaign/EventResearchReview.tsx',import.meta.url),'utf8'),{compilerOptions:{jsx:ts.JsxEmit.ReactJSX,module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,{exports,require:n=>mods[n],URLSearchParams,Error});
 return{calls,unmount(){for(const slot of slots)slot?.cleanup?.();},render(props={}){cursor=0;pending=[];const tree=exports.CampaignEventReviewHistory(props);pending.forEach(f=>f());return tree;}};
}
const response=data=>({ok:true,json:async()=>({data})});
function open(h,props={}) { h.render(props); button(h.render(props),'读取复核历史').props.onClick(); h.render(props); }
test('history discovers terminal Campaign without any active scan IDs, supports older pages, and stays read-only',async()=>{
 const h=harness(async url=>response(url.includes('cursor=')?{items:[row('older')],next_cursor:null}:{items:[row('latest')],next_cursor:'older-cursor'}));
 open(h);await tick();assert.match(text(h.render()),/closed-campaign/);
 button(h.render(),'加载更早复核').props.onClick();await tick();
 assert.equal(nodes(h.render()).filter(n=>n.type==='details').length,2);
 assert.ok(h.calls[1].url.includes('cursor=older-cursor'));
 assert.ok(h.calls.every(c=>c.init.method==='GET'));
 assert.match(text(h.render()),/Saved judgment/);
 assert.equal(button(h.render(),'明确绑定此事件版本并待复核'),undefined);
});
test('subject switch rejects delayed prior history and sends the subject filter',async()=>{
 let finish;const h=harness(async url=>url.includes('600519')?new Promise(r=>{finish=r;}):response({items:[row('new','000001')],next_cursor:null}));
 open(h,{securityCode:'600519'});h.render({securityCode:'000001'});await tick();
 finish(response({items:[row('old')],next_cursor:null}));await tick();
 const tree=h.render({securityCode:'000001'});assert.match(text(tree),/000001/);assert.doesNotMatch(text(tree),/600519/);
});
test('history errors are distinct from an empty archive',async()=>{
 const h=harness(async()=>({ok:false,json:async()=>({detail:'Read unavailable'})}));open(h);await tick();
 assert.match(text(h.render()),/历史读取失败/);assert.doesNotMatch(text(h.render()),/暂无已保存/);
});
test('pending history offers explicit entry to the existing judgment flow without binding a fresh event',async()=>{
 const h=harness(async()=>response({items:[{...row('pending'),status:'review_required',judgment:null}],next_cursor:null}));
 open(h);await tick();button(h.render(),'继续原有复核').props.onClick();
 const flow=nodes(h.render()).find(n=>typeof n.type==='function'&&n.props?.campaignId==='closed-campaign');
 assert.ok(flow);assert.equal(flow.props.event,undefined);
 assert.ok(h.calls.every(c=>c.init.method==='GET'));
});

test('history entry is always visible but does not fetch until explicitly opened',async()=>{
 const h=harness(async()=>response({items:[],next_cursor:null}));
 h.render();const tree=h.render();await tick();
 assert.ok(button(tree,'读取复核历史'));assert.equal(h.calls.length,0);
 button(tree,'读取复核历史').props.onClick();h.render();await tick();
 assert.equal(h.calls.length,1);assert.match(text(h.render()),/暂无已保存/);
});
